"""The review rules for a saved deal (Milestone 2.4), as pure functions.

Each function takes a deal as it stands and returns the DealChanges one
reviewer action makes - the new profile and status, plus the Correction and
StatusChange records that keep the history. Nothing is saved here: the API
hands the result to a DealRepository, which saves it only if the deal hasn't
changed in the meantime.

Statuses: draft -> reviewed -> approved.
- Correcting a field is allowed in draft or reviewed. A reviewed deal that
  changes goes back to draft, because what was reviewed is no longer there.
- An approved deal is locked until someone reopens it.
- "reject" records what's wrong (feedback) and leaves the deal in draft;
  the API then has the extractor re-derive the affected fields.
"""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from pydantic import ValidationError
from pydantic_core import to_jsonable_python

from backend.app.h9n.review.models import (
    Correction,
    CorrectionSource,
    DealChanges,
    DealLockedError,
    DealRecord,
    DealTransitionError,
    DealUpdateError,
    ReviewAction,
    StatusChange,
)
from backend.app.h9n.schemas.base_deal import FieldEvidence, ReviewStatus
from backend.app.h9n.schemas.repe_deal import REPEDealProfile

# Set only by review actions, never by a correction.
_WORKFLOW_FIELDS = {"review_status", "corrected_fields", "review_feedback"}

# A reviewer may resolve flags (e.g. dismiss a withheld value) but not
# rewrite where a value came from. Re-derived corrections replace a changed
# field's citation with a newly verified one (see feedback_updates).
_LOCKED_FOR = {
    "reviewer": _WORKFLOW_FIELDS | {"evidence"},
    "reviewer_feedback": _WORKFLOW_FIELDS,
}

# Bookkeeping lists: changes to them are recorded, but they aren't deal
# values, so they don't count toward corrected_fields.
_BOOKKEEPING_FIELDS = {
    "missing_information",
    "conflicting_information",
    "uncertain_information",
    "withheld_values",
    "evidence",
}

# action -> (statuses it applies to, status it leads to)
_TRANSITIONS: dict[ReviewAction, tuple[set[str], ReviewStatus]] = {
    "review": ({"draft"}, "reviewed"),
    "approve": ({"draft", "reviewed"}, "approved"),
    "reopen": ({"reviewed", "approved"}, "draft"),
    "reject": ({"draft", "reviewed"}, "draft"),
}

_NOT_ALLOWED = {
    ("review", "reviewed"): "This deal is already marked reviewed.",
    ("review", "approved"): "This deal is approved. Reopen it before marking it reviewed.",
    ("approve", "approved"): "This deal is already approved.",
    ("reopen", "draft"): "This deal is already a draft.",
    ("reject", "approved"): "This deal is approved. Reopen it before rejecting it.",
}

LOCKED_MESSAGE = "This deal is approved, so it can't be edited. Reopen it first."


def plan_corrections(
    deal: DealRecord,
    changes: dict[str, Any],
    *,
    actor: UUID,
    source: CorrectionSource = "reviewer",
    feedback: Optional[str] = None,
) -> Optional[DealChanges]:
    """The DealChanges for setting `changes` (field name -> new value), or
    None if every value is already what was asked for.

    Values are validated as strictly as an extraction (REPEDealProfile
    validates on assignment), so a wrong type or unknown field raises
    DealUpdateError instead of reaching the database.
    """
    if deal.status == "approved":
        raise DealLockedError(LOCKED_MESSAGE)
    if not changes:
        raise DealUpdateError("Send at least one field to change.")

    profile = deal.profile.model_copy(deep=True)
    corrections: list[Correction] = []
    for field_name, new_value in changes.items():
        if field_name not in REPEDealProfile.model_fields:
            raise DealUpdateError(f"{field_name!r} is not a field on the Deal Profile.")
        if field_name in _LOCKED_FOR[source]:
            raise DealUpdateError(f"{field_name!r} can't be changed directly.")

        original = to_jsonable_python(getattr(profile, field_name))
        try:
            setattr(profile, field_name, new_value)
        except ValidationError as exc:
            raise DealUpdateError(f"{field_name!r}: {exc.errors()[0]['msg']}") from exc
        corrected = to_jsonable_python(getattr(profile, field_name))
        if corrected == original:
            continue

        corrections.append(
            Correction(
                field_name=field_name,
                original_value=original,
                corrected_value=corrected,
                evidence=_evidence_for(deal.profile, field_name),
                source=source,
                feedback=feedback,
                corrected_by=actor,
            )
        )
        if field_name not in _BOOKKEEPING_FIELDS and field_name not in profile.corrected_fields:
            profile.corrected_fields.append(field_name)

    if not corrections:
        return None

    status_change = None
    if deal.status == "reviewed":
        status_change = StatusChange(
            action="edit",
            from_status="reviewed",
            to_status="draft",
            note="Changed after review.",
            changed_by=actor,
        )
    status: ReviewStatus = "draft"
    profile.review_status = status
    return DealChanges(profile=profile, status=status, corrections=corrections, status_change=status_change)


def plan_review_action(
    deal: DealRecord,
    action: ReviewAction,
    *,
    actor: UUID,
    feedback: Optional[str] = None,
) -> DealChanges:
    """The DealChanges for a review action on the deal as a whole."""
    allowed_from, to_status = _TRANSITIONS[action]
    if deal.status not in allowed_from:
        raise DealTransitionError(_NOT_ALLOWED[(action, deal.status)])

    feedback = (feedback or "").strip() or None
    if action == "reject" and not feedback:
        raise DealUpdateError("Say what's wrong with the deal when rejecting it.")

    profile = deal.profile.model_copy(deep=True)
    profile.review_status = to_status
    if action == "reject":
        profile.review_feedback = feedback

    return DealChanges(
        profile=profile,
        status=to_status,
        status_change=StatusChange(
            action=action,
            from_status=deal.status,
            to_status=to_status,
            note=feedback if action == "reject" else None,
            changed_by=actor,
        ),
    )


def _evidence_for(profile: REPEDealProfile, field_name: str) -> Optional[FieldEvidence]:
    return next((entry for entry in profile.evidence if entry.field_name == field_name), None)
