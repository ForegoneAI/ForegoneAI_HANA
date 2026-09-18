from typing import Optional

from pydantic import BaseModel, Field


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