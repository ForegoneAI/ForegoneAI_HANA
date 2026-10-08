import hashlib
import logging
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, NoReturn, Optional
from uuid import UUID, uuid4

from fastapi import Body, Depends, FastAPI, Form, HTTPException, UploadFile
from pydantic import BaseModel

from backend.app.h9n.auth import AuthenticatedUser, get_current_user, resolve_organization
from backend.app.h9n.extraction.repe_extractor import (
    DEFAULT_MODEL,
    ExtractionConfigurationError,
    ExtractionError,
    ExtractionInputError,
    ExtractionOutputError,
    ExtractionRefusedError,
    ExtractionUnavailableError,
    apply_reviewer_feedback,
    extract_repe_deal,
    extraction_input_sha256,
    extraction_prompt_sha256,
    feedback_updates,
)
from backend.app.h9n.extraction.run_repository import (
    ExtractionRunRecord,
    SupabaseExtractionRunRepository,
)
from backend.app.h9n.ingestion.pdf_reader import MAX_UPLOAD_BYTES, PdfReadError, read_pdf_bytes
from backend.app.h9n.rag.api import router as rag_router
from backend.app.h9n.rag.config import RagConfigurationError, get_rag_settings
from backend.app.h9n.review.store import DealNotFoundError, DealStore
from backend.app.h9n.schemas.repe_deal import REPEDealProfile


logger = logging.getLogger(__name__)

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
# saved under, so the caller can look it up again later for review, and the
# id of the extraction run recorded for it in Supabase (Milestone 1.3).
class ExtractResponse(BaseModel):
    deal_id: str
    profile: REPEDealProfile
    extraction_run_id: UUID


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
# Milestone 1.3 / 2.5: the caller must be signed in, and every attempt -
# successful or failed - is recorded as an extraction run for their
# organization in Supabase (see run_repository.py). organization_id is only
# needed when the caller belongs to more than one organization.
#
# Milestone 1.1: every failure comes back as a controlled error with a safe
# message - 422 for a file or document that can't be extracted, 502 when the
# model's output was unusable or refused, 503 when the provider is down or
# H9N isn't configured, 413 for an oversized upload - never a raw stack trace
# or model output. A profile that is returned has only verified values in its
# fields; anything the model couldn't back up is null there and listed in
# `withheld_values`.
@app.post("/api/h9n/repe/extract", response_model=ExtractResponse)
def extract_repe_deal_from_upload(
    file: UploadFile,
    organization_id: Optional[UUID] = Form(None),
    user: AuthenticatedUser = Depends(get_current_user),
) -> ExtractResponse:
    source_filename = Path(file.filename or "upload.pdf").name
    if file.content_type not in ("application/pdf", None) and not source_filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF deal packages are supported right now.")

    organization_id = resolve_organization(user, organization_id)

    # Read at most one byte past the limit, so an oversized upload is never
    # held in memory whole.
    file_bytes = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413, detail=f"PDFs may be at most {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )

    # Pages carry the uploaded filename (not a temp path) so citations make
    # sense to a reviewer. A file that can't be read fails here, before any
    # model call, so there is no extraction run to record.
    try:
        pages = read_pdf_bytes(file_bytes, source_filename)
    except PdfReadError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    deal_id = uuid4().hex
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    deal: Optional[REPEDealProfile] = None
    error: Optional[Exception] = None
    try:
        deal = extract_repe_deal(pages)
    except Exception as exc:  # Recorded as a failed run below, then re-raised.
        error = exc

    extraction_run_id = _record_extraction_run(
        ExtractionRunRecord(
            organization_id=organization_id,
            deal_id=deal_id,
            status="failed" if error else "succeeded",
            model=DEFAULT_MODEL,
            prompt_sha256=extraction_prompt_sha256(),
            source_filename=source_filename,
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

    if error is not None:
        _raise_extraction_error(error)

    _review_store.save(deal, deal_id)
    _review_store.save_owner(deal_id, organization_id)
    # So a reviewer's future rejection feedback has something to re-derive
    # a correction from (see the review endpoint below) - without this, a
    # correction could only ever be the exact value a human already worked
    # out, never one Claude re-derives from the source text.
    _review_store.save_pages(deal_id, pages)
    return ExtractResponse(deal_id=deal_id, profile=deal, extraction_run_id=extraction_run_id)


def _raise_extraction_error(error: Exception, *, prefix: str = "") -> NoReturn:
    """Maps an extraction failure to a controlled HTTP error (Milestone 1.1).
    ExtractionError messages are written to be safe for callers; anything
    unexpected gets a generic message so internals never leak, and is logged
    with its traceback so it isn't lost. `prefix` tells the caller what was
    already saved before the failure."""
    if isinstance(error, ExtractionInputError):
        raise HTTPException(status_code=422, detail=prefix + str(error)) from error
    if isinstance(error, (ExtractionOutputError, ExtractionRefusedError)):
        raise HTTPException(status_code=502, detail=prefix + str(error)) from error
    if isinstance(error, ExtractionUnavailableError):
        raise HTTPException(status_code=503, detail=prefix + str(error)) from error
    if isinstance(error, ExtractionConfigurationError):
        # The specific cause (missing key, unknown model) belongs in the
        # server log, not in a response to a caller.
        logger.error("H9N extraction is misconfigured: %s", error)
        raise HTTPException(
            status_code=503, detail=prefix + "The extraction service is not configured. Contact the H9N team."
        ) from error
    logger.exception("Unexpected H9N extraction failure", exc_info=error)
    if isinstance(error, ValueError):
        raise HTTPException(
            status_code=502, detail=prefix + "The extraction did not produce a usable result."
        ) from error
    raise HTTPException(status_code=500, detail=prefix + "Unexpected extraction failure.") from error


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


def _require_deal_access(deal_id: str, user: AuthenticatedUser) -> None:
    """404s unless the deal belongs to one of the caller's organizations
    (Milestone 2.5). Another organization's deal gets the same response as a
    deal that doesn't exist, so its existence isn't revealed."""
    if _review_store.owner_of(deal_id) not in user.organization_ids:
        raise HTTPException(status_code=404, detail=f"No deal found with id {deal_id!r}.")


# Milestone 1, item 4: fetch a previously extracted deal by id, e.g. to show
# it to a reviewer in a UI.
@app.get("/api/h9n/repe/deals/{deal_id}", response_model=REPEDealProfile)
def get_repe_deal(deal_id: str, user: AuthenticatedUser = Depends(get_current_user)) -> REPEDealProfile:
    _require_deal_access(deal_id, user)
    try:
        return _review_store.get(deal_id)
    except DealNotFoundError:
        raise HTTPException(status_code=404, detail=f"No deal found with id {deal_id!r}.")


# Milestone 1, item 4: a reviewer submits corrected values for one or more
# fields (e.g. {"asking_price": 9500000}), which are validated, applied, and
# recorded in the deal's own corrected_fields list so it's visible later
# which values were human-verified rather than model-extracted.
@app.patch("/api/h9n/repe/deals/{deal_id}", response_model=REPEDealProfile)
def correct_repe_deal(
    deal_id: str,
    corrections: dict[str, Any] = Body(...),
    user: AuthenticatedUser = Depends(get_current_user),
) -> REPEDealProfile:
    _require_deal_access(deal_id, user)
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
#
# Milestone 1.1: a correction is held to the same standard as an extraction.
# Claude can only change deal value fields (never review_status,
# withheld_values or evidence directly), and a corrected value is applied only
# if its citation verifies; otherwise it is added to withheld_values for the
# reviewer. If the correction step itself fails (provider down, unusable
# output), the response is a controlled 502/503 that says the rejection and
# feedback were still saved.
@app.post("/api/h9n/repe/deals/{deal_id}/review", response_model=REPEDealProfile)
def review_repe_deal(
    deal_id: str,
    review: ReviewRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> REPEDealProfile:
    _require_deal_access(deal_id, user)
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
    except ExtractionError as exc:
        _raise_extraction_error(
            exc, prefix="The rejection and feedback were saved, but the automatic correction failed: "
        )

    # One save: the verified corrections, their new citations, the updated
    # withheld list, and "pending" so a human looks again. {} when Claude
    # found nothing it could correct - the rejection then stands as submitted.
    updates = feedback_updates(deal, result)
    if updates:
        deal = _review_store.apply_corrections(deal_id, updates)
    return deal
