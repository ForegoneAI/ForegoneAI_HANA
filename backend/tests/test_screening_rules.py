"""Tests for Milestone 3.2 - deterministic screening rules.

Pure Python, no network or LLM: every case checks that a criterion gives the
right pass / fail / unknown, with the actual value, required value, profile
field and evidence it was judged on.
"""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.app.h9n.schemas.base_deal import FieldEvidence, WithheldValue
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.app.h9n.screening.mandate import CRITERIA_PROFILE_FIELDS, DEMO_MANDATE, Mandate, MandateCriteria
from backend.app.h9n.screening.rules import (
    RuleResult,
    evaluate_criteria,
    overall_outcome,
    screen_criteria,
    screen_deal,
)


def _profile(**fields) -> REPEDealProfile:
    return REPEDealProfile(**fields)


def _one(criteria: dict, profile: REPEDealProfile) -> RuleResult:
    results = evaluate_criteria(MandateCriteria(**criteria), profile)
    assert len(results) == 1
    return results[0]


def _evidence(field: str, value: str) -> FieldEvidence:
    return FieldEvidence(
        field_name=field, value=value, source_document="om.pdf", page_number=3,
        snippet=f"{field}: {value}", verification="value_matched",
    )


# --- Numeric ranges --------------------------------------------------------------


@pytest.mark.parametrize(
    ("price", "status"),
    [(4_999_999, "fail"), (5_000_000, "pass"), (20_000_000, "pass"), (50_000_000, "pass"), (50_000_001, "fail")],
)
def test_deal_size_is_inclusive(price, status):
    result = _one({"deal_size": {"min": 5_000_000, "max": 50_000_000}}, _profile(asking_price=price))
    assert result.status == status
    assert result.rule == "deal_size"
    assert result.profile_field == "asking_price"
    assert result.actual_value == price
    assert result.required_value == {"min": 5_000_000, "max": 50_000_000}


def test_float_rounding_at_a_bound_is_not_a_failure():
    result = _one({"key_metrics": {"cap_rate": {"min": 5.5}}}, _profile(cap_rate=5.4999999999999))
    assert result.status == "pass"
    assert _one({"key_metrics": {"cap_rate": {"min": 5.5}}}, _profile(cap_rate=5.49)).status == "fail"


def test_fail_detail_states_actual_and_required():
    result = _one({"key_metrics": {"occupancy_rate": {"min": 90}}}, _profile(occupancy_rate=84.5))
    assert result.status == "fail"
    assert "84.5%" in result.detail and "at least 90%" in result.detail


def test_negative_noi_is_compared_not_rejected():
    result = _one({"key_metrics": {"noi": {"min": 0}}}, _profile(noi=-125_000))
    assert result.status == "fail"
    assert "-$125,000" in result.detail


@pytest.mark.parametrize(("ltv", "status"), [(60, "pass"), (65, "pass"), (70.5, "fail")])
def test_leverage_is_a_maximum(ltv, status):
    result = _one({"leverage": {"max_ltv": 65}}, _profile(ltv=ltv))
    assert result.status == status
    assert result.rule == "leverage.max_ltv"
    assert result.profile_field == "ltv"
    assert result.required_value == {"max": 65}


def test_missing_number_is_unknown():
    result = _one({"deal_size": {"min": 1_000_000}}, _profile())
    assert result.status == "unknown"
    assert result.actual_value is None
    assert result.withheld is None
    assert "isn't stated" in result.detail


def test_withheld_number_is_unknown_and_never_compared():
    withheld = WithheldValue(
        field_name="cap_rate", proposed_value=7.0, reason="model_uncertain", detail="Approximate figure."
    )
    result = _one({"key_metrics": {"cap_rate": {"min": 5.5}}}, _profile(withheld_values=[withheld]))
    # 7.0 would pass, but it isn't verified, so the rule must not say so.
    assert result.status == "unknown"
    assert result.actual_value is None
    assert result.withheld == withheld
    assert "model_uncertain" in result.detail


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_number_is_unknown(value):
    assert _one({"key_metrics": {"cap_rate": {"min": 5.5}}}, _profile(cap_rate=value)).status == "unknown"


def test_evidence_and_correction_are_attached():
    profile = _profile(
        asking_price=9_500_000,
        evidence=[_evidence("asking_price", "$9,000,000"), _evidence("noi", "$600,000")],
        corrected_fields=["asking_price"],
    )
    result = _one({"deal_size": {"max": 10_000_000}}, profile)
    assert result.status == "pass"
    assert [e.field_name for e in result.evidence] == ["asking_price"]
    assert result.human_corrected is True


# --- Property type ---------------------------------------------------------------


def test_asset_type_pass_reads_wording_loosely():
    result = _one({"asset_types": ["Multifamily"]}, _profile(property_type="Garden-style apartment community"))
    assert result.status == "pass"
    assert result.actual_value == "Multifamily"
    assert result.profile_value == "Garden-style apartment community"
    assert result.required_value == {"one_of": ["Multifamily"]}


def test_asset_type_fail():
    result = _one({"asset_types": ["Multifamily", "Industrial"]}, _profile(property_type="Class A office building"))
    assert result.status == "fail"
    assert result.actual_value == "Office"


@pytest.mark.parametrize("property_type", [None, "   ", "Parking garage"])
def test_asset_type_unknown(property_type):
    result = _one({"asset_types": ["Multifamily"]}, _profile(property_type=property_type))
    assert result.status == "unknown"
    assert result.actual_value is None


# --- Markets ---------------------------------------------------------------------


def test_target_market_pass_from_address_when_market_is_empty():
    result = _one({"target_markets": ["Dallas-Fort Worth"]}, _profile(address="12 Elm St, Plano, TX 75024"))
    assert result.status == "pass"
    assert result.actual_value == "Dallas-Fort Worth"
    assert result.profile_field == "address"


def test_target_market_fail():
    result = _one({"target_markets": ["Austin", "Phoenix"]}, _profile(market="Chicago, IL"))
    assert result.status == "fail"
    assert result.actual_value == "Chicago"
    assert result.profile_field == "market"


def test_excluded_market():
    criteria = {"excluded_markets": ["New York"]}
    assert _one(criteria, _profile(market="Brooklyn, NY")).status == "fail"
    passed = _one(criteria, _profile(market="Austin, TX"))
    assert passed.status == "pass"
    assert passed.required_value == {"none_of": ["New York"]}


def test_partial_market_match_is_unknown():
    result = _one({"target_markets": ["Dallas-Fort Worth"]}, _profile(submarket="Uptown Dallas"))
    assert result.status == "unknown"
    assert result.actual_value == "Dallas-Fort Worth"
    assert result.profile_field == "submarket"
    # A partial match never decides an exclusion either.
    assert _one({"excluded_markets": ["Dallas-Fort Worth"]}, _profile(submarket="Uptown Dallas")).status == "unknown"


def test_unplaceable_market_is_unknown_with_withheld_value():
    withheld = WithheldValue(
        field_name="location", proposed_value="Austin, TX", reason="snippet_not_on_page", detail="Quote not found."
    )
    result = _one(
        {"target_markets": ["Austin"]}, _profile(market="Portland, ME", withheld_values=[withheld])
    )
    assert result.status == "unknown"
    assert result.profile_field == "market"
    assert result.withheld == withheld


# --- Whole screenings --------------------------------------------------------------


def _demo_fit() -> REPEDealProfile:
    return _profile(
        property_type="Multifamily",
        market="Phoenix, AZ",
        asking_price=24_000_000,
        cap_rate=5.8,
        occupancy_rate=94,
        ltv=60,
    )


def test_demo_mandate_passes_a_fitting_deal():
    result = screen_criteria(DEMO_MANDATE.criteria, _demo_fit())
    assert result.outcome == "pass"
    assert [r.rule for r in result.results] == [
        "asset_types", "target_markets", "deal_size",
        "key_metrics.cap_rate", "key_metrics.occupancy_rate", "leverage.max_ltv",
    ]


def test_only_set_criteria_become_rules():
    results = evaluate_criteria(MandateCriteria(leverage={"max_interest_rate": 7}), _demo_fit())
    assert [r.rule for r in results] == ["leverage.max_interest_rate"]
    assert results[0].status == "unknown"  # interest_rate not stated


def test_every_criterion_maps_to_a_rule():
    criteria = MandateCriteria(
        asset_types=["Office"],
        target_markets=["Austin"],
        excluded_markets=["Chicago"],
        deal_size={"min": 1},
        key_metrics={name: {"min": 1} for name in
                     ("cap_rate", "occupancy_rate", "noi", "annual_revenue",
                      "operating_expenses", "units", "square_feet")} | {"year_built": {"min": 1900}},
        leverage={"max_ltv": 70, "max_interest_rate": 8},
    )
    results = evaluate_criteria(criteria, _profile())
    assert {r.rule for r in results} == set(CRITERIA_PROFILE_FIELDS)
    for r in results:
        if r.rule not in ("target_markets", "excluded_markets"):
            assert r.profile_field == CRITERIA_PROFILE_FIELDS[r.rule]
    assert all(r.status == "unknown" for r in results)


@pytest.mark.parametrize(
    ("statuses", "outcome"),
    [(["pass", "pass"], "pass"), (["pass", "unknown"], "unknown"), (["unknown", "fail"], "fail"), ([], "pass")],
)
def test_overall_outcome(statuses, outcome):
    results = [
        RuleResult(rule="deal_size", status=s, profile_field="asking_price", required_value={}, detail="")
        for s in statuses
    ]
    assert overall_outcome(results) == outcome


def test_screen_deal_records_mandate_version_and_review_status():
    now = datetime.now(timezone.utc)
    mandate = Mandate(
        **DEMO_MANDATE.model_dump(), id=uuid4(), organization_id=uuid4(), version=3, created_at=now, updated_at=now
    )
    profile = _demo_fit().model_copy(update={"cap_rate": 4.9})
    result = screen_deal(mandate, profile)
    assert result.outcome == "fail"
    assert result.mandate_id == mandate.id
    assert result.mandate_version == 3
    assert result.profile_review_status == "pending"


def test_dict_profile_is_validated():
    result = screen_criteria(MandateCriteria(deal_size={"max": 10}), {"asking_price": 5})
    assert result.outcome == "pass"
    with pytest.raises(ValidationError):
        screen_criteria(MandateCriteria(deal_size={"max": 10}), {"asking_price": "lots"})


def test_criteria_must_be_validated_mandate_criteria():
    with pytest.raises(TypeError):
        evaluate_criteria({"deal_size": {"max": 10}}, _profile())


def test_screening_is_deterministic():
    first = screen_criteria(DEMO_MANDATE.criteria, _demo_fit()).model_dump()
    assert all(screen_criteria(DEMO_MANDATE.criteria, _demo_fit()).model_dump() == first for _ in range(5))
