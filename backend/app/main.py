import tempfile
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import Body, FastAPI, HTTPException, UploadFile
from pydantic import BaseModel

from backend.app.h9n.extraction.repe_extractor import (
    apply_reviewer_feedback,
    extract_repe_deal,
    merge_evidence,
)
from backend.app.h9n.ingestion.pdf_reader import read_pdf
from backend.app.h9n.review.store import DealNotFoundError, DealStore
from backend.app.h9n.schemas.repe_deal import REPEDealProfile


# Creates the main FastAPI application for HANA
app = FastAPI()

# Milestone 1, item 4: where extracted deals are saved so a reviewer can
# fetch and correct one later by id. See store.py for why this is a simple
# on-disk store rather than a real database.
_review_store = DealStore()


# What POST /extract returns: the extracted profile plus the id it was
# saved under, so the caller can look it up again later for review.
class ExtractResponse(BaseModel):
    deal_id: str
    profile: REPEDealProfile


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
@app.post("/api/h9n/repe/extract", response_model=ExtractResponse)
def extract_repe_deal_from_upload(file: UploadFile) -> ExtractResponse:
    if file.content_type not in ("application/pdf", None) and not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF deal packages are supported right now.")

    # read_pdf() takes a file path, so the upload is written to a temp file
    # (auto-deleted once the request finishes) rather than re-implementing
    # PDF parsing from an in-memory stream.
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(file.file.read())
        tmp.flush()

        pages = read_pdf(tmp.name)
        if not pages:
            raise HTTPException(status_code=422, detail="No text could be extracted from the uploaded PDF.")

        # The temp file's name is meaningless to the reviewer, so the
        # original uploaded filename is swapped back in for provenance.
        for page in pages:
            page["file_name"] = Path(file.filename).name

    try:
        deal = extract_repe_deal(pages)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    deal_id = _review_store.save(deal)
    # So a reviewer's future rejection feedback has something to re-derive
    # a correction from (see the review endpoint below) - without this, a
    # correction could only ever be the exact value a human already worked
    # out, never one Claude re-derives from the source text.
    _review_store.save_pages(deal_id, pages)
    return ExtractResponse(deal_id=deal_id, profile=deal)


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