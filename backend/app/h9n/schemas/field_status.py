"""
field_status.py

H9N Milestone 1.2 - one trust status per extracted field, so a UI or API
caller can tell a value it can rely on from one a human needs to look at
without reading the profile's free-text notes.

Every deal value field gets exactly one status:

- "supported"   - a value backed by a verified citation whose quoted passage
                  contains it, or a value a reviewer set or confirmed.
- "uncertain"   - a value was found but shouldn't be relied on yet: the model
                  doubted it, its citation didn't check out, it only has a
                  "quote_only" citation (narrative fields the model
                  summarizes), it has no citation at all, or its label gives
                  a different figure elsewhere in the document (a possible
                  conflict, e.g. in-place vs pro forma NOI - the value is
                  kept, the other passages are in `conflicting_values`).
- "conflicting" - passages the extraction cited for the field disagree, or
                  the model said so. The field is left null and every
                  passage is kept in the withheld entry's
                  `conflicting_values`.
- "missing"     - no value, and nothing proposed for it.

The status is derived from what the profile already records (the field's
value and evidence, `withheld_values`, the extractor's notes and
`corrected_fields`) rather than stored separately, so it can never drift out
of date when a reviewer corrects a field, accepts or dismisses a withheld
value, or the extractor re-derives a value from reviewer feedback. It is
exposed as `REPEDealProfile.field_statuses`, which every API response that
returns a profile includes.

A field a reviewer has corrected is trusted as the reviewer left it: it is
"supported" (or "missing" if they cleared it) and doesn't need review, even
if an extractor note about it remains. That mirrors the review form (M2.2),
where "corrected" outranks every extractor flag. The exception is a newer
proposal for the field waiting in `withheld_values` (e.g. from re-deriving it
after reviewer feedback): that needs a reviewer again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Optional

from pydantic import BaseModel, Field

from backend.app.h9n.schemas.base_deal import (
    BOOKKEEPING_FIELDS,
    ConflictingValue,
    FieldEvidence,
    PossibleConflict,
    WithheldValue,
)

if TYPE_CHECKING:
    from backend.app.h9n.schemas.base_deal import BaseDeal

FieldStatus = Literal["supported", "uncertain", "missing", "conflicting"]

# Why a field has its status, most specific first. Stable codes a UI can map
# to its own wording; every reason also carries a plain-language message.
FieldStatusReasonCode = Literal[
    "reviewer_corrected",  # a reviewer set this value (or cleared it)
    "verified_citation",  # the quoted passage contains the value
    "conflicting_values",  # passages in the document disagree
    "same_label_different_value",  # the label gives another figure elsewhere
    "model_flagged_conflicting",  # the model said the document disagrees
    "model_flagged_uncertain",  # the model doubted the value
    "unverified_value",  # proposed, but its citation didn't check out
    "quote_only_citation",  # only the quote was checked, not the value
    "no_citation",  # a value with no citation (e.g. an older extraction)
    "listed_as_missing",  # the model said the document doesn't state it
    "not_stated",  # no value and no note
]

# Every field not in base_deal.BOOKKEEPING_FIELDS is a deal value and gets a
# status. Re-exported here for callers that read statuses.
__all__ = ["BOOKKEEPING_FIELDS", "FieldStatus", "FieldStatusReport", "assess_field", "assess_fields"]

_CONFLICT_REASONS = {"model_conflicting", "conflicting_evidence"}


class FieldStatusReason(BaseModel):
    code: FieldStatusReasonCode
    message: str


class FieldStatusReport(BaseModel):
    """How far one field can be trusted, and why."""

    status: FieldStatus

    # True when a human should look before relying on the field: every status
    # except "supported", unless a reviewer has already set the field.
    needs_review: bool

    # Whether the current value (or its absence) came from a reviewer.
    reviewer_corrected: bool = False

    reasons: list[FieldStatusReason] = Field(default_factory=list)

    # The value waiting in withheld_values for a reviewer, if any.
    proposed_value: Optional[Any] = None

    # For a conflict or possible conflict: every passage found and the value
    # it states. Several passages can state the same value.
    conflicting_values: list[ConflictingValue] = Field(default_factory=list)

    # Every citation H9N holds for the field - the stored value's, the
    # withheld proposal's, and each conflicting passage - de-duplicated, so a
    # reviewer can check them all from one place.
    evidence: list[FieldEvidence] = Field(default_factory=list)


def note_names_field(note: str, field_name: str) -> bool:
    """Whether an extractor note is about `field_name`: it starts with the
    field's name, as written or with spaces ("cap_rate: not stated", "cap rate
    not stated"), followed by something other than a letter, digit or "_" -
    so a note about "units" isn't taken as one about "units_renovated". The
    same rule the review form (M2.2) uses to read these notes."""
    folded = note.strip().casefold()
    for label in (field_name, field_name.replace("_", " ")):
        rest = folded[len(label) :]
        if folded.startswith(label) and not (rest[:1].isalnum() or rest[:1] == "_"):
            return True
    return False


def note_text(note: str, field_name: str) -> str:
    """A note without its leading field name: "cap_rate: not stated" -> "not stated"."""
    stripped = note.strip()
    for label in (field_name, field_name.replace("_", " ")):
        if stripped.casefold().startswith(label):
            rest = stripped[len(label) :].lstrip(" \t:-–—")
            return rest or stripped
    return stripped


def value_fields(profile: "BaseDeal") -> list[str]:
    """The deal value fields of a profile, in schema order."""
    return [name for name in type(profile).model_fields if name not in BOOKKEEPING_FIELDS]


def _has_value(value: Any) -> bool:
    return value is not None and not (isinstance(value, str) and not value.strip())


def _dedupe(entries: list[FieldEvidence]) -> list[FieldEvidence]:
    seen: set[tuple[Any, ...]] = set()
    unique = []
    for entry in entries:
        key = (entry.source_document, entry.page_number, " ".join((entry.snippet or "").split()).casefold())
        if key not in seen:
            seen.add(key)
            unique.append(entry)
    return unique


def assess_field(profile: "BaseDeal", field_name: str) -> FieldStatusReport:
    """The status of one deal value field, as the profile stands now."""
    value = getattr(profile, field_name)
    has_value = _has_value(value)
    stored = [entry for entry in profile.evidence if entry.field_name == field_name]
    withheld: Optional[WithheldValue] = next(
        (entry for entry in profile.withheld_values if entry.field_name == field_name), None
    )
    possible: Optional[PossibleConflict] = next(
        (entry for entry in profile.possible_conflicts if entry.field_name == field_name), None
    )
    conflicting_values = (list(withheld.conflicting_values) if withheld else []) or (
        list(possible.conflicting_values) if possible else []
    )
    evidence = _dedupe(
        stored
        + ([withheld.evidence] if withheld and withheld.evidence else [])
        + [candidate.evidence for candidate in conflicting_values]
    )
    corrected = field_name in profile.corrected_fields

    def notes(source: list[str]) -> list[str]:
        return [note_text(note, field_name) for note in source if note_names_field(note, field_name)]

    def report(status: FieldStatus, reasons: list[FieldStatusReason], **extra: Any) -> FieldStatusReport:
        return FieldStatusReport(
            status=status,
            needs_review=status != "supported",
            reviewer_corrected=corrected,
            reasons=reasons,
            proposed_value=withheld.proposed_value if withheld else None,
            conflicting_values=conflicting_values,
            evidence=evidence,
            **extra,
        )

    if corrected:
        if withheld is None:
            # The reviewer's value (or blank) stands, whatever the extractor said.
            return FieldStatusReport(
                status="supported" if has_value else "missing",
                needs_review=False,
                reviewer_corrected=True,
                reasons=[
                    FieldStatusReason(
                        code="reviewer_corrected",
                        message="Set by a reviewer." if has_value else "Cleared by a reviewer.",
                    )
                ],
                evidence=evidence,
            )
        # A newer proposal is waiting (e.g. re-derived after reviewer
        # feedback): the reviewer has to accept or dismiss it. Extractor notes
        # from before the correction no longer apply.
        conflict_notes: list[str] = []
        uncertain_notes: list[str] = []
        missing_notes: list[str] = []
        possible = None
    else:
        conflict_notes = notes(profile.conflicting_information)
        uncertain_notes = notes(profile.uncertain_information)
        missing_notes = notes(profile.missing_information)

    if (withheld and withheld.reason in _CONFLICT_REASONS) or conflict_notes:
        reasons = []
        if withheld and withheld.reason == "conflicting_evidence":
            reasons.append(FieldStatusReason(code="conflicting_values", message=withheld.detail))
        elif withheld and withheld.reason == "model_conflicting":
            reasons.append(FieldStatusReason(code="model_flagged_conflicting", message=withheld.detail))
        reasons += [
            FieldStatusReason(code="model_flagged_conflicting", message=note)
            for note in conflict_notes
            if not any(note in reason.message for reason in reasons)
        ]
        return report("conflicting", reasons)

    reasons = []
    if possible is not None:
        reasons.append(FieldStatusReason(code="same_label_different_value", message=possible.detail))
    reasons += [
        FieldStatusReason(code="model_flagged_uncertain", message=note)
        for note in uncertain_notes
        if not (possible and note in possible.detail)
    ]
    if withheld:
        if withheld.reason == "model_uncertain":
            if not any(reason.code == "model_flagged_uncertain" for reason in reasons):
                reasons.append(FieldStatusReason(code="model_flagged_uncertain", message=withheld.detail))
        elif withheld.reason == "model_listed_as_missing":
            reasons.append(FieldStatusReason(code="listed_as_missing", message=withheld.detail))
        else:
            reasons.append(FieldStatusReason(code="unverified_value", message=withheld.detail))
    if corrected:
        reasons.append(
            FieldStatusReason(
                code="reviewer_corrected",
                message="The current value was set by a reviewer; a newer proposal is waiting for review.",
            )
        )
    elif has_value:
        verified = next((entry for entry in stored if entry.verification == "value_matched"), None)
        if not stored:
            reasons.append(FieldStatusReason(code="no_citation", message="The value has no citation."))
        elif verified is None:
            if any(entry.verification == "quote_only" for entry in stored):
                reasons.append(
                    FieldStatusReason(
                        code="quote_only_citation",
                        message="The citation's quote was found, but this summarized value can't be "
                        "matched to it word for word. Check it against the passage.",
                    )
                )
            else:
                reasons.append(
                    FieldStatusReason(code="unverified_value", message="The value's citation wasn't verified.")
                )
    if reasons:
        return report("uncertain", reasons)

    if not has_value:
        return report(
            "missing",
            [FieldStatusReason(code="listed_as_missing", message=note) for note in missing_notes]
            or [FieldStatusReason(code="not_stated", message="No value was found in the document.")],
        )

    return report(
        "supported",
        [FieldStatusReason(code="verified_citation", message="The cited passage contains this value.")],
    )


def assess_fields(profile: "BaseDeal") -> dict[str, FieldStatusReport]:
    """Every deal value field's status, in schema order."""
    return {name: assess_field(profile, name) for name in value_fields(profile)}
