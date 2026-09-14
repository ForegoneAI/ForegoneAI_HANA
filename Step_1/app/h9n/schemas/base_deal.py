from typing import Optional

from pydantic import BaseModel, Field


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