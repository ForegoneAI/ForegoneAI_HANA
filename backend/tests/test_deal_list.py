"""Milestone 2.1: GET /deals lists the caller's organizations' deals so the web
app can reopen one, and never lists another organization's."""

import os

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.h9n.auth import get_current_user
from backend.app.h9n.review.store import DealStore
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.tests.auth_fakes import OTHER_ORGANIZATION_ID, TEST_ORGANIZATION_ID


@pytest.fixture
def store(tmp_path, monkeypatch) -> DealStore:
    store = DealStore(tmp_path / "reviews")
    monkeypatch.setattr(main, "_review_store", store)
    return store


def _save(store: DealStore, deal: REPEDealProfile, owner, *, saved_at: int) -> str:
    deal_id = store.save(deal)
    if owner is not None:
        store.save_owner(deal_id, owner)
    # Fix the "last saved" time so the order is predictable.
    os.utime(store.store_dir / f"{deal_id}.json", (saved_at, saved_at))
    return deal_id


def test_lists_the_callers_deals_most_recently_saved_first(store):
    older = _save(
        store, REPEDealProfile(deal_name="Older", property_name="Elm Court"), TEST_ORGANIZATION_ID, saved_at=1_000
    )
    newer = _save(store, REPEDealProfile(deal_name="Newer"), TEST_ORGANIZATION_ID, saved_at=2_000)
    store.set_review_status(older, "approved")
    os.utime(store.store_dir / f"{older}.json", (1_000, 1_000))

    response = TestClient(main.app).get("/api/h9n/repe/deals")

    assert response.status_code == 200
    body = response.json()
    assert [row["deal_id"] for row in body] == [newer, older]
    assert body[1] == {
        "deal_id": older,
        "organization_id": str(TEST_ORGANIZATION_ID),
        "deal_name": "Older",
        "property_name": "Elm Court",
        "review_status": "approved",
        "saved_at": "1970-01-01T00:16:40Z",
    }


def test_other_organizations_and_ownerless_deals_are_not_listed(store):
    ours = _save(store, REPEDealProfile(deal_name="Ours"), TEST_ORGANIZATION_ID, saved_at=1_000)
    _save(store, REPEDealProfile(deal_name="Theirs"), OTHER_ORGANIZATION_ID, saved_at=2_000)
    _save(store, REPEDealProfile(deal_name="Legacy"), None, saved_at=3_000)

    response = TestClient(main.app).get("/api/h9n/repe/deals")

    assert [row["deal_id"] for row in response.json()] == [ours]


def test_an_empty_list_when_the_organization_has_no_deals(store):
    assert TestClient(main.app).get("/api/h9n/repe/deals").json() == []


def test_listing_deals_requires_sign_in(store):
    main.app.dependency_overrides.pop(get_current_user)

    response = TestClient(main.app).get("/api/h9n/repe/deals")

    assert response.status_code == 401
