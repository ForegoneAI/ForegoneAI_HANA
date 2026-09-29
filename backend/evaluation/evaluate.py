"""
evaluate.py

H9N Milestone 1, item 6 - Extraction Evaluation (scoring the cases defined
in cases.py: item 5's ground truth and item 7's holdout set).

For each case, runs the real extractor (extract_repe_deal) and compares
every field in the case's `expected` dict against what came back, field by
field. This calls the real Claude API, so - unlike the rest of the test
suite - it needs a real ANTHROPIC_API_KEY and costs a little money to run;
that's why it's a standalone script rather than part of `pytest`, which
must stay free and key-less for CI (see test_evaluate.py for what IS
covered by the automated, mocked test suite: the scoring logic itself).

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python -m backend.evaluation.evaluate                 # ground truth only
    python -m backend.evaluation.evaluate --holdout        # holdout only
    python -m backend.evaluation.evaluate --all            # both, reported separately
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from typing import Any, Optional

import anthropic

from backend.evaluation.cases import GROUND_TRUTH_CASES, HOLDOUT_CASES
from backend.app.h9n.extraction.repe_extractor import DEFAULT_MODEL, extract_repe_deal


@dataclass
class FieldResult:
    field_name: str
    expected: Any
    actual: Any
    correct: bool


@dataclass
class CaseResult:
    case_id: str
    fields: list[FieldResult] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def correct_count(self) -> int:
        return sum(1 for f in self.fields if f.correct)

    @property
    def total_count(self) -> int:
        return len(self.fields)

    @property
    def accuracy(self) -> Optional[float]:
        if self.error is not None or self.total_count == 0:
            return None
        return self.correct_count / self.total_count


def _values_match(expected: Any, actual: Any) -> bool:
    """Compares one expected/actual field value pair.

    Numbers are compared with a small tolerance (rather than exact
    equality) so trivial float formatting differences - e.g. Claude
    returning 7.90000001 instead of 7.9 - don't register as a wrong
    answer. Strings are compared case- and whitespace-insensitively for
    the same reason (e.g. "Multifamily" vs "multifamily").
    """
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        tolerance = max(1.0, abs(expected) * 0.01)
        return abs(expected - actual) <= tolerance
    if isinstance(expected, str) and isinstance(actual, str):
        return expected.strip().lower() == actual.strip().lower()
    return expected == actual


def evaluate_case(
    case: dict[str, Any],
    *,
    client: Optional[anthropic.Anthropic] = None,
    model: str = DEFAULT_MODEL,
) -> CaseResult:
    """Runs extract_repe_deal() on one case and scores it against
    `case["expected"]`. Any exception during extraction (network error,
    validation error, etc.) is caught and recorded as the case's `error`
    rather than raised, so one bad case doesn't stop the rest of a batch
    evaluation run."""
    try:
        deal = extract_repe_deal(case["pages"], client=client, model=model)
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
        return CaseResult(case_id=case["case_id"], error=f"{type(exc).__name__}: {exc}")

    result = CaseResult(case_id=case["case_id"])
    for field_name, expected_value in case["expected"].items():
        actual_value = getattr(deal, field_name, None)
        result.fields.append(
            FieldResult(
                field_name=field_name,
                expected=expected_value,
                actual=actual_value,
                correct=_values_match(expected_value, actual_value),
            )
        )
    return result


def run_evaluation(
    cases: list[dict[str, Any]],
    *,
    client: Optional[anthropic.Anthropic] = None,
    model: str = DEFAULT_MODEL,
) -> list[CaseResult]:
    """Runs evaluate_case() over every case in `cases`, reusing one client
    across all of them so only one is constructed."""
    llm_client = client or anthropic.Anthropic()
    return [evaluate_case(case, client=llm_client, model=model) for case in cases]


def format_report(results: list[CaseResult], *, label: str) -> str:
    """Formats a list of CaseResults as a plain-text report for the CLI."""
    lines = [f"=== {label} ({len(results)} case(s)) ==="]
    total_correct = 0
    total_fields = 0

    for result in results:
        if result.error is not None:
            lines.append(f"\n{result.case_id}: ERROR - {result.error}")
            continue

        total_correct += result.correct_count
        total_fields += result.total_count
        lines.append(
            f"\n{result.case_id}: {result.correct_count}/{result.total_count} fields correct"
        )
        for f in result.fields:
            marker = "OK  " if f.correct else "MISS"
            lines.append(f"  [{marker}] {f.field_name}: expected={f.expected!r} actual={f.actual!r}")

    if total_fields > 0:
        overall = total_correct / total_fields
        lines.append(f"\nOverall: {total_correct}/{total_fields} fields correct ({overall:.0%})")
    else:
        lines.append("\nOverall: no fields scored (every case errored).")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--holdout",
        action="store_true",
        help="Evaluate the holdout set (item 7) instead of the ground-truth set (item 5).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Evaluate both the ground-truth and holdout sets, reported separately.",
    )
    args = parser.parse_args()

    if args.all:
        print(format_report(run_evaluation(GROUND_TRUTH_CASES), label="Ground truth (item 5)"))
        print()
        print(format_report(run_evaluation(HOLDOUT_CASES), label="Holdout / unseen-deal (item 7)"))
    elif args.holdout:
        print(format_report(run_evaluation(HOLDOUT_CASES), label="Holdout / unseen-deal (item 7)"))
    else:
        print(format_report(run_evaluation(GROUND_TRUTH_CASES), label="Ground truth (item 5)"))


if __name__ == "__main__":
    main()
