"""M1.4/M1.5 benchmark entry point and legacy synthetic scoring helpers.

Run: python -m backend.evaluation.evaluate --allow-draft
See backend/evaluation/README.md for review, replay, holdout, and cost options.
Synthetic helpers are retained for existing unit tests only; the CLI routes to
benchmark.py and uses source snapshots with separately versioned answer keys.
"""

from __future__ import annotations

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


def main() -> int:
    """The public command now evaluates the real M1.4 dataset.

    Legacy synthetic scoring helpers above remain available to the existing
    unit tests; they do not establish performance on real deal packages.
    """
    from backend.evaluation.benchmark import main as benchmark_main

    return benchmark_main()


if __name__ == "__main__":
    raise SystemExit(main())
