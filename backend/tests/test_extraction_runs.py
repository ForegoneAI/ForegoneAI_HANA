"""Tests for Milestone 1.3 - persisting extraction runs.

Supabase is replaced with fakes, so these run in CI without credentials. They
check that every extraction attempt made on behalf of an organization is
recorded with its model, prompt, input fingerprints, and outcome, and that
nothing untraceable is ever returned to the caller.
"""

import io
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.h9n.extraction.repe_extractor import (
    DEFAULT_MODEL,
    extraction_input_sha256,
    extraction_prompt_sha256,
)
from backend.app.h9n.extraction.run_repository import (
    ExtractionRunRecord,
    SupabaseExtractionRunRepository,
)
from backend.app.h9n.rag import api
from backend.app.h9n.rag.config import RagSettings
from backend.app.h9n.review.store import DealStore
from backend.app.h9n.schemas.base_deal import FieldEvidence
from backend.app.h9n.schemas.repe_deal import REPEDealProfile


def _settings() -> RagSettings:
    return RagSettings(
        openrouter_api_key="test-openrouter-key",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-service-key",
        internal_api_key="test-internal-key",
        embedding_model="test-model",
        embedding_dimensions=3,
        openrouter_referer=None,
        openrouter_title=None,
        storage_bucket="test-bucket",
        chunk_size=60,
        chunk_overlap=15,
        max_upload_bytes=1_000_000,
        default_match_count=4,
    )


def _make_pdf_bytes(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _profile() -> REPEDealProfile:
    return REPEDealProfile(
        deal_name="Fixture Deal",
        asking_price=1_000_000,
        evidence=[
            FieldEvidence(
                field_name="asking_price",
                value="1000000",
                source_document="fixture.pdf",
                page_number=1,
                snippet="Asking Price: $1,000,000.",
            )
        ],
    )


def _record(**overrides) -> ExtractionRunRecord:
    now = datetime.now(timezone.utc)
    values = {
        "organization_id": uuid4(),
        "deal_id": uuid4(),
        "status": "succeeded",
        "model": "test-model",
        "prompt_sha256": "a" * 64,
        "source_filename": "fixture.pdf",
        "source_sha256": "b" * 64,
        "input_sha256": "c" * 64,
        "page_count": 1,
        "profile": _profile(),
        "started_at": now,
        "completed_at": now,
        "latency_ms": 5,
    }
    values.update(overrides)
    return ExtractionRunRecord(**values)


class FakeRunRepository:
    def __init__(self, *, fail: bool = False):
        self.runs: list[ExtractionRunRecord] = []
        self.run_id = uuid4()
        self._fail = fail

    def record(self, run: ExtractionRunRecord) -> UUID:
        if self._fail:
            raise RuntimeError("database unavailable")
        self.runs.append(run)
        return self.run_id


@pytest.fixture
def repository(tmp_path, monkeypatch) -> FakeRunRepository:
    fake = FakeRunRepository()
    monkeypatch.setattr(main, "_review_store", DealStore(tmp_path / "reviews"))
    monkeypatch.setattr(main, "get_extraction_run_repository", lambda: fake)
    monkeypatch.setattr(api, "get_rag_settings", _settings)
    return fake


def _post_extract(organization_id=None, api_key="test-internal-key"):
    headers = {"X-H9N-API-Key": api_key} if api_key else {}
    data = {"organization_id": str(organization_id)} if organization_id else {}
    return TestClient(main.app).post(
        "/api/h9n/repe/extract",
        headers=headers,
        data=data,
        files={
            "file": (
                "fixture.pdf",
                io.BytesIO(_make_pdf_bytes("Asking Price: $1,000,000.")),
                "application/pdf",
            )
        },
    )


def test_a_succeeded_run_needs_a_profile():
    with pytest.raises(ValueError):
        _record(profile=None)


def test_a_failed_run_needs_an_error_and_no_profile():
    with pytest.raises(ValueError):
        _record(status="failed", error_type="ValueError")
    with pytest.raises(ValueError):
        _record(status="failed", profile=None)

    failed = _record(status="failed", profile=None, error_type="ValueError", error_message="bad")
    assert failed.profile is None


def test_repository_records_the_run_through_the_atomic_rpc():
    run_id = uuid4()
    calls = []

    class FakeRpc:
        def execute(self):
            return type("Response", (), {"data": str(run_id)})()

    class FakeClient:
        def rpc(self, name, params):
            calls.append((name, params))
            return FakeRpc()

    record = _record()
    repository = SupabaseExtractionRunRepository(_settings(), client=FakeClient())

    assert repository.record(record) == run_id
    name, params = calls[0]
    assert name == "record_extraction_run"
    assert params["run"]["organization_id"] == str(record.organization_id)
    assert params["run"]["profile"]["evidence"][0]["page_number"] == 1


def test_prompt_fingerprint_is_stable_and_input_fingerprint_tracks_the_text():
    pages = [{"file_name": "fixture.pdf", "page_number": 1, "text": "Asking Price: $1,000,000."}]
    changed = [{"file_name": "fixture.pdf", "page_number": 1, "text": "Asking Price: $2,000,000."}]

    assert extraction_prompt_sha256() == extraction_prompt_sha256()
    assert len(extraction_prompt_sha256()) == 64
    assert extraction_input_sha256(pages) == extraction_input_sha256(list(pages))
    assert extraction_input_sha256(pages) != extraction_input_sha256(changed)


def test_extract_records_a_succeeded_run_for_an_organization(repository, monkeypatch):
    monkeypatch.setattr(main, "extract_repe_deal", lambda pages: _profile())
    organization_id = uuid4()

    response = _post_extract(organization_id)

    assert response.status_code == 200
    body = response.json()
    assert body["extraction_run_id"] == str(repository.run_id)

    run = repository.runs[0]
    assert run.status == "succeeded"
    assert run.organization_id == organization_id
    assert run.deal_id == UUID(body["deal_id"])
    assert run.model == DEFAULT_MODEL
    assert run.prompt_sha256 == extraction_prompt_sha256()
    assert run.source_filename == "fixture.pdf"
    assert run.page_count == 1
    assert run.profile.evidence[0].field_name == "asking_price"


def test_extract_records_a_failed_run_and_still_reports_the_error(repository, monkeypatch):
    def failing_extract(pages):
        raise ValueError("Claude did not return a structured extraction.")

    monkeypatch.setattr(main, "extract_repe_deal", failing_extract)

    response = _post_extract(uuid4())

    assert response.status_code == 502
    run = repository.runs[0]
    assert run.status == "failed"
    assert run.profile is None
    assert run.error_type == "ValueError"


def test_extract_without_an_organization_does_not_record_a_run(repository, monkeypatch):
    monkeypatch.setattr(main, "extract_repe_deal", lambda pages: _profile())

    response = _post_extract(organization_id=None, api_key=None)

    assert response.status_code == 200
    assert response.json()["extraction_run_id"] is None
    assert repository.runs == []


def test_extract_for_an_organization_requires_the_internal_api_key(repository, monkeypatch):
    def fail_if_called(pages):
        raise AssertionError("extraction should not run without a valid key")

    monkeypatch.setattr(main, "extract_repe_deal", fail_if_called)

    assert _post_extract(uuid4(), api_key=None).status_code == 401
    assert _post_extract(uuid4(), api_key="wrong-key").status_code == 403
    assert repository.runs == []


def test_extract_returns_nothing_when_the_run_cannot_be_recorded(tmp_path, monkeypatch):
    store = DealStore(tmp_path / "reviews")
    monkeypatch.setattr(main, "_review_store", store)
    monkeypatch.setattr(main, "get_extraction_run_repository", lambda: FakeRunRepository(fail=True))
    monkeypatch.setattr(api, "get_rag_settings", _settings)
    monkeypatch.setattr(main, "extract_repe_deal", lambda pages: _profile())

    response = _post_extract(uuid4())

    assert response.status_code == 502
    assert "database unavailable" not in response.text
    assert store.list_ids() == []
