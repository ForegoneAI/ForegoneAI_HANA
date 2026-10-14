"""Saved deals and their review trail (Milestone 2.4).

A deal is the Deal Profile extracted from one upload plus where it stands in
review. Its status moves draft -> reviewed -> approved; an approved deal is
the trusted input to screening and underwriting, so it can't be edited until
someone reopens it. Every change a reviewer makes is kept as a Correction or
StatusChange, never overwritten (see supabase/migrations/20261014_create_h9n_deals.sql).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from backend.app.h9n.schemas.base_deal import FieldEvidence, ReviewStatus
from backend.app.h9n.schemas.repe_deal import REPEDealProfile

# What a reviewer can do to a deal as a whole (POST /deals/{id}/review).
# "reject" needs feedback: it records what's wrong, has the extractor
# re-derive the affected fields, and leaves the deal in draft.
ReviewAction = Literal["review", "approve", "reopen", "reject"]

# A status change's cause: a ReviewAction, or "edit" - the automatic move
# back to draft when a reviewed deal is changed.
StatusChangeAction = Literal["review", "approve", "reopen", "reject", "edit"]

# Who supplied a corrected value: a reviewer typing it in, or the extractor
# re-deriving it from the document after a reviewer described what was wrong.
CorrectionSource = Literal["reviewer", "reviewer_feedback"]


class NewDeal(BaseModel):
    """A freshly extracted deal, about to be saved as version 1 in draft."""

    id: UUID
    organization_id: UUID
    profile: REPEDealProfile
    source_filename: str
    source_pages: Optional[list[dict[str, Any]]] = None
    extraction_run_id: Optional[UUID] = None
    created_by: UUID


class DealRecord(BaseModel):
    """A saved deal as it stands now."""

    id: UUID
    organization_id: UUID
    status: ReviewStatus
    version: int = Field(ge=1)
    profile: REPEDealProfile
    source_filename: str
    source_pages: Optional[list[dict[str, Any]]] = None
    extraction_run_id: Optional[UUID] = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class DealSummary(BaseModel):
    """One row of the deal list - enough to show and reopen a deal."""

    id: UUID
    organization_id: UUID
    status: ReviewStatus
    deal_name: Optional[str] = None
    property_name: Optional[str] = None
    updated_at: datetime


class Correction(BaseModel):
    """One changed field: what it was, what it became, and on what basis."""

    field_name: str
    original_value: Any = None
    corrected_value: Any = None
    # The field's citation when it was changed.
    evidence: Optional[FieldEvidence] = None
    source: CorrectionSource
    # The reviewer's own words, for corrections re-derived from feedback.
    feedback: Optional[str] = None
    corrected_by: UUID
    # Set once saved.
    deal_version: Optional[int] = None
    created_at: Optional[datetime] = None


class StatusChange(BaseModel):
    action: StatusChangeAction
    from_status: ReviewStatus
    to_status: ReviewStatus
    note: Optional[str] = None
    changed_by: UUID
    # Set once saved.
    deal_version: Optional[int] = None
    created_at: Optional[datetime] = None


class DealChanges(BaseModel):
    """Everything one reviewer action changes, saved together or not at all."""

    profile: REPEDealProfile
    status: ReviewStatus
    corrections: list[Correction] = Field(default_factory=list)
    status_change: Optional[StatusChange] = None


class DealHistory(BaseModel):
    """A deal's review trail, oldest first."""

    corrections: list[Correction] = Field(default_factory=list)
    status_changes: list[StatusChange] = Field(default_factory=list)


class DealNotFoundError(LookupError):
    """No deal with that id in the caller's organizations."""


class DealConflictError(Exception):
    """The request can't apply to the deal as it stands (an HTTP 409)."""


class DealVersionConflictError(DealConflictError):
    """Someone else changed the deal since the caller read it."""


class DealLockedError(DealConflictError):
    """The deal is approved, so it can't be edited until it's reopened."""


class DealTransitionError(DealConflictError):
    """The review action doesn't apply to the deal's current status."""


class DealUpdateError(ValueError):
    """The requested change itself is invalid (an HTTP 400)."""
