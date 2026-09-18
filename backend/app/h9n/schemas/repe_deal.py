from typing import Optional

from .base_deal import BaseDeal


# Represents a Real Estate Private Equity deal
# Inherits all common deal fields from BaseDeal
class REPEDealProfile(BaseDeal):

    # Property information
    property_name: Optional[str] = None
    property_type: Optional[str] = None
    address: Optional[str] = None
    market: Optional[str] = None
    submarket: Optional[str] = None

    # Physical property characteristics
    units: Optional[int] = None
    square_feet: Optional[float] = None
    year_built: Optional[int] = None
    occupancy_rate: Optional[float] = None

    # Property financial information
    annual_revenue: Optional[float] = None
    operating_expenses: Optional[float] = None
    noi: Optional[float] = None
    cap_rate: Optional[float] = None

    # Debt and financing information
    loan_amount: Optional[float] = None
    interest_rate: Optional[float] = None
    ltv: Optional[float] = None
    loan_term_years: Optional[int] = None

    # Sponsor and investment information
    sponsor_name: Optional[str] = None
    sponsor_equity: Optional[float] = None
    investment_strategy: Optional[str] = None
    business_plan: Optional[str] = None