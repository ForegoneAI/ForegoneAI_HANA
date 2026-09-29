from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# The three states a reviewer's verdict on a saved deal can be in - see
# BaseDeal.review_status below.
ReviewStatus = Literal["pending", "approved", "rejected"]


# One citation for a single extracted field: the value that was extracted,
# plus exactly where it came from. This is what lets a reviewer check a
# value against the source document instead of just trusting the model
# (Milestone 1, item 2 - Field-Level Source Evidence).
class FieldEvidence(BaseModel):

    # Which Deal Profile field this evidence supports, e.g. "asking_price".
    field_name: str

    # The value that was extracted for that field, as plain text (the Deal
    # Profile field itself holds the typed/normalized value - this is just
    # for the reviewer to match evidence to field at a glance).
    value: Optional[str] = None

    # Where the value came from.
    source_document: Optional[str] = None
    page_number: Optional[int] = None

    # A short, verbatim quote from the source document that supports the
    # value, so the reviewer doesn't have to re-read the whole page.
    snippet: Optional[str] = None


# Contains fields shared by both PE and REPE deals
class BaseDeal(BaseModel):

    # Validates on setattr (e.g. `deal.asking_price = 5_000_000`), not just
    # on construction, so a human reviewer's correction (Milestone 1, item 4)
    # can't silently write a value the schema wouldn't otherwise accept.
    model_config = ConfigDict(validate_assignment=True)

    # Basic deal information
    # Optional fields allow HANA to leave information missing instead of guessing
    deal_name: Optional[str] = None
    location: Optional[str] = None
    transaction_type: Optional[str] = None
    asking_price: Optional[float] = None

    # Tracks information that is missing or inconsistent in the source documents
    # default_factory creates a new empty list for every Deal object
    missing_information: list[str] = Field(default_factory=list)
    conflicting_information: list[str] = Field(default_factory=list)

    # One FieldEvidence entry per important field the extractor found a
    # value for, so a reviewer can see where each value came from instead of
    # trusting an unexplained model output.
    evidence: list[FieldEvidence] = Field(default_factory=list)

    # Flags a value that WAS found (unlike missing_information) and doesn't
    # contradict another value in the document (unlike conflicting_information),
    # but that the extractor isn't fully confident is correct - e.g. it had to
    # be inferred, calculated, or the source wording was ambiguous. Each entry
    # is a short note naming the field and why it's flagged, so a reviewer
    # knows which values are worth double-checking first
    # (Milestone 1, item 3 - Uncertainty Flagging).
    uncertain_information: list[str] = Field(default_factory=list)

    # Names of fields a human reviewer has corrected since extraction, so the
    # profile itself shows which values are model-extracted vs
    # human-verified, without needing a separate audit system to answer that
    # (Milestone 1, item 4 - Human Review and Correction).
    corrected_fields: list[str] = Field(default_factory=list)

    # The reviewer's own explanation of what's wrong, submitted alongside a
    # "rejected" verdict (see review_status below). This is what lets a
    # reviewer describe the problem in plain language - "the asking price is
    # wrong, it's actually $950k" - instead of having to work out and submit
    # the corrected value themselves. When feedback is given, the extractor
    # is asked to re-derive the affected field(s) from the original document
    # text (see repe_extractor.apply_reviewer_feedback); this field just
    # keeps a record of what the reviewer actually said, for the audit trail.
    review_feedback: Optional[str] = None

    # Whether a human reviewer has explicitly signed off on this profile as
    # correct: "pending" (default) until someone reviews it, then "approved"
    # once they confirm it's right, or "rejected" if they've looked and it
    # still isn't - as distinct from corrected_fields, which only tracks
    # that *a value changed*, not that a reviewer looked at the whole
    # profile and said "yes, this is right" (Milestone 1, item 4 - the plan's
    # "Approve and save the validated Deal Profile" step).
    review_status: ReviewStatus = "pending"