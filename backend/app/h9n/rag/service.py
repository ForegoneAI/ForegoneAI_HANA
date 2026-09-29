"""Application service coordinating chunking, embeddings, storage, and retrieval."""

from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

from .chunking import build_page_chunks
from .config import RagSettings
from .embeddings import EmbeddingProvider
from .pdf_ingestion import extract_pages_from_pdf_bytes
from .repository import SupabaseRagRepository
from .schemas import (
    PageText,
    RagIngestResponse,
    RagIngestTextRequest,
    RagSearchRequest,
    RagSearchResponse,
    RagSearchResult,
    RagSourceType,
)


class RagService:
    """Indexes page-preserved knowledge and returns cited semantic-search results."""

    def __init__(
        self,
        settings: RagSettings,
        repository: SupabaseRagRepository,
        embedding_provider: EmbeddingProvider,
    ) -> None:
        self._settings = settings
        self._repository = repository
        self._embedding_provider = embedding_provider

    def ingest_text(self, request: RagIngestTextRequest) -> RagIngestResponse:
        """Index structured page text, such as an approved analyst note or export."""
        source_bytes = "\n".join(page.text for page in request.pages).encode("utf-8")
        return self._index_pages(
            organization_id=request.organization_id,
            document_name=request.document_name,
            pages=request.pages,
            source_type=request.source_type,
            deal_id=request.deal_id,
            is_verified_knowledge=request.is_verified_knowledge,
            source_bytes=source_bytes,
        )

    def ingest_pdf(
        self,
        *,
        organization_id: UUID,
        document_name: str,
        file_bytes: bytes,
        source_type: RagSourceType,
        deal_id: UUID | None,
        is_verified_knowledge: bool,
    ) -> RagIngestResponse:
        """Save a private source PDF and index its readable text with page provenance."""
        pages = extract_pages_from_pdf_bytes(file_bytes)
        return self._index_pages(
            organization_id=organization_id,
            document_name=document_name,
            pages=pages,
            source_type=source_type,
            deal_id=deal_id,
            is_verified_knowledge=is_verified_knowledge,
            source_bytes=file_bytes,
            save_pdf=file_bytes,
        )

    def _index_pages(
        self,
        *,
        organization_id: UUID,
        document_name: str,
        pages: list[PageText],
        source_type: RagSourceType,
        deal_id: UUID | None,
        is_verified_knowledge: bool,
        source_bytes: bytes,
        save_pdf: bytes | None = None,
    ) -> RagIngestResponse:
        """Embed page chunks, then persist metadata and vectors with cleanup on failure."""
        chunks = build_page_chunks(
            pages,
            max_characters=self._settings.chunk_size,
            overlap_characters=self._settings.chunk_overlap,
        )
        if not chunks:
            raise ValueError("No non-empty document chunks were available for indexing.")

        # Embedding before storage avoids keeping a raw PDF if the external
        # embedding provider rejects the content or is temporarily unavailable.
        embeddings = self._embedding_provider.embed_texts(
            [chunk.content for chunk in chunks], organization_id
        )
        if len(embeddings) != len(chunks):
            raise RuntimeError("The number of embeddings did not match the number of chunks.")

        document_id = uuid4()
        storage_path: str | None = None
        if save_pdf is not None:
            # The UUID prevents collisions and the org prefix supports the
            # private-bucket RLS policy defined in the Supabase migration.
            storage_path = f"{organization_id}/{document_id}/{document_name}"

        try:
            if storage_path:
                self._repository.upload_pdf(storage_path, save_pdf)

            self._repository.create_document(
                document_id=document_id,
                organization_id=organization_id,
                document_name=document_name,
                source_type=source_type,
                content_sha256=hashlib.sha256(source_bytes).hexdigest(),
                page_count=len(pages),
                deal_id=deal_id,
                is_verified_knowledge=is_verified_knowledge,
                storage_path=storage_path,
            )
            self._repository.create_chunks(
                {
                    "id": str(uuid4()),
                    "organization_id": str(organization_id),
                    "document_id": str(document_id),
                    "deal_id": str(deal_id) if deal_id else None,
                    "page_number": chunk.page_number,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "embedding": embedding,
                    "embedding_model": self._settings.embedding_model,
                }
                for chunk, embedding in zip(chunks, embeddings, strict=True)
            )
        except Exception:
            # A document delete cascades vectors. If metadata was never stored,
            # the delete is harmless. A separate storage cleanup avoids orphaned PDFs.
            try:
                self._repository.delete_document(document_id)
            finally:
                if storage_path:
                    self._repository.remove_file(storage_path)
            raise

        return RagIngestResponse(
            document_id=document_id,
            chunk_count=len(chunks),
            page_count=len(pages),
            source_type=source_type,
            storage_path=storage_path,
        )

    def search(self, request: RagSearchRequest) -> RagSearchResponse:
        """Embed a query and return the highest-ranking source passages, not an AI answer."""
        query_embedding = self._embedding_provider.embed_texts(
            [request.query], request.organization_id
        )[0]
        rows = self._repository.search_chunks(
            organization_id=request.organization_id,
            query_embedding=query_embedding,
            match_count=request.match_count or self._settings.default_match_count,
            deal_id=request.deal_id,
            verified_knowledge_only=request.verified_knowledge_only,
        )
        return RagSearchResponse(results=[RagSearchResult.model_validate(row) for row in rows])
