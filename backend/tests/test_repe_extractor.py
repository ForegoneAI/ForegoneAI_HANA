"""
Automated tests for extract_repe_deal().

These use a fake Anthropic client (extraction_fakes.py) instead of calling the
real API, so this test suite:
  - runs in CI with no ANTHROPIC_API_KEY and no network access
  - costs nothing and never depends on the real Taberna CIM
  - still exercises the real code path: schema -> tool call -> validated
    REPEDealProfile, including the field-level evidence (Milestone 1,
    item 2) and uncertainty flags (Milestone 1, item 3).

Since Milestone 1.1 a fake tool call has to look like a real one - every
field present and every value backed by a snippet from the page - so the
extraction tests use the helpers in extraction_fakes.py. The detailed
reliability checks live in test_extraction_reliability.py.
"""

import pytest

from backend.app.h9n.extraction.repe_extractor import (
    IMPORTANT_FIELDS,
    apply_reviewer_feedback,
    extract_repe_deal,
)
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.tests.extraction_fakes import evidence, fake_client, full_output, text_response, tool_response


def test_extract_repe_deal_returns_a_validated_profile_with_evidence():
    pages = [
        {"file_name": "fixture.pdf", "page_number": 1, "text": "Deal Name: Fixture Deal\nAsking Price: $10,000,000."},
    ]
    client = fake_client(
        tool_response(
            full_output(
                deal_name="Fixture Deal",
                asking_price=10_000_000,
                evidence=[
                    evidence("deal_name", "Fixture Deal", "Deal Name: Fixture Deal"),
                    evidence("asking_price", 10_000_000, "Asking Price: $10,000,000."),
                ],
            )
        )
    )

    deal = extract_repe_deal(pages, client=client)

    assert deal.deal_name == "Fixture Deal"
    assert deal.asking_price == 10_000_000
    assert [e.field_name for e in deal.evidence] == ["deal_name", "asking_price"]
    assert deal.evidence[1].page_number == 1
    assert deal.withheld_values == []
    client.messages.create.assert_called_once()


def test_extract_repe_deal_withholds_a_value_the_model_flags_uncertain():
    # Before Milestone 1.1 a flagged value was stored with only a note beside
    # it. Now the field stays null and the value waits in withheld_values for
    # a reviewer, so an unreviewed guess can't pass for a verified fact.
    pages = [
        {
            "file_name": "fixture.pdf",
            "page_number": 2,
            "text": "NOI: $650,000. Asking Price: around $10M. Cap rate of roughly 6.5%.",
        },
    ]
    client = fake_client(
        tool_response(
            full_output(
                noi=650_000,
                cap_rate=6.5,
                evidence=[
                    evidence("noi", 650_000, "NOI: $650,000.", page_number=2),
                    evidence("cap_rate", 6.5, "Cap rate of roughly 6.5%.", page_number=2),
                ],
                field_flags=[
                    {"field_name": "cap_rate", "flag": "uncertain", "note": "stated as a rough figure"},
                ],
            )
        )
    )

    deal = extract_repe_deal(pages, client=client)

    assert deal.noi == 650_000
    assert deal.cap_rate is None
    assert len(deal.withheld_values) == 1
    withheld = deal.withheld_values[0]
    assert (withheld.field_name, withheld.proposed_value, withheld.reason) == ("cap_rate", 6.5, "model_uncertain")
    assert withheld.evidence.page_number == 2
    assert deal.conflicting_information == []
    assert len(deal.uncertain_information) == 1
    assert "cap_rate" in deal.uncertain_information[0]
    # Withheld values are listed in withheld_values, not as missing.
    assert deal.missing_information == []


def test_extract_repe_deal_rejects_empty_pages():
    with pytest.raises(ValueError):
        extract_repe_deal([], client=fake_client())


def test_extract_repe_deal_raises_if_model_returns_no_tool_call():
    client = fake_client(*[text_response("I could not extract this.") for _ in range(2)])

    pages = [{"file_name": "fixture.pdf", "page_number": 1, "text": "hello"}]
    with pytest.raises(ValueError):
        extract_repe_deal(pages, client=client)


def test_important_fields_covers_the_core_checkpoint_fields():
    # Guards against someone accidentally trimming the list that both the
    # missing-information check and the evidence requirement depend on.
    assert set(IMPORTANT_FIELDS) >= {"deal_name", "asking_price", "noi", "cap_rate"}


def test_apply_reviewer_feedback_returns_the_corrections_and_evidence():
    pages = [
        {"file_name": "fixture.pdf", "page_number": 4, "text": "Asking Price: $950,000."},
    ]
    deal = REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000)
    client = fake_client(
        tool_response(
            {
                "corrections": {"asking_price": 950_000},
                "updated_evidence": [evidence("asking_price", 950_000, "Asking Price: $950,000.", page_number=4)],
                "explanation": "The document states $950,000, not $1,000,000.",
            }
        )
    )

    result = apply_reviewer_feedback(
        pages, deal, "the asking price is wrong, it's actually $950k per page 4", client=client
    )

    assert result["corrections"] == {"asking_price": 950_000}
    assert result["updated_evidence"][0].field_name == "asking_price"
    assert result["withheld"] == []
    assert "950,000" in result["explanation"] or "950000" in result["explanation"]
    client.messages.create.assert_called_once()


def test_apply_reviewer_feedback_rejects_empty_pages():
    deal = REPEDealProfile(deal_name="Fixture Deal")
    with pytest.raises(ValueError):
        apply_reviewer_feedback([], deal, "something's wrong", client=fake_client())


def test_apply_reviewer_feedback_rejects_empty_feedback():
    pages = [{"file_name": "fixture.pdf", "page_number": 1, "text": "hello"}]
    deal = REPEDealProfile(deal_name="Fixture Deal")
    with pytest.raises(ValueError):
        apply_reviewer_feedback(pages, deal, "   ", client=fake_client())


def test_apply_reviewer_feedback_raises_if_model_returns_no_tool_call():
    client = fake_client(*[text_response("I'm not sure what to change.") for _ in range(2)])

    pages = [{"file_name": "fixture.pdf", "page_number": 1, "text": "hello"}]
    deal = REPEDealProfile(deal_name="Fixture Deal")
    with pytest.raises(ValueError):
        apply_reviewer_feedback(pages, deal, "something's wrong", client=client)
