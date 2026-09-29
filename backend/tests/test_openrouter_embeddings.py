"""Tests that the embedding provider targets OpenRouter without a network call."""

from types import SimpleNamespace
from uuid import uuid4

from backend.app.h9n.rag import embeddings
from backend.app.h9n.rag.config import RagSettings


def _settings() -> RagSettings:
    return RagSettings(
        openrouter_api_key="test-openrouter-key",
        supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-service-key",
        internal_api_key="test-internal-key",
        embedding_model="openai/text-embedding-3-small",
        embedding_dimensions=3,
        openrouter_referer="http://localhost:8000",
        openrouter_title="H9N RAG tests",
        storage_bucket="test-bucket",
        chunk_size=60,
        chunk_overlap=15,
        max_upload_bytes=1_000_000,
        default_match_count=4,
    )


def test_embedding_provider_uses_openrouter_endpoint_and_headers(monkeypatch):
    calls = {}

    class FakeEmbeddings:
        def create(self, **kwargs):
            calls["embedding_request"] = kwargs
            return SimpleNamespace(
                data=[SimpleNamespace(embedding=[0.1, 0.2, 0.3])]
            )

    class FakeClient:
        def __init__(self, **kwargs):
            calls["client"] = kwargs
            self.embeddings = FakeEmbeddings()

    monkeypatch.setattr(embeddings, "OpenAI", FakeClient)
    provider = embeddings.OpenRouterEmbeddingProvider(_settings())

    vectors = provider.embed_texts(["NOI is $650,000."], uuid4())

    assert calls["client"]["base_url"] == "https://openrouter.ai/api/v1"
    assert calls["client"]["api_key"] == "test-openrouter-key"
    assert calls["client"]["default_headers"] == {
        "HTTP-Referer": "http://localhost:8000",
        "X-OpenRouter-Title": "H9N RAG tests",
    }
    assert calls["embedding_request"]["model"] == "openai/text-embedding-3-small"
    assert vectors == [[0.1, 0.2, 0.3]]
