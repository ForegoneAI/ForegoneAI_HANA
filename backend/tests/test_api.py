"""Automated tests for the FastAPI endpoints, using FastAPI's TestClient so
no real server, port, or running process is needed. The extraction call is
monkeypatched so this suite never needs an ANTHROPIC_API_KEY, and the review
store is pointed at a temp directory so tests never touch backend/data/."""

import io

import anthropic
import httpx2
import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.h9n.extraction import repe_extractor
from backend.app.h9n.extraction.repe_extractor import (
    ExtractionConfigurationError,
    ExtractionInputError,
    ExtractionOutputError,
    ExtractionRefusedError,
    ExtractionUnavailableError,
)
from backend.app.h9n.review.store import DealStore
from backend.app.h9n.schemas.base_deal import WithheldValue
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.tests.extraction_fakes import evidence, fake_client, tool_response


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


def test_review_endpoint_reports_a_failed_correction_but_keeps_the_rejection(monkeypatch):
    # Milestone 1.1: a correction failure is a controlled error that says
    # what was saved - not a raw 500, and not a silent 200 that hides it.
    def fake_extract_repe_deal(pages):
        return REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000)

    def fake_apply_reviewer_feedback(pages, deal, feedback):
        raise ExtractionUnavailableError("The model provider could not be reached. Try again shortly.")

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

    assert review_response.status_code == 503
    assert "rejection and feedback were saved" in review_response.json()["detail"]
    saved = client.get(f"/api/h9n/repe/deals/{deal_id}").json()
    assert saved["review_status"] == "rejected"
    assert saved["review_feedback"] == "something about this looks off"


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


# --- Milestone 1.1: controlled errors from the extract endpoint ----------------


def _post_pdf(client, pdf_bytes):
    return client.post(
        "/api/h9n/repe/extract",
        files={"file": ("fixture.pdf", io.BytesIO(pdf_bytes), "application/pdf")},
    )


def test_extract_endpoint_rejects_a_file_that_is_not_really_a_pdf(monkeypatch):
    def fail_if_called(pages):
        raise AssertionError("the model should not be called for an unreadable file")

    monkeypatch.setattr(main, "extract_repe_deal", fail_if_called)

    response = _post_pdf(TestClient(main.app), b"not a pdf at all")

    assert response.status_code == 422
    assert "could not be read as a PDF" in response.json()["detail"]


def test_extract_endpoint_rejects_a_pdf_with_no_text(monkeypatch):
    def fail_if_called(pages):
        raise AssertionError("the model should not be called for a textless PDF")

    monkeypatch.setattr(main, "extract_repe_deal", fail_if_called)
    doc = pymupdf.open()
    doc.new_page()
    blank_pdf = doc.tobytes()
    doc.close()

    response = _post_pdf(TestClient(main.app), blank_pdf)

    assert response.status_code == 422
    assert "OCR" in response.json()["detail"]


@pytest.mark.parametrize(
    ("error", "status_code"),
    [
        (ExtractionInputError("The document is too long."), 422),
        (ExtractionOutputError("The model's output was cut off."), 502),
        (ExtractionRefusedError("The model declined."), 502),
        (ExtractionUnavailableError("The model provider timed out."), 503),
        (ExtractionConfigurationError("No Claude credentials are configured."), 503),
        (ValueError("raw model text that must not leak"), 502),
        (RuntimeError("internal detail that must not leak"), 500),
    ],
)
def test_extract_endpoint_turns_every_failure_into_a_controlled_error(monkeypatch, error, status_code):
    def failing_extract(pages):
        raise error

    monkeypatch.setattr(main, "extract_repe_deal", failing_extract)

    response = _post_pdf(TestClient(main.app), _make_pdf_bytes("Deal Name: Fixture Deal"))

    assert response.status_code == status_code
    assert "must not leak" not in response.text
    assert main._review_store.list_ids() == []


def test_extract_endpoint_hides_configuration_details_from_the_caller(monkeypatch):
    def failing_extract(pages):
        raise ExtractionConfigurationError("The extraction model 'secret-model' was not found.")

    monkeypatch.setattr(main, "extract_repe_deal", failing_extract)

    response = _post_pdf(TestClient(main.app), _make_pdf_bytes("Deal Name: Fixture Deal"))

    assert response.status_code == 503
    assert "secret-model" not in response.text


def test_extract_endpoint_returns_and_saves_withheld_values(monkeypatch):
    def fake_extract_repe_deal(pages):
        return REPEDealProfile(
            deal_name="Fixture Deal",
            withheld_values=[
                WithheldValue(
                    field_name="asking_price",
                    proposed_value=1_000_000,
                    reason="no_evidence",
                    detail="The model gave this value without citing where it came from.",
                )
            ],
        )

    monkeypatch.setattr(main, "extract_repe_deal", fake_extract_repe_deal)
    client = TestClient(main.app)

    body = _post_pdf(client, _make_pdf_bytes("Deal Name: Fixture Deal")).json()

    assert body["profile"]["asking_price"] is None
    assert body["profile"]["withheld_values"][0]["proposed_value"] == 1_000_000
    saved = client.get(f"/api/h9n/repe/deals/{body['deal_id']}").json()
    assert saved["withheld_values"][0]["reason"] == "no_evidence"


def test_extract_endpoint_rejects_an_upload_without_a_filename(monkeypatch):
    def fail_if_called(pages):
        raise AssertionError("a nameless upload should never reach extraction")

    monkeypatch.setattr(main, "extract_repe_deal", fail_if_called)

    response = TestClient(main.app).post(
        "/api/h9n/repe/extract",
        files={"file": ("", io.BytesIO(_make_pdf_bytes("Deal Name: Fixture Deal")), "application/pdf")},
    )

    # FastAPI treats a nameless upload as a missing file - a clean 422, not a
    # crash on file.filename being None.
    assert response.status_code == 422
    assert main._review_store.list_ids() == []


def test_extract_endpoint_rejects_an_oversized_upload_without_reading_it_all(monkeypatch):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1_000)
    monkeypatch.setattr(main, "extract_repe_deal", lambda pages: pytest.fail("should not extract"))

    response = _post_pdf(TestClient(main.app), b"%PDF-1.7" + b"0" * 5_000)

    assert response.status_code == 413
    assert main._review_store.list_ids() == []


def test_an_unexpected_extraction_failure_is_logged(monkeypatch, caplog):
    def broken(pages):
        raise ValueError("bug inside enforce_integrity")

    monkeypatch.setattr(main, "extract_repe_deal", broken)

    response = _post_pdf(TestClient(main.app), _make_pdf_bytes("Deal Name: Fixture Deal"))

    assert response.status_code == 502
    assert "bug inside enforce_integrity" not in response.text
    assert "bug inside enforce_integrity" in caplog.text


# --- Milestone 1.1: the reviewer-feedback path, with the real feedback code ----

_FEEDBACK_PAGES = [{"file_name": "fixture.pdf", "page_number": 1, "text": "Asking Price: $950,000\nNOI: $65,000"}]


def _saved_deal_for_feedback() -> str:
    deal = REPEDealProfile(
        deal_name="Fixture Deal",
        asking_price=1_000_000,
        withheld_values=[WithheldValue(field_name="noi", proposed_value=60_000, reason="model_uncertain", detail="x")],
    )
    deal_id = main._review_store.save(deal)
    main._review_store.save_pages(deal_id, _FEEDBACK_PAGES)
    return deal_id


def _claude_answers(monkeypatch, *responses, error=None):
    """Runs the real apply_reviewer_feedback() against a fake Claude."""
    client = fake_client(*responses, error=error)
    monkeypatch.setattr(
        main,
        "apply_reviewer_feedback",
        lambda pages, deal, feedback: repe_extractor.apply_reviewer_feedback(pages, deal, feedback, client=client),
    )


def _reject(deal_id):
    return TestClient(main.app, raise_server_exceptions=False).post(
        f"/api/h9n/repe/deals/{deal_id}/review", json={"status": "rejected", "feedback": "the price is wrong"}
    )


def _correction(corrections, updated_evidence=()):
    return tool_response({"corrections": corrections, "updated_evidence": list(updated_evidence), "explanation": "x"})


def test_a_verified_feedback_correction_is_applied(monkeypatch):
    citation = evidence("asking_price", 950_000, "Asking Price: $950,000")
    _claude_answers(monkeypatch, _correction({"asking_price": 950_000}, [citation]))
    deal_id = _saved_deal_for_feedback()

    body = _reject(deal_id).json()

    assert body["asking_price"] == 950_000
    assert body["evidence"][0]["snippet"] == "Asking Price: $950,000"
    assert body["corrected_fields"] == ["asking_price"]
    assert body["review_status"] == "pending"


def test_an_uncited_feedback_correction_is_withheld_not_applied(monkeypatch):
    _claude_answers(monkeypatch, _correction({"asking_price": 99_999_999}))
    deal_id = _saved_deal_for_feedback()

    body = _reject(deal_id).json()

    assert body["asking_price"] == 1_000_000
    assert body["corrected_fields"] == []
    assert [(w["field_name"], w["reason"]) for w in body["withheld_values"]] == [
        ("noi", "model_uncertain"),
        ("asking_price", "no_evidence"),
    ]
    assert body["review_status"] == "pending"


@pytest.mark.parametrize(
    "corrections",
    [
        pytest.param({"asking_price": "about ten million"}, id="malformed value"),
        pytest.param({"withheld_values": [], "evidence": []}, id="erase the review queue"),
    ],
)
def test_a_bad_feedback_correction_is_a_controlled_error_and_changes_nothing(monkeypatch, corrections):
    _claude_answers(monkeypatch, _correction(corrections), _correction(corrections))
    deal_id = _saved_deal_for_feedback()

    response = _reject(deal_id)

    assert response.status_code == 502
    assert "rejection and feedback were saved" in response.json()["detail"]
    saved = main._review_store.get(deal_id)
    assert saved.asking_price == 1_000_000
    assert [w.field_name for w in saved.withheld_values] == ["noi"]
    assert saved.review_status == "rejected"


def test_a_provider_outage_during_feedback_is_a_controlled_error(monkeypatch):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    _claude_answers(monkeypatch, error=anthropic.APIConnectionError(request=request))
    deal_id = _saved_deal_for_feedback()

    response = _reject(deal_id)

    assert response.status_code == 503
    assert main._review_store.get(deal_id).review_status == "rejected"
