from __future__ import annotations
from decimal import Decimal
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, model_validator

# Identify whether a value comes from a document, user, or calculation.
class Origin(str, Enum):
    source_fact = 'source_fact'
    human_assumption = 'human_assumption'
    derived = 'derived'

# Store financial inputs and their supporting evidence.
class InputValue(BaseModel):
    value: Decimal | None = None
    origin: Literal[Origin.source_fact, Origin.human_assumption]
    source_field: str | None = None
    evidence_id: str | None = None
    note: str | None = None

# Define financial inputs required for underwriting.
class UnderwritingInputs(BaseModel):
    purchase_price: InputValue
    annual_revenue: InputValue | None = None
    annual_operating_expenses: InputValue | None = None
    annual_noi: InputValue | None = None
    loan_amount: InputValue | None = None
    annual_interest_rate_pct: InputValue | None = None
    amortization_years: InputValue | None = None
    interest_only: bool = False
    hold_years: int = Field(default=5, ge=1, le=30)
    exit_cap_rate_pct: InputValue | None = None
    annual_noi_growth_pct: InputValue | None = None
    sale_cost_pct: InputValue | None = None
    upfront_costs: InputValue | None = None

    # Validate financial inputs before calculations.
    @model_validator(mode='after')
    def validate_ranges(self):
        nonnegative = [
            'purchase_price',
            'annual_revenue',
            'annual_operating_expenses',
            'loan_amount',
            'upfront_costs'
        ]

        # Reject negative values for nonnegative financial inputs.
        for name in nonnegative:
            item = getattr(self, name)
            if item and item.value is not None and item.value < 0:
                raise ValueError(f'{name} cannot be negative')

        # Ensure percentage inputs remain within valid ranges.
        for name in ['annual_interest_rate_pct', 'exit_cap_rate_pct', 'sale_cost_pct']:
            item = getattr(self, name)
            if item and item.value is not None and not (0 <= item.value <= 100):
                raise ValueError(f'{name} must be between 0 and 100')

        # Require a positive loan amortization period.
        if self.amortization_years and self.amortization_years.value is not None and self.amortization_years.value <= 0:
            raise ValueError('amortization_years must be positive')

        return self

# Represent calculated metrics with formulas and source references.
class Metric(BaseModel):
    value: Decimal | None
    unit: str
    formula: str
    inputs: list[str]
    origin: Literal[Origin.derived] = Origin.derived
    warning: str | None = None

# Define adjustable assumptions for financial scenarios.
class ScenarioAdjustments(BaseModel):
    purchase_price_pct: Decimal = Decimal('0')
    noi_pct: Decimal = Decimal('0')
    interest_rate_delta_pct: Decimal = Decimal('0')
    exit_cap_rate_delta_pct: Decimal = Decimal('0')
    noi_growth_delta_pct: Decimal = Decimal('0')

# Store calculated scenario metrics, cash flows, and warnings.
class ScenarioResult(BaseModel):
    name: str
    adjustments: ScenarioAdjustments
    metrics: dict[str, Metric]
    annual_cash_flows: list[Decimal] | None = None
    warnings: list[str] = Field(default_factory=list)

# Define an underwriting request with default financial scenarios.
class UnderwritingRequest(BaseModel):
    deal_id: str
    inputs: UnderwritingInputs

    # Default scenarios adjust NOI and exit capitalization rates.
    scenarios: dict[str, ScenarioAdjustments] = Field(default_factory=lambda: {
        'base': ScenarioAdjustments(),
        'downside': ScenarioAdjustments(
            noi_pct=Decimal('-10'),
            exit_cap_rate_delta_pct=Decimal('0.5')
        ),
        'upside': ScenarioAdjustments(
            noi_pct=Decimal('10'),
            exit_cap_rate_delta_pct=Decimal('-0.5')
        ),
    })

# Return underwriting results for each requested scenario.
class UnderwritingResponse(BaseModel):
    deal_id: str
    scenarios: dict[str, ScenarioResult]
