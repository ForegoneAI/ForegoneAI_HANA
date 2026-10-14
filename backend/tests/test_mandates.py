"""Tests for Milestone 3.1 - investment mandates.

Supabase is replaced with an in-memory fake (mandate_fakes.py), so these run in
CI without credentials. They cover the mandate form's validation, saving,
editing and archiving mandates per organization, selecting one for
screening, the API routes, and the demo mandate script.
"""

import re
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from postgrest.exceptions import APIError
from pydantic import ValidationError

from backend.app import main
from backend.app.h9n.auth import get_current_user
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
from backend.tests.auth_fakes import OTHER_ORGANIZATION_ID, TEST_ORGANIZATION_ID
from backend.tests.mandate_fakes import FakeSupabaseClient

def _settings() -> RagSettings:
    return RagSettings(
        openrouter_api_key="test-openrouter-key",
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


def test_lists_are_trimmed_deduplicated_and_saved_as_canonical_names():
    criteria = MandateCriteria(asset_types=["  Multifamily ", "multifamily", "", "Self  Storage", "Apartments"])
    assert criteria.asset_types == ["Multifamily", "Self-Storage"]


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
    real_fetch = repository._fetch_row

    def read_then_someone_else_edits(org, mandate_id):
        current = real_fetch(org, mandate_id)
        client.mandates.rows[0]["version"] = 2
        return current

    repository._fetch_row = read_then_someone_else_edits
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


# The organization the signed-in test user belongs to (see conftest.py).
ORG = TEST_ORGANIZATION_ID


def test_api_create_list_get_edit_archive_and_select(api_client):
    url, params = _url()
    created = api_client.post(url, params=params, json=DEMO_MANDATE.model_dump(mode="json"))
    assert created.status_code == 201, created.text
    mandate = Mandate.model_validate(created.json())

    listed = api_client.get(url, params=params)
    assert [item["id"] for item in listed.json()["mandates"]] == [str(mandate.id)]

    one_url, _ = _url(f"/{mandate.id}")
    assert api_client.get(one_url, params=params).json()["name"] == DEMO_MANDATE.name

    edit = {**DEMO_MANDATE.model_dump(mode="json"), "description": "Edited.", "version": 1}
    edited = api_client.put(one_url, params=params, json=edit)
    assert edited.status_code == 200 and edited.json()["version"] == 2

    stale = api_client.put(one_url, params=params, json=edit)
    assert stale.status_code == 409

    select_url, _ = _url(f"/{mandate.id}/for-screening")
    assert api_client.get(select_url, params=params).status_code == 200

    archive_url, _ = _url(f"/{mandate.id}/archive")
    assert api_client.post(archive_url, params=params).json()["is_archived"] is True
    assert api_client.get(select_url, params=params).status_code == 409
    assert api_client.get(url, params=params).json() == {"mandates": [], "skipped": 0}


def test_api_rejects_an_invalid_mandate_with_422(api_client):
    url, params = _url()
    response = api_client.post(url, params=params, json={"name": "Empty", "criteria": {}})
    assert response.status_code == 422
    assert api_client.fake.mandates.rows == []


def test_api_returns_404_for_an_unknown_or_foreign_mandate(api_client):
    theirs = _repository(api_client.fake).create(OTHER_ORGANIZATION_ID, DEMO_MANDATE)

    for mandate_id in (theirs.id, uuid4()):
        url, params = _url(f"/{mandate_id}")
        assert api_client.get(url, params=params).status_code == 404


def test_api_refuses_an_organization_the_user_is_not_a_member_of(api_client):
    _repository(api_client.fake).create(OTHER_ORGANIZATION_ID, DEMO_MANDATE)

    url, params = _url(organization_id=OTHER_ORGANIZATION_ID)
    response = api_client.get(url, params=params)

    assert response.status_code == 403
    assert "Demo" not in response.text


def test_api_returns_409_for_a_duplicate_name(api_client):
    url, params = _url()
    body = DEMO_MANDATE.model_dump(mode="json")
    assert api_client.post(url, params=params, json=body).status_code == 201
    assert api_client.post(url, params=params, json=body).status_code == 409


def test_api_requires_a_signed_in_user(api_client):
    main.app.dependency_overrides.pop(get_current_user)
    url, params = _url()
    assert api_client.get(url, params=params).status_code == 401


def test_api_uses_the_users_only_organization_when_none_is_given(api_client):
    created = api_client.post("/api/h9n/mandates", json=DEMO_MANDATE.model_dump(mode="json"))

    assert created.status_code == 201, created.text
    assert created.json()["organization_id"] == str(ORG)


def test_api_hides_database_errors(api_client):
    api_client.fake.mandates.fail_with = APIError({"code": "XX000", "message": "secret internal detail"})
    url, params = _url()
    response = api_client.get(url, params=params)
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
    created = api_client.post(url, params=params, json=DEMO_MANDATE.model_dump(mode="json")).json()

    created["description"] = "Edited after fetching."
    response = api_client.put(f"{url}/{created['id']}", params=params, json=created)

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
    response = api_client.post(url, params=params, json=DEMO_MANDATE.model_dump(mode="json"))
    assert response.status_code == 422
    assert "organization" in response.json()["detail"]


# --- Code review round 2 -----------------------------------------------------

from backend.app.h9n.screening import mandate as mandate_module  # noqa: E402
from backend.app.h9n.screening.mandate_repository import MandateDataError  # noqa: E402
from backend.app.h9n.screening.vocabulary import (  # noqa: E402
    ASSET_TYPES,
    MARKETS,
    normalize_asset_type,
    normalize_market,
    profile_asset_type,
    profile_market,
)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Multifamily", "Multifamily"),
        ("Apartments", "Multifamily"),
        ("Garden-style apartment community", "Multifamily"),
        ("Student apartments", "Student Housing"),
        ("Self Storage", "Self-Storage"),
        ("Cold storage warehouse", "Industrial"),
        ("Neighborhood shopping center", "Retail"),
        ("Hotel", "Hospitality"),
        ("Condominium", None),
        ("", None),
        (None, None),
    ],
)
def test_property_type_wording_maps_to_one_canonical_type(text, expected):
    assert normalize_asset_type(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Dallas-Fort Worth", "Dallas-Fort Worth"),
        ("Dallas, TX", "Dallas-Fort Worth"),
        ("DFW", "Dallas-Fort Worth"),
        ("Dallas-Fort Worth-Arlington, TX MSA", "Dallas-Fort Worth"),
        ("4100 Elm St, Plano, TX 75024", "Dallas-Fort Worth"),
        ("Greater Houston Metro Area", "Houston"),
        ("Tampa-St. Petersburg-Clearwater", "Tampa"),
        ("Washington, DC", "Washington, D.C."),
        ("Portland, OR", "Portland"),
        # Same city name, different state: never a guessed match.
        ("Portland, ME", None),
        ("Charleston, WV", None),
        ("Columbus, GA", None),
        ("Washington", None),
        ("Sun Belt", None),
        ("Texas", None),
    ],
)
def test_location_wording_maps_to_one_canonical_market(text, expected):
    assert normalize_market(text) == expected


def test_a_deal_profile_and_the_demo_mandate_meet_on_the_same_names():
    profile = REPEDealProfile(property_type="Garden-style apartment community", location="Dallas, TX")
    assert profile_asset_type(profile) in DEMO_MANDATE.criteria.asset_types
    assert profile_market(profile) in DEMO_MANDATE.criteria.target_markets
    # market is preferred over location when both name a known market.
    assert profile_market(REPEDealProfile(market="Austin", location="Dallas, TX")) == "Austin"
    assert profile_market(REPEDealProfile(address="1 Main St, Springfield, IL")) is None


def test_mandate_lists_only_accept_known_values_and_store_canonical_names():
    criteria = MandateCriteria(asset_types=["apartments"], target_markets=["DFW", "Dallas, TX", "Austin"])
    assert criteria.asset_types == ["Multifamily"]
    assert criteria.target_markets == ["Dallas-Fort Worth", "Austin"]
    with pytest.raises(ValidationError, match=r"Unknown markets: 'Sun Belt'"):
        MandateCriteria(target_markets=["Sun Belt", "Austin"])
    with pytest.raises(ValidationError, match="Unknown property types: 'Condominium'"):
        MandateCriteria(asset_types=["Condominium"])
    # "DFW" targeted and "Dallas, TX" excluded are the same market.
    with pytest.raises(ValidationError, match="both targeted and excluded"):
        MandateCriteria(target_markets=["DFW"], excluded_markets=["Dallas, TX"])


def test_the_demo_mandate_only_uses_canonical_values():
    assert set(DEMO_MANDATE.criteria.asset_types) <= set(ASSET_TYPES)
    assert set(DEMO_MANDATE.criteria.target_markets) <= set(MARKETS)


def test_the_vocabulary_route_lists_the_allowed_values(api_client):
    response = api_client.get("/api/h9n/mandates/vocabulary")
    assert response.status_code == 200
    assert response.json() == {"asset_types": ASSET_TYPES, "markets": MARKETS}


@pytest.mark.parametrize(
    "key_metrics", [{"units": {"min": 10.5}}, {"year_built": {"min": 1999.5}}, {"year_built": {"max": 2010.25}}]
)
def test_unit_counts_and_years_must_be_whole_numbers(key_metrics):
    with pytest.raises(ValidationError, match="whole numbers"):
        MandateCriteria(key_metrics=key_metrics)


def test_whole_number_limits_are_stored_as_integers():
    criteria = MandateCriteria(key_metrics={"year_built": {"min": 1999.0}, "units": {"max": 400}})
    dumped = criteria.model_dump(mode="json")["key_metrics"]
    assert dumped["year_built"]["min"] == 1999 and isinstance(dumped["year_built"]["min"], int)
    assert dumped["units"]["max"] == 400 and isinstance(dumped["units"]["max"], int)


def test_numeric_field_check_uses_real_types_not_type_names():
    assert mandate_module._profile_number_types("units") == {int}
    assert mandate_module._profile_number_types("cap_rate") == {float}
    assert mandate_module._profile_number_types("deal_name") == set()
    assert mandate_module._INTEGER_FIELDS == {"units", "year_built"}


def test_numeric_field_check_rejects_a_type_whose_name_merely_contains_int(monkeypatch):
    class Point:  # "Point" contains "int"; the old text check would have passed it
        pass

    field = REPEDealProfile.model_fields["cap_rate"]
    monkeypatch.setattr(field, "annotation", Point | None)
    assert mandate_module._profile_number_types("cap_rate") == set()
    with pytest.raises(RuntimeError, match="key_metrics.cap_rate must map to a numeric"):
        mandate_module._check_mapping()


def test_saved_criteria_carry_a_schema_version():
    client = FakeSupabaseClient()
    _repository(client).create(uuid4(), DEMO_MANDATE)
    assert client.mandates.rows[0]["criteria"]["schema_version"] == mandate_module.CRITERIA_SCHEMA_VERSION
    with pytest.raises(ValidationError):
        MandateCriteria(asset_types=["Office"], schema_version=2)


def _save_two_and_break_one(client, organization_id=None):
    repository = _repository(client)
    organization_id = organization_id or uuid4()
    good = repository.create(organization_id, _input("Good"))
    bad = repository.create(organization_id, _input("Bad"))
    row = next(row for row in client.mandates.rows if row["id"] == str(bad.id))
    row["criteria"]["surprise_field"] = True  # e.g. edited by hand in the database
    return repository, organization_id, good, bad


def test_one_unreadable_mandate_does_not_break_the_list(caplog):
    repository, organization_id, good, bad = _save_two_and_break_one(FakeSupabaseClient())

    assert [m.id for m in repository.list(organization_id)] == [good.id]
    assert str(bad.id) in caplog.text
    with pytest.raises(MandateDataError, match=str(bad.id)):
        repository.get(organization_id, bad.id)
    with pytest.raises(MandateDataError):
        select_mandate_for_screening(repository, organization_id, bad.id)


def test_an_unreadable_mandate_can_still_be_repaired_or_archived():
    repository, organization_id, _, bad = _save_two_and_break_one(FakeSupabaseClient())

    fixed = repository.update(organization_id, bad.id, MandateUpdate(**_input("Bad").model_dump(), version=1))
    assert fixed.version == 2 and repository.get(organization_id, bad.id).id == bad.id

    repository, organization_id, _, bad = _save_two_and_break_one(FakeSupabaseClient())
    archived = repository.archive(organization_id, bad.id)
    assert archived.is_archived and archived.id == bad.id and "surprise_field" in archived.problem
    # Archiving again reports the same success, and the broken row is out of the way.
    assert repository.archive(organization_id, bad.id).is_archived
    assert [m.name for m in repository.list(organization_id)] == ["Good"]


def test_api_reports_an_unreadable_mandate_clearly(api_client, monkeypatch):
    repository, organization_id, good, bad = _save_two_and_break_one(api_client.fake, ORG)
    monkeypatch.setattr(mandate_api, "get_mandate_repository", lambda: repository)
    params = {"organization_id": str(organization_id)}

    listed = api_client.get("/api/h9n/mandates", params=params)
    assert listed.status_code == 200 and [item["id"] for item in listed.json()["mandates"]] == [str(good.id)]

    fetched = api_client.get(f"/api/h9n/mandates/{bad.id}", params=params)
    assert fetched.status_code == 500
    assert "can't read" in fetched.json()["detail"] and "could not be reached" not in fetched.text


def test_a_misspelled_field_in_an_edit_is_rejected_not_silently_dropped(api_client):
    url, params = _url()
    created = api_client.post(url, params=params, json=DEMO_MANDATE.model_dump(mode="json")).json()

    typo = {key: value for key, value in created.items() if key != "description"}
    typo["descripton"] = "Oops"
    response = api_client.put(f"{url}/{created['id']}", params=params, json=typo)

    assert response.status_code == 422
    saved = api_client.get(f"{url}/{created['id']}", params=params).json()
    assert saved["description"] == DEMO_MANDATE.description and saved["version"] == 1


@pytest.mark.parametrize("left_out", ["description", "is_demo", "criteria", "name", "version"])
def test_an_edit_must_send_every_field(api_client, left_out):
    url, params = _url()
    created = api_client.post(url, params=params, json=DEMO_MANDATE.model_dump(mode="json")).json()

    edit = {key: value for key, value in created.items() if key != left_out}
    response = api_client.put(f"{url}/{created['id']}", params=params, json=edit)

    assert response.status_code == 422
    saved = api_client.get(f"{url}/{created['id']}", params=params).json()
    assert saved["is_demo"] is True and saved["description"] == DEMO_MANDATE.description


def test_an_edit_may_send_back_the_read_only_fields_but_cannot_change_them(api_client):
    url, params = _url()
    created = api_client.post(url, params=params, json=DEMO_MANDATE.model_dump(mode="json")).json()

    edit = {**created, "id": str(uuid4()), "organization_id": str(uuid4()), "is_archived": True}
    response = api_client.put(f"{url}/{created['id']}", params=params, json=edit)

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == created["id"] and body["organization_id"] == created["organization_id"]
    assert body["is_archived"] is False


def test_an_edit_that_clears_the_description_must_say_so_explicitly():
    update = MandateUpdate(**{**DEMO_MANDATE.model_dump(), "description": None, "version": 1})
    assert update.description is None


def test_archiving_a_mandate_that_vanishes_midway_is_a_404(api_client, monkeypatch):
    url, params = _url()
    created = api_client.post(url, params=params, json=DEMO_MANDATE.model_dump(mode="json")).json()
    repository = mandate_api.get_mandate_repository()
    real_fetch = repository._fetch_row

    def fetch_then_organization_is_deleted(org, mandate_id):
        row = real_fetch(org, mandate_id)
        api_client.fake.mandates.rows.clear()
        return row

    monkeypatch.setattr(repository, "_fetch_row", fetch_then_organization_is_deleted)
    response = api_client.post(f"{url}/{created['id']}/archive", params=params)
    assert response.status_code == 404


def test_the_demo_script_explains_an_unknown_organization(capsys, monkeypatch):
    from backend.scripts import create_demo_mandate as script

    fake = FakeSupabaseClient()
    fake.mandates.fail_on_insert = APIError({"code": "23503", "message": "violates foreign key constraint"})
    monkeypatch.setattr(script, "SupabaseMandateRepository", lambda settings: _repository(fake))
    monkeypatch.setattr(script.RagSettings, "from_environment", classmethod(lambda cls: _settings()))

    exit_code = script.main(["--organization-id", str(uuid4())])

    assert exit_code == 1
    assert "No organization with id" in capsys.readouterr().out


def test_an_unknown_extra_field_in_an_edit_is_rejected_even_when_nothing_is_missing(api_client):
    url, params = _url()
    created = api_client.post(url, params=params, json=DEMO_MANDATE.model_dump(mode="json")).json()

    response = api_client.put(
        f"{url}/{created['id']}", params=params, json={**created, "notes": "would be lost"}
    )

    assert response.status_code == 422
    assert "notes" in response.text


# --- Second review round -------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "Buffalo, New York",
        "Albany, New York",
        "Columbus, Mississippi",
        "Jacksonville, Arkansas",
        "Durham, New Hampshire",
        "Houston, Mississippi",
        "Birmingham, UK",
        "Durham, UK",
        "San Jose, Costa Rica",
        "Washington",
    ],
)
def test_a_place_in_another_state_or_country_never_matches_a_market(text):
    assert normalize_market(text) is None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Franklin, Tennessee", "Nashville"),
        ("Aurora, Colorado", "Denver"),
        ("Cary, North Carolina", "Raleigh-Durham"),
        ("Orange County", "Los Angeles"),
        ("Orange County, CA", "Los Angeles"),
        ("DC", "Washington, D.C."),
        ("Washington-Arlington-Alexandria, DC-VA-MD-WV", "Washington, D.C."),
        ("Dallas, Uptown or Downtown", "Dallas-Fort Worth"),  # "or" is not Oregon
        ("Uptown Dallas", "Dallas-Fort Worth"),
        ("Dallas TX 75201", "Dallas-Fort Worth"),
        ("Fort Worth Ave, Austin, TX", "Austin"),  # the city wins over a street name
        ("Seattle, Washington", "Seattle"),
        ("New York", "New York"),
    ],
)
def test_more_real_world_location_wording(text, expected):
    assert normalize_market(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Multifamily development site", "Land"),
        ("Land for development (multifamily)", "Land"),
        ("Industrial land", "Land"),
        ("Apartment community on 12 acres of land", "Multifamily"),
        ("Office building with ground-floor retail", "Office"),
        ("Office/Retail", "Office"),
        ("Flex office space", "Office"),
        ("Flex industrial", "Industrial"),
        ("Senior apartments", "Senior Housing"),
        ("Age-restricted apartments", "Senior Housing"),
        ("Seniors housing", "Senior Housing"),
        ("Medical office building", "Medical Office"),
    ],
)
def test_the_main_property_type_wins_over_side_mentions(text, expected):
    assert normalize_asset_type(text) == expected


def test_every_market_alias_means_exactly_one_market():
    from backend.app.h9n.screening import vocabulary

    assert set(vocabulary._MARKET_LOOKUP.values()) == set(MARKETS)
    assert set(vocabulary._MARKET_STATES) == set(MARKETS)


@pytest.mark.parametrize(
    "key_metrics",
    [
        {"units": {"min": 10**400}},
        {"cap_rate": {"min": 10**400}},
        {"noi": {"min": 10**400, "max": 1}},
        {"units": {"min": True}},
        {"cap_rate": {"max": False}},
    ],
)
def test_absurd_numbers_and_booleans_are_a_422_not_a_crash(api_client, key_metrics):
    url, params = _url()
    body = {"name": "Huge", "criteria": {"key_metrics": key_metrics}}
    response = api_client.post(url, params=params, json=body)
    assert response.status_code == 422
    assert api_client.fake.mandates.rows == []


def test_a_hand_edited_huge_number_does_not_break_the_list(api_client, monkeypatch):
    repository, organization_id, good, bad = _save_two_and_break_one(api_client.fake, ORG)
    row = next(row for row in api_client.fake.mandates.rows if row["id"] == str(bad.id))
    del row["criteria"]["surprise_field"]
    row["criteria"]["key_metrics"] = {"units": {"min": 10**400}}
    monkeypatch.setattr(mandate_api, "get_mandate_repository", lambda: repository)
    params = {"organization_id": str(organization_id)}

    listed = api_client.get("/api/h9n/mandates", params=params)
    assert listed.status_code == 200 and [item["id"] for item in listed.json()["mandates"]] == [str(good.id)]
    assert api_client.get(f"/api/h9n/mandates/{bad.id}", params=params).status_code == 500


def test_archiving_an_unreadable_mandate_through_the_api_reports_success(api_client, monkeypatch):
    repository, organization_id, _, bad = _save_two_and_break_one(api_client.fake, ORG)
    monkeypatch.setattr(mandate_api, "get_mandate_repository", lambda: repository)
    params = {"organization_id": str(organization_id)}

    for _ in range(2):  # retries see the same success
        response = api_client.post(f"/api/h9n/mandates/{bad.id}/archive", params=params)
        assert response.status_code == 200
        assert response.json()["is_archived"] is True and "problem" in response.json()


def test_the_demo_script_exits_cleanly_when_the_demo_already_exists(capsys, monkeypatch):
    from backend.scripts import create_demo_mandate as script

    repository = _repository()
    organization_id = uuid4()
    repository.create(organization_id, DEMO_MANDATE)
    monkeypatch.setattr(script, "SupabaseMandateRepository", lambda settings: repository)
    monkeypatch.setattr(script.RagSettings, "from_environment", classmethod(lambda cls: _settings()))

    assert script.main(["--organization-id", str(organization_id)]) == 0
    assert "already exists" in capsys.readouterr().out


# --- Third review round ------------------------------------------------------------

from backend.app.h9n.screening.vocabulary import (  # noqa: E402
    MarketMatch,
    canonical_asset_type,
    canonical_market,
    match_market,
    profile_market_match,
)


@pytest.mark.parametrize(
    "criteria, unknown",
    [
        ({"asset_types": ["Office and Retail"]}, "Office and Retail"),
        ({"asset_types": ["Office/Retail"]}, "Office/Retail"),
        ({"target_markets": ["Dallas and Houston", "Austin"]}, "Dallas and Houston"),
        ({"target_markets": ["Austin or San Antonio"]}, "Austin or San Antonio"),
        ({"excluded_markets": ["Uptown Dallas"]}, "Uptown Dallas"),
        ({"target_markets": ["Portland, ME"]}, "Portland, ME"),
    ],
)
def test_mandate_entries_that_name_more_or_less_than_one_value_are_rejected_not_trimmed(criteria, unknown):
    with pytest.raises(ValidationError, match=re.escape(repr(unknown))):
        MandateCriteria(**criteria)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Multifamily", "Multifamily"),
        ("apartments", "Multifamily"),
        ("Self Storage", "Self-Storage"),
        ("Office and Retail", None),
        ("Garden-style apartment community", None),  # deal wording, not a mandate entry
    ],
)
def test_strict_property_type_for_mandate_input(text, expected):
    assert canonical_asset_type(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Dallas-Fort Worth", "Dallas-Fort Worth"),
        ("DFW", "Dallas-Fort Worth"),
        ("Dallas, TX", "Dallas-Fort Worth"),
        ("Franklin, Tennessee", "Nashville"),
        ("Arlington, VA", "Washington, D.C."),
        ("Arlington, TX", "Dallas-Fort Worth"),
        ("Columbia, MD", "Baltimore"),
        ("Dallas, CA", None),
        ("Dallas and Houston", None),
        ("Uptown Dallas", None),
        ("123 Main St, Plano, TX", None),  # an address is deal data, not a mandate entry
    ],
)
def test_strict_market_for_mandate_input(text, expected):
    assert canonical_market(text) == expected


def test_a_mandate_saves_every_entry_it_was_given():
    criteria = MandateCriteria(
        asset_types=["Office", "Retail"], target_markets=["Dallas, TX", "Houston", "Austin", "San Antonio"]
    )
    assert criteria.asset_types == ["Office", "Retail"]
    assert criteria.target_markets == ["Dallas-Fort Worth", "Houston", "Austin", "San Antonio"]


# A table of real-looking deal-data strings, pinning down what loose matching
# does - including the cases that are only "partial" (needs review) or
# deliberately "unknown".
DEAL_MARKET_CASES = [
    ("Dallas-Fort Worth-Arlington, TX MSA", "Dallas-Fort Worth", "exact"),
    ("4100 Elm St, Plano, TX 75024", "Dallas-Fort Worth", "exact"),
    ("Dallas TX 75201", "Dallas-Fort Worth", "exact"),
    ("Arlington, VA", "Washington, D.C.", "exact"),
    ("Arlington, TX", "Dallas-Fort Worth", "exact"),
    ("Columbia, MD", "Baltimore", "exact"),
    ("Washington-Arlington-Alexandria, DC-VA-MD-WV", "Washington, D.C.", "exact"),
    ("Uptown Dallas", "Dallas-Fort Worth", "partial"),
    ("Brooklyn Park", "New York", "partial"),  # a Minneapolis suburb: flagged, not trusted
    ("DC Ranch", None, None),  # Scottsdale neighborhood: abbreviations aren't searched inside text
    ("St. Petersburg, Russia", None, None),
    ("Portland, ME", None, None),
    ("Buffalo, New York", None, None),
    ("Springfield, IL", None, None),
]


@pytest.mark.parametrize("text, market, confidence", DEAL_MARKET_CASES)
def test_deal_data_market_matching_table(text, market, confidence):
    match = match_market(text)
    assert (match.market if match else None) == market
    assert (match.confidence if match else None) == confidence


DEAL_TYPE_CASES = [
    ("Garden-style apartment community", "Multifamily"),
    ("Land O Lakes Apartments", "Multifamily"),  # bare "land" only counts when nothing else matches
    ("Land", "Land"),
    ("Vacant land", "Land"),
    ("Hotel conversion to apartments", "Hospitality"),  # intentional: today's use comes first
    ("Office building with ground-floor retail", "Office"),
    ("Multifamily development site", "Land"),
]


@pytest.mark.parametrize("text, expected", DEAL_TYPE_CASES)
def test_deal_data_property_type_table(text, expected):
    assert normalize_asset_type(text) == expected


def test_a_profile_market_says_which_field_it_came_from_and_prefers_exact_matches():
    profile = REPEDealProfile(market="Uptown Dallas", address="500 Main St, Austin, TX 78701")
    assert profile_market_match(profile) == MarketMatch("Austin", "exact", "austin", "address")

    only_partial = REPEDealProfile(market="Uptown Dallas")
    match = profile_market_match(only_partial)
    assert match.market == "Dallas-Fort Worth" and match.confidence == "partial" and match.field == "market"
    assert profile_market_match(REPEDealProfile(market="Springfield, IL")) is None


def test_a_real_code_bug_while_reading_is_not_hidden_as_bad_data(monkeypatch):
    repository = _repository()
    organization_id = uuid4()
    repository.create(organization_id, DEMO_MANDATE)

    def broken(row):
        raise TypeError("a bug, not bad data")

    monkeypatch.setattr(Mandate, "model_validate", staticmethod(broken))
    with pytest.raises(TypeError):
        repository.list(organization_id)


def test_the_list_says_how_many_mandates_it_left_out(api_client, monkeypatch):
    repository, organization_id, good, _ = _save_two_and_break_one(api_client.fake, ORG)
    monkeypatch.setattr(mandate_api, "get_mandate_repository", lambda: repository)

    listed = api_client.get("/api/h9n/mandates", params={"organization_id": str(organization_id)})
    assert listed.status_code == 200
    assert listed.json()["skipped"] == 1
    assert repository.list_with_skipped(organization_id) == ([good], 1)


def test_the_list_reports_zero_skipped_when_nothing_was_left_out(api_client):
    url, params = _url()
    api_client.post(url, params=params, json=DEMO_MANDATE.model_dump(mode="json"))
    assert api_client.get(url, params=params).json()["skipped"] == 0


def test_the_vocabulary_route_needs_the_same_access_as_the_others(api_client):
    main.app.dependency_overrides.pop(get_current_user)
    assert api_client.get("/api/h9n/mandates/vocabulary").status_code == 401


# --- Fourth review round ------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("100 Canada Dr, Plano, TX", "Dallas-Fort Worth"),
        ("12 Ireland Rd, Austin, TX", "Austin"),
        ("North Wales, PA", "Philadelphia"),
        ("La Canada Flintridge, CA", "Los Angeles"),
        ("100 Canada Dr, Plano 75024", "Dallas-Fort Worth"),
        # A location that ends in a foreign country still never matches.
        ("St. Petersburg, Russia", None),
        ("Birmingham UK", None),
        ("Toronto, Ontario, Canada", None),
    ],
)
def test_country_words_inside_a_us_address_do_not_block_a_match(text, expected):
    assert normalize_market(text) == expected


def test_a_bare_flex_mandate_entry_must_say_which_kind():
    assert canonical_asset_type("Flex") is None
    assert canonical_asset_type("Flex office") == "Office"
    with pytest.raises(ValidationError, match="'Flex'"):
        MandateCriteria(asset_types=["Flex"])
    # In deal wording "flex" still reads as industrial.
    assert normalize_asset_type("Flex") == "Industrial"
