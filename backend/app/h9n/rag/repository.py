"""Supabase persistence adapter for H9N RAG documents, chunks, and source PDFs."""

from __future__ import annotations

from typing import Any, Iterable
from uuid import UUID

from supabase import Client, create_client

from .config import RagSettings


class SupabaseRagRepository:
    """Persists RAG data through the server-only Supabase service-role client.

    The service role intentionally bypasses Supabase RLS, so this class must
    only be constructed on the FastAPI server after its access control check.
    It must never be imported into browser code or configured with a public key.
    """

    def __init__(self, settings: RagSettings, *, client: Client | None = None) -> None:
        settings.require("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
        self._settings = settings
        self._client = client or create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )

    def upload_pdf(self, storage_path: str, content: bytes) -> None:
        """Store an original PDF in the private bucket before it is indexed."""
        self._client.storage.from_(self._settings.storage_bucket).upload(
            path=storage_path,
            file=content,
            file_options={"content-type": "application/pdf", "upsert": "false"},
        )

    def remove_file(self, storage_path: str) -> None:
        """Remove a source object when a later indexing step fails."""
        self._client.storage.from_(self._settings.storage_bucket).remove([storage_path])

    def create_document(
        self,
        *,
        document_id: UUID,
        organization_id: UUID,
        document_name: str,
        source_type: str,
        content_sha256: str,
        page_count: int,
        deal_id: UUID | None,
        is_verified_knowledge: bool,
        storage_path: str | None,
    ) -> None:
        """Create document metadata before inserting its page-preserved chunks."""
        self._client.table("rag_documents").insert(
            {
                "id": str(document_id),
                "organization_id": str(organization_id),
                "deal_id": str(deal_id) if deal_id else None,
                "document_name": document_name,
                "source_type": source_type,
                "content_sha256": content_sha256,
                "page_count": page_count,
                "is_verified_knowledge": is_verified_knowledge,
                "storage_path": storage_path,
            }
        ).execute()

    def create_chunks(self, chunks: Iterable[dict[str, Any]]) -> None:
        """Insert all embeddings in one request to keep document indexing efficient."""
        rows = list(chunks)
        if rows:
            self._client.table("rag_chunks").insert(rows).execute()

    def delete_document(self, document_id: UUID) -> None:
        """Delete metadata and cascade its chunks after a failed partial ingest."""
        self._client.table("rag_documents").delete().eq("id", str(document_id)).execute()

    def search_chunks(
        self,
        *,
        organization_id: UUID,
        query_embedding: list[float],
        match_count: int,
        deal_id: UUID | None,
        verified_knowledge_only: bool,
    ) -> list[dict[str, Any]]:
        """Call the SQL RPC that applies tenant and optional deal filters before ranking."""
        response = self._client.rpc(
            "match_rag_chunks",
            {
                "query_embedding": query_embedding,
                "target_organization_id": str(organization_id),
                "target_deal_id": str(deal_id) if deal_id else None,
                "only_verified_knowledge": verified_knowledge_only,
                "match_count": match_count,
            },
        ).execute()
        return response.data or []
