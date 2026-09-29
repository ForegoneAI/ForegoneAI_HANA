"""Supabase persistence for H9N extraction runs (Milestone 1.3).

Every extraction attempt, successful or failed, is saved with enough metadata
to identify which model and prompt produced it, the exact input it saw, and
the page-level evidence behind each important field.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from supabase import Client, create_client

from backend.app.h9n.rag.config import RagSettings
from backend.app.h9n.schemas.repe_deal import REPEDealProfile


class ExtractionRunRecord(BaseModel):
    """One extraction attempt, shaped like a row of public.extraction_runs."""

    organization_id: UUID
    deal_id: UUID
    status: Literal["succeeded", "failed"]

    model: str
    prompt_sha256: str = Field(min_length=64, max_length=64)
    source_filename: str
    source_sha256: str = Field(min_length=64, max_length=64)
    input_sha256: str = Field(min_length=64, max_length=64)
    page_count: int = Field(gt=0)

    # Only a validated profile can be attached, so malformed model output can
    # never reach the database through this record.
    profile: Optional[REPEDealProfile] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None

    started_at: datetime
    completed_at: datetime
    latency_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def _status_matches_outcome(self) -> "ExtractionRunRecord":
        # Mirrors the table's check constraint so a bad record fails here,
        # with a clear Python error, instead of as a database rejection.
        if self.status == "succeeded" and (self.profile is None or self.error_type):
            raise ValueError("A succeeded run needs a profile and no error.")
        if self.status == "failed" and (self.profile is not None or not self.error_type):
            raise ValueError("A failed run needs an error_type and no profile.")
        return self


class SupabaseExtractionRunRepository:
    """Saves extraction runs through the server-only Supabase service-role client.

    Like SupabaseRagRepository, the service role bypasses RLS, so callers must
    establish which organization the request belongs to before recording.
    """

    def __init__(self, settings: RagSettings, *, client: Client | None = None) -> None:
        settings.require("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
        self._client = client or create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )

    def record(self, run: ExtractionRunRecord) -> UUID:
        """Save a run and its evidence atomically, returning the new run id."""
        response = self._client.rpc(
            "record_extraction_run",
            {"run": run.model_dump(mode="json")},
        ).execute()
        return UUID(str(response.data))
