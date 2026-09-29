import hashlib
import tempfile
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Optional
from uuid import UUID, uuid4

from fastapi import Body, FastAPI, Form, Header, HTTPException, UploadFile
from pydantic import BaseModel

from backend.app.h9n.extraction.repe_extractor import (
    DEFAULT_MODEL,
    apply_reviewer_feedback,
    extract_repe_deal,
    extraction_input_sha256,
    extraction_prompt_sha256,
    merge_evidence,
)
from backend.app.h9n.extraction.run_repository import (
    ExtractionRunRecord,
    SupabaseExtractionRunRepository,
)
from backend.app.h9n.ingestion.pdf_reader import read_pdf
from backend.app.h9n.rag.api import require_internal_rag_access
from backend.app.h9n.rag.api import router as rag_router
from backend.app.h9n.rag.config import RagConfigurationError, get_rag_settings
from backend.app.h9n.review.store import DealNotFoundError, DealStore
from backend.app.h9n.schemas.repe_deal import REPEDealProfile


# Creates the main FastAPI application for HANA
app = FastAPI()
app.include_router(rag_router)

# Milestone 1, item 4: where extracted deals are saved so a reviewer can
# fetch and correct one later by id. See store.py for why this is a simple
# on-disk store rather than a real database.
_review_store = DealStore()


# Milestone 1.3: where extraction runs are recorded. Built on first use so the
# app still starts (and tests still run) without Supabase credentials.
@lru_cache
def get_extraction_run_repository() -> SupabaseExtractionRunRepository:
    return SupabaseExtractionRunRepository(get_rag_settings())


# What POST /extract returns: the extracted profile plus the id it was
# saved under, so the caller can look it up again later for review.
# extraction_run_id is only set when the run was recorded in Supabase.
class ExtractResponse(BaseModel):
    deal_id: str
    profile: REPEDealProfile
    extraction_run_id: Optional[UUID] = None


# What a reviewer submits to POST /deals/{deal_id}/review. Only "approved"
# and "rejected" are accepted here - "pending" is only ever the starting
# state a fresh extraction gets, never something submitted after the fact.
class ReviewRequest(BaseModel):
    status: Literal["approved", "rejected"]

    # Only meaningful when status="rejected". The reviewer's own
    # explanation of what's wrong (e.g. "the asking price is wrong, it
    # should be around $950k per page 4") - if given, and the deal's
    # source document text is still available (see DealStore.save_pages),
    # this is sent to apply_reviewer_feedback() to automatically re-derive
    # and apply the corrected field(s), instead of requiring the reviewer
    # to work out and submit the exact value themselves via PATCH.
    feedback: Optional[str] = None


# Basic endpoint used to verify that the backend is running
@app.get("/")
def root():
    return {"message": "HANA Active"}


# Test endpoint for validating REPE deal data
@app.post("/api/h9n/repe/test")
def test_repe_deal(deal: REPEDealProfile):
    return deal


# Milestone 1, Part 1 checkpoint: upload a deal package (e.g. the Taberna
# CIM) and get back an automatically populated, schema-validated
# REPEDealProfile - no manual data entry. The profile is also saved to the
# review store (item 4) so it can be fetched and corrected later by the
# returned deal_id, instead of only existing in this one response.
#
# Milestone 1.3: when an organization_id is supplied, every attempt -
# successful or failed - is also recorded as an extraction run in Supabase
# (see run_repository.py). Recording writes into that tenant's data with the
# service role, so until real user auth exists it requires the same internal
# operator key as the RAG routes.
@app.post("/api/h9n/repe/extract", response_model=ExtractResponse)
def extract_repe_deal_from_upload(
    file: UploadFile,
    organization_id: Optional[UUID] = Form(None),
    x_h9n_api_key: Optional[str] = Header(default=None, alias="X-H9N-API-Key"),
) -> ExtractResponse:
    if file.content_type not in ("application/pdf", None) and not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF deal packages are supported right now.")

    if organization_id is not None:
        require_internal_rag_access(x_h9n_api_key)

    file_bytes = file.file.read()

    # read_pdf() takes a file path, so the upload is written to a temp file
    # (auto-deleted once the request finishes) rather than re-implementing
    # PDF parsing from an in-memory stream.
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(file_bytes)
        tmp.flush()

        pages = read_pdf(tmp.name)
        if not pages:
            raise HTTPException(status_code=422, detail="No text could be extracted from the uploaded PDF.")

        # The temp file's name is meaningless to the reviewer, so the
        # original uploaded filename is swapped back in for provenance.
        for page in pages:
            page["file_name"] = Path(file.filename).name

    deal_id = uuid4().hex
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    deal: Optional[REPEDealProfile] = None
    error: Optional[Exception] = None
    try:
        deal = extract_repe_deal(pages)
    except Exception as exc:  # Recorded as a failed run below, then re-raised.
        error = exc

    extraction_run_id = None
    if organization_id is not None:
        extraction_run_id = _record_extraction_run(
            ExtractionRunRecord(
                organization_id=organization_id,
                deal_id=deal_id,
                status="failed" if error else "succeeded",
                model=DEFAULT_MODEL,
                prompt_sha256=extraction_prompt_sha256(),
                source_filename=Path(file.filename).name,
                source_sha256=hashlib.sha256(file_bytes).hexdigest(),
                input_sha256=extraction_input_sha256(pages),
                page_count=len(pages),
                profile=deal,
                error_type=type(error).__name__ if error else None,
                error_message=str(error)[:2000] if error else None,
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                latency_ms=round((time.perf_counter() - started) * 1000),
            )
        )

    if isinstance(error, ValueError):
        raise HTTPException(status_code=502, detail=str(error)) from error
    if error is not None:
        raise error

    _review_store.save(deal, deal_id)
    # So a reviewer's future rejection feedback has something to re-derive
    # a correction from (see the review endpoint below) - without this, a
    # correction could only ever be the exact value a human already worked
    # out, never one Claude re-derives from the source text.
    _review_store.save_pages(deal_id, pages)
    return ExtractResponse(deal_id=deal_id, profile=deal, extraction_run_id=extraction_run_id)


def _record_extraction_run(run: ExtractionRunRecord) -> UUID:
    """Saves a run, failing the request if it can't be saved, so no caller ever
    receives an extraction that isn't traceable (Milestone 1.3)."""
    try:
        return get_extraction_run_repository().record(run)
    except RagConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # Never echo database errors back to the caller.
        raise HTTPException(
            status_code=502,
            detail="The extraction run could not be recorded, so its result was not returned.",
        ) from exc


# Milestone 1, item 4: fetch a previously extracted deal by id, e.g. to show
# it to a reviewer in a UI.
@app.get("/api/h9n/repe/deals/{deal_id}", response_model=REPEDealProfile)
def get_repe_deal(deal_id: str) -> REPEDealProfile:
    try:
        return _review_store.get(deal_id)
    except DealNotFoundError:
        raise HTTPException(status_code=404, detail=f"No deal found with id {deal_id!r}.")


# Milestone 1, item 4: a reviewer submits corrected values for one or more
# fields (e.g. {"asking_price": 9500000}), which are validated, applied, and
# recorded in the deal's own corrected_fields list so it's visible later
# which values were human-verified rather than model-extracted.
@app.patch("/api/h9n/repe/deals/{deal_id}", response_model=REPEDealProfile)
def correct_repe_deal(deal_id: str, corrections: dict[str, Any] = Body(...)) -> REPEDealProfile:
    try:
        return _review_store.apply_corrections(deal_id, corrections)
    except DealNotFoundError:
        raise HTTPException(status_code=404, detail=f"No deal found with id {deal_id!r}.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# Milestone 1, item 4: the plan's "Approve and save the validated Deal
# Profile" step. This is deliberately separate from PATCH /deals/{deal_id}
# above - correcting a field's value doesn't by itself mean a reviewer has
# looked at the whole profile and signed off on it, so this is where they
# explicitly say "yes, this is correct" (approved) or "no, it still isn't"
# (rejected).
#
# A "rejected" verdict can also carry `feedback`: the reviewer's own
# explanation of what's wrong. When given (and the deal's source document
# text is still available - see DealStore.save_pages), this is handed to
# apply_reviewer_feedback() to automatically re-derive and apply the
# corrected field(s) from the original text, and the deal is put back to
# "pending" so it gets a fresh look rather than sitting "rejected" forever.
# If there's no source text to re-derive from, or Claude can't confidently
# derive a fix from the feedback, the rejection and feedback are still
# recorded - the reviewer can always fall back to PATCH-ing an exact value.
@app.post("/api/h9n/repe/deals/{deal_id}/review", response_model=REPEDealProfile)
def review_repe_deal(deal_id: str, review: ReviewRequest) -> REPEDealProfile:
    try:
        deal = _review_store.set_review_status(deal_id, review.status)
    except DealNotFoundError:
        raise HTTPException(status_code=404, detail=f"No deal found with id {deal_id!r}.")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if review.status != "rejected" or not review.feedback or not review.feedback.strip():
        return deal

    deal = _review_store.apply_corrections(deal_id, {"review_feedback": review.feedback})

    if not _review_store.has_pages(deal_id):
        # No source text saved for this deal (e.g. it predates this
        # feature) - nothing to automatically re-derive a fix from.
        return deal

    try:
        pages = _review_store.get_pages(deal_id)
        result = apply_reviewer_feedback(pages, deal, review.feedback)
    except ValueError:
        # Claude couldn't confidently derive a fix (or returned nothing
        # usable) - leave the rejection + feedback recorded as-is rather
        # than failing the whole request.
        return deal

    if result["corrections"]:
        deal = _review_store.apply_corrections(deal_id, result["corrections"])
        if result["updated_evidence"]:
            merged_evidence = merge_evidence(deal.evidence, result["updated_evidence"])
            deal = _review_store.apply_corrections(deal_id, {"evidence": merged_evidence})
        # Something changed automatically - it needs a human to look again,
        # not to sit marked "rejected" as if nothing happened.
        deal = _review_store.apply_corrections(deal_id, {"review_status": "pending"})

    return deal