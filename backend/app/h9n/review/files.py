"""Where a deal's original PDF is kept (Milestone 2.3).

The PDF goes in the private Supabase bucket the RAG pipeline already uses,
under the deal's organization: {organization_id}/{deal_id}/source.pdf.
Nobody reads it from the bucket directly; the API hands out a short-lived
signed URL after checking the deal belongs to the caller's organization.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from supabase import Client, create_client

from backend.app.h9n.rag.config import RagSettings


def source_pdf_path(organization_id: UUID, deal_id: UUID) -> str:
    """The bucket path for a deal's PDF. A fixed file name avoids characters
    storage keys don't accept; the original name is kept on the deal."""
    return f"{organization_id}/{deal_id}/source.pdf"


class DealFileStore(Protocol):
    def upload(self, path: str, content: bytes) -> None: ...

    def remove(self, path: str) -> None: ...

    def signed_url(self, path: str, expires_in: int) -> str: ...


class SupabaseDealFileStore:
    """Deal PDFs in the private bucket, through the service-role client."""

    def __init__(self, settings: RagSettings, *, client: Client | None = None) -> None:
        settings.require("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
        self._bucket = settings.storage_bucket
        self._client = client or create_client(settings.supabase_url, settings.supabase_service_role_key)

    def upload(self, path: str, content: bytes) -> None:
        self._client.storage.from_(self._bucket).upload(
            path=path,
            file=content,
            file_options={"content-type": "application/pdf", "upsert": "false"},
        )

    def remove(self, path: str) -> None:
        self._client.storage.from_(self._bucket).remove([path])

    def signed_url(self, path: str, expires_in: int) -> str:
        response = self._client.storage.from_(self._bucket).create_signed_url(path, expires_in)
        url = response.get("signedUrl")
        if not url:
            raise RuntimeError(f"Supabase returned no signed URL for {path!r}.")
        return url
