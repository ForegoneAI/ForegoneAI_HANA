"""Shared fakes for extraction tests (Milestone 1.1).

The extraction tool call must now be complete (every field present, explicit
nulls) and every value needs evidence that checks out against the page text,
so these helpers build tool inputs and fake Claude responses that look like
the real thing without calling the API.
"""

from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import MagicMock

from backend.app.h9n.extraction.extraction_output import VALUE_FIELDS


def full_output(**overrides: Any) -> dict[str, Any]:
    """A complete, valid extraction tool input: every value field null and
    every list empty, with `overrides` applied on top."""
    output: dict[str, Any] = {name: None for name in VALUE_FIELDS}
    output.update(missing_information=[], evidence=[], field_flags=[])
    output.update(overrides)
    return output


def evidence(
    field_name: str,
    value: Any,
    snippet: str,
    *,
    page_number: int = 1,
    source_document: str = "fixture.pdf",
) -> dict[str, Any]:
    return {
        "field_name": field_name,
        "value": str(value),
        "source_document": source_document,
        "page_number": page_number,
        "snippet": snippet,
    }


def tool_response(tool_input: dict[str, Any], *, stop_reason: str = "tool_use", tool_id: str = "toolu_1"):
    block = SimpleNamespace(type="tool_use", id=tool_id, input=tool_input)
    return SimpleNamespace(content=[block], stop_reason=stop_reason, usage=None)


def text_response(text: str, *, stop_reason: str = "end_turn"):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop_reason, usage=None)


def fake_client(*responses: Any, error: Optional[BaseException] = None) -> MagicMock:
    """A client whose messages.create returns `responses` in order (or raises
    `error`), recording every call for inspection."""
    client = MagicMock()
    # extract_repe_deal() switches the SDK's own retries off on a caller's
    # client via with_options(); the fake hands back itself.
    client.with_options.return_value = client
    if error is not None:
        client.messages.create.side_effect = error
    else:
        client.messages.create.side_effect = list(responses)
    return client
