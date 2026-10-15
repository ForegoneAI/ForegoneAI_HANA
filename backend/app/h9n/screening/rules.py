"""
rules.py

H9N Milestone 3.2 - deterministic screening rules: every hard criterion of a
mandate (M3.1) is checked against a Deal Profile in plain Python, so known
criteria are never left to an LLM to judge.

Each criterion that is set becomes one rule, and every rule returns a
RuleResult saying "pass", "fail" or "unknown", together with the value it
compared, the value the mandate requires, the profile field it read, and that
field's source evidence.

"unknown" means "a reviewer needs to look", never a guess. A rule is unknown
when:

  * the profile field is null - not stated, or held back in withheld_values
    because its citation didn't verify or the extractor flagged it as
    uncertain or conflicting (M1.1). The withheld proposal is attached to the
    result so a reviewer can resolve it, but it is never compared;
  * a number isn't finite (NaN / infinity);
  * property_type can't be mapped to a known type ("Parking garage");
  * no market can be found, or it was only found as a word inside a longer
    place name (confidence "partial", e.g. "Uptown Dallas") - as M3.1 asks.

Comparisons are inclusive (a 5.5% cap rate meets "min 5.5"), and a value
within floating-point rounding of a bound counts as meeting it, so a
calculated 5.4999999999 doesn't fail "min 5.5".

Preferences are soft and never become rules (see mandate.py).
"""

from __future__ import annotations

import math
from typing import Any, Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field

from backend.app.h9n.schemas.base_deal import FieldEvidence, ReviewStatus, WithheldValue
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.app.h9n.screening.mandate import CRITERIA_PROFILE_FIELDS, Mandate, MandateCriteria, ValueRange
from backend.app.h9n.screening.vocabulary import PROFILE_MARKET_FIELDS, normalize_asset_type, profile_market_match

RuleStatus = Literal["pass", "fail", "unknown"]

# How the required value is shaped, by kind of rule:
#   asset_types / target_markets -> {"one_of": [...]}
#   excluded_markets             -> {"none_of": [...]}
#   deal_size / key_metrics.*    -> {"min": x, "max": y}  (None = open end)
#   leverage.*                   -> {"max": x}
RequiredValue = dict[str, Union[list[str], int, float, None]]

_MONEY_FIELDS = {"asking_price", "noi", "annual_revenue", "operating_expenses"}
_PERCENT_FIELDS = {"cap_rate", "occupancy_rate", "ltv", "interest_rate"}


class RuleResult(BaseModel):
    """The outcome of one mandate criterion for one deal."""

    # The criterion, named as in CRITERIA_PROFILE_FIELDS, e.g. "deal_size",
    # "key_metrics.cap_rate", "leverage.max_ltv".
    rule: str
    status: RuleStatus

    # The Deal Profile field the rule read. For markets, the field the market
    # was found in (market, submarket, location or address); "market" when it
    # was found in none of them.
    profile_field: str

    # What was compared: the number, or for property types and markets the
    # canonical name ("Multifamily", "Dallas-Fort Worth"). None when unknown
    # because nothing could be read.
    actual_value: Union[int, float, str, None] = None
    # The field exactly as the profile holds it ("garden-style apartment
    # community"), so a reviewer can see what the canonical name came from.
    profile_value: Union[int, float, str, None] = None

    required_value: RequiredValue

    # Verified citations for profile_field (empty if none).
    evidence: list[FieldEvidence] = Field(default_factory=list)

    # The value the extractor proposed but held back, when that's why the
    # field is null. Shown for review only; never compared.
    withheld: Optional[WithheldValue] = None

    # True when a reviewer corrected this field. Corrections don't update the
    # evidence, so its citation may show the value originally extracted.
    human_corrected: bool = False

    # One plain sentence explaining the outcome, for reviewers and M3.3.
    detail: str


class ScreeningResult(BaseModel):
    """Every rule's result for one deal against one mandate."""

    # "fail" if any rule fails, else "unknown" if any rule is unknown, else
    # "pass". A failure wins over unknowns: resolving them can't undo it.
    outcome: RuleStatus
    results: list[RuleResult]

    # Which mandate, and which edit of it, the deal was judged against (None
    # when screening unsaved criteria), so a result can always be traced to
    # the exact criteria it used.
    mandate_id: Optional[UUID] = None
    mandate_version: Optional[int] = None

    # The profile's review status at screening time. Screening doesn't refuse
    # an unapproved profile; the caller decides whether that's allowed.
    profile_review_status: ReviewStatus


def screen_deal(mandate: Mandate, profile: Union[REPEDealProfile, dict[str, Any]]) -> ScreeningResult:
    """Screens a deal against a saved mandate."""
    result = screen_criteria(mandate.criteria, profile)
    return result.model_copy(update={"mandate_id": mandate.id, "mandate_version": mandate.version})


def screen_criteria(
    criteria: MandateCriteria, profile: Union[REPEDealProfile, dict[str, Any]]
) -> ScreeningResult:
    """Screens a deal against mandate criteria (saved or not)."""
    profile = REPEDealProfile.model_validate(profile)
    results = evaluate_criteria(criteria, profile)
    return ScreeningResult(
        outcome=overall_outcome(results),
        results=results,
        profile_review_status=profile.review_status,
    )


def overall_outcome(results: list[RuleResult]) -> RuleStatus:
    statuses = {result.status for result in results}
    if "fail" in statuses:
        return "fail"
    if "unknown" in statuses:
        return "unknown"
    return "pass"


def evaluate_criteria(
    criteria: MandateCriteria, profile: Union[REPEDealProfile, dict[str, Any]]
) -> list[RuleResult]:
    """One RuleResult per hard criterion that is set, in the mandate's order.
    A dict profile is validated first (a malformed one raises
    pydantic.ValidationError rather than being screened)."""
    if not isinstance(criteria, MandateCriteria):
        raise TypeError(f"criteria must be MandateCriteria, got {type(criteria).__name__}.")
    profile = REPEDealProfile.model_validate(profile)

    results: list[RuleResult] = []
    if criteria.asset_types:
        results.append(check_asset_type(criteria.asset_types, profile))
    if criteria.target_markets:
        results.append(check_market(criteria.target_markets, profile, excluded=False))
    if criteria.excluded_markets:
        results.append(check_market(criteria.excluded_markets, profile, excluded=True))
    if criteria.deal_size:
        results.append(check_range("deal_size", criteria.deal_size, profile))
    for name, limits in criteria.key_metrics.items():
        results.append(check_range(f"key_metrics.{name}", limits, profile))
    if criteria.leverage:
        for name in ("max_ltv", "max_interest_rate"):
            limit = getattr(criteria.leverage, name)
            if limit is not None:
                results.append(check_range(f"leverage.{name}", ValueRange(max=limit), profile))
    return results


# --- Rules ----------------------------------------------------------------------


def check_range(rule: str, limits: ValueRange, profile: REPEDealProfile) -> RuleResult:
    """A numeric field against an inclusive min/max."""
    field = CRITERIA_PROFILE_FIELDS[rule]
    value = getattr(profile, field)
    required: RequiredValue = (
        {"max": limits.max} if rule.startswith("leverage.") else {"min": limits.min, "max": limits.max}
    )
    wanted = _describe_range(field, limits)

    if value is None:
        return _unknown_missing(rule, field, required, profile)
    if not math.isfinite(value):
        return _result(rule, "unknown", field, profile, required, actual=value,
                       detail=f"{field} is {value}, which can't be compared; it should be {wanted}.")

    too_low = limits.min is not None and value < limits.min and not _same(value, limits.min)
    too_high = limits.max is not None and value > limits.max and not _same(value, limits.max)
    shown = _format(field, value)
    if too_low or too_high:
        return _result(rule, "fail", field, profile, required, actual=value,
                       detail=f"{field} is {shown}; the mandate requires {wanted}.")
    return _result(rule, "pass", field, profile, required, actual=value,
                   detail=f"{field} is {shown}, which meets {wanted}.")


def check_asset_type(allowed: list[str], profile: REPEDealProfile) -> RuleResult:
    """The profile's property type, read loosely, against the allowed types."""
    rule, field = "asset_types", "property_type"
    required: RequiredValue = {"one_of": list(allowed)}
    raw = profile.property_type
    if raw is None or not raw.strip():
        return _unknown_missing(rule, field, required, profile)

    asset_type = normalize_asset_type(raw)
    if asset_type is None:
        return _result(rule, "unknown", field, profile, required,
                       detail=f"property_type {raw!r} isn't a recognized property type; a reviewer should "
                       f"decide whether it is one of: {', '.join(allowed)}.")
    if asset_type in allowed:
        return _result(rule, "pass", field, profile, required, actual=asset_type,
                       detail=f"{raw!r} is {asset_type}, an allowed property type.")
    return _result(rule, "fail", field, profile, required, actual=asset_type,
                   detail=f"{raw!r} is {asset_type}; the mandate only allows: {', '.join(allowed)}.")


def check_market(markets: list[str], profile: REPEDealProfile, *, excluded: bool) -> RuleResult:
    """The profile's market (from market, else submarket, location, address)
    against the target or excluded markets. A partial match is unknown."""
    rule = "excluded_markets" if excluded else "target_markets"
    required: RequiredValue = {"none_of" if excluded else "one_of": list(markets)}
    listed = ", ".join(markets)
    match = profile_market_match(profile)

    if match is None:
        withheld = next(
            (w for name in PROFILE_MARKET_FIELDS if (w := _withheld_for(profile, name))), None
        )
        detail = f"No known market was found in {', '.join(PROFILE_MARKET_FIELDS)}."
        if withheld:
            detail += f" A {withheld.field_name} of {withheld.proposed_value!r} was withheld ({withheld.reason})."
        return _result(rule, "unknown", "market", profile, required, withheld=withheld,
                       detail=detail + " A reviewer should confirm the market.")

    field = match.field or "market"
    source = f"{field} {getattr(profile, field)!r}"
    if match.confidence == "partial":
        return _result(rule, "unknown", field, profile, required, actual=match.market,
                       detail=f"{source} only partly matches {match.market} (via {match.matched_text!r}); "
                       "a reviewer should confirm the market.")

    inside = match.market in markets
    if excluded:
        status: RuleStatus = "fail" if inside else "pass"
        detail = (f"{source} is in {match.market}, an excluded market." if inside
                  else f"{source} is in {match.market}, which isn't excluded ({listed}).")
    else:
        status = "pass" if inside else "fail"
        detail = (f"{source} is in {match.market}, a target market." if inside
                  else f"{source} is in {match.market}; the mandate targets: {listed}.")
    return _result(rule, status, field, profile, required, actual=match.market, detail=detail)


# --- Helpers --------------------------------------------------------------------


def _result(
    rule: str,
    status: RuleStatus,
    field: str,
    profile: REPEDealProfile,
    required: RequiredValue,
    *,
    detail: str,
    actual: Union[int, float, str, None] = None,
    withheld: Optional[WithheldValue] = None,
) -> RuleResult:
    return RuleResult(
        rule=rule,
        status=status,
        profile_field=field,
        actual_value=actual,
        profile_value=getattr(profile, field, None),
        required_value=required,
        evidence=[e for e in profile.evidence if e.field_name == field],
        withheld=withheld,
        human_corrected=field in profile.corrected_fields,
        detail=detail,
    )


def _unknown_missing(rule: str, field: str, required: RequiredValue, profile: REPEDealProfile) -> RuleResult:
    """A rule whose field is null: says whether a value is waiting in review."""
    withheld = _withheld_for(profile, field)
    if withheld:
        detail = (f"{field} is empty: a value of {withheld.proposed_value!r} was withheld ({withheld.reason}) "
                  "and needs a reviewer to accept or dismiss it.")
    else:
        detail = f"{field} isn't stated in the deal profile."
    return _result(rule, "unknown", field, profile, required, withheld=withheld, detail=detail)


def _withheld_for(profile: REPEDealProfile, field: str) -> Optional[WithheldValue]:
    return next((w for w in profile.withheld_values if w.field_name == field), None)


def _same(value: float, bound: float) -> bool:
    # Absorbs float rounding only (5.4999999999 vs 5.5), never a real difference.
    return math.isclose(value, bound, rel_tol=1e-9, abs_tol=1e-9)


def _format(field: str, value: Union[int, float]) -> str:
    if field in _MONEY_FIELDS:
        sign, amount = ("-" if value < 0 else ""), abs(value)
        return f"{sign}${amount:,.0f}" if float(amount).is_integer() else f"{sign}${amount:,.2f}"
    if field in _PERCENT_FIELDS:
        return f"{value:g}%"
    if field == "year_built":
        return str(int(value))
    return f"{int(value):,}" if float(value).is_integer() else f"{value:,.2f}"


def _describe_range(field: str, limits: ValueRange) -> str:
    if limits.min is not None and limits.max is not None:
        return f"between {_format(field, limits.min)} and {_format(field, limits.max)}"
    if limits.min is not None:
        return f"at least {_format(field, limits.min)}"
    return f"at most {_format(field, limits.max)}"
