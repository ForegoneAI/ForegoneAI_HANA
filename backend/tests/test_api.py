"""Automated tests for the FastAPI endpoints, using FastAPI's TestClient so
no real server, port, or running process is needed. The extraction call is
monkeypatched so this suite never needs an ANTHROPIC_API_KEY."""

import io

import pymupdf
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.h9n.schemas.repe_deal import REPEDealProfile


def _make_pdf_bytes(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def test_root_endpoint_reports_the_backend_is_running():
    client = TestClient(main.app)
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {"message": "HANA Active"}


def test_extract_endpoint_rejects_non_pdf_uploads():
    client = TestClient(main.app)
    response = client.post(
        "/api/h9n/repe/extract",
        files={"file": ("notes.txt", io.BytesIO(b"not a pdf"), "text/plain")},
    )

    assert response.status_code == 400


def test_extract_endpoint_returns_a_deal_profile(monkeypatch):
    def fake_extract_repe_deal(pages):
        assert pages[0]["file_name"] == "fixture.pdf"
        return REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000)

    monkeypatch.setattr(main, "extract_repe_deal", fake_extract_repe_deal)

    client = TestClient(main.app)
    response = client.post(
        "/api/h9n/repe/extract",
        files={
            "file": (
                "fixture.pdf",
                io.BytesIO(_make_pdf_bytes("Deal Name: Fixture Deal")),
                "application/pdf",
            )
        },
    )

    assert response.status_code == 200
    assert response.json()["deal_name"] == "Fixture Deal"
    assert response.json()["asking_price"] == 1_000_000
