"""
Automated tests for the Deal Profile schemas.

These run in CI on every push/PR (see .github/workflows/backend-ci.yml) so
the team sees a pass/fail check on GitHub without installing anything or
running code themselves.
"""

from backend.app.h9n.schemas.base_deal import FieldEvidence
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


def test_pe_deal_profile_leaves_unstated_fields_null():
    deal = PEDealProfile(deal_name="Test Co", ebitda=2_000_000)

    assert deal.ebitda == 2_000_000
    assert deal.company_name is None
    assert deal.evidence == []


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
