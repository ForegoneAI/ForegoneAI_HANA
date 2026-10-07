"""
extraction_output.py

H9N Milestone 1.1 - the strict shape the model's extraction must take, and the
deterministic checks that decide which extracted values are stored.

Two layers stand between the model and the database:

1. `REPEExtractionOutput` validates the raw tool call. Every value field must
   be present (an explicit null when the document doesn't state it), unknown
   or reviewer-owned fields are rejected, placeholder strings like "N/A" become
   null, numbers must be real JSON numbers (not booleans or strings), and
   obviously impossible numbers (a 650% cap rate) are rejected. A tool call
   that fails here is retried and then fails the extraction - it is never
   partially stored. `ReviewerFeedbackOutput` does the same for a
   feedback-driven correction.

2. `enforce_integrity` (and `verify_corrections`, for feedback) then checks
   every value against the source pages. A value is stored only if its
   evidence cites a real page and quotes at least `MIN_SNIPPET_CHARS`
   characters that are actually on that page, and the quoted passage of the
   page contains the value: the same number (sign, scale and unit included)
   for a numeric field, the same words for a text field. The narrative fields
   in `QUOTE_ONLY_FIELDS` can't be matched word for word, so for them only the
   quote is checked and their evidence is labelled "quote_only". A value the
   model itself flagged as uncertain or conflicting, or listed as missing, is
   not stored either. Everything not stored is left null in the profile and
   recorded in `withheld_values` with the proposed value, the reason, and the
   citation, so a human reviewer can accept or dismiss it (Milestone 2).
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal, Optional, Union, get_args

from pydantic import BaseModel, ConfigDict, Field, create_model, field_validator, model_validator

from backend.app.h9n.schemas.base_deal import EvidenceVerification, FieldEvidence, WithheldReason, WithheldValue
from backend.app.h9n.schemas.repe_deal import REPEDealProfile


# Profile fields that describe the extraction rather than the deal. The model
# fills some of them in through its own shape (see REPEExtractionOutput), but
# none of them is a deal value that needs evidence.
_META_FIELDS = {
    "missing_information",
    "conflicting_information",
    "uncertain_information",
    "evidence",
}

# Fields only a human reviewer (or the review workflow) may set. They are kept
# out of the tool schemas entirely, so the model cannot approve its own work.
NON_EXTRACTABLE_FIELDS = {
    "corrected_fields",
    "review_status",
    "review_feedback",
    "withheld_values",
}

# Every deal value the model is asked to extract, in schema order - and every
# one of them needs verifiable evidence, not just the headline fields. Derived
# from REPEDealProfile so a field added there is extracted and checked here
# without anyone having to remember to update this module.
VALUE_FIELDS: list[str] = [
    name
    for name in REPEDealProfile.model_fields
    if name not in _META_FIELDS and name not in NON_EXTRACTABLE_FIELDS
]


def _field_types(field_name: str) -> tuple[Any, ...]:
    return get_args(REPEDealProfile.model_fields[field_name].annotation)


NUMERIC_FIELDS = {name for name in VALUE_FIELDS if int in _field_types(name) or float in _field_types(name)}
_INTEGER_FIELDS = {name for name in VALUE_FIELDS if int in _field_types(name)}

# Narrative fields the model summarizes from several passages, so the value
# never appears word for word in one quote. Their quote is still checked, but
# their evidence is labelled "quote_only" rather than "value_matched", and
# later stages (M1.2 status, M3.3 screening, M5.3 verifier) must treat them as
# needing a human look.
QUOTE_ONLY_FIELDS = {"business_plan", "investment_strategy"}

# A quote shorter than this (ignoring whitespace and "...") appears on almost
# any page by chance, so it shows nothing about where a value came from.
MIN_SNIPPET_CHARS = 8

# How far apart two "..."-separated pieces of a quote may be on the page. Long
# enough for a label and its value in a table, short enough that a quote
# can't pair a label with something from another part of the page.
MAX_ELLIPSIS_GAP_CHARS = 150

# Sanity bounds for numbers. Percentages are stored as their numeric value
# (6.5 means 6.5%), so anything outside 0-100 is malformed. NOI is left
# unbounded because a property can genuinely operate at a loss.
_PERCENT_FIELDS = {"cap_rate", "occupancy_rate", "ltv", "interest_rate"}
_NON_NEGATIVE_FIELDS = {
    "asking_price",
    "square_feet",
    "annual_revenue",
    "operating_expenses",
    "loan_amount",
    "sponsor_equity",
    "units",
    "loan_term_years",
}
_CURRENCY_FIELDS = {"asking_price", "annual_revenue", "operating_expenses", "noi", "loan_amount", "sponsor_equity"}

# Which kinds of number in the text can support each numeric field: a cap
# rate can't come from "$6,500,000", and an asking price can't come from
# "128 units". "plain" is a number with no %, currency sign, or unit word.
_SUPPORTING_KINDS: dict[str, set[str]] = {
    **{name: {"currency", "plain"} for name in _CURRENCY_FIELDS},
    **{name: {"percent", "plain"} for name in _PERCENT_FIELDS},
    "units": {"plain", "units"},
    "square_feet": {"plain", "area"},
    "year_built": {"plain", "years"},
    "loan_term_years": {"plain", "years"},
}

# Strings models sometimes use instead of null. Compared case-insensitively,
# ignoring trailing punctuation ("N/A." is still N/A).
_PLACEHOLDERS = {
    "",
    "n/a",
    "na",
    "n.a",
    "none",
    "null",
    "-",
    "--",
    "tbd",
    "unknown",
    "not stated",
    "not available",
    "not applicable",
    "not disclosed",
    "not specified",
    "not provided",
    "undisclosed",
    "unspecified",
}

_ValueFieldName = Literal[tuple(VALUE_FIELDS)]  # type: ignore[valid-type]


class ExtractedEvidence(BaseModel):
    """One citation as the model must supply it: every part required."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    field_name: _ValueFieldName  # type: ignore[valid-type]
    value: str = Field(min_length=1)
    source_document: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    snippet: str = Field(min_length=1)

    @field_validator("value", mode="before")
    @classmethod
    def _value_as_text(cls, value: Any) -> Any:
        # `value` is display text for the reviewer; a bare number is fine.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        return value


class FieldFlag(BaseModel):
    """The model's own statement that a value it found shouldn't be trusted as-is."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    field_name: _ValueFieldName  # type: ignore[valid-type]
    flag: Literal["uncertain", "conflicting"]
    note: str = Field(min_length=1)


class _ValueFieldsBase(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)

    @model_validator(mode="before")
    @classmethod
    def _placeholders_to_null(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        cleaned = dict(data)
        for name in VALUE_FIELDS:
            value = cleaned.get(name)
            if isinstance(value, str) and value.strip().rstrip(".").strip().lower() in _PLACEHOLDERS:
                cleaned[name] = None
        return cleaned


def _value_field_definition(name: str, *, required: bool) -> tuple[Any, Any]:
    annotation = REPEDealProfile.model_fields[name].annotation
    constraints: dict[str, Any] = {}
    if name in NUMERIC_FIELDS:
        # A real JSON number only: no `true` for units=1, no "10000000" strings.
        constraints["strict"] = True
    if name in _PERCENT_FIELDS:
        constraints.update(ge=0, le=100)
    elif name in _NON_NEGATIVE_FIELDS:
        constraints.update(ge=0)
    elif name == "year_built":
        constraints.update(ge=1700, le=2100)
    # `...` makes the field required: the model must state null explicitly
    # rather than leave a field out.
    return annotation, Field(... if required else None, **constraints)


# The exact shape of the extraction tool call. Built from REPEDealProfile so the
# two can't drift apart, minus reviewer-owned fields, with every value field
# required-but-nullable and anything unexpected rejected.
if TYPE_CHECKING:

    class REPEExtractionOutput(_ValueFieldsBase):
        missing_information: list[str]
        evidence: list[ExtractedEvidence]
        field_flags: list[FieldFlag]

        def __getattr__(self, name: str) -> Any: ...

    class ReviewerCorrections(_ValueFieldsBase):
        def __getattr__(self, name: str) -> Any: ...

else:
    REPEExtractionOutput = create_model(
        "REPEExtractionOutput",
        __base__=_ValueFieldsBase,
        **{name: _value_field_definition(name, required=True) for name in VALUE_FIELDS},
        missing_information=(list[str], Field(...)),
        evidence=(list[ExtractedEvidence], Field(...)),
        field_flags=(list[FieldFlag], Field(...)),
    )

    # A reviewer-feedback correction: any subset of the value fields, held to
    # the same types and bounds, and nothing else (no review_status, no
    # withheld_values). `model_fields_set` says which fields it changes.
    ReviewerCorrections = create_model(
        "ReviewerCorrections",
        __base__=_ValueFieldsBase,
        **{name: _value_field_definition(name, required=False) for name in VALUE_FIELDS},
    )


class ReviewerFeedbackOutput(BaseModel):
    """The exact shape of the reviewer-feedback tool call."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    corrections: ReviewerCorrections
    updated_evidence: list[ExtractedEvidence] = Field(default_factory=list)
    explanation: str


# --- Text normalization -----------------------------------------------------

_QUOTE_FOLDS = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "′": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "″": '"',
        "‐": "-",
        "‑": "-",
        "‒": "-",
        "–": "-",
        "—": "-",
        "―": "-",
        "−": "-",
    }
)
# Soft hyphens and zero-width characters are invisible in a PDF but break
# matching ("occu­pancy" vs "occupancy").
_INVISIBLE = re.compile("[­​‌‍⁠﻿]")
# A word broken across lines with a hyphen: "occu-\npancy".
_LINE_BREAK_HYPHEN = re.compile(r"(?<=[^\W\d_])-[ \t]*\n\s*(?=[^\W\d_])")
_WHITESPACE = re.compile(r"\s+")
_WORD = re.compile(r"[^\W_]+")


def _normalize(text: str, *, join_line_hyphens: bool = False) -> str:
    """NFKC (ligatures like "fi", "…" -> "..."), curly quotes and dashes to
    ASCII, invisible characters removed, case-insensitive. Whitespace runs
    collapse to one character - a newline if the run had one, else a space -
    so line structure is kept but spacing differences don't matter."""
    text = unicodedata.normalize("NFKC", text).translate(_QUOTE_FOLDS)
    text = _INVISIBLE.sub("", text)
    if join_line_hyphens:
        text = _LINE_BREAK_HYPHEN.sub("", text)
    text = _WHITESPACE.sub(lambda run: "\n" if "\n" in run.group() else " ", text)
    return text.casefold().strip()


def _quote_parts(snippet: str) -> list[str]:
    return [part.strip() for part in _normalize(snippet).split("...") if part.strip()]


def _quoted_chars(snippet: str) -> int:
    return sum(len(_WHITESPACE.sub("", part)) for part in _quote_parts(snippet))


def _part_pattern(part: str) -> str:
    """A regex for one quoted piece. Letters/digits next to each other in the
    quote must be next to each other on the page (so "2400" can't match
    "2\\n400"), a space between two words must be whitespace on the page, and
    whitespace next to punctuation is optional (PDF text is inconsistent
    there). The piece can't start or end in the middle of a word or number."""
    pieces: list[str] = []
    previous = ""
    spaced = False
    for char in part:
        if char.isspace():
            spaced = True
            continue
        if previous:
            if previous.isalnum() and char.isalnum():
                pieces.append(r"\s" if spaced else "")
            else:
                pieces.append(r"\s?")
        pieces.append(re.escape(char))
        previous, spaced = char, False
    pattern = "".join(pieces)
    if part[:1].isalnum():
        pattern = r"(?<![^\W_])" + pattern
    if part[-1:].isalnum():
        pattern += r"(?![^\W_])"
    return pattern


def _locate(parts: list[str], page: str, gap_allowed: Callable[[str], bool]) -> Optional[list[tuple[int, int]]]:
    """Where each quoted piece sits on the (normalized) page, in order, with
    every gap no longer than MAX_ELLIPSIS_GAP_CHARS and passing `gap_allowed`.
    Returns the matched spans, or None if the quote isn't on the page."""
    patterns = [re.compile(_part_pattern(part)) for part in parts]

    def search(index: int, start: int) -> Optional[list[tuple[int, int]]]:
        if index == len(patterns):
            return []
        for match in patterns[index].finditer(page, start):
            if index > 0:
                gap = page[start : match.start()]
                if len(gap) > MAX_ELLIPSIS_GAP_CHARS:
                    break
                if not gap_allowed(gap):
                    continue
            rest = search(index + 1, match.end())
            if rest is not None:
                return [match.span(), *rest]
        return None

    return search(0, 0)


def _find_quote(
    snippet: str, page_text: str, *, numeric: bool = False
) -> Optional[tuple[str, list[tuple[int, int]]]]:
    """The normalized page the quote was found on and its spans there, or None.
    For a numeric field a "..." gap may not skip over another number - that's
    how a label gets paired with the wrong figure."""
    parts = _quote_parts(snippet)
    if not parts:
        return None
    gap_allowed = (lambda gap: not any(char.isdigit() for char in gap)) if numeric else (lambda gap: True)
    for join_line_hyphens in (False, True):
        page = _normalize(page_text, join_line_hyphens=join_line_hyphens)
        spans = _locate(parts, page, gap_allowed)
        if spans is not None:
            return page, spans
    return None


def snippet_is_on_page(snippet: str, page_text: str) -> bool:
    """Whether `snippet` appears on the page, tolerating formatting noise:
    case, spacing and line breaks, curly quotes and dashes, ligatures,
    invisible characters, a word hyphenated across a line, and "..." between
    quoted pieces that are close together on the page."""
    return _find_quote(snippet, page_text) is not None


# --- Numbers ----------------------------------------------------------------

_DIGITS = re.compile(r"(?<![\w.])(?:\d(?:[\d,]*\d)?(?:\.\d+)?|\.\d+)")
# What may come right before a number: "(", a minus sign, "$". A minus right
# after a letter or digit is a range or a hyphenated word, not a sign.
_PREFIX = re.compile(
    r"(?:(?P<paren>\()\s?)?(?:(?P<minus>(?<![^\W_])-)\s?)?(?:(?P<currency>\$|usd)\s?(?:(?P<minus2>-)\s?)?)?$"
)
_SUFFIX = re.compile(r"(?P<space> ?)(?:(?P<percent>%|percent\b)|(?P<scale>thousand|million|billion|mm|bn|[kmb])\b)?")
_FOLLOWING_WORD = re.compile(r"[ ]?-?[ ]?(?P<word>[^\W\d_]+)")
_SCALES = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
_UNIT_WORDS = {
    "unit": "units",
    "units": "units",
    "sf": "area",
    "rsf": "area",
    "nrsf": "area",
    "gsf": "area",
    "sq": "area",
    "square": "area",
    "year": "years",
    "years": "years",
    "yr": "years",
    "yrs": "years",
    "acre": "other",
    "acres": "other",
    "bed": "other",
    "beds": "other",
    "key": "other",
    "keys": "other",
    "room": "other",
    "rooms": "other",
    "space": "other",
    "spaces": "other",
    "story": "other",
    "stories": "other",
    "building": "other",
    "buildings": "other",
    "mile": "other",
    "miles": "other",
    "month": "other",
    "months": "other",
    "day": "other",
    "days": "other",
}


@dataclass(frozen=True)
class _Number:
    start: int
    end: int
    value: float  # signed and scaled: "($1.5M)" is -1500000
    kind: str  # "percent", "currency", a _UNIT_WORDS kind, or "plain"


def _numbers(page: str) -> list[_Number]:
    """Every number on a normalized page, read with its context."""
    numbers = []
    for match in _DIGITS.finditer(page):
        start, end = match.span()
        value = float(match.group().replace(",", ""))

        prefix = _PREFIX.search(page, max(0, start - 8), start)
        currency = bool(prefix and prefix.group("currency"))
        negative = bool(prefix and (prefix.group("minus") or prefix.group("minus2")))

        kind = "plain"
        suffix = _SUFFIX.match(page, end)
        after = end
        if suffix and suffix.group("percent"):
            kind, after = "percent", suffix.end()
        elif suffix and suffix.group("scale"):
            scale = suffix.group("scale")
            # "10.0M" and "$10 M" are millions; "5 m from downtown" is not.
            if len(scale) > 1 or not suffix.group("space") or currency:
                value *= _SCALES[scale]
                after = suffix.end()

        if prefix and prefix.group("paren") and page.startswith(")", after):
            negative = True
        if currency:
            kind = "currency" if kind == "plain" else kind
        elif kind == "plain":
            following = _FOLLOWING_WORD.match(page, after)
            word = following.group("word") if following else ""
            if word in ("dollars", "usd"):
                kind = "currency"
            elif word in _UNIT_WORDS:
                kind = _UNIT_WORDS[word]

        numbers.append(_Number(start=start, end=end, value=-value if negative else value, kind=kind))
    return numbers


def numbers_in_text(text: str) -> list[float]:
    """Every number written in `text`, signed and with $10.0M / 950K style
    suffixes applied."""
    return [number.value for number in _numbers(_normalize(text))]


def _number_supports(field_name: str, value: Union[int, float], number: _Number) -> bool:
    if number.kind not in _SUPPORTING_KINDS.get(field_name, {"plain"}):
        return False
    candidates = [number.value]
    if field_name in _PERCENT_FIELDS and number.kind == "plain" and 0 < number.value <= 1:
        candidates.append(number.value * 100)  # "Occupancy: 0.94" is 94%
    return any(math.isclose(candidate, value, rel_tol=1e-9, abs_tol=1e-9) for candidate in candidates)


def _contains_words(haystack: list[str], needle: list[str]) -> bool:
    width = len(needle)
    return any(haystack[i : i + width] == needle for i in range(len(haystack) - width + 1))


def _value_in_quote(field_name: str, value: Any, page: str, spans: list[tuple[int, int]]) -> bool:
    """Whether the quoted part of the page holds `value` itself."""
    if field_name in NUMERIC_FIELDS:
        return any(
            _number_supports(field_name, value, number)
            for number in _numbers(page)
            if any(number.start < end and start < number.end for start, end in spans)
        )
    value_words = _WORD.findall(_normalize(str(value)))
    if not value_words:
        return False
    for start, end in spans:
        # Widen to whole words so a quote that clips a word still counts it.
        while start > 0 and page[start - 1].isalnum():
            start -= 1
        while end < len(page) and page[end].isalnum():
            end += 1
        if _contains_words(_WORD.findall(page[start:end]), value_words):
            return True
    return False


def snippet_supports_value(field_name: str, value: Any, snippet: str, page_text: str) -> bool:
    """The full evidence check for one citation, as `enforce_integrity` applies it."""
    return _verification(field_name, value, snippet, page_text)[0] is None


# --- Evidence verification --------------------------------------------------


def _display(value: Any) -> str:
    """The stored value as evidence text: 10000000.0 reads "10000000"."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _verification(
    field_name: str, value: Any, snippet: str, page_text: str
) -> tuple[Optional[tuple[WithheldReason, str]], Optional[EvidenceVerification]]:
    """(why the snippet fails to support `value`, or None; how it was verified)."""
    if _quoted_chars(snippet) < MIN_SNIPPET_CHARS:
        return (
            "snippet_too_short",
            f"The quoted snippet is under {MIN_SNIPPET_CHARS} characters, too short to show where the value came from.",
        ), None
    found = _find_quote(snippet, page_text, numeric=field_name in NUMERIC_FIELDS)
    if found is None:
        return ("snippet_not_on_page", "The quoted snippet was not found on the cited page."), None
    if field_name in QUOTE_ONLY_FIELDS:
        return None, "quote_only"
    page, spans = found
    if not _value_in_quote(field_name, value, page, spans):
        return ("value_not_in_snippet", f"The quoted passage does not contain the value {_display(value)!r}."), None
    return None, "value_matched"


def _find_page(entry: ExtractedEvidence, pages: list[dict[str, Any]]) -> tuple[Optional[dict[str, Any]], str]:
    """The cited page, or None and why not."""
    matches = [page for page in pages if page["page_number"] == entry.page_number]
    if len(matches) > 1:
        # Only possible when several documents are extracted together; the
        # cited file name picks between them.
        named = [page for page in matches if _normalize(page.get("file_name", "")) == _normalize(entry.source_document)]
        if len(named) == 1:
            return named[0], ""
        return None, (
            f"Page {entry.page_number} exists in more than one document and the citation's file name "
            f"{entry.source_document!r} doesn't pick one."
        )
    if not matches:
        return None, f"The citation points to page {entry.page_number}, which has no text in the document."
    return matches[0], ""


def _citation(
    entry: ExtractedEvidence,
    value: Any,
    page: Optional[dict[str, Any]],
    verification: Optional[EvidenceVerification] = None,
) -> FieldEvidence:
    """Plain FieldEvidence for the profile: the value text is the value actually
    proposed (not however the model wrote it), and the file name is taken from
    the page actually cited."""
    source_document = page.get("file_name", entry.source_document) if page else entry.source_document
    return FieldEvidence(
        field_name=entry.field_name,
        value=_display(value),
        source_document=source_document,
        page_number=entry.page_number,
        snippet=entry.snippet,
        verification=verification,
    )


@dataclass
class _FieldCheck:
    verified: Optional[FieldEvidence] = None
    failure: Optional[tuple[WithheldReason, str, FieldEvidence]] = None


def _check_field(
    field_name: str, value: Any, entries: list[ExtractedEvidence], pages: list[dict[str, Any]]
) -> _FieldCheck:
    """The first citation that verifies `value`, else the first failure."""
    check = _FieldCheck()
    for entry in entries:
        page, page_problem = _find_page(entry, pages)
        if page is None:
            problem: Optional[tuple[WithheldReason, str]] = ("page_not_in_document", page_problem)
            verification = None
        else:
            problem, verification = _verification(field_name, value, entry.snippet, page["text"])
        if problem is None:
            check.verified = _citation(entry, value, page, verification)
            return check
        if check.failure is None:
            check.failure = (*problem, _citation(entry, value, page))
    return check


def _withheld_from_check(field_name: str, value: Any, check: _FieldCheck, no_evidence_detail: str) -> WithheldValue:
    if check.failure is not None:
        reason, detail, cited = check.failure
        return WithheldValue(field_name=field_name, proposed_value=value, reason=reason, detail=detail, evidence=cited)
    return WithheldValue(field_name=field_name, proposed_value=value, reason="no_evidence", detail=no_evidence_detail)


def _fields_listed_as_missing(notes: list[str]) -> dict[str, str]:
    """Value fields a missing_information note names ("cap_rate: not stated",
    "cap rate not stated"), mapped to the note."""
    named: dict[str, str] = {}
    for note in notes:
        folded = note.strip().casefold()
        for field_name in VALUE_FIELDS:
            for label in (field_name, field_name.replace("_", " ")):
                rest = folded[len(label) :]
                if folded.startswith(label) and not (rest[:1].isalnum() or rest[:1] == "_"):
                    named.setdefault(field_name, note)
    return named


def _evidence_by_field(entries: list[ExtractedEvidence]) -> dict[str, list[ExtractedEvidence]]:
    grouped: dict[str, list[ExtractedEvidence]] = defaultdict(list)
    for entry in entries:
        grouped[entry.field_name].append(entry)
    return grouped


def enforce_integrity(output: REPEExtractionOutput, pages: list[dict[str, Any]]) -> REPEDealProfile:
    """Turns a validated extraction into a REPEDealProfile holding only verified values.

    Every non-null value lands in exactly one of two places:
    - its field, with its evidence, when a citation checks out and the model
      neither flagged it nor listed it as missing; or
    - `withheld_values` (its field left null), with the reason and whatever
      citation the model gave, for a human reviewer to accept or dismiss.
    """
    evidence_by_field = _evidence_by_field(output.evidence)
    flags_by_field: dict[str, list[FieldFlag]] = defaultdict(list)
    for flag in output.field_flags:
        flags_by_field[flag.field_name].append(flag)
    listed_missing = _fields_listed_as_missing(output.missing_information)

    values: dict[str, Any] = {}
    kept_evidence: list[FieldEvidence] = []
    withheld: list[WithheldValue] = []

    for field_name in VALUE_FIELDS:
        value = getattr(output, field_name)
        if value is None:
            continue

        check = _check_field(field_name, value, evidence_by_field.get(field_name, []), pages)
        cited = check.verified or (check.failure[2] if check.failure else None)
        flags = flags_by_field.get(field_name)

        if flags:
            reason: WithheldReason = (
                "model_conflicting" if any(flag.flag == "conflicting" for flag in flags) else "model_uncertain"
            )
            detail = "; ".join(flag.note for flag in flags)
        elif field_name in listed_missing:
            reason = "model_listed_as_missing"
            detail = f"The extraction also listed this field as missing: {listed_missing[field_name]!r}"
        elif check.verified is not None:
            values[field_name] = value
            kept_evidence.append(check.verified)
            continue
        else:
            withheld.append(
                _withheld_from_check(
                    field_name, value, check, "The model gave this value without citing where it came from."
                )
            )
            continue

        if cited is not None:
            cited = cited.model_copy(update={"verification": None})
        withheld.append(
            WithheldValue(field_name=field_name, proposed_value=value, reason=reason, detail=detail, evidence=cited)
        )

    uncertain_information = [
        f"{flag.field_name}: {flag.note}" for flag in output.field_flags if flag.flag == "uncertain"
    ]
    conflicting_information = [
        f"{flag.field_name}: {flag.note}" for flag in output.field_flags if flag.flag == "conflicting"
    ]

    return REPEDealProfile(
        **values,
        missing_information=list(output.missing_information),
        conflicting_information=conflicting_information,
        uncertain_information=uncertain_information,
        evidence=kept_evidence,
        withheld_values=withheld,
    )


@dataclass
class VerifiedCorrections:
    """What a reviewer-feedback correction may change, after the evidence checks."""

    values: dict[str, Any]  # verified new values, plus fields cleared to null
    evidence: list[FieldEvidence]  # one verified citation per non-null value
    withheld: list[WithheldValue]  # proposed corrections that didn't verify


def verify_corrections(
    corrections: ReviewerCorrections, evidence: list[ExtractedEvidence], pages: list[dict[str, Any]]
) -> VerifiedCorrections:
    """Holds a feedback-driven correction to the same evidence standard as an
    extraction. Clearing a field (null) needs no citation - it can't invent a
    value; a new value is applied only if a citation verifies it, and is
    otherwise returned as withheld for the reviewer."""
    evidence_by_field = _evidence_by_field(evidence)
    result = VerifiedCorrections(values={}, evidence=[], withheld=[])
    for field_name in VALUE_FIELDS:
        if field_name not in corrections.model_fields_set:
            continue
        value = getattr(corrections, field_name)
        if value is None:
            result.values[field_name] = None
            continue
        check = _check_field(field_name, value, evidence_by_field.get(field_name, []), pages)
        if check.verified is not None:
            result.values[field_name] = value
            result.evidence.append(check.verified)
        else:
            result.withheld.append(
                _withheld_from_check(
                    field_name, value, check, "The correction was proposed without citing where it came from."
                )
            )
    return result
