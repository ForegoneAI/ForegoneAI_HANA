"""
Automated tests for extract_repe_deal().

These use a fake Anthropic client (unittest.mock) instead of calling the
real API, so this test suite:
  - runs in CI with no ANTHROPIC_API_KEY and no network access
  - costs nothing and never depends on the real Taberna CIM
  - still exercises the real code path: schema -> tool call -> validated
    REPEDealProfile, including the field-level evidence (Milestone 1,
    item 2).
"""

from unittest.mock import MagicMock

import pytest

from backend.app.h9n.extraction.repe_extractor import IMPORTANT_FIELDS, extract_repe_deal


def _fake_client_returning(tool_input: dict) -> MagicMock:
    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.input = tool_input

    response = MagicMock()
    response.content = [tool_use_block]

    client = MagicMock()
    client.messages.create.return_value = response
    return client


def test_extract_repe_deal_returns_a_validated_profile_with_evidence():
    pages = [
        {"file_name": "fixture.pdf", "page_number": 1, "text": "Asking Price: $10,000,000."},
    ]
    fake_client = _fake_client_returning(
        {
            "deal_name": "Fixture Deal",
            "asking_price": 10_000_000,
            "missing_information": [],
            "conflicting_information": [],
            "evidence": [
                {
                    "field_name": "asking_price",
                    "value": "10000000",
                    "source_document": "fixture.pdf",
                    "page_number": 1,
                    "snippet": "Asking Price: $10,000,000.",
                }
            ],
        }
    )

    deal = extract_repe_deal(pages, client=fake_client)

    assert deal.deal_name == "Fixture Deal"
    assert deal.asking_price == 10_000_000
    assert len(deal.evidence) == 1
    assert deal.evidence[0].field_name == "asking_price"
    assert deal.evidence[0].page_number == 1
    fake_client.messages.create.assert_called_once()


def test_extract_repe_deal_rejects_empty_pages():
    with pytest.raises(ValueError):
        extract_repe_deal([], client=MagicMock())


def test_extract_repe_deal_raises_if_model_returns_no_tool_call():
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "I could not extract this."

    response = MagicMock()
    response.content = [text_block]
    response.stop_reason = "end_turn"

    fake_client = MagicMock()
    fake_client.messages.create.return_value = response

    pages = [{"file_name": "fixture.pdf", "page_number": 1, "text": "hello"}]
    with pytest.raises(ValueError):
        extract_repe_deal(pages, client=fake_client)


def test_important_fields_covers_the_core_checkpoint_fields():
    # Guards against someone accidentally trimming the list that both the
    # missing-information check and the evidence requirement depend on.
    assert set(IMPORTANT_FIELDS) >= {"deal_name", "asking_price", "noi", "cap_rate"}
