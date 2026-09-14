import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile

from Step_1.app.h9n.extraction.repe_extractor import extract_repe_deal
from Step_1.app.h9n.ingestion.pdf_reader import read_pdf
from Step_1.app.h9n.schemas.repe_deal import REPEDealProfile


# Creates the main FastAPI application for HANA
app = FastAPI()


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
# REPEDealProfile - no manual data entry.
@app.post("/api/h9n/repe/extract", response_model=REPEDealProfile)
def extract_repe_deal_from_upload(file: UploadFile) -> REPEDealProfile:
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

    return deal