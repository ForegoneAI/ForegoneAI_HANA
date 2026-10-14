"""Milestone 2.1: GET /deals lists the caller's organizations' deals so the web
app can reopen one, and never lists another organization's."""

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.h9n.auth import get_current_user
from backend.app.h9n.review.models import NewDeal
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.tests.auth_fakes import OTHER_ORGANIZATION_ID, TEST_ORGANIZATION_ID, TEST_USER


def _save(deal_repository, profile: REPEDealProfile, organization_id=TEST_ORGANIZATION_ID) -> str:
    return str(
        deal_repository.create(
            NewDeal(
                id=uuid4(),
                organization_id=organization_id,
                profile=profile,
                source_filename="x.pdf",
                created_by=TEST_USER.user_id,
            )
        ).id
    )


def test_lists_the_callers_deals_most_recently_changed_first(deal_repository):
    older = _save(deal_repository, REPEDealProfile(deal_name="Older", property_name="Elm Court"))
    newer = _save(deal_repository, REPEDealProfile(deal_name="Newer"))
    client = TestClient(main.app)

    assert [row["deal_id"] for row in client.get("/api/h9n/repe/deals").json()] == [newer, older]

    # Approving the older deal changes it, so it moves to the top.
    client.post(f"/api/h9n/repe/deals/{older}/review", json={"action": "approve", "version": 1})
    body = client.get("/api/h9n/repe/deals").json()

    assert [row["deal_id"] for row in body] == [older, newer]
    row = body[0]
    assert row["saved_at"]
    assert {key: value for key, value in row.items() if key != "saved_at"} == {
        "deal_id": older,
        "organization_id": str(TEST_ORGANIZATION_ID),
        "deal_name": "Older",
        "property_name": "Elm Court",
        "review_status": "approved",
    }


def test_other_organizations_deals_are_not_listed(deal_repository):
    ours = _save(deal_repository, REPEDealProfile(deal_name="Ours"))
    _save(deal_repository, REPEDealProfile(deal_name="Theirs"), OTHER_ORGANIZATION_ID)

    response = TestClient(main.app).get("/api/h9n/repe/deals")

    assert [row["deal_id"] for row in response.json()] == [ours]


def test_an_empty_list_when_the_organization_has_no_deals():
    assert TestClient(main.app).get("/api/h9n/repe/deals").json() == []


def test_listing_deals_requires_sign_in():
    main.app.dependency_overrides.pop(get_current_user)

    response = TestClient(main.app).get("/api/h9n/repe/deals")

    assert response.status_code == 401
