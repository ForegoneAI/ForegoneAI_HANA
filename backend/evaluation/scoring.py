"""Reference-based benchmark metrics, independent of the model and dataset.

Adapted from the supplied HANA M1 benchmark pack. Omitted output and crashed
cases stay in every applicable denominator. A null from a withheld value is
never treated as a successful missing-field detection.
"""

from __future__ import annotations

import math
from typing import Any


def ratio(n: int, d: int) -> float | None:
    return n / d if d else None


def equal(a: Any, b: Any, tolerance: float = 0) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= tolerance + 1e-8
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y, tolerance) for x, y in zip(a, b))
    if isinstance(a, str) and isinstance(b, str):
        return " ".join(a.casefold().split()) == " ".join(b.casefold().split())
    return type(a) is type(b) and a == b


def same_candidates(actual: Any, expected: list, tolerance: float) -> bool:
    """Unordered multiset comparison; ranges inside candidates retain order."""
    if not isinstance(actual, list) or len(actual) != len(expected):
        return False
    remaining = list(expected)
    for candidate in actual:
        match = next((i for i, v in enumerate(remaining) if equal(candidate, v, tolerance)), None)
        if match is None:
            return False
        remaining.pop(match)
    return True


def location_key(loc: Any) -> tuple | None:
    if not isinstance(loc, dict) or not isinstance(loc.get("document_id"), str) or not loc["document_id"]:
        return None
    if "page" in loc:
        if type(loc["page"]) is int and loc["page"] > 0 and not ("sheet" in loc or "cell" in loc):
            return loc["document_id"], "page", loc["page"]
        return None
    if all(isinstance(loc.get(k), str) and loc[k] for k in ("sheet", "cell")):
        return loc["document_id"], "cell", loc["sheet"], loc["cell"].upper()
    return None


def value_correct(pred: Any, gold: dict) -> bool:
    if not isinstance(pred, dict) or pred.get("status") != gold["status"] or "value" not in pred:
        return False
    if gold["status"] == "missing":
        return pred["value"] is None and not pred.get("candidates")
    if pred.get("unit") != gold["unit"]:
        return False
    if gold["status"] == "conflict":
        return pred["value"] is None and same_candidates(pred.get("candidates"), gold["candidates"], gold["abs_tolerance"])
    return not pred.get("candidates") and equal(pred["value"], gold["value"], gold["abs_tolerance"])


def evidence_correct(pred: Any, gold: dict, evidence: dict) -> bool:
    if not isinstance(pred, dict):
        return False
    locs = pred.get("evidence")
    if not isinstance(locs, list):
        return False
    if gold["status"] == "missing":
        return not locs
    actual = {location_key(x) for x in locs}
    expected = {location_key(x) for x in evidence["locations"]}
    if not actual or None in actual:
        return False
    # Normal fields accept curated alternatives; conflicts require every
    # conflicting location. Extra unreviewed citations fail either metric.
    return actual == expected if gold["status"] == "conflict" else bool(actual & expected) and actual <= expected


def score_case(prediction: dict, gold: dict, evidence: dict) -> tuple[list[dict], list[str]]:
    fields = prediction.get("fields", {})
    if not isinstance(fields, dict):
        fields = {}
    rows = []
    for name, expected in gold.items():
        pred = fields.get(name)
        correct = value_correct(pred, expected)
        ev = evidence_correct(pred, expected, evidence[name])
        claim = isinstance(pred, dict) and (pred.get("value") is not None or bool(pred.get("candidates")))
        missing = (isinstance(pred, dict) and pred.get("status") == "missing"
                   and "value" in pred and pred["value"] is None and not pred.get("candidates"))
        rows.append({
            "field": name, "expected_status": expected["status"], "prediction_present": pred is not None,
            "value_correct": correct, "evidence_correct": ev, "grounded_correct": correct and ev,
            "missing_predicted": missing, "claim": claim, "unsupported_reference_claim": claim and not correct,
            "prediction": pred, "expected": expected, "evidence_expected": evidence[name],
        })
    return rows, sorted(set(fields) - set(gold))


def summarize(rows: list[dict]) -> dict:
    present = [r for r in rows if r["expected_status"] == "present"]
    evidence = [r for r in rows if r["expected_status"] != "missing"]
    pdf = [r for r in evidence if all("page" in x for x in r["evidence_expected"]["locations"])]
    sheets = [r for r in evidence if any("cell" in x for x in r["evidence_expected"]["locations"])]
    missing = [r for r in rows if r["expected_status"] == "missing"]
    predicted_missing = [r for r in rows if r["missing_predicted"]]
    conflicts = [r for r in rows if r["expected_status"] == "conflict"]
    true_missing = sum(r["value_correct"] for r in missing)
    precision = ratio(true_missing, len(predicted_missing))
    recall = ratio(true_missing, len(missing))
    f1 = (2 * precision * recall / (precision + recall)
          if precision is not None and recall is not None and precision + recall
          else (0 if missing else None))

    def accuracy(group: list[dict], key: str) -> float | None:
        return ratio(sum(r[key] for r in group), len(group))

    return {
        "field_accuracy": accuracy(rows, "value_correct"),
        "present_value_accuracy": accuracy(present, "value_correct"),
        "output_coverage": accuracy(rows, "prediction_present"),
        "missing_detection_precision": precision, "missing_detection_recall": recall, "missing_detection_f1": f1,
        "unsupported_extraction_rate_reference": ratio(sum(r["unsupported_reference_claim"] for r in rows), sum(r["claim"] for r in rows)),
        "evidence_location_accuracy": accuracy(evidence, "evidence_correct"),
        "evidence_page_accuracy": accuracy(pdf, "evidence_correct"),
        "evidence_cell_accuracy": accuracy(sheets, "evidence_correct"),
        "grounded_accuracy": accuracy(rows, "grounded_correct"),
        "conflict_accuracy": accuracy(conflicts, "value_correct"),
        "counts": {"fields": len(rows), "present": len(present), "missing": len(missing),
                   "conflicts": len(conflicts), "claims": sum(r["claim"] for r in rows)},
    }


def model_cost(pred: dict, pricing: dict) -> float | None:
    """USD token estimate. Unknown usage/rates never become a free run.

    input_tokens includes both cache reads and creations. Cache creation has a
    separate optional rate, required only if creation tokens were reported.
    """
    if pred.get("execution_kind") == "local_no_model" and pred.get("usage") == []:
        return 0.0
    usage = pred.get("usage")
    if not isinstance(usage, list) or not usage:
        return None
    total = 0.0
    for call in usage:
        if not isinstance(call, dict) or not isinstance(call.get("model"), str):
            return None
        rate = pricing.get(call["model"])
        if not isinstance(rate, dict):
            return None
        inp, out = call.get("input_tokens"), call.get("output_tokens")
        cached, created = call.get("cached_input_tokens", 0), call.get("cache_creation_input_tokens", 0)
        if any(type(x) is not int or x < 0 for x in (inp, out, cached, created)) or cached + created > inp:
            return None
        tokens = {"input_per_million": inp - cached - created, "output_per_million": out,
                  "cached_input_per_million": cached, "cache_creation_input_per_million": created}
        for key, count in tokens.items():
            value = rate.get(key)
            if count == 0 and value is None:
                continue
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                return None
            total += count * value / 1_000_000
    return total
