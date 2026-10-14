import hashlib
import logging
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Iterator, NoReturn, Optional, TypeVar
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.app.h9n.auth import AuthenticatedUser, get_current_user, organizations_of, resolve_organization
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
from backend.app.h9n.review.models import (
    DealConflictError,
    DealHistory,
    DealNotFoundError,
    DealRecord,
    DealUpdateError,
    NewDeal,
    ReviewAction,
)
from backend.app.h9n.review.repository import DealRepository, SupabaseDealRepository
from backend.app.h9n.review.workflow import plan_corrections, plan_review_action
from backend.app.h9n.screening.api import router as mandate_router
from backend.app.h9n.schemas.base_deal import ReviewStatus
from backend.app.h9n.schemas.repe_deal import REPEDealProfile


logger = logging.getLogger(__name__)

# Creates the main FastAPI application for HANA
app = FastAPI()
app.include_router(rag_router)
# Milestone 3.1: investment mandates (see backend/app/h9n/screening/api.py).
app.include_router(mandate_router)

# Milestone 2.1: the web app (frontend/) runs on its own address, so browsers
# only let it call this API from origins listed here. Comma-separated; the
# default is the Next.js dev server.
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("H9N_ALLOWED_ORIGINS", "http://localhost:3000").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "PATCH"],
    allow_headers=["Authorization", "Content-Type"],
)

T = TypeVar("T")


# Milestone 2.4: where extracted deals and their review history are saved
# (see review/repository.py). Built on first use, like the run repository.
@lru_cache
def get_deal_repository() -> DealRepository:
    return SupabaseDealRepository(get_rag_settings())


# Milestone 1.3: where extraction runs are recorded. Built on first use so the
# app still starts (and tests still run) without Supabase credentials.
@lru_cache
def get_extraction_run_repository() -> SupabaseExtractionRunRepository:
    return SupabaseExtractionRunRepository(get_rag_settings())


# What POST /extract returns: the extracted profile plus the id it was
# saved under, so the caller can look it up again later for review, and the
# id of the extraction run recorded for it in Supabase (Milestone 1.3).
class ExtractResponse(BaseModel):
    deal_id: UUID
    profile: REPEDealProfile
    extraction_run_id: UUID


# One row of GET /deals: enough for the web app's deal list to show and
# reopen a saved deal without loading every full profile (Milestone 2.1).
class DealSummary(BaseModel):
    deal_id: UUID
    organization_id: UUID
    deal_name: Optional[str]
    property_name: Optional[str]
    review_status: ReviewStatus
    saved_at: datetime


# A saved deal as the API returns it (Milestone 2.4): the profile plus where
# it stands in review. `version` must be sent back with any change, so a
# change made against an out-of-date copy is refused instead of overwriting
# someone else's. The source page text stays server-side.
class DealOut(BaseModel):
    deal_id: UUID
    organization_id: UUID
    status: ReviewStatus
    version: int
    source_filename: str
    extraction_run_id: Optional[UUID]
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    profile: REPEDealProfile

    @classmethod
    def from_record(cls, record: DealRecord) -> "DealOut":
        return cls(deal_id=record.id, **record.model_dump(exclude={"id", "source_pages"}))


# What a reviewer submits to PATCH /deals/{deal_id}: the version they
# edited, and field name -> corrected value.
class CorrectionRequest(BaseModel):
    version: int
    changes: dict[str, Any]


# What a reviewer submits to POST /deals/{deal_id}/review (Milestone 2.4).
class ReviewRequest(BaseModel):
    action: ReviewAction
    version: int

    # Required for "reject": the reviewer's own explanation of what's wrong
    # (e.g. "the asking price is wrong, it should be around $950k per page
    # 4"). It's sent to apply_reviewer_feedback() to re-derive and apply the
    # corrected field(s) from the source text, instead of requiring the
    # reviewer to work out and submit the exact value themselves via PATCH.
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

    deal_id = uuid4()
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

    # Saved with its source pages, so a reviewer's later feedback can be
    # checked against the document again (see the review endpoint below).
    _deals(
        lambda deals: deals.create(
            NewDeal(
                id=deal_id,
                organization_id=organization_id,
                profile=deal,
                source_filename=source_filename,
                source_pages=pages,
                extraction_run_id=extraction_run_id,
                created_by=user.user_id,
            )
        )
    )
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


@contextmanager
def _deal_errors() -> Iterator[None]:
    """Turns deal-review failures into safe HTTP errors (Milestone 2.4). A
    deal outside the caller's organizations is a 404, the same as one that
    doesn't exist, so its existence isn't revealed (M2.5)."""
    try:
        yield
    except DealNotFoundError as exc:
        raise HTTPException(status_code=404, detail="No deal found with that id.") from exc
    except DealConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except DealUpdateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RagConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # Database details go to the log, never to the caller.
        logger.exception("Deal storage failed")
        raise HTTPException(status_code=502, detail="Deals could not be reached. Try again shortly.") from exc


def _deals(action: Callable[[DealRepository], T]) -> T:
    """Runs one deal-storage action, with _deal_errors()."""
    with _deal_errors():
        return action(get_deal_repository())


def _load_deal(deal_id: str, user: AuthenticatedUser) -> DealRecord:
    """The caller's deal, or a 404 (also for an id that isn't a valid id)."""
    try:
        parsed = UUID(deal_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="No deal found with that id.") from None
    return _deals(lambda deals: deals.get(parsed, user.organization_ids))


def _require_version(deal: DealRecord, version: int) -> None:
    """Refuses a change made against an out-of-date copy before doing any
    work; the database checks again when saving."""
    if version != deal.version:
        raise HTTPException(
            status_code=409,
            detail="Someone else changed this deal since you opened it. Reload it to see their changes.",
        )


# What GET /me returns: who is signed in and which organizations they may act
# for (Milestone 2.5).
class OrganizationOut(BaseModel):
    id: UUID
    name: str


class CurrentUser(BaseModel):
    user_id: UUID
    organizations: list[OrganizationOut]


# Milestone 2.5: the signed-in user and their organizations, by name. The web
# app uses this to ask a member of several organizations which one an upload
# is for - the API refuses to guess (see resolve_organization).
@app.get("/api/h9n/me", response_model=CurrentUser)
def current_user(user: AuthenticatedUser = Depends(get_current_user)) -> CurrentUser:
    return CurrentUser(
        user_id=user.user_id,
        organizations=[OrganizationOut(id=org.id, name=org.name) for org in organizations_of(user)],
    )


# Milestone 2.1 / 2.4: the deals the caller's organizations own, most
# recently changed first, so a reviewer can reopen one in the web app.
@app.get("/api/h9n/repe/deals", response_model=list[DealSummary])
def list_repe_deals(user: AuthenticatedUser = Depends(get_current_user)) -> list[DealSummary]:
    summaries = _deals(lambda deals: deals.list(user.organization_ids))
    return [
        DealSummary(
            deal_id=summary.id,
            organization_id=summary.organization_id,
            deal_name=summary.deal_name,
            property_name=summary.property_name,
            review_status=summary.status,
            saved_at=summary.updated_at,
        )
        for summary in summaries
    ]


# Fetch a saved deal: its profile and where it stands in review.
@app.get("/api/h9n/repe/deals/{deal_id}", response_model=DealOut)
def get_repe_deal(deal_id: str, user: AuthenticatedUser = Depends(get_current_user)) -> DealOut:
    return DealOut.from_record(_load_deal(deal_id, user))


# Milestone 2.4: everything reviewers have done to a deal, oldest first -
# each corrected field (original value, corrected value, its evidence, who,
# when) and each status change.
@app.get("/api/h9n/repe/deals/{deal_id}/history", response_model=DealHistory)
def get_repe_deal_history(deal_id: str, user: AuthenticatedUser = Depends(get_current_user)) -> DealHistory:
    deal = _load_deal(deal_id, user)
    return _deals(lambda deals: deals.history(deal))


# A reviewer corrects one or more fields, e.g.
# {"version": 3, "changes": {"asking_price": 9500000}}. Values are validated
# like an extraction (a wrong type or unknown field is a 400), each change is
# recorded with its original value and evidence (Milestone 2.4), and the
# field is added to the profile's corrected_fields. An approved deal can't be
# corrected until it's reopened, and a reviewed deal goes back to draft.
@app.patch("/api/h9n/repe/deals/{deal_id}", response_model=DealOut)
def correct_repe_deal(
    deal_id: str,
    request: CorrectionRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> DealOut:
    deal = _load_deal(deal_id, user)
    _require_version(deal, request.version)
    with _deal_errors():
        changes = plan_corrections(deal, request.changes, actor=user.user_id)
    if changes is None:  # Every value was already what was asked for.
        return DealOut.from_record(deal)
    return DealOut.from_record(_deals(lambda deals: deals.save(deal, changes, expected_version=request.version)))


# Milestone 2.4: a review action on the deal as a whole - "review" (draft ->
# reviewed), "approve" (draft or reviewed -> approved, the trusted input for
# screening and underwriting), "reopen" (back to draft), or "reject" (stays
# or goes back to draft, with feedback). Separate from PATCH above:
# correcting a field doesn't by itself mean anyone has checked the profile.
#
# "reject" needs `feedback`: the reviewer's explanation of what's wrong. It's
# saved first, then handed to apply_reviewer_feedback() to re-derive the
# affected field(s) from the deal's source text. Milestone 1.1: Claude can
# only change deal value fields, and a corrected value is applied only if
# its citation verifies; otherwise it is added to withheld_values for the
# reviewer. If the correction step fails (provider down, unusable output),
# the response is a controlled 502/503 that says the rejection was saved.
@app.post("/api/h9n/repe/deals/{deal_id}/review", response_model=DealOut)
def review_repe_deal(
    deal_id: str,
    review: ReviewRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> DealOut:
    deal = _load_deal(deal_id, user)
    _require_version(deal, review.version)
    with _deal_errors():
        changes = plan_review_action(deal, review.action, actor=user.user_id, feedback=review.feedback)
    deal = _deals(lambda deals: deals.save(deal, changes, expected_version=review.version))

    feedback = deal.profile.review_feedback
    if review.action != "reject" or not deal.source_pages or not feedback:
        return DealOut.from_record(deal)

    try:
        result = apply_reviewer_feedback(deal.source_pages, deal.profile, feedback)
    except ExtractionError as exc:
        _raise_extraction_error(
            exc, prefix="The rejection and feedback were saved, but the automatic correction failed: "
        )

    # One save: the verified corrections, their new citations, and the
    # updated withheld list. {} when Claude found nothing it could correct -
    # the rejection then stands as submitted.
    updates = feedback_updates(deal.profile, result)
    if updates:
        with _deal_errors():
            corrections = plan_corrections(
                deal, updates, actor=user.user_id, source="reviewer_feedback", feedback=feedback
            )
        if corrections is not None:
            deal = _deals(lambda deals: deals.save(deal, corrections, expected_version=deal.version))
    return DealOut.from_record(deal)
