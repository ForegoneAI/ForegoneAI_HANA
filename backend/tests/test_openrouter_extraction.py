"""Exercise OpenRouter routing through the real SDK with an offline transport.

These tests check URL/auth, forced tools, schema-repair turns, error handling,
and usage for non-Claude model IDs without sending documents or real keys.
"""

import json

import anthropic
import httpx2
import pytest

from backend.app.h9n.extraction import repe_extractor
from backend.app.h9n.extraction.repe_extractor import (
    EXTRACTION_TOOL_NAME,
    ExtractionConfigurationError,
    ExtractionOutputError,
    ExtractionUnavailableError,
    OPENROUTER_BASE_URL,
    extract_repe_deal,
)
from backend.app.h9n.extraction.telemetry import capture_model_usage
from backend.evaluation.benchmark import main
from backend.tests.extraction_fakes import evidence, full_output

PAGES = [{"file_name": "example.pdf", "page_number": 3, "text": "Asking price: $100.00"}]


def response(output, *, stop_reason="tool_use"):
    return {
        "id": "msg_test", "type": "message", "role": "assistant", "model": "google/test-model",
        "content": [{"type": "tool_use", "id": "tool_test", "name": EXTRACTION_TOOL_NAME, "input": output}],
        "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5, "cache_read_input_tokens": 2},
    }


def valid_output():
    return full_output(asking_price=100, evidence=[
        evidence("asking_price", 100, "Asking price: $100.00", page_number=3, source_document="example.pdf")])


def client(handler):
    return anthropic.Anthropic(base_url=OPENROUTER_BASE_URL, api_key="", auth_token="test-openrouter-key",
                               default_headers={"X-Api-Key": anthropic.omit},
                               http_client=httpx2.Client(transport=httpx2.MockTransport(handler)), max_retries=0)


def test_non_claude_model_preserves_validation_and_records_usage():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx2.Response(200, json=response(valid_output()))
    with capture_model_usage() as calls:
        deal = extract_repe_deal(PAGES, client=client(handler), model="google/test-model")
    request = requests[0]
    assert str(request.url) == "https://openrouter.ai/api/v1/messages"
    assert request.headers["Authorization"] == "Bearer test-openrouter-key"
    assert "x-api-key" not in request.headers
    body = json.loads(request.content)
    assert body["model"] == "google/test-model"
    assert body["provider"] == {"require_parameters": True}
    assert body["tool_choice"] == {"type": "tool", "name": EXTRACTION_TOOL_NAME, "disable_parallel_tool_use": True}
    assert body["tools"][0]["input_schema"]["additionalProperties"] is False
    schema = body["tools"][0]["input_schema"]
    assert schema["properties"]["evidence"]["items"]["type"] == "object"
    assert schema["properties"]["field_flags"]["items"]["type"] == "object"
    assert '"$ref"' not in json.dumps(schema)
    assert deal.asking_price == 100
    assert deal.evidence[0].page_number == 3
    assert calls[0]["model"] == "google/test-model"
    assert calls[0]["input_tokens"] == 12


def test_router_schema_repair_turn_uses_same_tool_and_counts_both_calls():
    bodies = []
    replies = iter([response(valid_output() | {"unrecognized": True}), response(valid_output())])
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, json=next(replies))
    with capture_model_usage() as calls:
        deal = extract_repe_deal(PAGES, client=client(handler), model="google/test-model")
    assert deal.asking_price == 100
    assert len(calls) == 2
    assert bodies[1]["messages"][-1]["content"][0]["type"] == "tool_result"
    assert bodies[1]["messages"][-1]["content"][0]["is_error"] is True


def test_router_malformed_output_never_becomes_a_profile():
    def handler(request):
        return httpx2.Response(200, json=response({"asking_price": "invented"}))
    with pytest.raises(ExtractionOutputError):
        extract_repe_deal(PAGES, client=client(handler), model="google/test-model")


@pytest.mark.parametrize("status,error", [(401, ExtractionConfigurationError), (402, ExtractionConfigurationError),
                                         (404, ExtractionConfigurationError), (429, ExtractionUnavailableError),
                                         (503, ExtractionUnavailableError)])
def test_router_http_errors_are_controlled(monkeypatch, status, error):
    monkeypatch.setenv("H9N_EXTRACTION_MAX_RETRIES", "0")
    def handler(request):
        return httpx2.Response(status, json={"error": {"type": "api_error", "message": "provider internals"}})
    with pytest.raises(error) as result:
        extract_repe_deal(PAGES, client=client(handler), model="google/test-model")
    assert "provider internals" not in str(result.value)


def test_router_client_uses_only_router_credentials(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unrelated-anthropic-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    router = repe_extractor._build_client("openrouter")
    assert str(router.base_url).rstrip("/") == OPENROUTER_BASE_URL
    assert router.api_key == ""
    assert router.auth_token == "test-openrouter-key"
    assert router.max_retries == 0
    router.close()


def test_router_can_be_selected_in_environment(monkeypatch):
    monkeypatch.setenv("H9N_EXTRACTION_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-openrouter-key")
    router = repe_extractor._build_client()
    assert str(router.base_url).rstrip("/") == OPENROUTER_BASE_URL
    router.close()


def test_missing_router_key_does_not_fall_back_to_anthropic(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "unrelated-anthropic-key")
    with pytest.raises(ExtractionConfigurationError, match="OPENROUTER_API_KEY"):
        repe_extractor._build_client("openrouter")


def test_unknown_provider_is_controlled():
    with pytest.raises(ExtractionConfigurationError, match="H9N_EXTRACTION_PROVIDER"):
        repe_extractor._build_client("unknown")


def test_replay_rejects_live_model_options():
    with pytest.raises(SystemExit) as result:
        main(["--predictions", "unused.json", "--provider", "openrouter", "--model", "google/test-model"])
    assert result.value.code == 2


def test_inline_schema_preserves_nested_requirements_and_validation():
    from backend.app.h9n.extraction.extraction_output import REPEExtractionOutput
    from pydantic import ValidationError

    original = REPEExtractionOutput.model_json_schema()
    before = json.dumps(original, sort_keys=True)
    expanded = repe_extractor._inline_schema_refs(original)
    assert json.dumps(original, sort_keys=True) == before
    for field, definition in (("evidence", "ExtractedEvidence"), ("field_flags", "FieldFlag")):
        nested = expanded["properties"][field]["items"]
        assert nested == original["$defs"][definition]
        assert nested["additionalProperties"] is False
        assert set(nested["required"]) == set(nested["properties"])
    assert expanded["properties"]["asking_price"] == original["properties"]["asking_price"]
    malformed = valid_output()
    malformed["evidence"] = [json.dumps(item) for item in malformed["evidence"]]
    with pytest.raises(ValidationError):
        REPEExtractionOutput.model_validate(malformed)


def test_inline_schema_covers_feedback_and_array_items():
    schema = repe_extractor._build_feedback_tool_schema()["input_schema"]
    assert '"$ref"' not in json.dumps(schema)
    assert schema["properties"]["corrections"]["type"] == "object"
    assert schema["properties"]["corrections"]["additionalProperties"] is False
    assert schema["properties"]["updated_evidence"]["items"]["type"] == "object"


@pytest.mark.parametrize("schema", [
    {"$ref": "#/$defs/Absent"},
    {"$ref": "https://example.invalid/schema"},
    {"$ref": "#/$defs/Loop", "$defs": {"Loop": {"$ref": "#/$defs/Loop"}}},
])
def test_unresolved_or_recursive_schema_fails_before_model_call(schema):
    with pytest.raises(ExtractionConfigurationError):
        repe_extractor._inline_schema_refs(schema)


def test_json_encoded_evidence_is_retried_with_object_hint():
    bodies = []
    malformed = valid_output()
    malformed["evidence"] = [json.dumps(item) for item in malformed["evidence"]]
    replies = iter([response(malformed), response(valid_output())])
    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, json=next(replies))
    deal = extract_repe_deal(PAGES, client=client(handler), model="google/test-model")
    assert deal.asking_price == 100
    repair = bodies[1]["messages"][-1]["content"][0]["content"]
    assert "not a string containing JSON" in repair
