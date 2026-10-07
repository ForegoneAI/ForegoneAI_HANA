"""
Automated tests for backend/evaluation/evaluate.py (Milestone 1, item 6).

These test the SCORING LOGIC only, using a fake Anthropic client - they do
not call the real API and don't prove anything about real extraction
accuracy. Actually scoring the extractor requires a real ANTHROPIC_API_KEY
and is run manually via `python -m backend.evaluation.evaluate` (see that
file's docstring), not as part of this automated, key-less suite.
"""

from unittest.mock import MagicMock

from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.evaluation import evaluate
from backend.evaluation.cases import GROUND_TRUTH_CASES
from backend.evaluation.evaluate import (
    CaseResult,
    _values_match,
    evaluate_case,
    format_report,
    run_evaluation,
)
from backend.tests.extraction_fakes import fake_client


def _extractor_returning(monkeypatch, values: dict) -> None:
    """Stubs the extractor itself with a fixed profile. These tests are about
    scoring, so they shouldn't depend on what a fake model call has to look
    like to pass extraction's own validation and evidence checks (those are
    covered in test_repe_extractor.py and test_extraction_reliability.py)."""

    def fake_extract_repe_deal(pages, *, client=None, model=None):
        return REPEDealProfile(**values)

    monkeypatch.setattr(evaluate, "extract_repe_deal", fake_extract_repe_deal)


def test_values_match_allows_small_numeric_tolerance():
    assert _values_match(7.9, 7.9000001)
    assert _values_match(18_500_000, 18_500_000)
    assert not _values_match(18_500_000, 10)


def test_values_match_is_case_and_whitespace_insensitive_for_strings():
    assert _values_match("Multifamily", "multifamily")
    assert _values_match(" Austin, TX ", "Austin, TX")
    assert not _values_match("Multifamily", "Office")


def test_evaluate_case_scores_a_fully_correct_extraction_at_100_percent(monkeypatch):
    case = GROUND_TRUTH_CASES[0]
    _extractor_returning(monkeypatch, dict(case["expected"]))

    result = evaluate_case(case, client=MagicMock())

    assert result.error is None
    assert result.accuracy == 1.0
    assert result.correct_count == result.total_count


def test_evaluate_case_flags_a_wrong_field_without_failing_the_whole_case(monkeypatch):
    case = GROUND_TRUTH_CASES[0]
    wrong_output = dict(case["expected"])
    wrong_output["asking_price"] = 1  # deliberately wrong
    _extractor_returning(monkeypatch, wrong_output)

    result = evaluate_case(case, client=MagicMock())

    assert result.error is None
    assert result.accuracy is not None and result.accuracy < 1.0
    wrong_field = next(f for f in result.fields if f.field_name == "asking_price")
    assert wrong_field.correct is False


def test_evaluate_case_records_an_error_instead_of_raising():
    case = GROUND_TRUTH_CASES[0]

    result = evaluate_case(case, client=fake_client(error=RuntimeError("network error")))

    assert result.error is not None
    assert "network error" in result.error
    assert result.accuracy is None


def test_run_evaluation_scores_every_case(monkeypatch):
    _extractor_returning(monkeypatch, dict(GROUND_TRUTH_CASES[0]["expected"]))

    results = run_evaluation(GROUND_TRUTH_CASES, client=MagicMock())

    assert len(results) == len(GROUND_TRUTH_CASES)
    assert all(isinstance(r, CaseResult) for r in results)


def test_format_report_includes_overall_accuracy(monkeypatch):
    _extractor_returning(monkeypatch, dict(GROUND_TRUTH_CASES[0]["expected"]))
    results = run_evaluation([GROUND_TRUTH_CASES[0]], client=MagicMock())

    report = format_report(results, label="Test run")

    assert "Test run" in report
    assert "Overall:" in report
    assert "100%" in report
