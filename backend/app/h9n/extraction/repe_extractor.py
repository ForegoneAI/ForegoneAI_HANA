"""
repe_extractor.py

H9N Milestone 1, Parts 1-3 - LLM Structured Extraction, Field-Level Source
Evidence, and Uncertainty Flagging - hardened by Milestone 1.1 (extraction
reliability).

Takes the page-preserved text produced by
`backend.app.h9n.ingestion.pdf_reader.read_pdf` for a real estate deal
package (e.g. a CIM) and asks an LLM to populate a `REPEDealProfile` with
every value it can find, leaving anything not stated in the source text
as an explicit null.

For every value it finds, the model must also cite exactly where it got it -
the source document, the page number, and a short verbatim snippet. Milestone
1.1 makes that citation load-bearing: the model's tool call is validated
against a strict schema (`extraction_output.REPEExtractionOutput`, retried
once with the validation errors if it doesn't fit), and then every value is
checked against the source pages (`extraction_output.enforce_integrity`).
Only values whose cited passage really contains them - and that the model
didn't itself flag as uncertain or conflicting - are stored in their fields.
Everything else is left null and recorded in `withheld_values` for a human
reviewer.

Every failure surfaces as an `ExtractionError` subclass with a message that
is safe to return to an API caller - bad input, a provider outage, missing
configuration, a refusal, or output that still wasn't valid after a retry -
instead of a raw SDK or pydantic exception. One extraction (every request,
retry and backoff together) stays within H9N_EXTRACTION_TIMEOUT_SECONDS.

This module also implements the LLM side of Milestone 1, item 4 - Human
Review and Correction: `apply_reviewer_feedback` lets a reviewer describe
what's wrong with an extracted profile in plain language and have Claude
re-derive the corrected field(s) from the original document text, rather
than the reviewer having to work out and submit exact values themselves
(that manual path still exists too - see `DealStore.apply_corrections`).
Since Milestone 1.1 that path is held to the same standard: the same strict
validation, the same controlled errors, and the same evidence checks
(`extraction_output.verify_corrections`) before a correction is applied.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Optional, TypeVar

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from backend.app.h9n.extraction.extraction_output import (
    MIN_SNIPPET_CHARS,
    REPEExtractionOutput,
    ReviewerFeedbackOutput,
    enforce_integrity,
    verify_corrections,
)
from backend.app.h9n.schemas.base_deal import FieldEvidence, WithheldValue
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.app.h9n.extraction.telemetry import record_model_response

logger = logging.getLogger(__name__)

# Reads a local .env (without overriding real environment variables) at import,
# so DEFAULT_MODEL below - read once here - can come from .env too.
load_dotenv(override=False)

# OpenRouter uses author/model IDs even when the underlying model is Claude.
# Explicit provider selection keeps extraction credentials separate from RAG.
OPENROUTER_BASE_URL = "https://openrouter.ai/api"
DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-4.5"
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5-20250929"
DEFAULT_MODEL = os.environ.get("H9N_EXTRACTION_MODEL") or (
    DEFAULT_OPENROUTER_MODEL
    if os.environ.get("H9N_EXTRACTION_PROVIDER", "anthropic").strip().lower() == "openrouter"
    else DEFAULT_ANTHROPIC_MODEL
)

# Every field now carries a citation, so the tool call is several times larger
# than the bare profile. Output tokens are only billed when generated, so a
# high ceiling costs nothing extra and keeps a long profile from truncating.
MAX_OUTPUT_TOKENS = 16000

# How many times the model gets to produce a valid tool call. The second
# attempt is shown exactly which fields failed validation.
MAX_OUTPUT_ATTEMPTS = 2

# Defaults and limits for the settings read by _extraction_settings().
# The timeout is the budget for a whole extraction - every request, retry and
# backoff - not per request, so a slow provider can't hold a request for
# (retries x timeout) the way per-request SDK retries would.
DEFAULT_TIMEOUT_SECONDS = 300
MAX_TIMEOUT_SECONDS = 3600
DEFAULT_MAX_RETRIES = 2
MAX_RETRIES_LIMIT = 10
# Roughly 150k tokens - inside the model's context window with room for the
# prompt and output. Longer packages fail clearly instead of mid-request.
DEFAULT_MAX_INPUT_CHARS = 600_000

# Retried with backoff (within the time budget): timeouts, connection
# failures, and these statuses plus any 5xx.
_TRANSIENT_STATUS_CODES = {408, 409, 429}
_MAX_BACKOFF_SECONDS = 8

# Module-level so tests can replace them.
_monotonic = time.monotonic
_sleep = time.sleep

EXTRACTION_TOOL_NAME = "extract_repe_deal_profile"

# The fields a reviewer most needs to know are missing. When one isn't stated
# in the document, the model is asked to say so in `missing_information`.
# (Since Milestone 1.1 every extracted value needs evidence, not just these.)
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


class ExtractionError(ValueError):
    """Base class for every controlled extraction failure. Messages are safe
    to return to an API caller: no model output, keys, or provider internals."""


class ExtractionInputError(ExtractionError):
    """The pages can't be extracted from (empty, malformed, or too long)."""


class ExtractionOutputError(ExtractionError):
    """The model's output was truncated, unreadable, or still invalid after a retry."""


class ExtractionRefusedError(ExtractionError):
    """The model declined to process the document."""


class ExtractionUnavailableError(ExtractionError):
    """The model provider timed out, was unreachable, or was overloaded."""


class ExtractionConfigurationError(ExtractionError):
    """Credentials, model name, or settings are wrong on our side."""


# The citation rules both prompts share, so an extraction and a correction are
# quoted - and checked - the same way.
_CITATION_RULES = f"""\
  - field_name: the exact schema field name, e.g. "asking_price".
  - value: the value, as plain text.
  - source_document: the file name from that page's marker.
  - page_number: the page number from that page's marker.
  - snippet: a quote of at least {MIN_SNIPPET_CHARS} characters (about one \
sentence) copied exactly, character for character, from that page's text, \
that contains the value. For a numeric field the snippet must include the \
number as written in the document, sign included (e.g. "$10.0M", "6.5%", \
"($150,000)"). For a text field the snippet must contain the value's words. \
Never paraphrase or invent a snippet.
  - If a label and its value are not next to each other in the text (as in a \
table), quote the label and the value with "..." between them, e.g. \
"Units ... 400". Use "..." only to skip a few words, never to skip over \
another number.
- A value without an evidence entry whose snippet can be found on the cited \
page, containing the value, will be withheld."""

SYSTEM_PROMPT = f"""You are H9N's structured extraction engine for real estate \
private equity (REPE) deal packages (CIMs, offering memoranda, and similar \
documents).

You will be given the full text of a deal package, broken into pages, each \
one marked with its source file name and page number, e.g. \
"--- taberna_cim.pdf | Page 3 ---". Your only job is to call the \
`{EXTRACTION_TOOL_NAME}` tool with the deal's information filled in as \
completely and accurately as possible.

Your output is checked automatically against the document. Any value that \
cannot be verified from its citation is withheld from the deal profile for a \
human reviewer, so accuracy matters more than completeness.

Rules:
- Only use information that is explicitly stated in the document text. Never \
guess, estimate, calculate, or infer a value that is not directly stated.
- Every field in the tool schema must be present. If a field is not stated \
anywhere in the document, set it to null. Never use a placeholder such as \
"N/A", "unknown", "TBD", or an empty string instead of null.
- If an important field ({_IMPORTANT_FIELDS_TEXT}) is not stated in the \
document, add an entry to `missing_information` that starts with the field \
name, e.g. "cap_rate: not stated in the document". Never list a field as \
missing if you give it a value.
- Normalize currency values to plain numbers (e.g. "$10,000,000" -> \
10000000, "$10.0M" -> 10000000). Normalize percentages to their numeric \
value (e.g. "6.5%" -> 6.5, and a fraction like "0.94" occupancy -> 94). Keep \
the sign: "($150,000)" or "-$150,000" -> -150000.
- For a text field, use words from the document. You may drop surrounding \
words and fix capitalization (e.g. "a self-storage facility" -> \
"Self-Storage", "MEADOWBROOK APARTMENTS" -> "Meadowbrook Apartments"), but \
never use a word that isn't in the snippet (don't turn "apartment community" \
into "Multifamily").
- For EVERY field you give a non-null value, add one entry to `evidence` with:
{_CITATION_RULES} Do not add evidence for a field you left null.
- If you find a value but are not fully confident it's correct - e.g. the \
wording is ambiguous or approximate ("around $10M"), or it comes from a less \
authoritative section than the rest of the document (a marketing summary \
rather than the financial statements) - still set it, cite it, and add an \
entry to `field_flags` with flag "uncertain" and a short note explaining why.
- If the document states two different values for the same field (e.g. two \
different asking prices in different sections), set the value from the more \
authoritative or more recent context, cite it, and add an entry to \
`field_flags` with flag "conflicting" and a note describing both values and \
where each appears. Do not silently drop either value.
- Flagged values are withheld for a human reviewer together with your note, \
so flag honestly: never flag a value just to avoid committing to it, and \
never leave a genuine doubt unflagged.
"""

_Output = TypeVar("_Output", bound=BaseModel)


def _inline_schema_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Expand local Pydantic definitions without weakening their constraints.

    Some provider translations lose `$ref` array-item schemas and treat nested
    evidence/flags as strings. Explicit object schemas work across those routes.
    This changes the schema sent to the model; local Pydantic validation and
    citation integrity checks remain authoritative. Never decode/coerce a bad
    model response to make it pass validation.
    """
    definitions = schema.get("$defs", {})

    def expand(node: Any, active: tuple[str, ...] = ()) -> Any:
        if isinstance(node, list):
            return [expand(item, active) for item in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            ref = node["$ref"]
            if not isinstance(ref, str) or not ref.startswith("#/$defs/") or ref in active:
                raise ExtractionConfigurationError("The extraction tool schema has an unsupported reference.")
            name = ref.removeprefix("#/$defs/")
            if name not in definitions:
                raise ExtractionConfigurationError("The extraction tool schema has an unresolved reference.")
            resolved = expand(definitions[name], (*active, ref))
            siblings = expand({key: value for key, value in node.items() if key != "$ref"}, active)
            return {**resolved, **siblings}
        return {key: expand(value, active) for key, value in node.items() if key != "$defs"}

    return expand(schema)


def _tool_definition(name: str, description: str, output_model: type[BaseModel]) -> dict[str, Any]:
    schema = _inline_schema_refs(output_model.model_json_schema())
    schema.pop("title", None)
    return {"name": name, "description": description, "input_schema": schema}


def _build_tool_schema() -> dict[str, Any]:
    """Builds the Anthropic tool definition from the strict extraction output
    model (Milestone 1.1): every value field required-but-nullable, no
    reviewer-owned fields, and no properties beyond the schema."""
    return _tool_definition(
        EXTRACTION_TOOL_NAME,
        "Records a REPEDealProfile extracted from the real estate deal "
        "package text provided by the user. Every field must be present; "
        "fields with no support in the source text are null. Every "
        "non-null value needs a matching `evidence` entry quoting the "
        "page it came from, and any value that isn't fully trustworthy "
        "(ambiguous, approximate, or contradicted elsewhere) needs a "
        "`field_flags` entry. Evidence and field_flags are arrays of JSON "
        "objects, never strings containing serialized objects.",
        REPEExtractionOutput,
    )


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


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ExtractionConfigurationError(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise ExtractionConfigurationError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _extraction_settings() -> tuple[int, int, int]:
    """(timeout_seconds, max_retries, max_input_chars), read at call time so a
    changed environment takes effect without a restart."""
    return (
        _env_int("H9N_EXTRACTION_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS, minimum=1, maximum=MAX_TIMEOUT_SECONDS),
        _env_int("H9N_EXTRACTION_MAX_RETRIES", DEFAULT_MAX_RETRIES, minimum=0, maximum=MAX_RETRIES_LIMIT),
        _env_int("H9N_EXTRACTION_MAX_INPUT_CHARS", DEFAULT_MAX_INPUT_CHARS, minimum=1, maximum=10_000_000),
    )


def _prepare_pages(pages: list[dict[str, Any]], *, caller: str = "extract_repe_deal()") -> list[dict[str, Any]]:
    """Checks the pages are well-formed and returns the ones with text, so a
    malformed page list fails clearly before any model call."""
    if not pages:
        raise ExtractionInputError(
            f"{caller} received no pages. Check that read_pdf() was able to open the file and returned page text."
        )

    seen: set[tuple[str, int]] = set()
    usable = []
    for page in pages:
        if not isinstance(page, dict):
            raise ExtractionInputError("Each page must be a dict with page_number and text.")
        page_number = page.get("page_number")
        text = page.get("text")
        file_name = page.get("file_name", "document")
        if isinstance(page_number, bool) or not isinstance(page_number, int) or page_number < 1:
            raise ExtractionInputError("Each page needs a positive integer page_number.")
        if not isinstance(text, str):
            raise ExtractionInputError(f"Page {page_number} has no text string.")
        if not isinstance(file_name, str):
            raise ExtractionInputError(f"Page {page_number} has a file_name that isn't text.")
        key = (file_name, page_number)
        if key in seen:
            raise ExtractionInputError(f"Page {page_number} appears more than once.")
        seen.add(key)
        if text.strip():
            usable.append(page)

    if not usable:
        raise ExtractionInputError("The document has no readable text to extract from.")
    return usable


def _build_client(provider: str | None = None) -> anthropic.Anthropic:
    provider = (provider or os.environ.get("H9N_EXTRACTION_PROVIDER", "anthropic")).strip().lower()
    if provider not in ("anthropic", "openrouter"):
        raise ExtractionConfigurationError("H9N_EXTRACTION_PROVIDER must be anthropic or openrouter.")
    if provider == "openrouter":
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not key:
            raise ExtractionConfigurationError("Set OPENROUTER_API_KEY for OpenRouter extraction.")
        # OpenRouter accepts native Messages requests at /api/v1/messages.
        # Bearer auth and an explicitly empty api_key prevent an unrelated
        # ANTHROPIC_API_KEY from being sent to OpenRouter. The same SDK/tool
        # shape preserves schema repair, evidence checks, usage, and deadlines.
        return anthropic.Anthropic(
            base_url=OPENROUTER_BASE_URL,
            api_key="",
            auth_token=key,
            max_retries=0,
            default_headers={"X-Api-Key": anthropic.omit},
        )
    try:
        # Retries are done by _send() within the time budget, not by the SDK.
        client = anthropic.Anthropic(max_retries=0)
    except anthropic.AnthropicError as exc:
        raise ExtractionConfigurationError("The Claude client could not be created.") from exc
    # The SDK only notices missing credentials when a request is sent (as a
    # TypeError), so check up front and fail with a clear configuration error.
    if not (client.api_key or client.auth_token or client.credentials):
        raise ExtractionConfigurationError(
            "No Claude credentials are configured. Set ANTHROPIC_API_KEY in .env or the runtime environment."
        )
    return client


def _prepare_client(client: Optional[anthropic.Anthropic], provider: str | None = None) -> anthropic.Anthropic:
    """The client to send with. A caller's own client keeps its settings but
    has its SDK retries switched off, so _send() is the only retry loop."""
    if client is None:
        return _build_client(provider)
    return client.with_options(max_retries=0)


def _provider_error(exc: anthropic.APIError, model: str) -> ExtractionError:
    """Maps an SDK error to a controlled ExtractionError, most specific first."""
    if isinstance(exc, anthropic.APITimeoutError):
        return ExtractionUnavailableError("The model provider timed out. Try again shortly.")
    if isinstance(exc, anthropic.APIConnectionError):
        return ExtractionUnavailableError("The model provider could not be reached. Try again shortly.")
    if isinstance(exc, anthropic.RateLimitError):
        return ExtractionUnavailableError("The model provider is rate limiting requests. Try again shortly.")
    if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
        return ExtractionConfigurationError("The model provider rejected H9N's credentials.")
    if isinstance(exc, anthropic.NotFoundError):
        return ExtractionConfigurationError(
            f"The extraction model {model!r} was not found. Check H9N_EXTRACTION_MODEL."
        )
    if isinstance(exc, anthropic.APIStatusError):
        if exc.status_code >= 500:
            return ExtractionUnavailableError("The model provider had an internal error. Try again shortly.")
        if exc.status_code == 413:
            return ExtractionInputError("The document is too large for a single extraction request.")
        return ExtractionConfigurationError(
            f"The model provider rejected the extraction request (HTTP {exc.status_code})."
        )
    return ExtractionOutputError("The model provider returned a response H9N could not read.")


def _is_transient(exc: anthropic.APIError) -> bool:
    if isinstance(exc, anthropic.APIConnectionError):  # includes timeouts
        return True
    return isinstance(exc, anthropic.APIStatusError) and (
        exc.status_code in _TRANSIENT_STATUS_CODES or exc.status_code >= 500
    )


def _send(llm_client: anthropic.Anthropic, *, deadline: float, max_retries: int, **request: Any):
    """One request, retried with backoff for transient provider failures
    while the time budget lasts. Each attempt may use only the time left, so
    the whole extraction ends by `deadline`."""
    if str(getattr(llm_client, "base_url", "")).rstrip("/") == OPENROUTER_BASE_URL:
        # Route only to endpoints supporting the forced tool-call parameters.
        # Local Pydantic validation remains mandatory for every returned call.
        request["extra_body"] = {"provider": {"require_parameters": True}}
    retry = 0
    while True:
        remaining = deadline - _monotonic()
        if remaining <= 0:
            raise ExtractionUnavailableError("The extraction ran out of time. Try again shortly.")
        try:
            return llm_client.messages.create(**request, timeout=remaining)
        except anthropic.APIError as exc:
            backoff = min(2**retry, _MAX_BACKOFF_SECONDS)
            if _is_transient(exc) and retry < max_retries and deadline - _monotonic() > backoff:
                logger.warning(
                    "H9N model request failed (%s); retry %d of %d in %ds",
                    type(exc).__name__,
                    retry + 1,
                    max_retries,
                    backoff,
                )
                _sleep(backoff)
                retry += 1
                continue
            raise _provider_error(exc, request["model"]) from exc


def _log_attempt(tool_name: str, attempt: int, response: Any) -> None:
    usage = getattr(response, "usage", None)
    logger.info(
        "H9N %s attempt %d: stop_reason=%s input_tokens=%s output_tokens=%s request_id=%s",
        tool_name,
        attempt,
        getattr(response, "stop_reason", None),
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
        getattr(response, "_request_id", None),
    )


def _summarize_validation_error(exc: ValidationError, *, limit: int = 25) -> str:
    """Field-by-field problems without echoing the model's values back."""
    lines = []
    for error in exc.errors(include_input=False, include_url=False)[:limit]:
        location = ".".join(str(part) for part in error["loc"]) or "(root)"
        lines.append(f"- {location}: {error['msg']}")
        if error["type"] == "model_type":
            lines.append("  Supply a JSON object with the declared properties, not a string containing JSON.")
    remaining = exc.error_count() - limit
    if remaining > 0:
        lines.append(f"- ...and {remaining} more")
    return "\n".join(lines)


def _call_tool(
    llm_client: anthropic.Anthropic,
    *,
    model: str,
    system: str,
    tool: dict[str, Any],
    prompt: str,
    output_model: type[_Output],
    deadline: float,
    max_retries: int,
) -> _Output:
    """Forces one call of `tool` and validates it against `output_model`,
    giving the model one more attempt - shown exactly what failed - if the
    call is missing or invalid. Anything else is a controlled error."""
    tool_name = tool["name"]
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    problem = ""  # Why the latest attempt failed; every retry path sets it.
    for attempt in range(1, MAX_OUTPUT_ATTEMPTS + 1):
        response = _send(
            llm_client,
            deadline=deadline,
            max_retries=max_retries,
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=system,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool_name, "disable_parallel_tool_use": True},
            messages=messages,
        )
        _log_attempt(tool_name, attempt, response)
        # Record before validation/refusal checks: discarded responses and
        # schema-repair attempts still consume billed tokens (M1.5).
        record_model_response(response, model)

        if response.stop_reason == "refusal":
            raise ExtractionRefusedError("The model declined to process this document.")
        if response.stop_reason == "max_tokens":
            # A truncated tool call can still parse as a smaller, valid-looking
            # object, so it's rejected outright rather than validated.
            raise ExtractionOutputError("The model's output was cut off before it finished, so it was discarded.")

        tool_call = next((block for block in response.content if block.type == "tool_use"), None)
        if tool_call is None:
            problem = "the model did not call the tool"
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": f"Call the `{tool_name}` tool with your answer."})
            continue

        try:
            return output_model.model_validate(tool_call.input)
        except ValidationError as exc:
            problem = f"{exc.error_count()} schema error(s)"
            summary = _summarize_validation_error(exc)
            logger.warning("H9N %s attempt %d failed validation:\n%s", tool_name, attempt, summary)
            messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_call.id,
                            "is_error": True,
                            "content": (
                                "The tool call did not match the tool schema, so none of it was saved. "
                                f"Fix these problems and call the tool again with the complete answer:\n{summary}"
                            ),
                        }
                    ],
                }
            )

    raise ExtractionOutputError(
        f"The model did not return a valid result after {MAX_OUTPUT_ATTEMPTS} attempts ({problem}), "
        "so nothing was saved."
    )


def extract_repe_deal(
    pages: list[dict[str, Any]],
    *,
    client: Optional[anthropic.Anthropic] = None,
    model: str = DEFAULT_MODEL,
    provider: str | None = None,
) -> REPEDealProfile:
    """Sends page-preserved deal package text to Claude and returns a
    REPEDealProfile whose value fields hold only verified values.

    Parameters
    ----------
    pages:
        The list of {"file_name", "page_number", "text"} dicts produced by
        `read_pdf()`.
    client:
        An existing `anthropic.Anthropic` client to reuse (its own SDK retries
        are switched off; H9N's retries apply). If not provided, one is built
        from the configured provider's environment credentials.
    model:
        The provider's model ID, such as an OpenRouter author/model ID.
    provider:
        "anthropic" or "openrouter"; defaults to H9N_EXTRACTION_PROVIDER.

    Returns
    -------
    REPEDealProfile
        A schema-validated deal profile. Fields the document doesn't state
        are None. Values the model proposed but couldn't back up - or flagged
        itself - are also None in their fields, and listed in
        `withheld_values` for a human reviewer.

    Raises
    ------
    ExtractionInputError
        If `pages` is empty, malformed, blank, or too long.
    ExtractionOutputError
        If the model's output was truncated, or still didn't match the
        schema after `MAX_OUTPUT_ATTEMPTS` attempts.
    ExtractionRefusedError
        If the model declined the request.
    ExtractionUnavailableError
        If the provider timed out, was unreachable, or overloaded, or the
        time budget ran out.
    ExtractionConfigurationError
        If credentials, the model name, or a setting is wrong.

    All of these subclass ValueError (via ExtractionError).
    """
    usable_pages = _prepare_pages(pages)
    timeout_seconds, max_retries, max_input_chars = _extraction_settings()

    document_text = _pages_to_document_text(usable_pages)
    if len(document_text) > max_input_chars:
        raise ExtractionInputError(
            f"The document has {len(document_text):,} characters of text, more than the "
            f"{max_input_chars:,} a single extraction can read. Split the package and try again."
        )

    output = _call_tool(
        _prepare_client(client, provider),
        model=model,
        system=SYSTEM_PROMPT,
        tool=_build_tool_schema(),
        prompt=(
            "Extract the real estate deal information from the following deal package text. "
            "The text is split by page so you can locate where each value came from.\n\n"
            f"{document_text}"
        ),
        output_model=REPEExtractionOutput,
        deadline=_monotonic() + timeout_seconds,
        max_retries=max_retries,
    )
    return enforce_integrity(output, usable_pages)


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

Your corrections are checked automatically against the document. A \
correction that cannot be verified from its citation is not applied; it is \
shown to the reviewer instead.

Rules:
- Only change fields the reviewer's note indicates are actually wrong. Leave \
every other field alone - do not "helpfully" re-extract fields the reviewer \
didn't flag, even if you'd extract them differently a second time.
- Only use information explicitly stated in the document text to decide the \
corrected value. Never guess, estimate, calculate, or invent a value - if the \
reviewer's note points at a field but the document doesn't clearly support a \
specific corrected value, leave that field out of `corrections` and explain \
why in `explanation`.
- `corrections` maps deal field names (e.g. "asking_price") to corrected \
values. Include only fields that are actually changing. Set a field to null \
only if the document doesn't state it at all. Normalize numbers the same way \
as an extraction: "$950K" -> 950000, "6.5%" -> 6.5, signs kept.
- For EVERY non-null value in `corrections`, add one entry to \
`updated_evidence` with:
{_CITATION_RULES} Don't add an `updated_evidence` entry for a field that \
isn't in `corrections`.
- `explanation` is a short (one or two sentence) note of what was wrong and \
what you changed, for the audit trail - written for the reviewer, not the \
document author.
"""


def _build_feedback_tool_schema() -> dict[str, Any]:
    return _tool_definition(
        FEEDBACK_TOOL_NAME,
        "Records the corrected field value(s) for a REPEDealProfile "
        "that a human reviewer has flagged as wrong, based on the "
        "reviewer's own explanation and the original deal package text. "
        "Every corrected value needs an `updated_evidence` entry quoting "
        "the page it came from.",
        ReviewerFeedbackOutput,
    )


def apply_reviewer_feedback(
    pages: list[dict[str, Any]],
    deal: REPEDealProfile,
    feedback: str,
    *,
    client: Optional[anthropic.Anthropic] = None,
    model: str = DEFAULT_MODEL,
    provider: str | None = None,
) -> dict[str, Any]:
    """Given the original document pages, the current (reviewer-flagged)
    deal profile, and the reviewer's own explanation of what's wrong, asks
    Claude to re-derive just the affected field(s) from the source text.

    The answer is validated as strictly as an extraction (only deal value
    fields, real types, sane bounds), and each corrected value is checked
    against the pages the same way (`verify_corrections`): a correction whose
    citation doesn't hold up is not applied, but returned in `withheld`.

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
        {"corrections": {field_name: value, ...},     # verified, or cleared to None
         "updated_evidence": [FieldEvidence, ...],    # one per non-null correction
         "withheld": [WithheldValue, ...],            # proposed but not verified
         "explanation": "..."}
        Pass it to `feedback_updates()` to get the one update to save.

    Raises
    ------
    ExtractionError
        The same controlled errors as `extract_repe_deal` (all ValueErrors):
        empty pages or feedback, provider failures, output still invalid
        after a retry.
    """
    usable_pages = _prepare_pages(pages, caller="apply_reviewer_feedback()")
    if not feedback or not feedback.strip():
        raise ExtractionInputError("apply_reviewer_feedback() requires non-empty reviewer feedback.")
    timeout_seconds, max_retries, max_input_chars = _extraction_settings()

    document_text = _pages_to_document_text(usable_pages)
    if len(document_text) > max_input_chars:
        raise ExtractionInputError(
            f"The document has {len(document_text):,} characters of text, more than the "
            f"{max_input_chars:,} a single request can read."
        )

    output = _call_tool(
        _prepare_client(client, provider),
        model=model,
        system=FEEDBACK_SYSTEM_PROMPT,
        tool=_build_feedback_tool_schema(),
        prompt=(
            "Here is the original deal package text, split by page:\n\n"
            f"{document_text}\n\n"
            "Here is the REPEDealProfile as currently extracted (as JSON):\n\n"
            f"{json.dumps(deal.model_dump(), indent=2)}\n\n"
            f"Here is the reviewer's explanation of what's wrong with it:\n\n{feedback}"
        ),
        output_model=ReviewerFeedbackOutput,
        deadline=_monotonic() + timeout_seconds,
        max_retries=max_retries,
    )
    verified = verify_corrections(output.corrections, output.updated_evidence, usable_pages)
    return {
        "corrections": verified.values,
        "updated_evidence": verified.evidence,
        "withheld": verified.withheld,
        "explanation": output.explanation,
    }


def feedback_updates(deal: REPEDealProfile, result: dict[str, Any]) -> dict[str, Any]:
    """The single `DealStore.apply_corrections()` update for an
    `apply_reviewer_feedback()` result, or {} if nothing changes.

    Shared by the API (main.py's review endpoint) and the interactive demo,
    so a feedback-driven correction is applied the same way by both:
    - corrected values are set (and so recorded in corrected_fields);
    - each corrected field's old citation is replaced by the new, verified
      one, and a field cleared to null loses its citation;
    - any withheld entry for a corrected field is resolved (superseded), and
      corrections that didn't verify are added as new withheld entries;
    - the deal goes back to "pending" for a human to look again.
    """
    corrections: dict[str, Any] = result.get("corrections") or {}
    withheld = [WithheldValue.model_validate(item) for item in result.get("withheld") or []]
    if not corrections and not withheld:
        return {}

    changed = set(corrections)
    new_evidence = [FieldEvidence.model_validate(item) for item in result.get("updated_evidence") or []]
    return {
        **corrections,
        "evidence": [entry for entry in deal.evidence if entry.field_name not in changed] + new_evidence,
        "withheld_values": [entry for entry in deal.withheld_values if entry.field_name not in changed] + withheld,
        "review_status": "pending",
    }
