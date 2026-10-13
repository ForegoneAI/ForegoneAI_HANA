"""
mandate.py

H9N Milestone 3.1 - the investment mandate: the explicit criteria a fund uses
to decide whether a deal is worth a closer look (asset types, geography, deal
size, key metrics, leverage limits, and softer preferences).

It is deliberately a small, editable form rather than a policy engine. Every
hard criterion maps to exactly one REPEDealProfile field (see
`CRITERIA_PROFILE_FIELDS`), so the screening rules in M3.2 can compare a
mandate with an approved Deal Profile without any guesswork:

    asset_types          -> property_type
    target_markets       -> market
    excluded_markets     -> market
    deal_size            -> asking_price
    key_metrics[<field>] -> <field>      (e.g. key_metrics["cap_rate"] -> cap_rate)
    leverage.max_ltv     -> ltv
    leverage.max_interest_rate -> interest_rate

Units follow the Deal Profile: money in US dollars, percentages as their
numeric value (6.5 means 6.5%, never 0.065).

`preferences` are soft: they are shown to the reviewer and the M3.3 AI
explanation, but no rule ever passes or fails a deal on them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.h9n.schemas.repe_deal import REPEDealProfile

# Limits that keep a mandate a short, readable form (and keep the stored row
# small). Far above anything a real mandate needs.
MAX_NAME_CHARS = 120
MAX_DESCRIPTION_CHARS = 2000
MAX_LIST_ITEMS = 50
MAX_ITEM_CHARS = 120

# Numeric Deal Profile fields a mandate may put a min/max on. Price, LTV and
# interest rate are left out on purpose: they have their own sections
# (deal_size, leverage), so each profile field is constrained in one place.
MetricField = Literal[
    "cap_rate",
    "occupancy_rate",
    "noi",
    "annual_revenue",
    "operating_expenses",
    "units",
    "square_feet",
    "year_built",
]

# Fields stored as percentages (0-100), matching the Deal Profile.
_PERCENT_FIELDS = {"cap_rate", "occupancy_rate"}
# Fields that can't be negative. NOI is left out: a property can lose money.
_NON_NEGATIVE_FIELDS = {"annual_revenue", "operating_expenses", "units", "square_feet"}

# Which Deal Profile field each hard criterion is checked against. Kept as
# data so M3.2 can read it, and so a test can confirm every target still
# exists on REPEDealProfile if a field is ever renamed.
CRITERIA_PROFILE_FIELDS: dict[str, str] = {
    "asset_types": "property_type",
    "target_markets": "market",
    "excluded_markets": "market",
    "deal_size": "asking_price",
    "leverage.max_ltv": "ltv",
    "leverage.max_interest_rate": "interest_rate",
    **{f"key_metrics.{name}": name for name in MetricField.__args__},
}


class ValueRange(BaseModel):
    """An inclusive range. Either end may be left open, but not both."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    min: Optional[float] = None
    max: Optional[float] = None

    @model_validator(mode="after")
    def _is_a_real_range(self) -> "ValueRange":
        if self.min is None and self.max is None:
            raise ValueError("Give a min, a max, or both.")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError(f"min ({self.min:g}) is larger than max ({self.max:g}).")
        return self


class LeverageLimits(BaseModel):
    """Debt limits, as percentages (65 means 65%)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    max_ltv: Optional[float] = Field(default=None, ge=0, le=100)
    max_interest_rate: Optional[float] = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _has_a_limit(self) -> "LeverageLimits":
        if self.max_ltv is None and self.max_interest_rate is None:
            raise ValueError("Give max_ltv, max_interest_rate, or both - or leave leverage out.")
        return self


def _clean_list(values: list[str]) -> list[str]:
    """Trims each entry, drops blanks, and drops repeats (ignoring case) while
    keeping the order the user typed them in."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = " ".join(str(value).split())
        if not text:
            continue
        if len(text) > MAX_ITEM_CHARS:
            raise ValueError(f"Entries must be at most {MAX_ITEM_CHARS} characters.")
        key = text.casefold()
        if key not in seen:
            seen.add(key)
            cleaned.append(text)
    return cleaned


class MandateCriteria(BaseModel):
    """What a deal must look like to fit the mandate. An empty list or a
    missing section means "no requirement" for that criterion."""

    model_config = ConfigDict(extra="forbid")

    # Property types the fund invests in, e.g. ["Multifamily"]. Compared with
    # the profile's property_type; empty means any type.
    asset_types: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)

    # Markets the fund targets / refuses, e.g. ["Dallas-Fort Worth"]. Compared
    # with the profile's market; empty target list means anywhere.
    target_markets: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)
    excluded_markets: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)

    # Deal size, as the asking price in US dollars.
    deal_size: Optional[ValueRange] = None

    # Min/max on other numeric profile fields, e.g. {"cap_rate": {"min": 5.5}}.
    key_metrics: dict[MetricField, ValueRange] = Field(default_factory=dict)

    leverage: Optional[LeverageLimits] = None

    # Soft preferences shown to reviewers and the AI explanation (M3.3), e.g.
    # "Value-add business plan". Never turned into pass/fail rules.
    preferences: list[str] = Field(default_factory=list, max_length=MAX_LIST_ITEMS)

    @field_validator("asset_types", "target_markets", "excluded_markets", "preferences")
    @classmethod
    def _tidy_lists(cls, values: list[str]) -> list[str]:
        return _clean_list(values)

    @field_validator("deal_size")
    @classmethod
    def _deal_size_not_negative(cls, value: Optional[ValueRange]) -> Optional[ValueRange]:
        if value is not None and ((value.min or 0) < 0 or (value.max or 0) < 0):
            raise ValueError("Deal size can't be negative.")
        return value

    @model_validator(mode="after")
    def _is_usable(self) -> "MandateCriteria":
        for name, limits in self.key_metrics.items():
            if name in _NON_NEGATIVE_FIELDS and any(b is not None and b < 0 for b in (limits.min, limits.max)):
                raise ValueError(f"{name} can't be negative.")
            if name == "year_built" and any(
                b is not None and not 1700 <= b <= 2100 for b in (limits.min, limits.max)
            ):
                raise ValueError("year_built must be a year between 1700 and 2100.")
            if name in _PERCENT_FIELDS:
                for bound in (limits.min, limits.max):
                    if bound is not None and not 0 <= bound <= 100:
                        raise ValueError(
                            f"{name} is a percentage: use 0-100 (6.5 means 6.5%), got {bound:g}."
                        )

        both = {market.casefold() for market in self.target_markets} & {
            market.casefold() for market in self.excluded_markets
        }
        if both:
            raise ValueError(
                "These markets are both targeted and excluded: " + ", ".join(sorted(both)) + "."
            )

        if not self.has_hard_criteria():
            raise ValueError(
                "A mandate needs at least one hard criterion (asset types, markets, deal size, "
                "a key metric, or a leverage limit); preferences alone can't screen a deal."
            )
        return self

    def has_hard_criteria(self) -> bool:
        return bool(
            self.asset_types
            or self.target_markets
            or self.excluded_markets
            or self.deal_size
            or self.key_metrics
            or self.leverage
        )


class MandateInput(BaseModel):
    """What a user submits to create a mandate (or to replace one when editing)."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=MAX_NAME_CHARS)
    description: Optional[str] = Field(default=None, max_length=MAX_DESCRIPTION_CHARS)
    criteria: MandateCriteria
    # Marks example mandates so nobody mistakes them for a real fund's policy.
    is_demo: bool = False

    @field_validator("name")
    @classmethod
    def _single_spaced_name(cls, value: str) -> str:
        return " ".join(value.split())


class MandateUpdate(MandateInput):
    """An edit: the full new mandate plus the version it was based on, so two
    people editing at once can't silently overwrite each other.

    The read-only fields of a fetched Mandate (id, timestamps, ...) are
    ignored, so a client can load a mandate, change it, and send it back."""

    model_config = ConfigDict(extra="ignore")

    version: int = Field(ge=1)


class Mandate(MandateInput):
    """A saved mandate, shaped like a row of public.investment_mandates.

    Stored rows are re-validated on every read. If the criteria rules are
    ever tightened, update existing rows in the same change, or old mandates
    will fail to load."""

    model_config = ConfigDict(extra="ignore")

    id: UUID
    organization_id: UUID
    is_archived: bool = False
    # Starts at 1 and goes up by one on every edit. Screening results (M3.2+)
    # should record it, so a result can always be traced to the exact
    # criteria it was judged against.
    version: int = Field(ge=1)
    created_at: datetime
    updated_at: datetime


# The sample mandate for demos (M3.1's "at least one demo mandate"). Clearly a
# made-up example, not any real fund's policy.
DEMO_MANDATE = MandateInput(
    name="Demo - Sun Belt Value-Add Multifamily",
    description=(
        "Example mandate for demos and testing only; not a real fund's criteria. "
        "Targets value-add apartment communities in Sun Belt growth markets."
    ),
    is_demo=True,
    criteria=MandateCriteria(
        asset_types=["Multifamily"],
        target_markets=[
            "Dallas-Fort Worth",
            "Austin",
            "Houston",
            "San Antonio",
            "Phoenix",
            "Atlanta",
            "Charlotte",
            "Raleigh-Durham",
            "Nashville",
            "Tampa",
            "Orlando",
        ],
        deal_size=ValueRange(min=5_000_000, max=50_000_000),
        key_metrics={
            "cap_rate": ValueRange(min=5.5),
            "occupancy_rate": ValueRange(min=90),
        },
        leverage=LeverageLimits(max_ltv=65),
        preferences=[
            "Value-add business plan with interior renovation upside",
            "Garden-style or mid-rise product",
        ],
    ),
)


def _check_mapping() -> None:
    # Fails at import (and therefore in every test run) if a mapped profile
    # field disappears from REPEDealProfile.
    missing = sorted(set(CRITERIA_PROFILE_FIELDS.values()) - set(REPEDealProfile.model_fields))
    if missing:
        raise RuntimeError(f"Mandate criteria point at missing Deal Profile fields: {missing}")
    for name in MetricField.__args__:
        annotation = str(REPEDealProfile.model_fields[name].annotation)
        if "int" not in annotation and "float" not in annotation:
            raise RuntimeError(f"key_metrics.{name} must map to a numeric Deal Profile field.")


_check_mapping()
