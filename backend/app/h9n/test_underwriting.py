from decimal import Decimal as D
from backend.app.h9n.underwriting.models import UnderwritingInputs, InputValue, ScenarioAdjustments
from backend.app.h9n.underwriting.finance import calculate, irr

# Create a financial input sourced from a document.
def fact(v):
    return InputValue(value=D(str(v)), origin='source_fact', evidence_id='e1')

# Create a financial input based on a human assumption.
def assumed(v):
    return InputValue(value=D(str(v)), origin='human_assumption')

# Generate sample financial inputs for testing.
def example():
    return UnderwritingInputs(
        purchase_price=fact(1000000),
        annual_revenue=fact(180000),
        annual_operating_expenses=fact(80000),
        loan_amount=assumed(600000),
        annual_interest_rate_pct=assumed(6),
        amortization_years=assumed(30),
        hold_years=5,
        exit_cap_rate_pct=assumed(8),
        annual_noi_growth_pct=assumed(2),
        sale_cost_pct=assumed(2),
        upfront_costs=assumed(20000)
    )

# Verify NOI, cap rate, LTV, debt service, DSCR, and equity returns.
def test_basic_metrics():
    m = calculate(example()).metrics

    assert m['noi'].value == D(100000)
    assert m['cap_rate'].value == D(10)
    assert m['ltv'].value == D(60)
    assert m['annual_debt_service'].value > 0
    assert m['dscr'].value > 1
    assert m['moic'].value is not None
    assert m['irr'].value is not None

# Ensure missing inputs remain None instead of becoming zero.
def test_missing_inputs_do_not_become_zero():
    x = UnderwritingInputs(purchase_price=fact(1000000))
    m = calculate(x).metrics

    assert m['noi'].value is None
    assert m['dscr'].value is None
    assert m['irr'].value is None

# Verify downside assumptions reduce returns without modifying inputs.
def test_downside_changes_results():
    x = example()
    base = calculate(x)

    downside = calculate(
        x,
        'downside',
        ScenarioAdjustments(
            noi_pct=D(-10),
            exit_cap_rate_delta_pct=D('0.5')
        )
    )

    assert downside.metrics['noi'].value < base.metrics['noi'].value
    assert downside.metrics['irr'].value < base.metrics['irr'].value
    assert x.annual_revenue.value == D(180000)

# Verify IRR against a known 10% return.
def test_irr_known_case():
    assert abs(irr([D(-100), D(110)]) - D(10)) < D('0.0001')

# Verify annual debt service for a zero-interest loan.
def test_zero_interest_debt():
    x = example()
    x.annual_interest_rate_pct = assumed(0)

    assert calculate(x).metrics['annual_debt_service'].value == D(20000)

# Ensure missing exit assumptions prevent MOIC calculation.
def test_no_return_without_exit_assumptions():
    x = example()
    x.exit_cap_rate_pct = None

    assert calculate(x).metrics['moic'].value is None
