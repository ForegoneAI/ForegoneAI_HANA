"""Deterministic REPE underwriting calculations using Decimal."""

from __future__ import annotations
from decimal import Decimal, getcontext
from .models import UnderwritingInputs, Metric, ScenarioAdjustments, ScenarioResult

# Set decimal precision and percentage conversion.
getcontext().prec = 28
D = Decimal
HUNDRED = D('100')

# Retrieve an input value, returning None if unavailable.
def val(inputs: UnderwritingInputs, key: str) -> Decimal | None:
    item = getattr(inputs, key)
    return item.value if item is not None else None

# Create a metric with its formula and input references.
def metric(value, unit, formula, fields, warning=None):
    return Metric(value=value, unit=unit, formula=formula, inputs=fields, warning=warning)

# Calculate IRR using the bisection method.
def irr(flows: list[Decimal]) -> Decimal | None:
    """Returns None when a valid IRR cannot be determined."""
    if len(flows) < 2 or not any(x > 0 for x in flows) or not any(x < 0 for x in flows):
        return None

    # Calculate net present value at a given discount rate.
    def npv(rate):
        return sum(
            (cash / (D('1') + rate) ** t for t, cash in enumerate(flows)),
            D('0')
        )

    low, high = D('-0.9999'), D('1')
    f_low, f_high = npv(low), npv(high)

    # Expand the search range until an IRR root is bracketed.
    while f_low * f_high > 0 and high < D('1000000'):
        high = high * 2 + 1
        f_high = npv(high)

    if f_low * f_high > 0:
        return None

    # Narrow the interval to approximate the IRR.
    for _ in range(160):
        mid = (low + high) / 2
        f_mid = npv(mid)

        if abs(f_mid) < D('0.00000001'):
            return mid * HUNDRED

        if f_low * f_mid <= 0:
            high, f_high = mid, f_mid
        else:
            low, f_low = mid, f_mid

    return ((low + high) / 2) * HUNDRED

# Calculate annual debt payments for amortizing or interest-only loans.
def annual_debt_service(
    principal: Decimal,
    rate_pct: Decimal,
    amort_years: Decimal | None,
    interest_only: bool
):
    if principal < 0 or rate_pct < 0:
        return None

    r = rate_pct / D('1200')

    if interest_only:
        return principal * rate_pct / HUNDRED

    if amort_years is None or amort_years <= 0:
        return None

    months = amort_years * 12
    if months != int(months):
        return None

    # Handle loans with zero interest.
    if r == 0:
        return principal / months * 12

    payment = principal * r / (1 - (1 + r) ** (-int(months)))
    return payment * 12

# Calculate remaining loan principal at the end of the holding period.
def balance_after_years(principal, rate_pct, amort_years, hold_years, interest_only):
    if interest_only:
        return principal

    if amort_years is None or amort_years <= 0:
        return None

    months = int(amort_years * 12)
    if amort_years * 12 != months:
        return None

    n = min(hold_years * 12, months)
    r = rate_pct / D('1200')

    if r == 0:
        return max(D('0'), principal * (1 - D(n) / D(months)))

    # Subtract accumulated loan payments from the outstanding balance.
    monthly = annual_debt_service(principal, rate_pct, amort_years, False) / 12
    return max(
        D('0'),
        principal * (1 + r) ** n - monthly * (((1 + r) ** n - 1) / r)
    )

# Calculate financial metrics for a selected underwriting scenario.
def calculate(
    inputs: UnderwritingInputs,
    name: str = 'base',
    adjustments: ScenarioAdjustments | None = None
) -> ScenarioResult:

    a = adjustments or ScenarioAdjustments()
    warnings = []

    # Apply scenario adjustments to purchase price and NOI.
    price = val(inputs, 'purchase_price')
    if price is not None:
        price *= (1 + a.purchase_price_pct / HUNDRED)

    revenue = val(inputs, 'annual_revenue')
    expenses = val(inputs, 'annual_operating_expenses')
    noi = val(inputs, 'annual_noi')

    # Derive NOI when revenue and expenses are available.
    if noi is None and revenue is not None and expenses is not None:
        noi = revenue - expenses

    if noi is not None:
        noi *= (1 + a.noi_pct / HUNDRED)

    # Retrieve loan terms and adjust scenario assumptions.
    loan = val(inputs, 'loan_amount')
    rate = val(inputs, 'annual_interest_rate_pct')
    if rate is not None:
        rate += a.interest_rate_delta_pct

    amort = val(inputs, 'amortization_years')
    exit_cap = val(inputs, 'exit_cap_rate_pct')
    if exit_cap is not None:
        exit_cap += a.exit_cap_rate_delta_pct

    growth = val(inputs, 'annual_noi_growth_pct')
    if growth is not None:
        growth += a.noi_growth_delta_pct

    costs = val(inputs, 'upfront_costs')
    sale_pct = val(inputs, 'sale_cost_pct')

    # Flag invalid or unusual financial assumptions.
    if price is not None and price <= 0:
        warnings.append('Purchase price must be positive for ratios and equity analysis.')
    if exit_cap is not None and exit_cap <= 0:
        warnings.append('Exit cap rate must be positive.')
    if rate is not None and rate < 0:
        warnings.append('Interest rate cannot be negative.')
    if loan is not None and price is not None and loan > price:
        warnings.append('Loan exceeds purchase price.')

    # Calculate debt service and key financial ratios.
    ds = annual_debt_service(loan, rate, amort, inputs.interest_only) if loan is not None and rate is not None and rate >= 0 else None
    cap = noi / price * HUNDRED if noi is not None and price is not None and price > 0 else None
    ltv = loan / price * HUNDRED if loan is not None and price is not None and price > 0 else None
    dscr = noi / ds if noi is not None and ds is not None and ds > 0 else None

    # Store calculated metrics with formulas and source fields.
    fields = {
        'noi': metric(noi, 'currency', 'annual_noi or annual_revenue - annual_operating_expenses', ['annual_noi', 'annual_revenue', 'annual_operating_expenses']),
        'cap_rate': metric(cap, 'percent', 'NOI / purchase_price * 100', ['annual_noi', 'purchase_price']),
        'ltv': metric(ltv, 'percent', 'loan_amount / purchase_price * 100', ['loan_amount', 'purchase_price']),
        'annual_debt_service': metric(ds, 'currency', '12 * amortizing monthly payment (or annual interest-only payment)', ['loan_amount', 'annual_interest_rate_pct', 'amortization_years']),
        'dscr': metric(dscr, 'ratio', 'NOI / annual_debt_service', ['annual_noi', 'loan_amount', 'annual_interest_rate_pct']),
    }

    flows = None

    # Calculate equity returns only when all required inputs exist.
    if all(v is not None for v in [price, noi, loan, ds, exit_cap, growth, costs, sale_pct]) and price > 0 and exit_cap > 0 and rate is not None and rate >= 0:
        equity = price - loan + costs

        if equity <= 0:
            warnings.append('Initial equity must be positive to calculate equity returns.')
        else:
            flows = [-equity]

            # Project annual cash flow during the holding period.
            for year in range(1, inputs.hold_years + 1):
                annual_noi = noi * (1 + growth / HUNDRED) ** (year - 1)
                flows.append(annual_noi - ds)

            # Estimate exit proceeds and subtract the remaining loan balance.
            exit_noi = noi * (1 + growth / HUNDRED) ** inputs.hold_years
            sale = exit_noi / (exit_cap / HUNDRED)
            balance = balance_after_years(loan, rate, amort, inputs.hold_years, inputs.interest_only)

            if balance is not None:
                flows[-1] += sale * (1 - sale_pct / HUNDRED) - balance
            else:
                flows = None

    # Report when equity returns cannot be calculated.
    if flows is None:
        warnings.append('MOIC/IRR unavailable: complete positive-equity, exit, debt, cost and growth inputs are required.')

    # Calculate equity multiple and internal rate of return.
    moic = sum((f for f in flows[1:]), D('0')) / (-flows[0]) if flows else None

    fields['moic'] = metric(
        moic, 'multiple', 'sum(equity distributions) / initial equity',
        ['purchase_price', 'loan_amount', 'upfront_costs', 'exit_cap_rate_pct', 'annual_noi_growth_pct', 'sale_cost_pct']
    )

    fields['irr'] = metric(
        irr(flows) if flows else None, 'percent',
        'discount rate where NPV(equity cash flows) = 0',
        ['purchase_price', 'loan_amount', 'annual_noi', 'exit_cap_rate_pct', 'annual_noi_growth_pct']
    )

    # Return scenario metrics, cash flows, and validation warnings.
    return ScenarioResult(
        name=name,
        adjustments=a,
        metrics=fields,
        annual_cash_flows=flows,
        warnings=warnings
    )
