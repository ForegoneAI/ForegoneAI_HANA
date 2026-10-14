"""Tests for Milestone 2.4 - saving corrections and approval.

The review rules (review/workflow.py) are pure functions, tested directly.
SupabaseDealRepository is tested against a fake client that records each
query, so these check what is sent to Supabase - the organization filters,
the save_deal_changes() payload, and how its PT409/PT404 errors are read.
The SQL itself (save_deal_changes, RLS) needs a real Postgres, so it isn't
run in CI; it was checked against a local Postgres 16 when written.
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from postgrest.exceptions import APIError

from backend.app.h9n.review.models import (
    DealLockedError,
    DealNotFoundError,
    DealRecord,
    DealTransitionError,
    DealUpdateError,
    DealVersionConflictError,
    NewDeal,
)
from backend.app.h9n.review.repository import InMemoryDealRepository, SupabaseDealRepository
from backend.app.h9n.review.workflow import plan_corrections, plan_review_action
from backend.app.h9n.schemas.base_deal import FieldEvidence, WithheldValue
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.tests.auth_fakes import OTHER_ORGANIZATION_ID, TEST_ORGANIZATION_ID
from backend.tests.test_auth import _settings

REVIEWER = UUID("aaaaaaaa-0000-0000-0000-00000000000a")
NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)
PRICE_CITATION = FieldEvidence(field_name="asking_price", value="1000000", page_number=3, snippet="Price: $1,000,000")


def _deal(status="draft", version=1, **profile) -> DealRecord:
    return DealRecord(
        id=uuid4(),
        organization_id=TEST_ORGANIZATION_ID,
        status=status,
        version=version,
        profile=REPEDealProfile(review_status=status, **profile),
        source_filename="x.pdf",
        created_by=REVIEWER,
        created_at=NOW,
        updated_at=NOW,
    )


# --- The review rules -------------------------------------------------------


def test_a_correction_records_the_original_value_and_its_evidence():
    deal = _deal(asking_price=1_000_000, evidence=[PRICE_CITATION])

    changes = plan_corrections(deal, {"asking_price": 950_000}, actor=REVIEWER)

    [correction] = changes.corrections
    assert (correction.original_value, correction.corrected_value) == (1_000_000, 950_000)
    assert correction.evidence == PRICE_CITATION
    assert (correction.source, correction.corrected_by) == ("reviewer", REVIEWER)
    assert changes.profile.asking_price == 950_000
    assert changes.profile.corrected_fields == ["asking_price"]
    # The citation stays, so a reviewer can still see what the document said.
    assert changes.profile.evidence == [PRICE_CITATION]
    # Nothing is changed on the deal that was passed in.
    assert deal.profile.asking_price == 1_000_000


def test_planning_a_correction_never_changes_the_deal_passed_in():
    deal = _deal(asking_price=1_000_000)

    plan_corrections(deal, {"asking_price": 1, "deal_name": "New"}, actor=REVIEWER)

    assert (deal.profile.asking_price, deal.profile.deal_name, deal.profile.corrected_fields) == (1_000_000, None, [])


def test_a_value_is_stored_as_the_schema_reads_it():
    changes = plan_corrections(_deal(), {"asking_price": "950000"}, actor=REVIEWER)

    assert changes.corrections[0].corrected_value == 950_000.0


def test_clearing_a_value_is_a_correction():
    changes = plan_corrections(_deal(asking_price=1_000_000), {"asking_price": None}, actor=REVIEWER)

    assert changes.corrections[0].corrected_value is None
    assert changes.profile.asking_price is None


def test_correcting_a_reviewed_deal_sends_it_back_to_draft():
    changes = plan_corrections(_deal(status="reviewed"), {"deal_name": "New"}, actor=REVIEWER)

    assert changes.status == changes.profile.review_status == "draft"
    assert (changes.status_change.action, changes.status_change.from_status) == ("edit", "reviewed")


def test_correcting_a_draft_records_no_status_change():
    assert plan_corrections(_deal(), {"deal_name": "New"}, actor=REVIEWER).status_change is None


def test_an_approved_deal_cannot_be_corrected():
    with pytest.raises(DealLockedError, match="Reopen it first"):
        plan_corrections(_deal(status="approved"), {"deal_name": "New"}, actor=REVIEWER)


def test_only_changed_fields_are_recorded():
    changes = plan_corrections(
        _deal(deal_name="Same", asking_price=1), {"deal_name": "Same", "asking_price": 2}, actor=REVIEWER
    )

    assert [correction.field_name for correction in changes.corrections] == ["asking_price"]
    assert plan_corrections(_deal(deal_name="Same"), {"deal_name": "Same"}, actor=REVIEWER) is None


def test_resolving_a_flag_is_recorded_but_is_not_a_corrected_value():
    withheld = WithheldValue(field_name="noi", proposed_value=60_000, reason="model_uncertain", detail="x")
    deal = _deal(withheld_values=[withheld], uncertain_information=["noi: approximate"])

    changes = plan_corrections(deal, {"withheld_values": [], "uncertain_information": []}, actor=REVIEWER)

    assert {correction.field_name for correction in changes.corrections} == {"withheld_values", "uncertain_information"}
    assert changes.profile.corrected_fields == []


@pytest.mark.parametrize("field_name", ["review_status", "corrected_fields", "review_feedback", "evidence"])
def test_a_reviewer_cannot_set_workflow_fields_or_rewrite_evidence(field_name):
    with pytest.raises(DealUpdateError, match="can't be changed directly"):
        plan_corrections(_deal(), {field_name: None}, actor=REVIEWER)


def test_a_feedback_correction_may_replace_a_fields_citation():
    new_citation = FieldEvidence(field_name="asking_price", value="950000", page_number=4, snippet="Price: $950,000")

    changes = plan_corrections(
        _deal(asking_price=1_000_000, evidence=[PRICE_CITATION]),
        {"asking_price": 950_000, "evidence": [new_citation]},
        actor=REVIEWER,
        source="reviewer_feedback",
        feedback="the price is wrong",
    )

    assert changes.profile.evidence == [new_citation]
    assert {(c.field_name, c.source, c.feedback) for c in changes.corrections} == {
        ("asking_price", "reviewer_feedback", "the price is wrong"),
        ("evidence", "reviewer_feedback", "the price is wrong"),
    }
    assert changes.profile.corrected_fields == ["asking_price"]


def test_a_feedback_correction_still_cannot_change_the_status():
    with pytest.raises(DealUpdateError):
        plan_corrections(_deal(), {"review_status": "approved"}, actor=REVIEWER, source="reviewer_feedback")


@pytest.mark.parametrize(
    "changes, message",
    [({"nope": 1}, "not a field"), ({"asking_price": "lots"}, "'asking_price'"), ({}, "at least one")],
)
def test_an_invalid_correction_is_refused(changes, message):
    with pytest.raises(DealUpdateError, match=message):
        plan_corrections(_deal(), changes, actor=REVIEWER)


@pytest.mark.parametrize(
    "status, action, to_status",
    [
        ("draft", "review", "reviewed"),
        ("draft", "approve", "approved"),
        ("reviewed", "approve", "approved"),
        ("reviewed", "reopen", "draft"),
        ("approved", "reopen", "draft"),
        ("draft", "reject", "draft"),
        ("reviewed", "reject", "draft"),
    ],
)
def test_review_actions_move_the_deal_between_statuses(status, action, to_status):
    changes = plan_review_action(_deal(status=status), action, actor=REVIEWER, feedback="wrong price")

    assert changes.status == changes.profile.review_status == to_status
    change = changes.status_change
    assert (change.action, change.from_status, change.to_status, change.changed_by) == (
        action,
        status,
        to_status,
        REVIEWER,
    )
    assert changes.corrections == []


@pytest.mark.parametrize(
    "status, action",
    [("reviewed", "review"), ("approved", "review"), ("approved", "approve"), ("draft", "reopen"), ("approved", "reject")],
)
def test_a_review_action_that_does_not_apply_is_refused(status, action):
    with pytest.raises(DealTransitionError):
        plan_review_action(_deal(status=status), action, actor=REVIEWER, feedback="x")


def test_reject_records_the_feedback_on_the_profile_and_the_status_change():
    changes = plan_review_action(_deal(), "reject", actor=REVIEWER, feedback="  the price is wrong ")

    assert changes.profile.review_feedback == "the price is wrong"
    assert changes.status_change.note == "the price is wrong"


@pytest.mark.parametrize("feedback", [None, "", "   "])
def test_reject_needs_feedback(feedback):
    with pytest.raises(DealUpdateError):
        plan_review_action(_deal(), "reject", actor=REVIEWER, feedback=feedback)


def test_feedback_is_only_kept_for_a_rejection():
    changes = plan_review_action(_deal(), "approve", actor=REVIEWER, feedback="looks fine")

    assert changes.profile.review_feedback is None
    assert changes.status_change.note is None


# --- The in-memory repository follows the same rules -------------------------


def _new_deal(organization_id=TEST_ORGANIZATION_ID, **profile) -> NewDeal:
    return NewDeal(
        id=uuid4(),
        organization_id=organization_id,
        profile=REPEDealProfile(**profile),
        source_filename="x.pdf",
        created_by=REVIEWER,
    )


def test_in_memory_saves_bump_the_version_and_keep_history():
    deals = InMemoryDealRepository()
    deal = deals.create(_new_deal(asking_price=1))

    saved = deals.save(deal, plan_corrections(deal, {"asking_price": 2}, actor=REVIEWER), expected_version=1)

    assert (saved.version, saved.profile.asking_price) == (2, 2)
    assert saved.updated_at > deal.updated_at
    [correction] = deals.history(saved).corrections
    assert (correction.deal_version, correction.created_at) == (2, saved.updated_at)


def test_in_memory_refuses_a_stale_version_and_other_organizations():
    deals = InMemoryDealRepository()
    deal = deals.create(_new_deal(asking_price=1))
    deals.save(deal, plan_corrections(deal, {"asking_price": 2}, actor=REVIEWER), expected_version=1)

    with pytest.raises(DealVersionConflictError):
        deals.save(deal, plan_corrections(deal, {"asking_price": 3}, actor=REVIEWER), expected_version=1)
    with pytest.raises(DealNotFoundError):
        deals.get(deal.id, [OTHER_ORGANIZATION_ID])
    assert deals.get(deal.id, [TEST_ORGANIZATION_ID]).profile.asking_price == 2


def test_in_memory_returns_copies_not_its_own_records():
    deals = InMemoryDealRepository()
    deal = deals.create(_new_deal(deal_name="Elm"))

    deals.get(deal.id, [TEST_ORGANIZATION_ID]).profile.deal_name = "Changed"

    assert deals.get(deal.id, [TEST_ORGANIZATION_ID]).profile.deal_name == "Elm"


# --- What SupabaseDealRepository sends to Supabase ---------------------------


class RecordingClient:
    """Records each query as (table or rpc, [(method, args), ...]) and answers
    with the next queued response."""

    def __init__(self, *responses):
        self.queries = []
        self._responses = list(responses)

    def _query(self, target):
        calls = []
        self.queries.append((target, calls))
        client = self

        class Query:
            def __getattr__(self, method):
                def call(*args, **kwargs):
                    calls.append((method, args, kwargs))
                    return self

                return call

            def execute(self):
                response = client._responses.pop(0)
                if isinstance(response, Exception):
                    raise response
                return SimpleNamespace(data=response)

        return Query()

    def table(self, name):
        return self._query(name)

    def rpc(self, name, params):
        query = self._query(f"rpc:{name}")
        self.queries[-1][1].append(("params", (params,), {}))
        return query


def _row(deal_id, **overrides):
    return {
        "id": str(deal_id),
        "organization_id": str(TEST_ORGANIZATION_ID),
        "status": "draft",
        "version": 1,
        "profile": {"deal_name": "Elm"},
        "source_filename": "x.pdf",
        "source_pages": None,
        "extraction_run_id": None,
        "created_by": str(REVIEWER),
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        **overrides,
    }


def _repository(client) -> SupabaseDealRepository:
    return SupabaseDealRepository(_settings(), client=client)


def test_supabase_create_inserts_a_draft_at_version_1():
    new = _new_deal(deal_name="Elm")
    client = RecordingClient([_row(new.id)])

    record = _repository(client).create(new)

    [(table, calls)] = client.queries
    [(_, (row,), _)] = [call for call in calls if call[0] == "insert"]
    assert table == "deals"
    assert (row["status"], row["version"], row["organization_id"]) == ("draft", 1, str(TEST_ORGANIZATION_ID))
    assert row["profile"]["deal_name"] == "Elm"
    assert record.id == new.id


def test_supabase_get_filters_by_the_callers_organizations():
    deal_id = uuid4()
    client = RecordingClient([_row(deal_id)])

    _repository(client).get(deal_id, [TEST_ORGANIZATION_ID, OTHER_ORGANIZATION_ID])

    [(_, calls)] = client.queries
    assert ("eq", ("id", str(deal_id)), {}) in calls
    assert ("in_", ("organization_id", sorted([str(TEST_ORGANIZATION_ID), str(OTHER_ORGANIZATION_ID)])), {}) in calls


def test_supabase_get_of_a_deal_outside_the_callers_organizations_is_not_found():
    with pytest.raises(DealNotFoundError):
        _repository(RecordingClient([])).get(uuid4(), [TEST_ORGANIZATION_ID])


def test_supabase_get_with_no_organizations_never_queries():
    client = RecordingClient()

    with pytest.raises(DealNotFoundError):
        _repository(client).get(uuid4(), [])
    assert _repository(client).list([]) == []
    assert client.queries == []


def test_supabase_list_reads_only_the_summary_fields_newest_first():
    client = RecordingClient(
        [{"id": str(uuid4()), "organization_id": str(TEST_ORGANIZATION_ID), "status": "approved",
          "updated_at": NOW.isoformat(), "deal_name": "Elm", "property_name": None}]
    )

    [summary] = _repository(client).list([TEST_ORGANIZATION_ID])

    [(_, calls)] = client.queries
    [(_, (columns,), _)] = [call for call in calls if call[0] == "select"]
    assert "source_pages" not in columns and "deal_name:profile->>deal_name" in columns
    assert ("order", ("updated_at",), {"desc": True}) in calls
    assert (summary.status, summary.deal_name) == ("approved", "Elm")


def test_supabase_save_sends_one_change_and_rereads_the_deal():
    deal = _deal(asking_price=1, evidence=[PRICE_CITATION])
    changes = plan_corrections(deal, {"asking_price": 2}, actor=REVIEWER)
    client = RecordingClient(2, [_row(deal.id, version=2)])

    saved = _repository(client).save(deal, changes, expected_version=1)

    (target, calls), _ = client.queries
    [(_, (params,), _)] = [call for call in calls if call[0] == "params"]
    change = params["change"]
    assert target == "rpc:save_deal_changes"
    assert (change["deal_id"], change["organization_id"]) == (str(deal.id), str(TEST_ORGANIZATION_ID))
    assert (change["expected_version"], change["status"]) == (1, "draft")
    assert change["profile"]["asking_price"] == 2
    [correction] = change["corrections"]
    assert (correction["field_name"], correction["original_value"], correction["corrected_value"]) == (
        "asking_price",
        1,
        2,
    )
    assert correction["evidence"]["page_number"] == 3
    assert correction["corrected_by"] == str(REVIEWER)
    assert change["status_change"] is None
    assert saved.version == 2


@pytest.mark.parametrize(
    "code, error",
    [("PT409", DealVersionConflictError), ("PT404", DealNotFoundError)],
)
def test_supabase_save_reads_the_functions_error_codes(code, error):
    deal = _deal()
    changes = plan_review_action(deal, "approve", actor=REVIEWER)
    client = RecordingClient(APIError({"code": code, "message": "x"}))

    with pytest.raises(error):
        _repository(client).save(deal, changes, expected_version=1)


def test_supabase_save_passes_other_database_errors_on():
    deal = _deal()
    client = RecordingClient(APIError({"code": "XX000", "message": "internal"}))

    with pytest.raises(APIError):
        _repository(client).save(deal, plan_review_action(deal, "approve", actor=REVIEWER), expected_version=1)


def test_supabase_history_is_filtered_by_deal_and_organization():
    deal = _deal()
    correction = {
        "field_name": "asking_price", "original_value": 1, "corrected_value": 2, "evidence": None,
        "source": "reviewer", "feedback": None, "corrected_by": str(REVIEWER), "deal_version": 2,
        "created_at": NOW.isoformat(),
    }
    change = {
        "action": "approve", "from_status": "draft", "to_status": "approved", "note": None,
        "changed_by": str(REVIEWER), "deal_version": 3, "created_at": NOW.isoformat(),
    }
    client = RecordingClient([correction], [change])

    history = _repository(client).history(deal)

    assert [target for target, _ in client.queries] == ["deal_corrections", "deal_status_changes"]
    for _, calls in client.queries:
        assert ("eq", ("deal_id", str(deal.id)), {}) in calls
        assert ("eq", ("organization_id", str(TEST_ORGANIZATION_ID)), {}) in calls
        assert ("order", ("created_at",), {}) in calls
    assert history.corrections[0].corrected_value == 2
    assert history.status_changes[0].action == "approve"
