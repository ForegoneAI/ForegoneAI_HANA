from typing import Optional

from .base_deal import BaseDeal


# Represents a traditional Private Equity company acquisition
# Inherits all common deal fields from BaseDeal
class PEDealProfile(BaseDeal):

    # Target company information
    company_name: Optional[str] = None
    industry: Optional[str] = None
    subsector: Optional[str] = None
    employee_count: Optional[int] = None
    ownership_type: Optional[str] = None

    # Company financial performance
    annual_revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    ebitda: Optional[float] = None
    adjusted_ebitda: Optional[float] = None
    free_cash_flow: Optional[float] = None
    capex: Optional[float] = None
    working_capital: Optional[float] = None

    # Existing company capital structure
    debt: Optional[float] = None
    cash: Optional[float] = None

    # Proposed acquisition structure
    seller_rollover: Optional[float] = None
    earnout: Optional[float] = None
    seller_financing: Optional[float] = None

    # Important business risks and quality indicators
    customer_concentration: Optional[str] = None
    revenue_quality: Optional[str] = None