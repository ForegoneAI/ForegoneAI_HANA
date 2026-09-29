"""Automated tests for the FastAPI endpoints, using FastAPI's TestClient so
no real server, port, or running process is needed. The extraction call is
monkeypatched so this suite never needs an ANTHROPIC_API_KEY, and the review
store is pointed at a temp directory so tests never touch backend/data/."""

import io

import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.h9n.review.store import DealStore
from backend.app.h9n.schemas.repe_deal import REPEDealProfile


@pytest.fixture(autouse=True)
def _use_a_temp_review_store(tmp_path, monkeypatch):
    """Every test in this file gets its own empty, throwaway review store,
    instead of all sharing (and polluting) backend/data/reviews/."""
    monkeypatch.setattr(main, "_review_store", DealStore(tmp_path / "reviews"))


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


def test_extract_endpoint_returns_a_deal_profile_and_saves_it(monkeypatch):
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
    body = response.json()
    assert body["profile"]["deal_name"] == "Fixture Deal"
    assert body["profile"]["asking_price"] == 1_000_000
    # Milestone 1, item 4: the extracted deal should be fetchable again by
    # the id the extract endpoint just returned.
    deal_id = body["deal_id"]
    fetch_response = client.get(f"/api/h9n/repe/deals/{deal_id}")
    assert fetch_response.status_code == 200
    assert fetch_response.json()["deal_name"] == "Fixture Deal"


def test_get_deal_endpoint_404s_for_an_unknown_id():
    client = TestClient(main.app)
    response = client.get("/api/h9n/repe/deals/does-not-exist")

    assert response.status_code == 404


def test_patch_deal_endpoint_applies_a_correction_and_records_it(monkeypatch):
    def fake_extract_repe_deal(pages):
        return REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000)

    monkeypatch.setattr(main, "extract_repe_deal", fake_extract_repe_deal)

    client = TestClient(main.app)
    extract_response = client.post(
        "/api/h9n/repe/extract",
        files={
            "file": (
                "fixture.pdf",
                io.BytesIO(_make_pdf_bytes("Deal Name: Fixture Deal")),
                "application/pdf",
            )
        },
    )
    deal_id = extract_response.json()["deal_id"]

    patch_response = client.patch(
        f"/api/h9n/repe/deals/{deal_id}",
        json={"asking_price": 950_000},
    )

    assert patch_response.status_code == 200
    body = patch_response.json()
    assert body["asking_price"] == 950_000
    assert "asking_price" in body["corrected_fields"]

    # The correction should have actually been saved, not just returned.
    fetch_response = client.get(f"/api/h9n/repe/deals/{deal_id}")
    assert fetch_response.json()["asking_price"] == 950_000


def test_patch_deal_endpoint_404s_for_an_unknown_id():
    client = TestClient(main.app)
    response = client.patch(
        "/api/h9n/repe/deals/does-not-exist",
        json={"asking_price": 1},
    )

    assert response.status_code == 404


def test_patch_deal_endpoint_rejects_an_unknown_field(monkeypatch):
    def fake_extract_repe_deal(pages):
        return REPEDealProfile(deal_name="Fixture Deal")

    monkeypatch.setattr(main, "extract_repe_deal", fake_extract_repe_deal)

    client = TestClient(main.app)
    extract_response = client.post(
        "/api/h9n/repe/extract",
        files={
            "file": (
                "fixture.pdf",
                io.BytesIO(_make_pdf_bytes("Deal Name: Fixture Deal")),
                "application/pdf",
            )
        },
    )
    deal_id = extract_response.json()["deal_id"]

    response = client.patch(
        f"/api/h9n/repe/deals/{deal_id}",
        json={"not_a_real_field": 123},
    )

    assert response.status_code == 400


def test_extracted_deal_starts_pending_review(monkeypatch):
    def fake_extract_repe_deal(pages):
        return REPEDealProfile(deal_name="Fixture Deal")

    monkeypatch.setattr(main, "extract_repe_deal", fake_extract_repe_deal)

    client = TestClient(main.app)
    extract_response = client.post(
        "/api/h9n/repe/extract",
        files={
            "file": (
                "fixture.pdf",
                io.BytesIO(_make_pdf_bytes("Deal Name: Fixture Deal")),
                "application/pdf",
            )
        },
    )

    assert extract_response.json()["profile"]["review_status"] == "pending"


def test_review_endpoint_approves_a_deal(monkeypatch):
    def fake_extract_repe_deal(pages):
        return REPEDealProfile(deal_name="Fixture Deal")

    monkeypatch.setattr(main, "extract_repe_deal", fake_extract_repe_deal)

    client = TestClient(main.app)
    extract_response = client.post(
        "/api/h9n/repe/extract",
        files={
            "file": (
                "fixture.pdf",
                io.BytesIO(_make_pdf_bytes("Deal Name: Fixture Deal")),
                "application/pdf",
            )
        },
    )
    deal_id = extract_response.json()["deal_id"]

    review_response = client.post(
        f"/api/h9n/repe/deals/{deal_id}/review",
        json={"status": "approved"},
    )

    assert review_response.status_code == 200
    assert review_response.json()["review_status"] == "approved"

    # The verdict should have actually been saved, not just returned.
    fetch_response = client.get(f"/api/h9n/repe/deals/{deal_id}")
    assert fetch_response.json()["review_status"] == "approved"


def test_review_endpoint_can_reject_a_deal(monkeypatch):
    def fake_extract_repe_deal(pages):
        return REPEDealProfile(deal_name="Fixture Deal")

    monkeypatch.setattr(main, "extract_repe_deal", fake_extract_repe_deal)

    client = TestClient(main.app)
    extract_response = client.post(
        "/api/h9n/repe/extract",
        files={
            "file": (
                "fixture.pdf",
                io.BytesIO(_make_pdf_bytes("Deal Name: Fixture Deal")),
                "application/pdf",
            )
        },
    )
    deal_id = extract_response.json()["deal_id"]

    review_response = client.post(
        f"/api/h9n/repe/deals/{deal_id}/review",
        json={"status": "rejected"},
    )

    assert review_response.status_code == 200
    assert review_response.json()["review_status"] == "rejected"


def test_review_endpoint_rejected_with_feedback_applies_a_correction_and_reopens_for_review(
    monkeypatch,
):
    def fake_extract_repe_deal(pages):
        return REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000)

    def fake_apply_reviewer_feedback(pages, deal, feedback):
        assert deal.asking_price == 1_000_000
        assert "asking price" in feedback
        return {
            "corrections": {"asking_price": 950_000},
            "updated_evidence": [
                {
                    "field_name": "asking_price",
                    "value": "950000",
                    "source_document": "fixture.pdf",
                    "page_number": 4,
                    "snippet": "Asking Price: $950,000.",
                }
            ],
            "explanation": "The document actually states $950,000.",
        }

    monkeypatch.setattr(main, "extract_repe_deal", fake_extract_repe_deal)
    monkeypatch.setattr(main, "apply_reviewer_feedback", fake_apply_reviewer_feedback)

    client = TestClient(main.app)
    extract_response = client.post(
        "/api/h9n/repe/extract",
        files={
            "file": (
                "fixture.pdf",
                io.BytesIO(_make_pdf_bytes("Deal Name: Fixture Deal")),
                "application/pdf",
            )
        },
    )
    deal_id = extract_response.json()["deal_id"]

    review_response = client.post(
        f"/api/h9n/repe/deals/{deal_id}/review",
        json={"status": "rejected", "feedback": "the asking price is wrong"},
    )

    assert review_response.status_code == 200
    body = review_response.json()
    # Applied and recorded like any other correction (Milestone 1, item 4) -
    # but derived from the reviewer's feedback instead of them PATCH-ing the
    # exact value themselves.
    assert body["asking_price"] == 950_000
    assert "asking_price" in body["corrected_fields"]
    assert body["review_feedback"] == "the asking price is wrong"
    assert any(e["value"] == "950000" for e in body["evidence"])
    # Something changed automatically, so it needs another look rather than
    # sitting "rejected" as if the correction never happened.
    assert body["review_status"] == "pending"

    # And it was actually persisted, not just returned.
    fetch_response = client.get(f"/api/h9n/repe/deals/{deal_id}")
    assert fetch_response.json()["asking_price"] == 950_000
    assert fetch_response.json()["review_status"] == "pending"


def test_review_endpoint_rejected_with_feedback_but_no_derivable_fix_stays_rejected(monkeypatch):
    def fake_extract_repe_deal(pages):
        return REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000)

    def fake_apply_reviewer_feedback(pages, deal, feedback):
        # Claude looked, but couldn't confidently derive a corrected value.
        return {"corrections": {}, "updated_evidence": [], "explanation": "Not enough information."}

    monkeypatch.setattr(main, "extract_repe_deal", fake_extract_repe_deal)
    monkeypatch.setattr(main, "apply_reviewer_feedback", fake_apply_reviewer_feedback)

    client = TestClient(main.app)
    extract_response = client.post(
        "/api/h9n/repe/extract",
        files={
            "file": (
                "fixture.pdf",
                io.BytesIO(_make_pdf_bytes("Deal Name: Fixture Deal")),
                "application/pdf",
            )
        },
    )
    deal_id = extract_response.json()["deal_id"]

    review_response = client.post(
        f"/api/h9n/repe/deals/{deal_id}/review",
        json={"status": "rejected", "feedback": "something about this looks off"},
    )

    assert review_response.status_code == 200
    body = review_response.json()
    assert body["asking_price"] == 1_000_000
    assert body["corrected_fields"] == []
    assert body["review_feedback"] == "something about this looks off"
    # Nothing was auto-corrected, so the rejection stands as submitted.
    assert body["review_status"] == "rejected"


def test_review_endpoint_rejected_with_feedback_survives_a_correction_error(monkeypatch):
    def fake_extract_repe_deal(pages):
        return REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000)

    def fake_apply_reviewer_feedback(pages, deal, feedback):
        raise ValueError("Claude did not return a structured correction.")

    monkeypatch.setattr(main, "extract_repe_deal", fake_extract_repe_deal)
    monkeypatch.setattr(main, "apply_reviewer_feedback", fake_apply_reviewer_feedback)

    client = TestClient(main.app)
    extract_response = client.post(
        "/api/h9n/repe/extract",
        files={
            "file": (
                "fixture.pdf",
                io.BytesIO(_make_pdf_bytes("Deal Name: Fixture Deal")),
                "application/pdf",
            )
        },
    )
    deal_id = extract_response.json()["deal_id"]

    review_response = client.post(
        f"/api/h9n/repe/deals/{deal_id}/review",
        json={"status": "rejected", "feedback": "something about this looks off"},
    )

    # A correction failure shouldn't 500 the whole request - the rejection
    # and feedback are still recorded, just without an auto-applied fix.
    assert review_response.status_code == 200
    body = review_response.json()
    assert body["review_status"] == "rejected"
    assert body["review_feedback"] == "something about this looks off"


def test_review_endpoint_rejected_with_feedback_but_no_saved_pages_skips_correction(monkeypatch):
    # A deal saved without ever going through /extract (e.g. created some
    # other way) has no source text saved - there's nothing to re-derive a
    # fix from, so the correction step should be skipped entirely rather
    # than erroring.
    def fail_if_called(pages, deal, feedback):
        raise AssertionError("apply_reviewer_feedback should not be called with no saved pages")

    monkeypatch.setattr(main, "apply_reviewer_feedback", fail_if_called)

    deal_id = main._review_store.save(REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000))

    client = TestClient(main.app)
    review_response = client.post(
        f"/api/h9n/repe/deals/{deal_id}/review",
        json={"status": "rejected", "feedback": "the asking price is wrong"},
    )

    assert review_response.status_code == 200
    body = review_response.json()
    assert body["asking_price"] == 1_000_000
    assert body["review_feedback"] == "the asking price is wrong"
    assert body["review_status"] == "rejected"


def test_review_endpoint_rejected_without_feedback_does_not_call_the_extractor(monkeypatch):
    def fail_if_called(pages, deal, feedback):
        raise AssertionError("apply_reviewer_feedback should not be called without feedback")

    def fake_extract_repe_deal(pages):
        return REPEDealProfile(deal_name="Fixture Deal")

    monkeypatch.setattr(main, "extract_repe_deal", fake_extract_repe_deal)
    monkeypatch.setattr(main, "apply_reviewer_feedback", fail_if_called)

    client = TestClient(main.app)
    extract_response = client.post(
        "/api/h9n/repe/extract",
        files={
            "file": (
                "fixture.pdf",
                io.BytesIO(_make_pdf_bytes("Deal Name: Fixture Deal")),
                "application/pdf",
            )
        },
    )
    deal_id = extract_response.json()["deal_id"]

    review_response = client.post(
        f"/api/h9n/repe/deals/{deal_id}/review",
        json={"status": "rejected"},
    )

    assert review_response.status_code == 200
    assert review_response.json()["review_status"] == "rejected"
    assert review_response.json()["review_feedback"] is None


def test_review_endpoint_404s_for_an_unknown_id():
    client = TestClient(main.app)
    response = client.post(
        "/api/h9n/repe/deals/does-not-exist/review",
        json={"status": "approved"},
    )

    assert response.status_code == 404


def test_review_endpoint_rejects_pending_as_a_submitted_status():
    # "pending" is only ever the default a fresh extraction starts with -
    # FastAPI/pydantic should reject it before it ever reaches the store,
    # since ReviewRequest.status only allows "approved" or "rejected".
    client = TestClient(main.app)
    response = client.post(
        "/api/h9n/repe/deals/does-not-exist/review",
        json={"status": "pending"},
    )

    assert response.status_code == 422
