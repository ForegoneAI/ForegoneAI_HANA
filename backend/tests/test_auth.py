"""Tests for Milestone 2.5 - Supabase Auth and organization isolation.

Supabase is replaced with fakes, so no real tokens or network are involved.
They check that protected routes need a signed-in user, that only tokens of
signed-in users are accepted, and that a user from one organization cannot
reach another organization's deals.
"""

from uuid import UUID

import pymupdf
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.h9n import auth
from backend.app.h9n.auth import (
    InvalidTokenError,
    SupabaseAuthService,
    get_current_user,
    resolve_organization,
)
from backend.app.h9n.rag.config import RagConfigurationError, RagSettings
from backend.app.h9n.review.store import DealStore
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.tests.auth_fakes import OTHER_ORGANIZATION_ID, TEST_ORGANIZATION_ID, user_in

USER_ID = UUID("aaaaaaaa-0000-0000-0000-00000000000a")


def _settings() -> RagSettings:
    return RagSettings(
        openrouter_api_key=None,
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-service-key",
        embedding_model="test-model",
        embedding_dimensions=3,
        openrouter_referer=None,
        openrouter_title=None,
        storage_bucket="test-bucket",
        chunk_size=60,
        chunk_overlap=15,
        max_upload_bytes=1_000_000,
        default_match_count=4,
    )


class FakeSupabaseClient:
    """Answers get_claims() with fixed claims and the membership query with fixed rows."""

    def __init__(self, claims=None, *, error: Exception | None = None, memberships=()):
        self._claims = claims
        self._error = error
        self._memberships = [{"organization_id": str(org)} for org in memberships]
        self.membership_filters = {}
        self.auth = self

    def get_claims(self, jwt):
        if self._error:
            raise self._error
        return None if self._claims is None else {"claims": self._claims, "headers": {}, "signature": b""}

    def table(self, name):
        assert name == "organization_memberships"
        return self

    def select(self, columns):
        return self

    def eq(self, column, value):
        self.membership_filters[column] = value
        return self

    def execute(self):
        return type("Response", (), {"data": self._memberships})()


def _service(**kwargs) -> SupabaseAuthService:
    return SupabaseAuthService(_settings(), client=FakeSupabaseClient(**kwargs))


# --- Token verification -----------------------------------------------------


def test_a_signed_in_users_token_resolves_to_their_user_id():
    service = _service(claims={"sub": str(USER_ID), "role": "authenticated"})

    assert service.verify_token("token") == USER_ID


@pytest.mark.parametrize(
    "claims",
    [
        {"sub": str(USER_ID), "role": "anon"},
        {"sub": str(USER_ID), "role": "service_role"},
        {"role": "authenticated"},
        {"sub": "not-a-uuid", "role": "authenticated"},
        None,
    ],
    ids=["anon token", "service-role token", "no subject", "bad subject", "no claims"],
)
def test_tokens_that_are_not_a_signed_in_users_are_rejected(claims):
    with pytest.raises(InvalidTokenError):
        _service(claims=claims).verify_token("token")


def test_an_expired_or_forged_token_is_rejected():
    service = _service(error=Exception("JWT has expired"))

    with pytest.raises(InvalidTokenError):
        service.verify_token("token")


def test_memberships_are_looked_up_for_active_rows_only():
    client = FakeSupabaseClient(memberships=[TEST_ORGANIZATION_ID, OTHER_ORGANIZATION_ID])
    service = SupabaseAuthService(_settings(), client=client)

    assert service.active_organization_ids(USER_ID) == {TEST_ORGANIZATION_ID, OTHER_ORGANIZATION_ID}
    assert client.membership_filters == {"user_id": str(USER_ID), "is_active": True}


# --- The get_current_user dependency, end to end ----------------------------


@pytest.fixture
def real_sign_in(tmp_path, monkeypatch):
    """Use the real get_current_user (not conftest's signed-in stand-in), backed
    by a fake Supabase that recognises the token "valid-token"."""
    main.app.dependency_overrides.pop(get_current_user)
    monkeypatch.setattr(main, "_review_store", DealStore(tmp_path / "reviews"))

    class FakeAuthService:
        def verify_token(self, token):
            if token != "valid-token":
                raise InvalidTokenError("The access token is invalid or has expired.")
            return USER_ID

        def active_organization_ids(self, user_id):
            return frozenset({TEST_ORGANIZATION_ID})

    monkeypatch.setattr(auth, "get_auth_service", lambda: FakeAuthService())


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic dXNlcjpwYXNz"}, {"Authorization": "Bearer "}, {"Authorization": "Bearer bad"}],
    ids=["no header", "wrong scheme", "empty token", "invalid token"],
)
def test_protected_routes_reject_callers_who_are_not_signed_in(real_sign_in, headers):
    client = TestClient(main.app)

    response = client.get("/api/h9n/repe/deals/anything", headers=headers)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_a_signed_in_user_reaches_their_own_organizations_deal(real_sign_in):
    deal_id = main._review_store.save(REPEDealProfile(deal_name="Ours"))
    main._review_store.save_owner(deal_id, TEST_ORGANIZATION_ID)

    response = TestClient(main.app).get(
        f"/api/h9n/repe/deals/{deal_id}", headers={"Authorization": "Bearer valid-token"}
    )

    assert response.status_code == 200
    assert response.json()["deal_name"] == "Ours"


def test_missing_supabase_configuration_is_a_503(monkeypatch):
    main.app.dependency_overrides.pop(get_current_user)

    def unconfigured():
        raise RagConfigurationError("RAG is not configured. Set SUPABASE_URL in .env or the runtime environment.")

    monkeypatch.setattr(auth, "get_auth_service", unconfigured)

    response = TestClient(main.app).get(
        "/api/h9n/repe/deals/anything", headers={"Authorization": "Bearer valid-token"}
    )

    assert response.status_code == 503


# --- Choosing the organization a request acts for ---------------------------


def test_a_requested_organization_must_be_one_of_the_users():
    user = user_in(TEST_ORGANIZATION_ID)

    assert resolve_organization(user, TEST_ORGANIZATION_ID) == TEST_ORGANIZATION_ID
    with pytest.raises(HTTPException) as refused:
        resolve_organization(user, OTHER_ORGANIZATION_ID)
    assert refused.value.status_code == 403


def test_with_no_organization_requested_a_single_membership_is_used():
    assert resolve_organization(user_in(TEST_ORGANIZATION_ID), None) == TEST_ORGANIZATION_ID


@pytest.mark.parametrize(
    ("organizations", "status_code"),
    [((), 403), ((TEST_ORGANIZATION_ID, OTHER_ORGANIZATION_ID), 400)],
    ids=["no memberships", "several memberships"],
)
def test_with_no_organization_requested_an_ambiguous_user_is_refused(organizations, status_code):
    with pytest.raises(HTTPException) as refused:
        resolve_organization(user_in(*organizations), None)
    assert refused.value.status_code == status_code


# --- Deals are invisible outside their organization -------------------------


@pytest.fixture
def other_organizations_deal(tmp_path, monkeypatch) -> str:
    monkeypatch.setattr(main, "_review_store", DealStore(tmp_path / "reviews"))
    deal_id = main._review_store.save(REPEDealProfile(deal_name="Theirs", asking_price=1_000_000))
    main._review_store.save_owner(deal_id, OTHER_ORGANIZATION_ID)
    main._review_store.save_pages(deal_id, [{"file_name": "x.pdf", "page_number": 1, "text": "x"}])
    return deal_id


def test_another_organizations_deal_looks_like_it_does_not_exist(other_organizations_deal):
    client = TestClient(main.app)
    deal_id = other_organizations_deal

    responses = [
        client.get(f"/api/h9n/repe/deals/{deal_id}"),
        client.patch(f"/api/h9n/repe/deals/{deal_id}", json={"asking_price": 1}),
        client.post(f"/api/h9n/repe/deals/{deal_id}/review", json={"status": "approved"}),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404]
    # Nothing was changed by the refused requests.
    saved = main._review_store.get(deal_id)
    assert saved.asking_price == 1_000_000
    assert saved.review_status == "pending"


def test_a_deal_saved_without_an_owner_is_not_served(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_review_store", DealStore(tmp_path / "reviews"))
    deal_id = main._review_store.save(REPEDealProfile(deal_name="Legacy"))

    assert TestClient(main.app).get(f"/api/h9n/repe/deals/{deal_id}").status_code == 404


def test_an_extracted_deal_belongs_to_the_organization_it_was_extracted_for(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "_review_store", DealStore(tmp_path / "reviews"))
    monkeypatch.setattr(main, "extract_repe_deal", lambda pages: REPEDealProfile(deal_name="Fresh"))
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Deal Name: Fresh")
    pdf = doc.tobytes()
    doc.close()

    response = TestClient(main.app).post(
        "/api/h9n/repe/extract", files={"file": ("fresh.pdf", pdf, "application/pdf")}
    )

    assert response.status_code == 200
    assert main._review_store.owner_of(response.json()["deal_id"]) == TEST_ORGANIZATION_ID
    assert main._review_store.list_ids() == [response.json()["deal_id"]]
