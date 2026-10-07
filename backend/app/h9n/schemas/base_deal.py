from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

# The three states a reviewer's verdict on a saved deal can be in - see
# BaseDeal.review_status below.
ReviewStatus = Literal["pending", "approved", "rejected"]

# See FieldEvidence.verification.
EvidenceVerification = Literal["value_matched", "quote_only"]


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

    # How the extractor checked this citation (Milestone 1.1): "value_matched"
    # when the quoted passage contains the value itself, "quote_only" when only
    # the quote could be checked (narrative fields like business_plan, which
    # the model summarizes). None for citations the extractor didn't verify.
    verification: Optional[EvidenceVerification] = None


# Why an extracted value was kept out of its field (Milestone 1.1). The first
# five mean the model's citation didn't hold up; the last three mean the model
# itself said the value shouldn't be taken at face value.
WithheldReason = Literal[
    "no_evidence",
    "page_not_in_document",
    "snippet_too_short",
    "snippet_not_on_page",
    "value_not_in_snippet",
    "model_uncertain",
    "model_conflicting",
    "model_listed_as_missing",
]


# A value the extractor proposed but could not verify, held back for a human
# reviewer instead of being stored as data (Milestone 1.1). The field itself
# is left null, so an unreviewed value can never be mistaken for a verified
# one downstream; the reviewer either accepts `proposed_value` (setting the
# field and marking it corrected) or dismisses it (the field stays null).
class WithheldValue(BaseModel):

    # Which Deal Profile field the value was proposed for, e.g. "noi".
    field_name: str

    # The value the model proposed. It has already passed the field's own
    # type and bounds checks - it is withheld because it couldn't be verified
    # or the model itself doubted it (see `reason`), not because it is
    # malformed.
    proposed_value: Union[int, float, str]

    reason: WithheldReason

    # Plain-language explanation for the reviewer, e.g. "The quoted snippet
    # was not found on page 3."
    detail: str

    # The citation the model gave, if any, so the reviewer can jump straight
    # to where it claimed the value came from.
    evidence: Optional[FieldEvidence] = None


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

    # One verified FieldEvidence entry per stored value (every field, since
    # Milestone 1.1), so a reviewer can see where each value came from instead
    # of trusting an unexplained model output.
    evidence: list[FieldEvidence] = Field(default_factory=list)

    # Flags a value that WAS found (unlike missing_information) and doesn't
    # contradict another value in the document (unlike conflicting_information),
    # but that the extractor isn't fully confident is correct - e.g. the
    # source wording was ambiguous or approximate. Since Milestone 1.1 the
    # flagged value itself waits in withheld_values, not its field. Each entry
    # is a short note naming the field and why it's flagged, so a reviewer
    # knows which values are worth double-checking first
    # (Milestone 1, item 3 - Uncertainty Flagging).
    uncertain_information: list[str] = Field(default_factory=list)

    # Values the extractor proposed but could not verify against the source
    # document, or that it flagged as uncertain or conflicting. Their fields
    # are left null; each entry keeps the proposed value, the reason, and any
    # citation so a reviewer can accept or dismiss it (Milestone 1.1).
    withheld_values: list[WithheldValue] = Field(default_factory=list)

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
