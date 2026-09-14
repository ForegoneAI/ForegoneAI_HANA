from Backend.app.h9n.schemas.repe_deal import REPEDealProfile
from Backend.app.h9n.schemas.pe_deal import PEDealProfile


# Creates a sample Real Estate Private Equity deal
# This tests both inherited BaseDeal fields and REPE-specific fields
repe_deal = REPEDealProfile(
    deal_name="Taberna Country Club",
    property_name="Taberna Country Club",
    property_type="Golf / Country Club",
    location="New Bern, NC",
    asking_price=10_000_000,
    noi=750_000
)


# Creates a sample traditional Private Equity deal
# This tests both inherited BaseDeal fields and PE-specific fields
pe_deal = PEDealProfile(
    deal_name="Trucking Company Acquisition",
    company_name="Example Trucking Company",
    industry="Transportation",
    annual_revenue=15_000_000,
    ebitda=2_000_000
)


# Displays the complete REPE object after Pydantic validation
print("REPE DEAL")
print(repe_deal.model_dump())


# Displays the complete PE object after Pydantic validation
print("\nPE DEAL")
print(pe_deal.model_dump())