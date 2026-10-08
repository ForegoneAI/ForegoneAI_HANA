"""FastAPI routes for source-cited H9N RAG ingestion and retrieval.

Every route requires a signed-in Supabase user (Milestone 2.5) and acts only
for an organization that user belongs to.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from backend.app.h9n.auth import AuthenticatedUser, get_current_user, resolve_organization

from .config import RagConfigurationError, get_rag_settings
from .embeddings import OpenRouterEmbeddingProvider
from .pdf_ingestion import PdfIngestionError
from .repository import SupabaseRagRepository
from .schemas import (
    RagIngestResponse,
    RagIngestTextRequest,
    RagSearchRequest,
    RagSearchResponse,
    RagSourceType,
)
from .service import RagService


router = APIRouter(prefix="/api/h9n/rag", tags=["H9N RAG"])


@lru_cache
def get_rag_service() -> RagService:
    """Build the network clients only when a RAG route is actually requested."""
    settings = get_rag_settings()
    settings.require(
        "OPENROUTER_API_KEY",
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
    )
    return RagService(
        settings=settings,
        repository=SupabaseRagRepository(settings),
        embedding_provider=OpenRouterEmbeddingProvider(settings),
    )


def _raise_safe_rag_error(exc: Exception) -> None:
    """Map operational failures to useful API responses without leaking secrets."""
    if isinstance(exc, RagConfigurationError):
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if isinstance(exc, (ValueError, PdfIngestionError)):
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    raise HTTPException(
        status_code=502,
        detail="RAG indexing service failed. The document was not made available for retrieval.",
    ) from exc


@router.post(
    "/documents/text",
    response_model=RagIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
def ingest_page_text(
    request: RagIngestTextRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> RagIngestResponse:
    """Index page-preserved text from an internal export or approved knowledge source."""
    resolve_organization(user, request.organization_id)
    try:
        return get_rag_service().ingest_text(request)
    except Exception as exc:  # The mapper intentionally emits only safe error details.
        _raise_safe_rag_error(exc)


@router.post(
    "/documents/pdf",
    response_model=RagIngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_pdf(
    organization_id: UUID = Form(...),
    source_type: RagSourceType = Form("deal_package"),
    deal_id: UUID | None = Form(None),
    is_verified_knowledge: bool = Form(False),
    file: UploadFile = File(...),
    user: AuthenticatedUser = Depends(get_current_user),
) -> RagIngestResponse:
    """Upload a text-based PDF, save it privately, and index source-cited chunks."""
    resolve_organization(user, organization_id)
    settings = get_rag_settings()
    filename = Path(file.filename or "").name
    is_pdf_name = filename.lower().endswith(".pdf")
    is_pdf_content_type = file.content_type == "application/pdf"
    if not filename or not (is_pdf_name and is_pdf_content_type):
        raise HTTPException(
            status_code=400,
            detail="Upload a PDF with content type application/pdf and a .pdf filename.",
        )

    # Reading at most one byte above the configured ceiling prevents a client
    # from forcing unbounded memory use in this synchronous first implementation.
    file_bytes = await file.read(settings.max_upload_bytes + 1)
    if len(file_bytes) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Uploaded PDF exceeds the configured size limit.")
    if not file_bytes.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Uploaded file does not have a valid PDF signature.")

    try:
        return get_rag_service().ingest_pdf(
            organization_id=organization_id,
            document_name=filename,
            file_bytes=file_bytes,
            source_type=source_type,
            deal_id=deal_id,
            is_verified_knowledge=is_verified_knowledge,
        )
    except Exception as exc:  # The mapper intentionally emits only safe error details.
        _raise_safe_rag_error(exc)


@router.post(
    "/search",
    response_model=RagSearchResponse,
)
def search_rag(
    request: RagSearchRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> RagSearchResponse:
    """Return source passages for a semantic query; this endpoint never fabricates an answer."""
    resolve_organization(user, request.organization_id)
    try:
        return get_rag_service().search(request)
    except Exception as exc:  # The mapper intentionally emits only safe error details.
        _raise_safe_rag_error(exc)
