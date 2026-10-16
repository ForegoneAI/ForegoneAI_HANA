"""The benchmark fields that score H9N's production extractor.

Every benchmark field is one of these: named after the REPEDealProfile field
it tests, in the benchmark's units (currency in base units, percentages as
ratios: 6.5% -> 0.065). The loader rejects any other field, so the answer key
and the extractor can't drift apart. A fact the profile has no field for is
not benchmarked: add the profile field first, then label it.

Narrative fields (investment_strategy, business_plan) are left out: they are
summarized prose that exact-match scoring can't grade.
"""

import math

# name -> (benchmark unit, what a reviewer should record)
PRODUCTION_FIELDS: dict[str, tuple[str, str]] = {
    "deal_name": ("text", "Deal or offering name as the document states it."),
    "property_name": ("text", "Name of the subject property."),
    "property_type": ("text", "Property type in the document's own words (e.g. Multifamily, Office)."),
    "address": ("text", "Street address of the subject property."),
    "location": ("text", "Location as the document summarizes it (city/state or similar)."),
    "market": ("text", "Market (metro area) of the subject property."),
    "submarket": ("text", "Submarket or neighborhood, if stated."),
    "transaction_type": ("text", "Transaction type (e.g. sale, recapitalization, development), if stated."),
    "units": ("count", "Number of units (residential units, keys, or suites as stated)."),
    "square_feet": ("sqft", "The property's stated size in square feet (building or rentable area)."),
    "year_built": ("year", "Year built."),
    "occupancy_rate": ("ratio", "Current occupancy as a ratio (94% -> 0.94)."),
    "annual_revenue": ("USD", "Current annual revenue / gross income as stated."),
    "operating_expenses": ("USD", "Current annual operating expenses as stated."),
    "noi": ("USD", "Current (in-place) net operating income; not pro forma."),
    "cap_rate": ("ratio", "Current (in-place) cap rate as a ratio; not pro forma."),
    "asking_price": ("USD", "Asking or offering price of the subject property."),
    "loan_amount": ("USD", "Loan amount stated for the deal (existing, proposed or modeled)."),
    "interest_rate": ("ratio", "Interest rate of that loan as a ratio."),
    "ltv": ("ratio", "Loan-to-value as a ratio."),
    "loan_term_years": ("years", "Loan term in years."),
    "sponsor_name": ("text", "Sponsor's name."),
    "sponsor_equity": ("USD", "Sponsor's equity contribution."),
}

# Production stores these as percentages (6.5); the benchmark uses ratios.
PERCENT_FIELDS = frozenset({"occupancy_rate", "cap_rate", "interest_rate", "ltv"})

# unit -> (value type, minimum, maximum). Bounds follow the extractor's own
# (extraction_output.py), so a label it could never match fails at import
# instead of scoring every run as wrong.
UNIT_RULES = {"text": (str, None, None), "USD": (float, None, None), "sqft": (float, 0, None),
              "ratio": (float, 0, 1), "count": (int, 0, None), "year": (int, 1700, 2100), "years": (int, 0, None)}


def check_value(value, unit: str) -> None:
    """Raise ValueError unless `value` is a valid non-null value in `unit`."""
    kind, low, high = UNIT_RULES[unit]
    if kind is str:
        valid = isinstance(value, str) and bool(value.strip())
    else:
        number = type(value) is int or (kind is float and type(value) is float and math.isfinite(value))
        valid = number and (low is None or value >= low) and (high is None or value <= high)
    if not valid:
        hint = " (ratios are fractions: 5.87% is 0.0587)" if unit == "ratio" else ""
        raise ValueError(f"{value!r} is not a valid {unit} value{hint}")
