"""API safety tests for RAG routes without live Supabase or OpenRouter clients."""

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.h9n.rag import api
from backend.app.h9n.rag.config import RagSettings
from backend.app.h9n.rag.schemas import RagSearchResponse, RagSearchResult


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


def test_search_requires_the_internal_api_key(monkeypatch):
    monkeypatch.setattr(api, "get_rag_settings", _settings)
    client = TestClient(main.app)

    response = client.post(
        "/api/h9n/rag/search",
        json={"organization_id": str(uuid4()), "query": "Find cap rate evidence"},
    )

    assert response.status_code == 401


def test_search_returns_cited_results_with_a_valid_internal_key(monkeypatch):
    organization_id = uuid4()
    document_id = uuid4()

    class FakeService:
        def search(self, request):
            assert request.organization_id == organization_id
            return RagSearchResponse(
                results=[
                    RagSearchResult(
                        document_id=document_id,
                        document_name="fixture.pdf",
                        source_type="deal_package",
                        is_verified_knowledge=False,
                        page_number=4,
                        chunk_index=0,
                        content="Cap rate is 6.5%.",
                        similarity=0.95,
                    )
                ]
            )

    monkeypatch.setattr(api, "get_rag_settings", _settings)
    monkeypatch.setattr(api, "get_rag_service", lambda: FakeService())
    client = TestClient(main.app)

    response = client.post(
        "/api/h9n/rag/search",
        headers={"X-H9N-API-Key": "test-internal-key"},
        json={"organization_id": str(organization_id), "query": "Find cap rate evidence"},
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["document_name"] == "fixture.pdf"
    assert response.json()["results"][0]["page_number"] == 4
