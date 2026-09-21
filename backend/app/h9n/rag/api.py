"""FastAPI routes for internal, source-cited H9N RAG ingestion and retrieval."""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile, status

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
        "H9N_RAG_INTERNAL_API_KEY",
    )
    return RagService(
        settings=settings,
        repository=SupabaseRagRepository(settings),
        embedding_provider=OpenRouterEmbeddingProvider(settings),
    )


def require_internal_rag_access(
    x_h9n_api_key: str | None = Header(default=None, alias="X-H9N-API-Key"),
) -> None:
    """Protect the pre-auth RAG routes from unauthenticated public use.

    This is an internal operator key, not customer authentication. Replace this
    dependency with Supabase JWT validation plus organization-membership checks
    before the routes are exposed to customers.
    """
    settings = get_rag_settings()
    try:
        settings.require("H9N_RAG_INTERNAL_API_KEY")
    except RagConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not x_h9n_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing RAG API key.")
    if not secrets.compare_digest(x_h9n_api_key, settings.internal_api_key or ""):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid RAG API key.")


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
    dependencies=[Depends(require_internal_rag_access)],
)
def ingest_page_text(request: RagIngestTextRequest) -> RagIngestResponse:
    """Index page-preserved text from an internal export or approved knowledge source."""
    try:
        return get_rag_service().ingest_text(request)
    except Exception as exc:  # The mapper intentionally emits only safe error details.
        _raise_safe_rag_error(exc)


@router.post(
    "/documents/pdf",
    response_model=RagIngestResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_internal_rag_access)],
)
async def ingest_pdf(
    organization_id: UUID = Form(...),
    source_type: RagSourceType = Form("deal_package"),
    deal_id: UUID | None = Form(None),
    is_verified_knowledge: bool = Form(False),
    file: UploadFile = File(...),
) -> RagIngestResponse:
    """Upload a text-based PDF, save it privately, and index source-cited chunks."""
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
    dependencies=[Depends(require_internal_rag_access)],
)
def search_rag(request: RagSearchRequest) -> RagSearchResponse:
    """Return source passages for a semantic query; this endpoint never fabricates an answer."""
    try:
        return get_rag_service().search(request)
    except Exception as exc:  # The mapper intentionally emits only safe error details.
        _raise_safe_rag_error(exc)
