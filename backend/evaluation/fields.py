"""The benchmark fields that score H9N's production extractor.

A benchmark field named after a REPEDealProfile field tests that field as the
profile defines it, in the benchmark's units (currency in base units,
percentages as ratios: 6.5% -> 0.065). Every other benchmark field is
`reference`: kept as a labelled fact about the deal, reported separately,
and never counted in the headline score, because the extractor has nowhere
to put it.

Narrative fields (investment_strategy, business_plan) are left out: they are
summarized prose that exact-match scoring can't grade.
"""

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

SCOPES = ("production", "reference")


def default_scope(name: str) -> str:
    return "production" if name in PRODUCTION_FIELDS else "reference"
