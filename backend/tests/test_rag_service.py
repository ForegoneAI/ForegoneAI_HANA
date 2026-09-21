"""RAG service tests use fake providers so no customer data or API keys are needed."""

from uuid import UUID, uuid4

from backend.app.h9n.rag.config import RagSettings
from backend.app.h9n.rag.schemas import (
    PageText,
    RagIngestTextRequest,
    RagSearchRequest,
)
from backend.app.h9n.rag.service import RagService


class FakeEmbeddingProvider:
    """Returns predictable vectors instead of sending test text to OpenRouter."""

    def embed_texts(self, texts, organization_id):
        return [[float(index), 0.5, 1.0] for index, _ in enumerate(texts)]


class FakeRepository:
    """Captures persistence calls and returns a fixed source-cited search result."""

    def __init__(self, organization_id, document_id):
        self.organization_id = organization_id
        self.document_id = document_id
        self.document = None
        self.chunks = []

    def create_document(self, **kwargs):
        self.document = kwargs

    def create_chunks(self, chunks):
        self.chunks = list(chunks)

    def delete_document(self, document_id):
        self.deleted_document_id = document_id

    def search_chunks(self, **kwargs):
        return [
            {
                "document_id": str(self.document_id),
                "document_name": "fixture.pdf",
                "deal_id": None,
                "source_type": "deal_package",
                "is_verified_knowledge": False,
                "page_number": 2,
                "chunk_index": 1,
                "content": "NOI is $500,000.",
                "similarity": 0.91,
            }
        ]


def _settings() -> RagSettings:
    """Use test-only values; no network client is constructed in these tests."""
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


def test_ingest_text_creates_page_preserved_chunks_with_embeddings():
    organization_id = uuid4()
    document_id = uuid4()
    repository = FakeRepository(organization_id, document_id)
    service = RagService(_settings(), repository, FakeEmbeddingProvider())
    request = RagIngestTextRequest(
        organization_id=organization_id,
        document_name="fixture.pdf",
        source_type="deal_package",
        pages=[PageText(page_number=7, text="Asking price is $10,000,000. " * 8)],
    )

    response = service.ingest_text(request)

    assert response.chunk_count > 1
    assert response.page_count == 1
    assert repository.document["organization_id"] == organization_id
    assert all(chunk["page_number"] == 7 for chunk in repository.chunks)
    assert all(len(chunk["embedding"]) == 3 for chunk in repository.chunks)


def test_search_returns_source_cited_results_from_the_repository():
    organization_id = uuid4()
    document_id = uuid4()
    service = RagService(
        _settings(), FakeRepository(organization_id, document_id), FakeEmbeddingProvider()
    )

    response = service.search(
        RagSearchRequest(organization_id=organization_id, query="What is the NOI?")
    )

    assert len(response.results) == 1
    assert response.results[0].document_id == document_id
    assert response.results[0].page_number == 2
    assert response.results[0].similarity == 0.91
