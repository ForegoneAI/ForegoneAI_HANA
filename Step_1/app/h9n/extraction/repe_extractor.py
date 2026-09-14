"""
repe_extractor.py

H9N Milestone 1, Part 1 - LLM Structured Extraction.

Takes the page-preserved text produced by
`Backend.app.h9n.ingestion.pdf_reader.read_pdf` for a real estate deal
package (e.g. a CIM) and asks an LLM to populate a `REPEDealProfile` with
every value it can find, leaving anything not stated in the source text
as None.

This module intentionally does NOT yet implement:
- field-level source evidence / provenance (Milestone 1, item 2)
- uncertainty flagging beyond the schema's missing/conflicting lists (item 3)
- human review & correction (item 4)
- evaluation against a ground-truth set (items 5-7)
Those are separate, later steps in the Milestone 1 plan.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import anthropic

from Backend.app.h9n.schemas.repe_deal import REPEDealProfile


# The model used for structured extraction. Override with the
# H9N_EXTRACTION_MODEL env var without touching code. Check
# https://docs.claude.com for the current list of available model IDs.
DEFAULT_MODEL = os.environ.get("H9N_EXTRACTION_MODEL", "claude-sonnet-4-5-20250929")

# Structured extraction rarely needs a huge completion since the output is
# just the deal profile fields, but we leave headroom for long text fields
# like business_plan.
MAX_OUTPUT_TOKENS = 4096

EXTRACTION_TOOL_NAME = "extract_repe_deal_profile"

SYSTEM_PROMPT = """You are H9N's structured extraction engine for real estate \
private equity (REPE) deal packages (CIMs, offering memoranda, and similar \
documents).

You will be given the full text of a deal package, broken into pages. Your \
only job is to call the `extract_repe_deal_profile` tool with the deal's \
information filled in as completely and accurately as possible.

Rules:
- Only use information that is explicitly stated in the document text. Never \
guess, estimate, or infer a value that is not directly supported by the text.
- If a field is not stated anywhere in the document, leave it as null. Do not \
invent a value to avoid leaving a field empty.
- If a required or important field (deal_name, property_name, property_type, \
address, asking_price, noi, cap_rate) is missing from the document, add a \
short description of what's missing to `missing_information`.
- If the document states two different values for the same field (e.g. two \
different asking prices in different sections), pick the value that appears \
in the more authoritative or more recent context, and add a short note \
describing the discrepancy to `conflicting_information`. Do not silently drop \
either value.
- Normalize currency values to plain numbers (e.g. "$10,000,000" -> \
10000000, "$10.0M" -> 10000000). Normalize percentages to their numeric \
value (e.g. "6.5%" -> 6.5).
- Extract every field defined on the schema, not just the ones that seem \
most important.
"""


def _build_tool_schema() -> dict[str, Any]:
    """Builds the Anthropic tool definition from the REPEDealProfile schema.

    REPEDealProfile is a flat Pydantic model (no nested sub-models), so its
    `model_json_schema()` output can be used directly as a tool input schema.
    """
    schema = REPEDealProfile.model_json_schema()
    schema.pop("title", None)

    return {
        "name": EXTRACTION_TOOL_NAME,
        "description": (
            "Records a fully populated REPEDealProfile extracted from the "
            "real estate deal package text provided by the user. Every "
            "field on the schema should be considered; fields with no "
            "support in the source text should be left null."
        ),
        "input_schema": schema,
    }


def _pages_to_document_text(pages: list[dict[str, Any]]) -> str:
    """Joins the page-level dicts produced by `read_pdf()` into one
    page-preserved block of text the LLM can read and cite by page."""
    blocks = []
    for page in pages:
        label = page.get("file_name", "document")
        marker = f"--- {label} | Page {page['page_number']} ---"
        blocks.append(f"{marker}\n{page['text'].strip()}")
    return "\n\n".join(blocks)


def extract_repe_deal(
    pages: list[dict[str, Any]],
    *,
    client: Optional[anthropic.Anthropic] = None,
    model: str = DEFAULT_MODEL,
) -> REPEDealProfile:
    """Sends page-preserved deal package text to Claude and returns a
    validated REPEDealProfile.

    Parameters
    ----------
    pages:
        The list of {"file_name", "page_number", "text"} dicts produced by
        `read_pdf()`.
    client:
        An existing `anthropic.Anthropic` client to reuse. If not provided,
        one is built from the `ANTHROPIC_API_KEY` environment variable.
    model:
        The Claude model id to use for extraction.

    Returns
    -------
    REPEDealProfile
        A schema-validated deal profile. Fields the model could not find in
        the source text are left as None (BaseDeal's default).

    Raises
    ------
    ValueError
        If `pages` is empty, or the model does not return a usable
        structured extraction.
    pydantic.ValidationError
        If the model's output fails REPEDealProfile validation.
    """
    if not pages:
        raise ValueError(
            "extract_repe_deal() received no pages. Check that read_pdf() "
            "was able to open the file and returned page text."
        )

    document_text = _pages_to_document_text(pages)

    llm_client = client or anthropic.Anthropic()

    response = llm_client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[_build_tool_schema()],
        tool_choice={"type": "tool", "name": EXTRACTION_TOOL_NAME},
        messages=[
            {
                "role": "user",
                "content": (
                    "Extract the real estate deal information from the "
                    "following deal package text. The text is split by page "
                    "so you can locate where each value came from.\n\n"
                    f"{document_text}"
                ),
            }
        ],
    )

    tool_call = next(
        (block for block in response.content if block.type == "tool_use"),
        None,
    )
    if tool_call is None:
        text_blocks = [block.text for block in response.content if block.type == "text"]
        raise ValueError(
            "Claude did not return a structured extraction. "
            f"stop_reason={response.stop_reason!r} "
            f"text={' '.join(text_blocks)!r}"
        )

    # Let pydantic.ValidationError propagate as-is if the model's tool call
    # doesn't match the schema (e.g. wrong type for a field) - the caller
    # gets pydantic's normal, field-by-field error detail for debugging.
    return REPEDealProfile(**tool_call.input)
