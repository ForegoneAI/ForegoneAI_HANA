"""Tests for Milestone 3.1 - investment mandates.

Supabase is replaced with an in-memory fake (mandate_fakes.py), so these run in
CI without credentials. They cover the mandate form's validation, saving,
editing and archiving mandates per organization, selecting one for
screening, the API routes, and the demo mandate script.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError
from pydantic import ValidationError

from backend.app import main
from backend.app.h9n.rag import api as rag_api
from backend.app.h9n.rag.config import RagSettings
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.app.h9n.screening import api as mandate_api
from backend.app.h9n.screening.mandate import (
    CRITERIA_PROFILE_FIELDS,
    DEMO_MANDATE,
    Mandate,
    MandateCriteria,
    MandateInput,
    MandateUpdate,
)
from backend.app.h9n.screening.mandate_repository import (
    MandateArchivedError,
    MandateConflictError,
    MandateNotFoundError,
    SupabaseMandateRepository,
    select_mandate_for_screening,
)
from backend.scripts.create_demo_mandate import create_demo_mandate
from backend.tests.mandate_fakes import FakeSupabaseClient

API_KEY = "test-internal-key"


def _settings() -> RagSettings:
    return RagSettings(
        openrouter_api_key="test-openrouter-key",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-service-key",
        internal_api_key=API_KEY,
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


def _repository(client=None) -> SupabaseMandateRepository:
    return SupabaseMandateRepository(_settings(), client=client or FakeSupabaseClient())


def _input(name="Core Office", **criteria) -> MandateInput:
    return MandateInput(name=name, criteria=MandateCriteria(**(criteria or {"asset_types": ["Office"]})))


# --- The mandate form ------------------------------------------------------


def test_the_demo_mandate_is_valid_and_clearly_marked_as_a_demo():
    assert DEMO_MANDATE.is_demo
    assert DEMO_MANDATE.name.startswith("Demo")
    criteria = DEMO_MANDATE.criteria
    assert criteria.asset_types == ["Multifamily"]
    assert criteria.deal_size.min == 5_000_000 and criteria.deal_size.max == 50_000_000
    assert criteria.key_metrics["cap_rate"].min == 5.5
    assert criteria.key_metrics["occupancy_rate"].min == 90
    assert criteria.leverage.max_ltv == 65
    # Round-trips through JSON exactly, the way it's stored.
    assert MandateInput.model_validate_json(DEMO_MANDATE.model_dump_json()) == DEMO_MANDATE


def test_every_criterion_maps_to_a_real_deal_profile_field():
    assert set(CRITERIA_PROFILE_FIELDS.values()) <= set(REPEDealProfile.model_fields)


def test_lists_are_trimmed_and_deduplicated_ignoring_case():
    criteria = MandateCriteria(asset_types=["  Multifamily ", "multifamily", "", "Self  Storage"])
    assert criteria.asset_types == ["Multifamily", "Self Storage"]


@pytest.mark.parametrize(
    "criteria, message",
    [
        ({}, "at least one hard criterion"),
        ({"preferences": ["Value-add"]}, "at least one hard criterion"),
        ({"deal_size": {"min": 50_000_000, "max": 5_000_000}}, "larger than max"),
        ({"deal_size": {}}, "Give a min, a max, or both"),
        ({"deal_size": {"min": -1}}, "can't be negative"),
        ({"key_metrics": {"cap_rate": {"min": 0.055}}, "asset_types": []}, None),  # 0.055% is odd but valid
        ({"key_metrics": {"cap_rate": {"min": 550}}}, "is a percentage"),
        ({"key_metrics": {"asking_price": {"min": 1}}}, "key_metrics.asking_price"),
        ({"leverage": {"max_ltv": 120}}, "less than or equal to 100"),
        ({"leverage": {}}, "max_ltv, max_interest_rate"),
        ({"target_markets": ["Austin"], "excluded_markets": ["austin"]}, "both targeted and excluded"),
        ({"asset_types": ["Office"], "surprise": True}, "Extra inputs are not permitted"),
    ],
)
def test_invalid_criteria_are_rejected_with_a_clear_reason(criteria, message):
    if message is None:
        MandateCriteria(**criteria)
        return
    with pytest.raises(ValidationError, match=message):
        MandateCriteria(**criteria)


def test_impossible_numbers_are_rejected():
    with pytest.raises(ValidationError):
        MandateCriteria(deal_size={"max": float("inf")})


def test_a_mandate_needs_a_name():
    with pytest.raises(ValidationError):
        MandateInput(name="   ", criteria=MandateCriteria(asset_types=["Office"]))


# --- Saving, editing, archiving -------------------------------------------


def test_a_mandate_can_be_saved_and_read_back():
    repository = _repository()
    organization_id = uuid4()

    saved = repository.create(organization_id, DEMO_MANDATE)

    assert saved.version == 1 and not saved.is_archived
    assert saved.organization_id == organization_id
    assert repository.get(organization_id, saved.id).criteria == DEMO_MANDATE.criteria
    assert [m.id for m in repository.list(organization_id)] == [saved.id]


def test_another_organizations_mandate_looks_like_it_does_not_exist():
    repository = _repository()
    saved = repository.create(uuid4(), DEMO_MANDATE)

    other_organization = uuid4()
    assert repository.list(other_organization) == []
    with pytest.raises(MandateNotFoundError):
        repository.get(other_organization, saved.id)
    with pytest.raises(MandateNotFoundError):
        repository.update(other_organization, saved.id, MandateUpdate(**DEMO_MANDATE.model_dump(), version=1))


def test_two_active_mandates_in_one_organization_cannot_share_a_name():
    repository = _repository()
    organization_id = uuid4()
    repository.create(organization_id, _input("Core Office"))

    with pytest.raises(MandateConflictError, match="already exists"):
        repository.create(organization_id, _input("core office"))
    # A different organization may use the same name.
    repository.create(uuid4(), _input("Core Office"))


def test_editing_bumps_the_version_and_keeps_the_rest():
    repository = _repository()
    organization_id = uuid4()
    saved = repository.create(organization_id, DEMO_MANDATE)

    changed = DEMO_MANDATE.model_copy(deep=True)
    changed.criteria.leverage.max_ltv = 60
    updated = repository.update(organization_id, saved.id, MandateUpdate(**changed.model_dump(), version=1))

    assert updated.version == 2
    assert updated.criteria.leverage.max_ltv == 60
    assert updated.created_at == saved.created_at
    assert updated.updated_at > saved.updated_at


def test_an_edit_based_on_an_old_version_is_refused_instead_of_overwriting():
    repository = _repository()
    organization_id = uuid4()
    saved = repository.create(organization_id, DEMO_MANDATE)
    repository.update(organization_id, saved.id, MandateUpdate(**DEMO_MANDATE.model_dump(), version=1))

    with pytest.raises(MandateConflictError, match="version 2"):
        repository.update(organization_id, saved.id, MandateUpdate(**DEMO_MANDATE.model_dump(), version=1))


def test_two_edits_racing_from_the_same_version_cannot_both_win():
    client = FakeSupabaseClient()
    repository = _repository(client)
    organization_id = uuid4()
    saved = repository.create(organization_id, DEMO_MANDATE)

    # Someone else's edit lands between our read and our write.
    real_get = repository.get

    def get_then_someone_else_edits(org, mandate_id):
        current = real_get(org, mandate_id)
        client.mandates.rows[0]["version"] = 2
        return current

    repository.get = get_then_someone_else_edits
    with pytest.raises(MandateConflictError):
        repository.update(organization_id, saved.id, MandateUpdate(**DEMO_MANDATE.model_dump(), version=1))


def test_archived_mandates_are_hidden_kept_and_frozen():
    repository = _repository()
    organization_id = uuid4()
    saved = repository.create(organization_id, DEMO_MANDATE)

    archived = repository.archive(organization_id, saved.id)

    assert archived.is_archived
    assert repository.list(organization_id) == []
    assert [m.id for m in repository.list(organization_id, include_archived=True)] == [saved.id]
    with pytest.raises(MandateArchivedError):
        repository.update(organization_id, saved.id, MandateUpdate(**DEMO_MANDATE.model_dump(), version=1))
    # Archiving twice is harmless, and the name is free again.
    assert repository.archive(organization_id, saved.id).is_archived
    repository.create(organization_id, DEMO_MANDATE)


def test_only_an_active_mandate_can_be_selected_for_screening():
    repository = _repository()
    organization_id = uuid4()
    saved = repository.create(organization_id, DEMO_MANDATE)

    selected = select_mandate_for_screening(repository, organization_id, saved.id)
    assert selected.id == saved.id and selected.version == 1

    repository.archive(organization_id, saved.id)
    with pytest.raises(MandateArchivedError):
        select_mandate_for_screening(repository, organization_id, saved.id)


def test_stored_criteria_leave_out_empty_bounds():
    client = FakeSupabaseClient()
    _repository(client).create(uuid4(), DEMO_MANDATE)
    stored = client.mandates.rows[0]["criteria"]
    assert stored["key_metrics"]["cap_rate"] == {"min": 5.5}
    assert "max_interest_rate" not in stored["leverage"]


def test_the_repository_refuses_to_start_without_supabase_settings():
    settings = _settings()
    unconfigured = RagSettings(**{**settings.__dict__, "supabase_url": None})
    with pytest.raises(Exception, match="SUPABASE_URL"):
        SupabaseMandateRepository(unconfigured)


# --- Demo script -----------------------------------------------------------


def test_the_demo_script_saves_the_demo_once():
    repository = _repository()
    organization_id = uuid4()

    created, message = create_demo_mandate(repository, organization_id)
    assert created and "Created" in message

    created_again, message = create_demo_mandate(repository, organization_id)
    assert not created_again and "already exists" in message
    assert len(repository.list(organization_id)) == 1


# --- API routes ------------------------------------------------------------


@pytest.fixture
def api_client(monkeypatch):
    fake = FakeSupabaseClient()
    repository = _repository(fake)
    monkeypatch.setattr(rag_api, "get_rag_settings", _settings)
    monkeypatch.setattr(mandate_api, "get_mandate_repository", lambda: repository)
    client = TestClient(main.app)
    client.fake = fake
    return client


def _url(path="", organization_id=None):
    return f"/api/h9n/mandates{path}", {"organization_id": str(organization_id or ORG)}


ORG = uuid4()
HEADERS = {"X-H9N-API-Key": API_KEY}


def test_api_create_list_get_edit_archive_and_select(api_client):
    url, params = _url()
    created = api_client.post(url, params=params, headers=HEADERS, json=DEMO_MANDATE.model_dump(mode="json"))
    assert created.status_code == 201, created.text
    mandate = Mandate.model_validate(created.json())

    listed = api_client.get(url, params=params, headers=HEADERS)
    assert [item["id"] for item in listed.json()] == [str(mandate.id)]

    one_url, _ = _url(f"/{mandate.id}")
    assert api_client.get(one_url, params=params, headers=HEADERS).json()["name"] == DEMO_MANDATE.name

    edit = {**DEMO_MANDATE.model_dump(mode="json"), "description": "Edited.", "version": 1}
    edited = api_client.put(one_url, params=params, headers=HEADERS, json=edit)
    assert edited.status_code == 200 and edited.json()["version"] == 2

    stale = api_client.put(one_url, params=params, headers=HEADERS, json=edit)
    assert stale.status_code == 409

    select_url, _ = _url(f"/{mandate.id}/for-screening")
    assert api_client.get(select_url, params=params, headers=HEADERS).status_code == 200

    archive_url, _ = _url(f"/{mandate.id}/archive")
    assert api_client.post(archive_url, params=params, headers=HEADERS).json()["is_archived"] is True
    assert api_client.get(select_url, params=params, headers=HEADERS).status_code == 409
    assert api_client.get(url, params=params, headers=HEADERS).json() == []


def test_api_rejects_an_invalid_mandate_with_422(api_client):
    url, params = _url()
    response = api_client.post(url, params=params, headers=HEADERS, json={"name": "Empty", "criteria": {}})
    assert response.status_code == 422
    assert api_client.fake.mandates.rows == []


def test_api_returns_404_for_an_unknown_or_foreign_mandate(api_client):
    url, params = _url()
    created = api_client.post(url, params=params, headers=HEADERS, json=DEMO_MANDATE.model_dump(mode="json"))
    mandate_id = created.json()["id"]

    other_url, other_params = _url(f"/{mandate_id}", organization_id=uuid4())
    assert api_client.get(other_url, params=other_params, headers=HEADERS).status_code == 404


def test_api_returns_409_for_a_duplicate_name(api_client):
    url, params = _url()
    body = DEMO_MANDATE.model_dump(mode="json")
    assert api_client.post(url, params=params, headers=HEADERS, json=body).status_code == 201
    assert api_client.post(url, params=params, headers=HEADERS, json=body).status_code == 409


@pytest.mark.parametrize("headers, expected", [({}, 401), ({"X-H9N-API-Key": "wrong"}, 403)])
def test_api_requires_the_internal_key(api_client, headers, expected):
    url, params = _url()
    assert api_client.get(url, params=params, headers=headers).status_code == expected


def test_api_requires_an_organization(api_client):
    assert api_client.get("/api/h9n/mandates", headers=HEADERS).status_code == 422


def test_api_hides_database_errors(api_client):
    api_client.fake.mandates.fail_with = APIError({"code": "XX000", "message": "secret internal detail"})
    url, params = _url()
    response = api_client.get(url, params=params, headers=HEADERS)
    assert response.status_code == 502
    assert "secret" not in response.text


# --- Fixes from review ------------------------------------------------------


@pytest.mark.parametrize(
    "key_metrics, message",
    [
        ({"units": {"min": -5}}, "can't be negative"),
        ({"square_feet": {"max": -1}}, "can't be negative"),
        ({"year_built": {"min": 1200}}, "between 1700 and 2100"),
    ],
)
def test_impossible_metric_limits_are_rejected(key_metrics, message):
    with pytest.raises(ValidationError, match=message):
        MandateCriteria(key_metrics=key_metrics)


def test_noi_limits_may_be_negative():
    MandateCriteria(key_metrics={"noi": {"min": -100_000}})


def test_a_fetched_mandate_can_be_edited_and_sent_straight_back(api_client):
    url, params = _url()
    created = api_client.post(url, params=params, headers=HEADERS, json=DEMO_MANDATE.model_dump(mode="json")).json()

    created["description"] = "Edited after fetching."
    response = api_client.put(f"{url}/{created['id']}", params=params, headers=HEADERS, json=created)

    assert response.status_code == 200, response.text
    assert response.json()["version"] == 2
    assert response.json()["description"] == "Edited after fetching."


def test_archiving_does_not_change_the_version():
    repository = _repository()
    organization_id = uuid4()
    saved = repository.create(organization_id, DEMO_MANDATE)
    assert repository.archive(organization_id, saved.id).version == saved.version


def test_the_demo_script_reports_a_race_instead_of_crashing():
    repository = _repository()
    organization_id = uuid4()
    real_list = repository.list

    def list_then_someone_else_creates(org, **kwargs):
        mandates = real_list(org, **kwargs)
        real_create(org, DEMO_MANDATE)
        return mandates

    real_create = repository.create
    repository.list = list_then_someone_else_creates
    created, message = create_demo_mandate(repository, organization_id)
    assert not created and "already exists" in message


def test_saving_for_an_organization_that_does_not_exist_is_a_clear_error(api_client):
    api_client.fake.mandates.fail_with = APIError({"code": "23503", "message": "violates foreign key"})
    url, params = _url()
    response = api_client.post(url, params=params, headers=HEADERS, json=DEMO_MANDATE.model_dump(mode="json"))
    assert response.status_code == 422
    assert "organization" in response.json()["detail"]
