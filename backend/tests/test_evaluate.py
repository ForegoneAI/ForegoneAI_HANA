"""
Automated tests for backend/evaluation/evaluate.py (Milestone 1, item 6).

These test the SCORING LOGIC only, using a fake Anthropic client - they do
not call the real API and don't prove anything about real extraction
accuracy. Actually scoring the extractor requires a real ANTHROPIC_API_KEY
and is run manually via `python -m backend.evaluation.evaluate` (see that
file's docstring), not as part of this automated, key-less suite.
"""

from unittest.mock import MagicMock

from backend.evaluation.cases import GROUND_TRUTH_CASES
from backend.evaluation.evaluate import (
    CaseResult,
    _values_match,
    evaluate_case,
    format_report,
    run_evaluation,
)


def _fake_client_returning(tool_input: dict) -> MagicMock:
    tool_use_block = MagicMock()
    tool_use_block.type = "tool_use"
    tool_use_block.input = tool_input

    response = MagicMock()
    response.content = [tool_use_block]

    client = MagicMock()
    client.messages.create.return_value = response
    return client


def test_values_match_allows_small_numeric_tolerance():
    assert _values_match(7.9, 7.9000001)
    assert _values_match(18_500_000, 18_500_000)
    assert not _values_match(18_500_000, 10)


def test_values_match_is_case_and_whitespace_insensitive_for_strings():
    assert _values_match("Multifamily", "multifamily")
    assert _values_match(" Austin, TX ", "Austin, TX")
    assert not _values_match("Multifamily", "Office")


def test_evaluate_case_scores_a_fully_correct_extraction_at_100_percent():
    case = GROUND_TRUTH_CASES[0]
    fake_client = _fake_client_returning(dict(case["expected"]))

    result = evaluate_case(case, client=fake_client)

    assert result.error is None
    assert result.accuracy == 1.0
    assert result.correct_count == result.total_count


def test_evaluate_case_flags_a_wrong_field_without_failing_the_whole_case():
    case = GROUND_TRUTH_CASES[0]
    wrong_output = dict(case["expected"])
    wrong_output["asking_price"] = 1  # deliberately wrong
    fake_client = _fake_client_returning(wrong_output)

    result = evaluate_case(case, client=fake_client)

    assert result.error is None
    assert result.accuracy is not None and result.accuracy < 1.0
    wrong_field = next(f for f in result.fields if f.field_name == "asking_price")
    assert wrong_field.correct is False


def test_evaluate_case_records_an_error_instead_of_raising():
    case = GROUND_TRUTH_CASES[0]
    fake_client = MagicMock()
    fake_client.messages.create.side_effect = RuntimeError("network error")

    result = evaluate_case(case, client=fake_client)

    assert result.error is not None
    assert "network error" in result.error
    assert result.accuracy is None


def test_run_evaluation_scores_every_case():
    fake_client = _fake_client_returning(dict(GROUND_TRUTH_CASES[0]["expected"]))

    results = run_evaluation(GROUND_TRUTH_CASES, client=fake_client)

    assert len(results) == len(GROUND_TRUTH_CASES)
    assert all(isinstance(r, CaseResult) for r in results)


def test_format_report_includes_overall_accuracy():
    fake_client = _fake_client_returning(dict(GROUND_TRUTH_CASES[0]["expected"]))
    results = run_evaluation([GROUND_TRUTH_CASES[0]], client=fake_client)

    report = format_report(results, label="Test run")

    assert "Test run" in report
    assert "Overall:" in report
    assert "100%" in report
