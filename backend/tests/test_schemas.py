"""
Automated tests for the Deal Profile schemas.

These run in CI on every push/PR (see .github/workflows/backend-ci.yml) so
the team sees a pass/fail check on GitHub without installing anything or
running code themselves.
"""

import pydantic
import pytest

from backend.app.h9n.schemas.base_deal import FieldEvidence, WithheldValue
from backend.app.h9n.schemas.pe_deal import PEDealProfile
from backend.app.h9n.schemas.repe_deal import REPEDealProfile


def test_repe_deal_profile_leaves_unstated_fields_null():
    deal = REPEDealProfile(deal_name="Test Deal", asking_price=1_000_000)

    assert deal.deal_name == "Test Deal"
    assert deal.asking_price == 1_000_000
    # Fields not passed in should stay None, never a guessed default.
    assert deal.property_name is None
    assert deal.cap_rate is None
    assert deal.missing_information == []
    assert deal.conflicting_information == []
    assert deal.evidence == []
    assert deal.uncertain_information == []


def test_pe_deal_profile_leaves_unstated_fields_null():
    deal = PEDealProfile(deal_name="Test Co", ebitda=2_000_000)

    assert deal.ebitda == 2_000_000
    assert deal.company_name is None
    assert deal.evidence == []
    assert deal.uncertain_information == []


def test_field_evidence_attaches_to_a_deal_profile():
    deal = REPEDealProfile(
        deal_name="Test Deal",
        evidence=[
            FieldEvidence(
                field_name="deal_name",
                value="Test Deal",
                source_document="test.pdf",
                page_number=1,
                snippet="Deal Name: Test Deal",
            )
        ],
    )

    assert len(deal.evidence) == 1
    evidence = deal.evidence[0]
    assert evidence.field_name == "deal_name"
    assert evidence.source_document == "test.pdf"
    assert evidence.page_number == 1


def test_uncertain_information_flags_a_value_without_marking_it_missing():
    # Milestone 1, item 3: a field that WAS extracted but isn't fully
    # trusted should show up in uncertain_information, not missing_information
    # or conflicting_information - those mean something different.
    deal = REPEDealProfile(
        deal_name="Test Deal",
        cap_rate=6.5,
        uncertain_information=[
            "cap_rate: calculated from NOI and asking price, not stated directly"
        ],
    )

    assert deal.cap_rate == 6.5
    assert deal.missing_information == []
    assert deal.conflicting_information == []
    assert len(deal.uncertain_information) == 1
    assert "cap_rate" in deal.uncertain_information[0]


def test_corrected_fields_starts_empty():
    # Milestone 1, item 4: a freshly extracted (uncorrected) deal shouldn't
    # claim anything has been human-reviewed yet.
    deal = REPEDealProfile(deal_name="Test Deal")

    assert deal.corrected_fields == []


def test_review_status_starts_pending():
    # Milestone 1, item 4: a freshly extracted deal hasn't been looked at by
    # a reviewer yet, so it shouldn't claim to be approved (or rejected).
    deal = REPEDealProfile(deal_name="Test Deal")

    assert deal.review_status == "pending"


def test_review_status_rejects_a_value_that_isnt_one_of_the_three_states():
    with pytest.raises(pydantic.ValidationError):
        REPEDealProfile(deal_name="Test Deal", review_status="maybe")


def test_assignment_is_validated_so_a_bad_correction_is_rejected():
    # BaseDeal sets validate_assignment=True specifically so that a human
    # reviewer's correction (applied via setattr in DealStore) can't sneak
    # a value past the schema the way construction-time validation would
    # normally catch.
    deal = REPEDealProfile(asking_price=1_000_000)

    with pytest.raises(pydantic.ValidationError):
        deal.asking_price = "not a number"


def test_withheld_values_starts_empty():
    deal = REPEDealProfile(deal_name="Fixture Deal")

    assert deal.withheld_values == []


def test_a_withheld_value_keeps_its_proposed_value_reason_and_citation():
    # Milestone 1.1: an unverified value waits here, with its field left
    # null, until a reviewer accepts or dismisses it.
    deal = REPEDealProfile(
        withheld_values=[
            WithheldValue(
                field_name="cap_rate",
                proposed_value=6.5,
                reason="snippet_not_on_page",
                detail="The quoted snippet was not found on page 2.",
                evidence=FieldEvidence(field_name="cap_rate", value="6.5", page_number=2, snippet="Cap rate 6.5%"),
            )
        ]
    )

    withheld = deal.withheld_values[0]
    assert deal.cap_rate is None
    assert (withheld.proposed_value, withheld.reason, withheld.evidence.page_number) == (6.5, "snippet_not_on_page", 2)


def test_a_withheld_value_needs_a_known_reason():
    with pytest.raises(pydantic.ValidationError):
        WithheldValue(field_name="noi", proposed_value=1, reason="looked_wrong", detail="x")


def test_a_profile_saved_before_withheld_values_existed_still_loads():
    deal = REPEDealProfile.model_validate({"deal_name": "Old Deal", "evidence": [], "review_status": "approved"})

    assert deal.withheld_values == []
