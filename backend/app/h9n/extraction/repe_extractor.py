"""
repe_extractor.py

H9N Milestone 1, Parts 1-3 - LLM Structured Extraction, Field-Level Source
Evidence, and Uncertainty Flagging.

Takes the page-preserved text produced by
`backend.app.h9n.ingestion.pdf_reader.read_pdf` for a real estate deal
package (e.g. a CIM) and asks an LLM to populate a `REPEDealProfile` with
every value it can find, leaving anything not stated in the source text
as None.

For each of the deal's most important fields (see `IMPORTANT_FIELDS` below),
the model is also asked to cite exactly where it got the value - the source
document, the page number, and a short supporting snippet - via
`REPEDealProfile.evidence`. This is Milestone 1, item 2: a reviewer should be
able to see where H9N obtained a value instead of trusting an unexplained
model output.

On top of that, the model is asked to flag any important field where it DID
find a value but isn't fully confident it's correct - e.g. it had to infer or
calculate the number, or the wording was ambiguous - via
`REPEDealProfile.uncertain_information`. This is Milestone 1, item 3: a
reviewer's attention should be drawn to the values most worth double-checking,
not just the ones that are missing or contradictory.

This module also implements the LLM side of Milestone 1, item 4 - Human
Review and Correction: `apply_reviewer_feedback` lets a reviewer describe
what's wrong with an extracted profile in plain language and have Claude
re-derive the corrected field(s) from the original document text, rather
than the reviewer having to work out and submit exact values themselves
(that manual path still exists too - see `DealStore.apply_corrections`).

This module intentionally does NOT yet implement evaluation against a
ground-truth set (items 5-7) - that's a separate, later step in the
Milestone 1 plan.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Optional

import anthropic

from backend.app.h9n.schemas.base_deal import FieldEvidence
from backend.app.h9n.schemas.repe_deal import REPEDealProfile


# The model used for structured extraction. Override with the
# H9N_EXTRACTION_MODEL env var without touching code. Check
# https://docs.claude.com for the current list of available model IDs.
DEFAULT_MODEL = os.environ.get("H9N_EXTRACTION_MODEL", "claude-sonnet-4-5-20250929")

# Structured extraction rarely needs a huge completion since the output is
# just the deal profile fields, but we leave headroom for long text fields
# like business_plan.
MAX_OUTPUT_TOKENS = 4096

EXTRACTION_TOOL_NAME = "extract_repe_deal_profile"

# The fields a reviewer most needs to trust without re-reading the whole
# document. Used both to decide what counts as "missing" and, as of
# Milestone 1 item 2, which fields need a source-evidence citation. Defined
# once here so the two uses can't drift apart.
IMPORTANT_FIELDS = [
    "deal_name",
    "property_name",
    "property_type",
    "address",
    "asking_price",
    "noi",
    "cap_rate",
]
_IMPORTANT_FIELDS_TEXT = ", ".join(IMPORTANT_FIELDS)

SYSTEM_PROMPT = f"""You are H9N's structured extraction engine for real estate \
private equity (REPE) deal packages (CIMs, offering memoranda, and similar \
documents).

You will be given the full text of a deal package, broken into pages, each \
one marked with its source file name and page number, e.g. \
"--- taberna_cim.pdf | Page 3 ---". Your only job is to call the \
`extract_repe_deal_profile` tool with the deal's information filled in as \
completely and accurately as possible.

Rules:
- Only use information that is explicitly stated in the document text. Never \
guess, estimate, or infer a value that is not directly supported by the text.
- If a field is not stated anywhere in the document, leave it as null. Do not \
invent a value to avoid leaving a field empty.
- If a required or important field ({_IMPORTANT_FIELDS_TEXT}) is missing from \
the document, add a short description of what's missing to \
`missing_information`.
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
- For each of these important fields ({_IMPORTANT_FIELDS_TEXT}) that you DO \
find a value for, add one entry to `evidence` with:
  - field_name: the exact schema field name, e.g. "asking_price".
  - value: the value you extracted, as plain text.
  - source_document: the file name from that page's marker.
  - page_number: the page number from that page's marker.
  - snippet: a short, verbatim quote (about one sentence) copied directly \
from that page's text that supports the value. Never paraphrase or invent \
the snippet.
- Do not add an evidence entry for a field you left null or could not find \
anywhere in the document.
- For each of these important fields ({_IMPORTANT_FIELDS_TEXT}) where you DID \
find a value but are not fully confident it's correct, add a short note to \
`uncertain_information` naming the field and explaining why, for example: \
the value had to be calculated or inferred rather than read directly \
(e.g. cap rate derived from NOI and asking price instead of stated outright), \
the wording was ambiguous or informal (e.g. "around $10M", a rounded or \
approximate figure), or the value came from a source that seems less \
authoritative than the rest of the document (e.g. a marketing summary rather \
than the financial statements). Do not use `uncertain_information` for a \
field that's simply missing (use `missing_information`) or one where the \
document states two contradictory values (use `conflicting_information`) - \
this is only for a single value you did extract but don't fully trust.
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
            "support in the source text should be left null. Important "
            "fields should also get a matching entry in `evidence` citing "
            "where the value came from, and a note in `uncertain_information` "
            "if the value was found but isn't fully trustworthy (inferred, "
            "calculated, or ambiguously worded)."
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


def extraction_prompt_sha256() -> str:
    """Fingerprints the system prompt and tool schema sent with every
    extraction (Milestone 1.3), so a saved run records exactly which
    instructions produced it without anyone having to bump a version number
    by hand when the prompt or REPEDealProfile changes."""
    tool_schema = json.dumps(_build_tool_schema(), sort_keys=True)
    return hashlib.sha256(f"{SYSTEM_PROMPT}\n{tool_schema}".encode()).hexdigest()


def extraction_input_sha256(pages: list[dict[str, Any]]) -> str:
    """Fingerprints the page-preserved text the model actually receives, so
    two runs can be confirmed to have seen identical input (Milestone 1.3)."""
    return hashlib.sha256(_pages_to_document_text(pages).encode()).hexdigest()


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


# --- Milestone 1, item 4 (extended) - feedback-driven correction ---------
#
# apply_corrections() in review/store.py lets a reviewer push exact values
# they've already worked out ("asking_price should be 950000"). The
# functions below instead let a reviewer just describe what's *wrong*
# ("the asking price looks off, the OM actually says $950k on page 4") and
# have Claude re-derive the correct value(s) from the original document
# text, the same way the initial extraction did - rather than the reviewer
# having to re-read the document and compute the correction themselves.

FEEDBACK_TOOL_NAME = "apply_reviewer_feedback"

FEEDBACK_SYSTEM_PROMPT = f"""You are H9N's structured extraction engine for real estate \
private equity (REPE) deal packages, now helping a human reviewer correct a \
previous extraction.

You will be given the full text of a deal package (broken into pages, each \
one marked with its source file name and page number), the REPEDealProfile \
that was already extracted from it, and a reviewer's note explaining what's \
wrong with that profile. Your job is to call the `{FEEDBACK_TOOL_NAME}` tool \
with the fix.

Rules:
- Only change fields the reviewer's note indicates are actually wrong. Leave \
every other field alone - do not "helpfully" re-extract fields the reviewer \
didn't flag, even if you'd extract them differently a second time.
- Only use information explicitly stated in the document text to decide the \
corrected value. Never guess, estimate, or invent a value - if the reviewer's \
note points at a field but the document doesn't clearly support a specific \
corrected value, leave that field out of `corrections` rather than making one \
up, and explain why in `explanation`.
- `corrections` is a mapping of exact REPEDealProfile field name (e.g. \
"asking_price") to its corrected value. Include only fields that are actually \
changing.
- For each of these important fields ({_IMPORTANT_FIELDS_TEXT}) that appears \
in `corrections`, add a matching entry to `updated_evidence` (field_name, \
value, source_document, page_number, snippet) citing where the corrected \
value came from, the same way the original extraction would have. Don't add \
an `updated_evidence` entry for a field that isn't in `corrections`.
- `explanation` is a short (one or two sentence) note of what was wrong and \
what you changed, for the audit trail - written for the reviewer, not the \
document author.
"""


def _build_feedback_tool_schema() -> dict[str, Any]:
    evidence_schema = FieldEvidence.model_json_schema()
    evidence_schema.pop("title", None)

    return {
        "name": FEEDBACK_TOOL_NAME,
        "description": (
            "Records the corrected field value(s) for a REPEDealProfile "
            "that a human reviewer has flagged as wrong, based on the "
            "reviewer's own explanation and the original deal package text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "corrections": {
                    "type": "object",
                    "description": (
                        "Mapping of exact REPEDealProfile field name to its "
                        "corrected value. Only include fields that are "
                        "actually changing."
                    ),
                    "additionalProperties": True,
                },
                "updated_evidence": {
                    "type": "array",
                    "description": (
                        "One entry per important field present in "
                        "`corrections`, citing where the corrected value "
                        "came from."
                    ),
                    "items": evidence_schema,
                },
                "explanation": {
                    "type": "string",
                    "description": "What was wrong and what changed, for the audit trail.",
                },
            },
            "required": ["corrections", "explanation"],
        },
    }


def apply_reviewer_feedback(
    pages: list[dict[str, Any]],
    deal: REPEDealProfile,
    feedback: str,
    *,
    client: Optional[anthropic.Anthropic] = None,
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Given the original document pages, the current (reviewer-flagged)
    deal profile, and the reviewer's own explanation of what's wrong, asks
    Claude to re-derive just the affected field(s) from the source text.

    Parameters
    ----------
    pages:
        The same page-preserved text (from `read_pdf()`) the deal was
        originally extracted from - typically fetched via
        `DealStore.get_pages()`.
    deal:
        The deal profile as it stands right now (before this correction).
    feedback:
        The reviewer's plain-language explanation of what's wrong, e.g.
        "the asking price is wrong, it should be around $950k per page 4".

    Returns
    -------
    dict
        {"corrections": {field_name: value, ...},
         "updated_evidence": [{"field_name": ..., "value": ..., ...}, ...],
         "explanation": "..."}
        `corrections` is meant to be passed straight to
        `DealStore.apply_corrections()`.

    Raises
    ------
    ValueError
        If `pages` is empty, or the model does not return a usable
        structured response.
    """
    if not pages:
        raise ValueError(
            "apply_reviewer_feedback() received no pages. The deal's source "
            "text is required to re-derive a corrected value - see "
            "DealStore.save_pages()/get_pages()."
        )
    if not feedback or not feedback.strip():
        raise ValueError("apply_reviewer_feedback() requires non-empty reviewer feedback.")

    document_text = _pages_to_document_text(pages)
    llm_client = client or anthropic.Anthropic()

    response = llm_client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=FEEDBACK_SYSTEM_PROMPT,
        tools=[_build_feedback_tool_schema()],
        tool_choice={"type": "tool", "name": FEEDBACK_TOOL_NAME},
        messages=[
            {
                "role": "user",
                "content": (
                    "Here is the original deal package text, split by page:\n\n"
                    f"{document_text}\n\n"
                    "Here is the REPEDealProfile as currently extracted "
                    "(as JSON):\n\n"
                    f"{json.dumps(deal.model_dump(), indent=2)}\n\n"
                    "Here is the reviewer's explanation of what's wrong "
                    f"with it:\n\n{feedback}"
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
            "Claude did not return a structured correction. "
            f"stop_reason={response.stop_reason!r} "
            f"text={' '.join(text_blocks)!r}"
        )

    result = dict(tool_call.input)
    result.setdefault("corrections", {})
    result.setdefault("updated_evidence", [])
    result.setdefault("explanation", "")
    return result


def merge_evidence(existing: list[Any], updates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replaces any existing FieldEvidence entry (from `deal.evidence`, so
    either FieldEvidence objects or plain dicts) whose field_name matches
    one of `updates` (the `updated_evidence` list `apply_reviewer_feedback`
    returns), and appends the rest - so a correction's citation supersedes
    the (now-wrong) original one instead of leaving both around.

    Shared by both the API (main.py's review endpoint) and the interactive
    demo, so a feedback-driven correction's evidence gets merged the same
    way regardless of which one applied it.
    """
    updated_field_names = {update["field_name"] for update in updates}
    kept = [
        entry.model_dump() if hasattr(entry, "model_dump") else entry
        for entry in existing
        if (entry.field_name if hasattr(entry, "field_name") else entry["field_name"])
        not in updated_field_names
    ]
    return kept + updates
