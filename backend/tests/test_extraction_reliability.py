"""Tests for Milestone 1.1 - extraction reliability.

Covers the layers between the model and the database:
  - the strict tool-call schemas (REPEExtractionOutput, ReviewerFeedbackOutput)
    and the validate-and-retry loop,
  - controlled errors and the time budget for bad input, provider failures,
    and bad output,
  - the evidence checks that decide which values are stored and which are
    withheld for a reviewer (enforce_integrity, verify_corrections),
  - the hardened reviewer-feedback path.

Everything runs against fake clients (or the real SDK over a fake HTTP
transport), so no API key or network is needed.
"""

import inspect
import json

import anthropic
import httpx2
import pydantic
import pytest
from anthropic.resources.messages import Messages

from backend.app.h9n.extraction import repe_extractor
from backend.app.h9n.extraction.extraction_output import (
    MIN_SNIPPET_CHARS,
    NON_EXTRACTABLE_FIELDS,
    VALUE_FIELDS,
    ExtractedEvidence,
    REPEExtractionOutput,
    ReviewerFeedbackOutput,
    enforce_integrity,
    numbers_in_text,
    snippet_is_on_page,
    snippet_supports_value,
)
from backend.app.h9n.extraction.repe_extractor import (
    EXTRACTION_TOOL_NAME,
    MAX_OUTPUT_ATTEMPTS,
    ExtractionConfigurationError,
    ExtractionInputError,
    ExtractionOutputError,
    ExtractionRefusedError,
    ExtractionUnavailableError,
    _build_tool_schema,
    apply_reviewer_feedback,
    extract_repe_deal,
    feedback_updates,
)
from backend.app.h9n.schemas.base_deal import FieldEvidence, WithheldValue
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.evaluation.cases import GROUND_TRUTH_CASES
from backend.tests.extraction_fakes import evidence, fake_client, full_output, text_response, tool_response

PAGES = [
    {
        "file_name": "fixture.pdf",
        "page_number": 1,
        "text": "Deal Name: Fixture Deal\nAsking Price: $10,000,000\nOccupancy: 94%",
    },
    {
        "file_name": "fixture.pdf",
        "page_number": 3,
        "text": "Sponsor: Acme Capital Partners\nNOI of $650K for the trailing twelve months.",
    },
]


def _valid_output(**overrides):
    values = {
        "deal_name": "Fixture Deal",
        "asking_price": 10_000_000,
        "evidence": [
            evidence("deal_name", "Fixture Deal", "Deal Name: Fixture Deal"),
            evidence("asking_price", 10_000_000, "Asking Price: $10,000,000"),
        ],
    }
    values.update(overrides)
    return full_output(**values)


def _page(text, page_number=1, file_name="fixture.pdf"):
    return {"file_name": file_name, "page_number": page_number, "text": text}


def _enforce(pages=PAGES, **overrides):
    return enforce_integrity(REPEExtractionOutput.model_validate(full_output(**overrides)), pages)


def _one(field_name, value, snippet, page_text, **entry_options):
    """enforce_integrity on a one-page document with one value and one citation."""
    return _enforce(
        [_page(page_text)], **{field_name: value}, evidence=[evidence(field_name, value, snippet, **entry_options)]
    )


# --- Tool schema -------------------------------------------------------------


def test_tool_schema_requires_every_field_and_hides_reviewer_fields():
    schema = _build_tool_schema()["input_schema"]

    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert set(VALUE_FIELDS) <= set(schema["properties"])
    assert not NON_EXTRACTABLE_FIELDS & set(schema["properties"])
    for name in ("evidence", "field_flags"):
        assert schema["properties"][name]["items"]["additionalProperties"] is False


def test_every_deal_field_is_extracted_and_checked():
    # Not just the headline IMPORTANT_FIELDS - every deal value on the profile.
    assert {"occupancy_rate", "interest_rate", "sponsor_name", "business_plan"} <= set(VALUE_FIELDS)


def test_the_model_cannot_set_how_its_evidence_was_verified():
    # `verification` is set by the checker, never taken from the model.
    evidence_schema = _build_tool_schema()["input_schema"]["properties"]["evidence"]["items"]

    assert "verification" not in evidence_schema["properties"]


# --- Strict output validation -----------------------------------------------


@pytest.mark.parametrize(
    "bad_output",
    [
        pytest.param(_valid_output(made_up_field=1), id="unknown field"),
        pytest.param(_valid_output(review_status="approved"), id="reviewer-owned field"),
        pytest.param({k: v for k, v in _valid_output().items() if k != "noi"}, id="omitted field"),
        pytest.param(_valid_output(cap_rate=650), id="out-of-bounds percentage"),
        pytest.param(_valid_output(asking_price=-5), id="negative price"),
        pytest.param(_valid_output(year_built=3025), id="impossible year"),
        pytest.param(_valid_output(asking_price="$10M"), id="unnormalized number"),
        pytest.param(_valid_output(asking_price="10000000"), id="number as a string"),
        pytest.param(_valid_output(units=True), id="boolean as an integer"),
        pytest.param(_valid_output(cap_rate=False), id="boolean as a float"),
        pytest.param(_valid_output(asking_price=float("nan")), id="NaN"),
        pytest.param(
            _valid_output(field_flags=[{"field_name": "not_a_field", "flag": "uncertain", "note": "x"}]),
            id="flag for unknown field",
        ),
        pytest.param(
            full_output(evidence=[{"field_name": "noi", "value": "1", "page_number": 1, "snippet": "x"}]),
            id="incomplete evidence",
        ),
    ],
)
def test_malformed_output_is_rejected_by_the_schema(bad_output):
    with pytest.raises(pydantic.ValidationError):
        REPEExtractionOutput.model_validate(bad_output)


def test_an_integer_is_accepted_for_a_decimal_field():
    assert REPEExtractionOutput.model_validate(full_output(asking_price=10_000_000)).asking_price == 10_000_000


def test_evidence_value_accepts_a_bare_number_as_display_text():
    # `value` is only shown to the reviewer, so a number shouldn't cost a retry.
    entry = ExtractedEvidence.model_validate(evidence("noi", 650_000, "NOI: $650,000") | {"value": 650000})

    assert entry.value == "650000"


def test_placeholder_strings_become_explicit_nulls():
    output = REPEExtractionOutput.model_validate(
        full_output(
            market="N/A",
            submarket="  unknown ",
            sponsor_name="",
            business_plan="TBD",
            investment_strategy="Not disclosed",
            transaction_type="N/A.",
            location="Not specified",
        )
    )

    for field_name in ("market", "submarket", "sponsor_name", "business_plan", "investment_strategy"):
        assert getattr(output, field_name) is None
    assert output.transaction_type is None
    assert output.location is None


def test_invalid_output_is_retried_with_the_validation_errors_then_succeeds():
    client = fake_client(
        tool_response(_valid_output(review_status="approved")),
        tool_response(_valid_output(), tool_id="toolu_2"),
    )

    deal = extract_repe_deal(PAGES, client=client)

    assert deal.asking_price == 10_000_000
    assert deal.review_status == "pending"
    assert client.messages.create.call_count == 2
    retry_messages = client.messages.create.call_args.kwargs["messages"]
    # The retry replays the failed call before the error, as the API requires
    # (a tool_result must follow the tool_use it answers).
    assert [message["role"] for message in retry_messages] == ["user", "assistant", "user"]
    assert retry_messages[1]["content"][0].type == "tool_use"
    feedback = retry_messages[2]["content"][0]
    assert feedback["type"] == "tool_result"
    assert feedback["tool_use_id"] == "toolu_1"
    assert feedback["is_error"] is True
    assert "review_status" in feedback["content"]
    # The error message describes the problem without echoing values back.
    assert "approved" not in feedback["content"]


def _sdk_message(tool_input, tool_id, tool_name=EXTRACTION_TOOL_NAME):
    return {
        "id": f"msg_{tool_id}",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-5-20250929",
        "content": [{"type": "tool_use", "id": tool_id, "name": tool_name, "input": tool_input}],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
    }


def _sdk_client(handler):
    return anthropic.Anthropic(api_key="test", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))


def test_the_retry_turn_is_a_valid_request_through_the_real_sdk():
    # The fakes above can't tell whether the SDK can serialize the replayed
    # response content; the real SDK over a fake transport can.
    bodies = []
    replies = iter([_sdk_message(_valid_output(made_up_field=1), "toolu_1"), _sdk_message(_valid_output(), "toolu_2")])

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, json=next(replies))

    deal = extract_repe_deal(PAGES, client=_sdk_client(handler))

    assert deal.asking_price == 10_000_000
    retry = bodies[1]["messages"]
    assert retry[1]["role"] == "assistant"
    assert retry[1]["content"][0]["type"] == "tool_use" and retry[1]["content"][0]["id"] == "toolu_1"
    assert retry[2]["content"][0]["type"] == "tool_result" and retry[2]["content"][0]["tool_use_id"] == "toolu_1"


def test_output_that_stays_invalid_fails_without_saving_anything():
    client = fake_client(*[tool_response(_valid_output(made_up_field=1)) for _ in range(MAX_OUTPUT_ATTEMPTS)])

    with pytest.raises(ExtractionOutputError, match="nothing was saved"):
        extract_repe_deal(PAGES, client=client)
    assert client.messages.create.call_count == MAX_OUTPUT_ATTEMPTS


def test_a_response_without_a_tool_call_is_retried():
    client = fake_client(text_response("Here is the deal..."), tool_response(_valid_output()))

    deal = extract_repe_deal(PAGES, client=client)

    assert deal.deal_name == "Fixture Deal"
    assert client.messages.create.call_count == 2


def test_truncated_output_is_rejected_without_a_retry():
    client = fake_client(tool_response(_valid_output(), stop_reason="max_tokens"))

    with pytest.raises(ExtractionOutputError, match="cut off"):
        extract_repe_deal(PAGES, client=client)
    client.messages.create.assert_called_once()


def test_a_refusal_is_reported_without_a_retry():
    client = fake_client(text_response("", stop_reason="refusal"))

    with pytest.raises(ExtractionRefusedError):
        extract_repe_deal(PAGES, client=client)
    client.messages.create.assert_called_once()


def test_the_request_forces_exactly_one_call_of_the_extraction_tool():
    client = fake_client(tool_response(_valid_output()))

    extract_repe_deal(PAGES, client=client)

    kwargs = client.messages.create.call_args.kwargs
    assert kwargs["tool_choice"] == {
        "type": "tool",
        "name": "extract_repe_deal_profile",
        "disable_parallel_tool_use": True,
    }
    assert kwargs["max_tokens"] == repe_extractor.MAX_OUTPUT_TOKENS


def test_the_request_only_uses_arguments_the_installed_sdk_accepts():
    # A fake client accepts any argument, so check the request against the
    # real SDK's signature - otherwise a parameter the pinned SDK version
    # doesn't support (e.g. `temperature`, removed in anthropic 1.x) would
    # only fail on a live, paid call.
    client = fake_client(tool_response(_valid_output()))

    extract_repe_deal(PAGES, client=client)

    accepted = set(inspect.signature(Messages.create).parameters) - {"self"}
    assert set(client.messages.create.call_args.kwargs) <= accepted


# --- Provider errors, retries, the time budget, and configuration ------------

_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, status_code):
    return cls("provider error body", response=httpx2.Response(status_code, request=_REQUEST), body=None)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (anthropic.APITimeoutError(request=_REQUEST), ExtractionUnavailableError),
        (anthropic.APIConnectionError(request=_REQUEST), ExtractionUnavailableError),
        (_status_error(anthropic.RateLimitError, 429), ExtractionUnavailableError),
        (_status_error(anthropic.InternalServerError, 500), ExtractionUnavailableError),
        (_status_error(anthropic.APIStatusError, 529), ExtractionUnavailableError),
        (_status_error(anthropic.AuthenticationError, 401), ExtractionConfigurationError),
        (_status_error(anthropic.PermissionDeniedError, 403), ExtractionConfigurationError),
        (_status_error(anthropic.NotFoundError, 404), ExtractionConfigurationError),
        (_status_error(anthropic.BadRequestError, 400), ExtractionConfigurationError),
        (_status_error(anthropic.APIStatusError, 413), ExtractionInputError),
    ],
)
def test_provider_errors_become_controlled_extraction_errors(error, expected):
    with pytest.raises(expected) as excinfo:
        extract_repe_deal(PAGES, client=fake_client(error=error))

    assert isinstance(excinfo.value, ValueError)
    assert "provider error body" not in str(excinfo.value)


def test_a_transient_failure_is_retried_and_can_still_succeed():
    client = fake_client(anthropic.APIConnectionError(request=_REQUEST), tool_response(_valid_output()))

    assert extract_repe_deal(PAGES, client=client).asking_price == 10_000_000
    assert client.messages.create.call_count == 2


@pytest.mark.parametrize(("setting", "calls"), [("0", 1), ("3", 4)])
def test_transient_retries_follow_the_max_retries_setting(monkeypatch, setting, calls):
    monkeypatch.setenv("H9N_EXTRACTION_MAX_RETRIES", setting)
    client = fake_client(error=anthropic.APITimeoutError(request=_REQUEST))

    with pytest.raises(ExtractionUnavailableError):
        extract_repe_deal(PAGES, client=client)
    assert client.messages.create.call_count == calls


def test_a_permanent_failure_is_not_retried():
    client = fake_client(error=_status_error(anthropic.AuthenticationError, 401))

    with pytest.raises(ExtractionConfigurationError):
        extract_repe_deal(PAGES, client=client)
    client.messages.create.assert_called_once()


class _FakeClock:
    """Time that only moves when a request "takes" time or backoff sleeps."""

    def __init__(self):
        self.now = 1000.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_the_whole_extraction_stays_within_the_time_budget(monkeypatch):
    clock = _FakeClock()
    monkeypatch.setattr(repe_extractor, "_monotonic", clock.monotonic)
    monkeypatch.setattr(repe_extractor, "_sleep", clock.sleep)
    monkeypatch.setenv("H9N_EXTRACTION_TIMEOUT_SECONDS", "100")
    monkeypatch.setenv("H9N_EXTRACTION_MAX_RETRIES", "10")
    timeouts = []

    def slow_request(**kwargs):
        timeouts.append(kwargs["timeout"])
        clock.now += kwargs["timeout"]  # the request uses all the time it is given
        raise anthropic.APITimeoutError(request=_REQUEST)

    client = fake_client()
    client.messages.create.side_effect = slow_request

    with pytest.raises(ExtractionUnavailableError):
        extract_repe_deal(PAGES, client=client)
    assert clock.now - 1000.0 <= 100
    assert timeouts[0] == 100
    assert all(timeout <= 100 for timeout in timeouts)


def test_the_sdks_own_retries_are_switched_off():
    client = fake_client(tool_response(_valid_output()))

    extract_repe_deal(PAGES, client=client)

    client.with_options.assert_called_once_with(max_retries=0)


def test_a_built_client_leaves_retries_to_h9n(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    assert repe_extractor._build_client().max_retries == 0


def test_missing_credentials_are_a_configuration_error(monkeypatch, tmp_path):
    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    with pytest.raises(ExtractionConfigurationError, match="ANTHROPIC_API_KEY"):
        extract_repe_deal(PAGES)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("H9N_EXTRACTION_TIMEOUT_SECONDS", "soon"),
        ("H9N_EXTRACTION_TIMEOUT_SECONDS", "0"),
        ("H9N_EXTRACTION_TIMEOUT_SECONDS", "999999"),
        ("H9N_EXTRACTION_MAX_RETRIES", "-1"),
        ("H9N_EXTRACTION_MAX_RETRIES", "1000"),
        ("H9N_EXTRACTION_MAX_INPUT_CHARS", "0"),
    ],
)
def test_an_invalid_setting_is_a_configuration_error(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    client = fake_client()

    with pytest.raises(ExtractionConfigurationError, match=name):
        extract_repe_deal(PAGES, client=client)
    client.messages.create.assert_not_called()


# --- Input checks -------------------------------------------------------------


@pytest.mark.parametrize(
    "pages",
    [
        pytest.param([], id="no pages"),
        pytest.param([_page("   \n ")], id="only blank pages"),
        pytest.param([_page("x", page_number=0)], id="page number zero"),
        pytest.param([_page("x", page_number="1")], id="page number not int"),
        pytest.param([_page(None)], id="no text"),
        pytest.param([_page("x", file_name=7)], id="file name not text"),
        pytest.param([_page("a"), _page("b")], id="duplicate page"),
    ],
)
def test_malformed_pages_fail_before_any_model_call(pages):
    client = fake_client()

    with pytest.raises(ExtractionInputError):
        extract_repe_deal(pages, client=client)
    client.messages.create.assert_not_called()


def test_a_document_over_the_input_limit_fails_before_any_model_call(monkeypatch):
    monkeypatch.setenv("H9N_EXTRACTION_MAX_INPUT_CHARS", "50")
    client = fake_client()

    with pytest.raises(ExtractionInputError, match="more than the 50"):
        extract_repe_deal(PAGES, client=client)
    client.messages.create.assert_not_called()


def test_blank_pages_are_left_out_of_the_prompt_without_renumbering():
    pages = PAGES + [_page("  ", page_number=4)]
    client = fake_client(tool_response(_valid_output()))

    extract_repe_deal(pages, client=client)

    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "--- fixture.pdf | Page 3 ---" in prompt
    assert "Page 4" not in prompt


# --- Evidence checks: what gets stored -----------------------------------------


def test_verified_values_are_kept_with_their_evidence():
    deal = _enforce(
        deal_name="Fixture Deal",
        occupancy_rate=94,
        sponsor_name="Acme Capital Partners",
        noi=650_000,
        evidence=[
            evidence("deal_name", "Fixture Deal", "deal name: FIXTURE DEAL"),
            evidence("occupancy_rate", 94, "Occupancy: 94%"),
            evidence("sponsor_name", "Acme Capital Partners", "Sponsor: Acme Capital Partners", page_number=3),
            evidence("noi", 650_000, "NOI of $650K for the trailing twelve months.", page_number=3),
        ],
    )

    assert (deal.deal_name, deal.occupancy_rate, deal.sponsor_name, deal.noi) == (
        "Fixture Deal",
        94,
        "Acme Capital Partners",
        650_000,
    )
    assert len(deal.evidence) == 4
    assert {entry.verification for entry in deal.evidence} == {"value_matched"}
    assert deal.withheld_values == []
    assert deal.missing_information == []


@pytest.mark.parametrize(
    ("field_name", "value", "entry", "reason"),
    [
        # An important field and a non-important one for each reason: every
        # extracted value is held to the same standard.
        ("asking_price", 10_000_000, None, "no_evidence"),
        ("sponsor_name", "Acme Capital Partners", None, "no_evidence"),
        (
            "asking_price",
            10_000_000,
            evidence("asking_price", 1, "Asking Price: $10,000,000", page_number=9),
            "page_not_in_document",
        ),
        ("occupancy_rate", 94, evidence("occupancy_rate", 94, "Occupancy: 94%", page_number=2), "page_not_in_document"),
        ("asking_price", 10_000_000, evidence("asking_price", 1, "10,000"), "snippet_too_short"),
        (
            "asking_price",
            10_000_000,
            evidence("asking_price", 1, "Asking Price: $10,000,000", page_number=3),
            "snippet_not_on_page",
        ),
        (
            "sponsor_name",
            "Acme Capital Partners",
            evidence("sponsor_name", "x", "Sponsored by Acme Capital", page_number=3),
            "snippet_not_on_page",
        ),
        ("asking_price", 12_000_000, evidence("asking_price", 1, "Asking Price: $10,000,000"), "value_not_in_snippet"),
        ("occupancy_rate", 96, evidence("occupancy_rate", 96, "Occupancy: 94%"), "value_not_in_snippet"),
        ("noi", 650, evidence("noi", 650, "NOI of $650K", page_number=3), "value_not_in_snippet"),
        ("deal_name", "Other Deal", evidence("deal_name", "x", "Deal Name: Fixture Deal"), "value_not_in_snippet"),
    ],
)
def test_unverified_values_are_withheld_not_stored(field_name, value, entry, reason):
    deal = _enforce(**{field_name: value}, evidence=[entry] if entry else [])

    assert getattr(deal, field_name) is None
    assert deal.evidence == []
    [withheld] = deal.withheld_values
    assert (withheld.field_name, withheld.proposed_value, withheld.reason) == (field_name, value, reason)
    assert (withheld.evidence is None) == (entry is None)
    # Withheld values live in withheld_values only; missing_information is
    # what the document doesn't state.
    assert deal.missing_information == []


@pytest.mark.parametrize(("flag", "reason"), [("uncertain", "model_uncertain"), ("conflicting", "model_conflicting")])
def test_values_the_model_flags_are_withheld_even_with_good_evidence(flag, reason):
    deal = _enforce(
        asking_price=10_000_000,
        evidence=[evidence("asking_price", 10_000_000, "Asking Price: $10,000,000")],
        field_flags=[{"field_name": "asking_price", "flag": flag, "note": "OM page 5 says $9.5M"}],
    )

    assert deal.asking_price is None
    [withheld] = deal.withheld_values
    assert withheld.reason == reason
    assert withheld.detail == "OM page 5 says $9.5M"
    assert withheld.evidence.snippet == "Asking Price: $10,000,000"
    assert withheld.evidence.verification is None
    notes = deal.uncertain_information if flag == "uncertain" else deal.conflicting_information
    assert notes == ["asking_price: OM page 5 says $9.5M"]
    assert deal.missing_information == []


@pytest.mark.parametrize("note", ["asking_price: not stated in the document", "Asking price not stated"])
def test_a_value_the_model_also_lists_as_missing_is_withheld(note):
    deal = _enforce(
        asking_price=10_000_000,
        evidence=[evidence("asking_price", 10_000_000, "Asking Price: $10,000,000")],
        missing_information=[note],
    )

    assert deal.asking_price is None
    assert deal.withheld_values[0].reason == "model_listed_as_missing"
    assert deal.missing_information == [note]


def test_a_missing_note_only_withholds_the_field_it_names():
    deal = _enforce(
        deal_name="Fixture Deal",
        evidence=[evidence("deal_name", "Fixture Deal", "Deal Name: Fixture Deal")],
        missing_information=["cap_rate: not stated"],
    )

    assert deal.deal_name == "Fixture Deal"


def test_a_second_citation_can_verify_a_value_the_first_one_failed_to():
    deal = _enforce(
        asking_price=10_000_000,
        evidence=[
            evidence("asking_price", 10_000_000, "Price: ten million"),
            evidence("asking_price", 10_000_000, "Asking Price: $10,000,000"),
        ],
    )

    assert deal.asking_price == 10_000_000
    assert deal.withheld_values == []


def test_evidence_for_a_null_field_is_dropped_and_file_names_are_normalized():
    deal = _enforce(
        deal_name="Fixture Deal",
        evidence=[
            evidence("deal_name", "Fixture Deal", "Deal Name: Fixture Deal", source_document="FIXTURE (1).pdf"),
            evidence("noi", 650_000, "NOI of $650K", page_number=3),
        ],
    )

    assert [e.field_name for e in deal.evidence] == ["deal_name"]
    assert deal.evidence[0].source_document == "fixture.pdf"
    assert deal.noi is None
    assert deal.withheld_values == []


def test_kept_evidence_shows_the_stored_value_not_the_models_text():
    deal = _enforce(
        [_page("Asking Price: $10,000,000")],
        asking_price=10_000_000,
        evidence=[evidence("asking_price", "9,500,000", "Asking Price: $10,000,000")],
    )

    assert deal.asking_price == 10_000_000
    assert deal.evidence[0].value == "10000000"


def test_reviewer_fields_always_start_at_their_defaults():
    deal = _enforce()

    assert deal.review_status == "pending"
    assert deal.corrected_fields == []
    assert deal.review_feedback is None


# --- Evidence checks: numbers ----------------------------------------------------


@pytest.mark.parametrize(
    ("field_name", "value", "snippet", "page_text"),
    [
        pytest.param("year_built", 2015, "Year Built: 2000", "Year Built: 2000", id="year off by 15"),
        pytest.param(
            "units", 101, "The property has 100 units.", "The property has 100 units.", id="unit count off by 1"
        ),
        pytest.param(
            "asking_price", 10_050_000, "Asking Price: $10,000,000", "Asking Price: $10,000,000", id="price off by 0.5%"
        ),
        pytest.param(
            "noi", 150_000, "Trailing NOI: $150,000", "Trailing NOI: -$150,000 (deficit)", id="minus sign dropped"
        ),
        pytest.param(
            "noi",
            150_000,
            "Net Operating Income: ($150,000)",
            "Net Operating Income: ($150,000)",
            id="parenthesized loss read as profit",
        ),
        pytest.param(
            "asking_price",
            128,
            "128 units offered at $18,500,000",
            "128 units offered at $18,500,000",
            id="unit count read as price",
        ),
        pytest.param(
            "occupancy_rate",
            95,
            "95 units and 92% occupied",
            "95 units and 92% occupied",
            id="unit count read as occupancy",
        ),
        pytest.param("cap_rate", 6.5, "Price: $6.5M today", "Price: $6.5M today", id="price read as cap rate"),
        pytest.param(
            "units", 2400, "Buildings: 2400 units total", "Buildings: 2\n400 units total", id="two numbers merged"
        ),
        pytest.param(
            "units", 50, "Total units 50 in phase one", "Total units 150 in phase one", id="part of a bigger number"
        ),
        pytest.param(
            "asking_price",
            12_000_000,
            "Asking Price: ... $12,000,000",
            "Asking Price: $10,000,000\nSenior loan: $12,000,000",
            id="ellipsis skips another number",
        ),
    ],
)
def test_a_wrong_number_is_not_verified(field_name, value, snippet, page_text):
    deal = _one(field_name, value, snippet, page_text)

    assert getattr(deal, field_name) is None
    assert deal.withheld_values[0].reason in ("value_not_in_snippet", "snippet_not_on_page")


@pytest.mark.parametrize(
    ("field_name", "value", "snippet", "page_text"),
    [
        pytest.param(
            "asking_price",
            10_000_000,
            "Asking Price: $10,000,000",
            "ASKING  PRICE:\n$10,000,000",
            id="exact with spacing noise",
        ),
        pytest.param("asking_price", 10_000_000, "offered at $10.0M today", "offered at $10.0M today", id="$10.0M"),
        pytest.param("noi", 950_000, "NOI of $950K this year", "NOI of $950K this year", id="950K"),
        pytest.param(
            "asking_price",
            18_500_000,
            "priced at 18.5 million dollars",
            "priced at 18.5 million dollars",
            id="18.5 million",
        ),
        pytest.param("asking_price", 1_200_000_000, "a $1.2B portfolio sale", "a $1.2B portfolio sale", id="1.2B"),
        pytest.param("cap_rate", 6.5, "Cap Rate: 6.5%", "Cap Rate: 6.5%", id="percent"),
        pytest.param(
            "occupancy_rate", 94, "Physical Occupancy: 0.94", "Physical Occupancy: 0.94", id="fraction as percent"
        ),
        pytest.param("units", 128, "128 units on site", "128 units on site", id="units"),
        pytest.param(
            "units", 128, "Units: 128", "Units: 128\nYear Built: 1998", id="label on the next line is not a unit"
        ),
        pytest.param("year_built", 1998, "Built in 1998 and renovated", "Built in 1998 and renovated", id="year"),
        pytest.param("square_feet", 85_000, "Rentable Area: 85,000 SF", "Rentable Area: 85,000 SF", id="area"),
        pytest.param("loan_term_years", 10, "a 10-year fixed loan", "a 10-year fixed loan", id="term"),
        pytest.param(
            "noi",
            -150_000,
            "Net Operating Income: ($150,000)",
            "Net Operating Income: ($150,000)",
            id="parenthesized loss",
        ),
        pytest.param("noi", -150_000, "Trailing NOI: -$150,000", "Trailing NOI: -$150,000", id="negative"),
        pytest.param(
            "units", 400, "Units ... 400", "Pine Ridge\nUnits\n(all two-bedroom)\n400", id="table label and value"
        ),
    ],
)
def test_a_correct_number_is_verified(field_name, value, snippet, page_text):
    deal = _one(field_name, value, snippet, page_text)

    assert getattr(deal, field_name) == value, deal.withheld_values


def test_a_table_value_with_another_number_in_between_is_withheld_not_guessed():
    # "Units ... 400" here skips the "2" of the Buildings column; the checker
    # can't tell columns apart, so it refuses rather than risk the wrong one.
    deal = _one("units", 400, "Units ... 400", "Buildings\nUnits\nYear Built\n2\n400\n1987")

    assert deal.units is None
    assert deal.withheld_values[0].reason == "snippet_not_on_page"


@pytest.mark.parametrize(
    ("text", "numbers"),
    [
        ("Asking Price: $10,000,000", [10_000_000]),
        ("offered at $10.0M", [10_000_000]),
        ("$10 M asking", [10_000_000]),
        ("NOI of $950K", [950_000]),
        ("NOI: ($150,000)", [-150_000]),
        ("NOI: -$150,000", [-150_000]),
        ("built 2010-2015", [2010, 2015]),
        ("5 m from downtown", [5]),
        ("Cap Rate: 6.5%", [6.5]),
    ],
)
def test_numbers_are_read_with_their_sign_and_scale(text, numbers):
    assert numbers_in_text(text) == numbers


# --- Evidence checks: text and quotes -----------------------------------------


def test_an_invented_text_value_needs_more_than_a_scrap_of_a_quote():
    deal = _one("deal_name", "Completely Invented Name", "e", "Deal Name: Fixture Deal")

    assert deal.deal_name is None
    assert deal.withheld_values[0].reason == "snippet_too_short"


@pytest.mark.parametrize(
    ("field_name", "value", "page_text"),
    [
        ("property_type", "Office", "Property Type: Multifamily"),
        ("property_type", "garden-styleapartment", "a 240-unit garden-style apartment community"),
        ("property_type", "Multifamily", "a 240-unit garden-style apartment community"),
    ],
)
def test_a_text_value_must_be_in_its_quote(field_name, value, page_text):
    # The last case is a correct but reworded value: withheld until M1.4
    # defines normalized property types (a safe failure).
    deal = _one(field_name, value, page_text, page_text)

    assert getattr(deal, field_name) is None
    assert deal.withheld_values[0].reason == "value_not_in_snippet"


@pytest.mark.parametrize(
    ("field_name", "value", "page_text"),
    [
        ("property_type", "Self-Storage", "Cedar Ridge is a self-storage facility."),
        ("deal_name", "Meadowbrook Apartments", "MEADOWBROOK APARTMENTS\nOffering Memorandum"),
    ],
)
def test_a_trimmed_or_recapitalized_text_value_is_verified(field_name, value, page_text):
    # What the prompt allows: drop surrounding words, fix capitalization.
    deal = _one(field_name, value, page_text, page_text)

    assert getattr(deal, field_name) == value, deal.withheld_values


def test_a_text_value_matches_whole_words_case_insensitively():
    deal = _one(
        "property_type", "Self-Storage", "is a self-storage facility", "Cedar Ridge is a self-storage facility."
    )

    assert deal.property_type == "Self-Storage"


def test_narrative_fields_are_stored_with_quote_only_evidence():
    page = "The sponsor plans to renovate 40 units and push rents to market over three years."
    deal = _one("business_plan", "Renovate units and raise rents to market.", page, page)

    assert deal.business_plan == "Renovate units and raise rents to market."
    assert deal.evidence[0].verification == "quote_only"


def test_narrative_fields_still_need_a_real_quote():
    deal = _one(
        "business_plan", "Renovate units.", "The sponsor plans a full teardown.", "The sponsor plans to renovate."
    )

    assert deal.business_plan is None
    assert deal.withheld_values[0].reason == "snippet_not_on_page"


@pytest.mark.parametrize(
    ("snippet", "page_text"),
    [
        ("Asking Price: $10,000,000", "ASKING  PRICE:\n$10,000,000"),
        ("the “seller’s” price — firm", 'The "seller\'s" price - firm'),
        ("occupancy is stable", "occu-\npancy is stable"),
        ("occupancy is stable", "occu­pancy is stable"),
        ("NOI grew ... to $650K", "NOI grew steadily over three years to $650K"),
        ("financial statements", "ﬁnancial statements"),
        ("Asking Price:$10,000,000", "Asking Price: $10,000,000"),
    ],
)
def test_snippet_matching_tolerates_pdf_formatting_noise(snippet, page_text):
    assert snippet_is_on_page(snippet, page_text)


@pytest.mark.parametrize(
    ("snippet", "page_text"),
    [
        ("Asking Price: $12,000,000", "Asking Price: $10,000,000"),
        ("to $650K ... NOI grew", "NOI grew steadily to $650K"),
        ("...", "anything"),
        ("Buildings: 2400 units", "Buildings: 2\n400 units"),
        ("Deal Name ... Fixture", "Deal Name: " + "x " * 200 + "Fixture"),
        ("AskingPrice", "Asking Price"),
    ],
)
def test_snippet_matching_still_rejects_text_that_is_not_there(snippet, page_text):
    assert not snippet_is_on_page(snippet, page_text)


def test_the_minimum_snippet_length_ignores_spaces_and_ellipses():
    assert MIN_SNIPPET_CHARS == 8
    assert not snippet_supports_value("units", 128, "Units 12", "Units 128")  # 7 characters
    assert snippet_supports_value("units", 128, "Units 128", "Units 128")  # 8 characters


def test_a_page_number_shared_by_two_documents_is_resolved_by_file_name():
    pages = [
        _page("Asking Price: $10,000,000", file_name="om.pdf"),
        _page("Asking Price: $9,000,000", file_name="teaser.pdf"),
    ]

    resolved = _enforce(
        pages,
        asking_price=10_000_000,
        evidence=[evidence("asking_price", 10_000_000, "Asking Price: $10,000,000", source_document="OM.pdf")],
    )
    ambiguous = _enforce(
        pages,
        asking_price=10_000_000,
        evidence=[evidence("asking_price", 10_000_000, "Asking Price: $10,000,000", source_document="cim.pdf")],
    )

    assert resolved.asking_price == 10_000_000
    assert resolved.evidence[0].source_document == "om.pdf"
    assert ambiguous.asking_price is None
    assert "more than one document" in ambiguous.withheld_values[0].detail


def _oracle_output(case):
    """What a perfect extraction of an evaluation case looks like: every
    expected value, cited with the exact line of the page it's on."""
    values = dict(case["expected"])
    entries = []
    for field_name, value in values.items():
        for page in case["pages"]:
            lines = [line for line in page["text"].split("\n") if line.strip()]
            match = next(
                (line for line in lines if snippet_supports_value(field_name, value, line, page["text"])), None
            )
            if match:
                entries.append(
                    evidence(
                        field_name, value, match, page_number=page["page_number"], source_document=page["file_name"]
                    )
                )
                break
        else:
            raise AssertionError(f"{case['case_id']}: no line states {field_name}={value!r}")
    return full_output(**values, evidence=entries)


# Ground-truth cases only: the holdout cases stay unseen by anything tuned
# against them, the evidence checker included.
@pytest.mark.parametrize("case", GROUND_TRUTH_CASES, ids=lambda case: case["case_id"])
def test_a_correct_extraction_of_each_ground_truth_deal_is_fully_kept(case):
    # A free check against false withholding: when the model cites the right
    # line for every value, the evidence checks must keep every one of them.
    deal = enforce_integrity(REPEExtractionOutput.model_validate(_oracle_output(case)), case["pages"])

    assert deal.withheld_values == []
    for field_name, value in case["expected"].items():
        assert getattr(deal, field_name) == value


# --- Reviewer feedback ----------------------------------------------------------

FEEDBACK_PAGES = [_page("Asking Price: $950,000.\nNOI: $65,000", page_number=4)]


def _feedback(corrections, updated_evidence=(), explanation="Fixed."):
    return tool_response(
        {"corrections": corrections, "updated_evidence": list(updated_evidence), "explanation": explanation},
    )


def _deal():
    return REPEDealProfile(
        deal_name="Fixture Deal",
        asking_price=1_000_000,
        evidence=[
            FieldEvidence(field_name="asking_price", value="1000000", page_number=1, snippet="old"),
            FieldEvidence(field_name="deal_name", value="Fixture Deal", page_number=1, snippet="Deal: Fixture Deal"),
        ],
        withheld_values=[
            WithheldValue(field_name="asking_price", proposed_value=990_000, reason="model_uncertain", detail="x"),
            WithheldValue(field_name="noi", proposed_value=60_000, reason="no_evidence", detail="x"),
        ],
    )


def test_a_cited_correction_is_returned_with_verified_evidence():
    client = fake_client(
        _feedback(
            {"asking_price": 950_000}, [evidence("asking_price", 950_000, "Asking Price: $950,000.", page_number=4)]
        )
    )

    result = apply_reviewer_feedback(FEEDBACK_PAGES, _deal(), "price is wrong", client=client)

    assert result["corrections"] == {"asking_price": 950_000}
    assert result["updated_evidence"][0].verification == "value_matched"
    assert result["withheld"] == []


@pytest.mark.parametrize(
    ("corrections", "updated_evidence", "reason"),
    [
        ({"asking_price": 99_999_999}, [], "no_evidence"),
        (
            {"asking_price": 900_000},
            [evidence("asking_price", 900_000, "Asking Price: $950,000.", page_number=4)],
            "value_not_in_snippet",
        ),
    ],
)
def test_an_unverified_correction_is_withheld_not_applied(corrections, updated_evidence, reason):
    client = fake_client(_feedback(corrections, updated_evidence))

    result = apply_reviewer_feedback(FEEDBACK_PAGES, _deal(), "price is wrong", client=client)

    assert result["corrections"] == {}
    assert result["updated_evidence"] == []
    [withheld] = result["withheld"]
    assert (withheld.field_name, withheld.reason) == ("asking_price", reason)


def test_a_correction_can_clear_a_field_without_a_citation():
    client = fake_client(_feedback({"asking_price": None}))

    result = apply_reviewer_feedback(FEEDBACK_PAGES, _deal(), "there is no asking price", client=client)

    assert result["corrections"] == {"asking_price": None}


@pytest.mark.parametrize(
    "corrections",
    [
        pytest.param({"withheld_values": []}, id="erase the review queue"),
        pytest.param({"evidence": []}, id="erase the citations"),
        pytest.param({"review_status": "approved"}, id="approve itself"),
        pytest.param({"asking_price": "about ten million"}, id="malformed value"),
    ],
)
def test_a_correction_can_only_change_deal_values(corrections):
    client = fake_client(*[_feedback(corrections) for _ in range(MAX_OUTPUT_ATTEMPTS)])

    with pytest.raises(ExtractionOutputError):
        apply_reviewer_feedback(FEEDBACK_PAGES, _deal(), "fix it", client=client)
    assert client.messages.create.call_count == MAX_OUTPUT_ATTEMPTS


def test_a_provider_outage_during_feedback_is_a_controlled_error():
    client = fake_client(error=anthropic.APIConnectionError(request=_REQUEST))

    with pytest.raises(ExtractionUnavailableError):
        apply_reviewer_feedback(FEEDBACK_PAGES, _deal(), "fix it", client=client)


def test_the_feedback_tool_schema_only_offers_deal_value_fields():
    schema = repe_extractor._build_feedback_tool_schema()["input_schema"]
    corrections = schema["properties"]["corrections"]

    assert set(corrections["properties"]) == set(VALUE_FIELDS)
    assert corrections["additionalProperties"] is False
    assert ReviewerFeedbackOutput.model_json_schema()["additionalProperties"] is False


def test_feedback_updates_replace_citations_and_resolve_withheld_entries():
    deal = _deal()
    new_citation = FieldEvidence(
        field_name="asking_price", value="950000", page_number=4, snippet="Asking Price: $950,000."
    )
    new_withheld = WithheldValue(field_name="cap_rate", proposed_value=6.5, reason="no_evidence", detail="x")

    updates = feedback_updates(
        deal,
        {"corrections": {"asking_price": 950_000}, "updated_evidence": [new_citation], "withheld": [new_withheld]},
    )

    assert updates["asking_price"] == 950_000
    assert [e.snippet for e in updates["evidence"]] == ["Deal: Fixture Deal", "Asking Price: $950,000."]
    # The old asking_price proposal is superseded; the NOI one still waits.
    assert [w.field_name for w in updates["withheld_values"]] == ["noi", "cap_rate"]
    assert updates["review_status"] == "pending"


def test_feedback_updates_drop_the_citation_of_a_cleared_field():
    updates = feedback_updates(_deal(), {"corrections": {"asking_price": None}, "updated_evidence": [], "withheld": []})

    assert [e.field_name for e in updates["evidence"]] == ["deal_name"]


def test_feedback_updates_are_empty_when_nothing_changes():
    assert feedback_updates(_deal(), {"corrections": {}, "updated_evidence": [], "withheld": []}) == {}


def test_file_names_that_differ_only_in_case_do_not_pick_a_page():
    pages = [
        _page("Asking Price: $10,000,000", file_name="om.pdf"),
        _page("Asking Price: $10,000,000", file_name="OM.pdf"),
    ]

    deal = _enforce(
        pages,
        asking_price=10_000_000,
        evidence=[evidence("asking_price", 10_000_000, "Asking Price: $10,000,000", source_document="om.pdf")],
    )

    assert deal.asking_price is None
    assert "more than one document" in deal.withheld_values[0].detail
