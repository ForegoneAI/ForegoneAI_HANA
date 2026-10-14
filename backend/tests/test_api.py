"""Automated tests for the FastAPI endpoints, using FastAPI's TestClient so
no real server, port, or running process is needed. The extraction call is
monkeypatched so this suite never needs an ANTHROPIC_API_KEY, and saved deals
live in memory (conftest.py's deal_repository) so tests never need Supabase."""

import io
from uuid import uuid4

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
from backend.app.h9n.review.models import NewDeal
from backend.app.h9n.schemas.base_deal import WithheldValue
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.tests.auth_fakes import TEST_ORGANIZATION_ID, TEST_USER
from backend.tests.extraction_fakes import evidence, fake_client, tool_response


def _make_pdf_bytes(text: str) -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def _extract(monkeypatch, client, profile: REPEDealProfile) -> dict:
    """Uploads a PDF whose extraction returns `profile`; returns the response."""
    monkeypatch.setattr(main, "extract_repe_deal", lambda pages: profile)
    response = client.post(
        "/api/h9n/repe/extract",
        files={"file": ("fixture.pdf", io.BytesIO(_make_pdf_bytes("Deal Name: Fixture Deal")), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _save_deal(deal_repository, profile: REPEDealProfile, *, pages=None) -> str:
    """Saves a deal straight into the repository, as /extract would."""
    record = deal_repository.create(
        NewDeal(
            id=uuid4(),
            organization_id=TEST_ORGANIZATION_ID,
            profile=profile,
            source_filename="fixture.pdf",
            source_pages=pages,
            created_by=TEST_USER.user_id,
        )
    )
    return str(record.id)


def _review(client, deal_id, action, version, feedback=None):
    body = {"action": action, "version": version}
    if feedback is not None:
        body["feedback"] = feedback
    return client.post(f"/api/h9n/repe/deals/{deal_id}/review", json=body)


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


def test_extract_endpoint_returns_a_deal_profile_and_saves_it(monkeypatch, run_repository, deal_repository):
    def fake_extract_repe_deal(pages):
        assert pages[0]["file_name"] == "fixture.pdf"
        return REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000)

    monkeypatch.setattr(main, "extract_repe_deal", fake_extract_repe_deal)
    client = TestClient(main.app)

    body = client.post(
        "/api/h9n/repe/extract",
        files={"file": ("fixture.pdf", io.BytesIO(_make_pdf_bytes("Deal Name: Fixture Deal")), "application/pdf")},
    ).json()

    assert body["profile"]["deal_name"] == "Fixture Deal"
    assert body["profile"]["asking_price"] == 1_000_000
    # Saved as a draft at version 1, linked to its run, uploader, and pages.
    fetched = client.get(f"/api/h9n/repe/deals/{body['deal_id']}").json()
    assert fetched["status"] == "draft"
    assert fetched["version"] == 1
    assert fetched["profile"]["deal_name"] == "Fixture Deal"
    assert fetched["profile"]["review_status"] == "draft"
    assert fetched["organization_id"] == str(TEST_ORGANIZATION_ID)
    assert fetched["created_by"] == str(TEST_USER.user_id)
    assert fetched["extraction_run_id"] == str(run_repository.run_id)
    assert fetched["source_filename"] == "fixture.pdf"
    # The page text stays server-side, for feedback corrections.
    assert "source_pages" not in fetched
    saved = next(iter(deal_repository.deals.values()))
    assert saved.source_pages[0]["text"].startswith("Deal Name: Fixture Deal")
    # The run records the same deal id.
    assert str(run_repository.runs[0].deal_id) == body["deal_id"]


def test_a_deal_that_cannot_be_saved_is_a_controlled_error(monkeypatch, deal_repository):
    def broken_create(deal):
        raise RuntimeError("connection string with a password")

    monkeypatch.setattr(deal_repository, "create", broken_create)
    monkeypatch.setattr(main, "extract_repe_deal", lambda pages: REPEDealProfile(deal_name="Fixture Deal"))

    response = TestClient(main.app).post(
        "/api/h9n/repe/extract",
        files={"file": ("fixture.pdf", io.BytesIO(_make_pdf_bytes("Deal Name: Fixture Deal")), "application/pdf")},
    )

    assert response.status_code == 502
    assert "password" not in response.text


@pytest.mark.parametrize("deal_id", ["does-not-exist", str(uuid4())])
def test_get_deal_endpoint_404s_for_an_unknown_id(deal_id):
    assert TestClient(main.app).get(f"/api/h9n/repe/deals/{deal_id}").status_code == 404


# --- Milestone 2.4: corrections ----------------------------------------------


def test_a_correction_is_applied_saved_and_recorded(monkeypatch):
    client = TestClient(main.app)
    deal_id = _extract(monkeypatch, client, REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000))["deal_id"]

    response = client.patch(f"/api/h9n/repe/deals/{deal_id}", json={"version": 1, "changes": {"asking_price": 950_000}})

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 2
    assert body["profile"]["asking_price"] == 950_000
    assert body["profile"]["corrected_fields"] == ["asking_price"]
    assert client.get(f"/api/h9n/repe/deals/{deal_id}").json()["profile"]["asking_price"] == 950_000

    history = client.get(f"/api/h9n/repe/deals/{deal_id}/history").json()
    [correction] = history["corrections"]
    assert correction["field_name"] == "asking_price"
    assert correction["original_value"] == 1_000_000
    assert correction["corrected_value"] == 950_000
    assert correction["source"] == "reviewer"
    assert correction["corrected_by"] == str(TEST_USER.user_id)
    assert correction["deal_version"] == 2
    assert correction["created_at"]


def test_a_correction_keeps_the_evidence_the_original_value_had(deal_repository):
    cited = REPEDealProfile(asking_price=1_000_000, evidence=[evidence("asking_price", 1_000_000, "Price: $1,000,000")])
    deal_id = _save_deal(deal_repository, cited)
    client = TestClient(main.app)

    client.patch(f"/api/h9n/repe/deals/{deal_id}", json={"version": 1, "changes": {"asking_price": 950_000}})

    [correction] = client.get(f"/api/h9n/repe/deals/{deal_id}/history").json()["corrections"]
    assert correction["evidence"]["snippet"] == "Price: $1,000,000"


def test_corrections_are_never_overwritten_by_a_stale_copy(deal_repository):
    deal_id = _save_deal(deal_repository, REPEDealProfile(asking_price=1_000_000))
    client = TestClient(main.app)
    # Two reviewers open version 1; the first saves.
    assert client.patch(f"/api/h9n/repe/deals/{deal_id}", json={"version": 1, "changes": {"asking_price": 950_000}}).status_code == 200

    stale = client.patch(f"/api/h9n/repe/deals/{deal_id}", json={"version": 1, "changes": {"asking_price": 900_000}})

    assert stale.status_code == 409
    assert "Reload" in stale.json()["detail"]
    assert client.get(f"/api/h9n/repe/deals/{deal_id}").json()["profile"]["asking_price"] == 950_000


def test_a_conflict_found_only_when_saving_is_still_a_409(monkeypatch, deal_repository):
    # Another save lands between reading the deal and saving the change.
    deal_id = _save_deal(deal_repository, REPEDealProfile(asking_price=1_000_000))
    real_get = deal_repository.get

    def get_then_someone_else_saves(deal_id, organization_ids):
        deal = real_get(deal_id, organization_ids)
        stored = deal_repository.deals[deal.id]
        deal_repository.deals[deal.id] = stored.model_copy(update={"version": stored.version + 1})
        return deal

    monkeypatch.setattr(deal_repository, "get", get_then_someone_else_saves)

    response = TestClient(main.app).patch(
        f"/api/h9n/repe/deals/{deal_id}", json={"version": 1, "changes": {"asking_price": 900_000}}
    )

    assert response.status_code == 409


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"not_a_real_field": 123}, "not a field"),
        ({"asking_price": "about a million"}, "asking_price"),
        ({"review_status": "approved"}, "can't be changed directly"),
        ({"corrected_fields": []}, "can't be changed directly"),
        ({"evidence": []}, "can't be changed directly"),
        ({}, "at least one field"),
    ],
)
def test_an_invalid_correction_is_a_400_and_changes_nothing(deal_repository, changes, message):
    deal_id = _save_deal(deal_repository, REPEDealProfile(asking_price=1_000_000))
    client = TestClient(main.app)

    response = client.patch(f"/api/h9n/repe/deals/{deal_id}", json={"version": 1, "changes": changes})

    assert response.status_code == 400
    assert message in response.json()["detail"]
    saved = client.get(f"/api/h9n/repe/deals/{deal_id}").json()
    assert saved["version"] == 1
    assert saved["status"] == "draft"


def test_a_correction_that_changes_nothing_is_not_recorded(deal_repository):
    deal_id = _save_deal(deal_repository, REPEDealProfile(asking_price=1_000_000))
    client = TestClient(main.app)

    response = client.patch(f"/api/h9n/repe/deals/{deal_id}", json={"version": 1, "changes": {"asking_price": 1_000_000}})

    assert response.json()["version"] == 1
    assert client.get(f"/api/h9n/repe/deals/{deal_id}/history").json()["corrections"] == []


def test_a_reviewer_can_dismiss_a_withheld_value(deal_repository):
    withheld = WithheldValue(field_name="noi", proposed_value=60_000, reason="model_uncertain", detail="x")
    deal_id = _save_deal(deal_repository, REPEDealProfile(withheld_values=[withheld]))
    client = TestClient(main.app)

    body = client.patch(f"/api/h9n/repe/deals/{deal_id}", json={"version": 1, "changes": {"withheld_values": []}}).json()

    assert body["profile"]["withheld_values"] == []
    # Recorded, but not counted as correcting a deal value.
    assert body["profile"]["corrected_fields"] == []
    [correction] = client.get(f"/api/h9n/repe/deals/{deal_id}/history").json()["corrections"]
    assert correction["field_name"] == "withheld_values"


def test_patch_deal_endpoint_404s_for_an_unknown_id():
    response = TestClient(main.app).patch(
        f"/api/h9n/repe/deals/{uuid4()}", json={"version": 1, "changes": {"asking_price": 1}}
    )

    assert response.status_code == 404


# --- Milestone 2.4: review actions -------------------------------------------


def test_a_deal_moves_from_draft_to_reviewed_to_approved(deal_repository):
    deal_id = _save_deal(deal_repository, REPEDealProfile(deal_name="Fixture Deal"))
    client = TestClient(main.app)

    reviewed = _review(client, deal_id, "review", 1)
    approved = _review(client, deal_id, "approve", 2)

    assert reviewed.status_code == 200 and reviewed.json()["status"] == "reviewed"
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    saved = client.get(f"/api/h9n/repe/deals/{deal_id}").json()
    assert (saved["status"], saved["version"], saved["profile"]["review_status"]) == ("approved", 3, "approved")

    changes = client.get(f"/api/h9n/repe/deals/{deal_id}/history").json()["status_changes"]
    assert [(c["action"], c["from_status"], c["to_status"], c["deal_version"]) for c in changes] == [
        ("review", "draft", "reviewed", 2),
        ("approve", "reviewed", "approved", 3),
    ]
    assert all(c["changed_by"] == str(TEST_USER.user_id) for c in changes)


def test_a_draft_can_be_approved_directly(deal_repository):
    deal_id = _save_deal(deal_repository, REPEDealProfile(deal_name="Fixture Deal"))

    assert _review(TestClient(main.app), deal_id, "approve", 1).json()["status"] == "approved"


def test_an_approved_deal_is_locked_until_reopened(deal_repository):
    deal_id = _save_deal(deal_repository, REPEDealProfile(asking_price=1_000_000))
    client = TestClient(main.app)
    _review(client, deal_id, "approve", 1)

    locked = client.patch(f"/api/h9n/repe/deals/{deal_id}", json={"version": 2, "changes": {"asking_price": 1}})
    assert locked.status_code == 409
    assert "Reopen" in locked.json()["detail"]

    reopened = _review(client, deal_id, "reopen", 2)
    assert reopened.json()["status"] == "draft"
    edited = client.patch(f"/api/h9n/repe/deals/{deal_id}", json={"version": 3, "changes": {"asking_price": 1}})
    assert edited.status_code == 200


def test_correcting_a_reviewed_deal_sends_it_back_to_draft(deal_repository):
    deal_id = _save_deal(deal_repository, REPEDealProfile(asking_price=1_000_000))
    client = TestClient(main.app)
    _review(client, deal_id, "review", 1)

    body = client.patch(f"/api/h9n/repe/deals/{deal_id}", json={"version": 2, "changes": {"asking_price": 1}}).json()

    assert body["status"] == "draft"
    last = client.get(f"/api/h9n/repe/deals/{deal_id}/history").json()["status_changes"][-1]
    assert (last["action"], last["from_status"], last["to_status"]) == ("edit", "reviewed", "draft")


@pytest.mark.parametrize(
    "actions, then, message",
    [
        ([], "reopen", "already a draft"),
        (["review"], "review", "already marked reviewed"),
        (["approve"], "approve", "already approved"),
        (["approve"], "review", "Reopen it"),
    ],
)
def test_a_review_action_that_does_not_apply_is_a_409(deal_repository, actions, then, message):
    deal_id = _save_deal(deal_repository, REPEDealProfile(deal_name="Fixture Deal"))
    client = TestClient(main.app)
    for version, action in enumerate(actions, start=1):
        _review(client, deal_id, action, version)

    response = _review(client, deal_id, then, len(actions) + 1)

    assert response.status_code == 409
    assert message in response.json()["detail"]


def test_a_review_action_on_a_stale_copy_is_a_409(deal_repository):
    deal_id = _save_deal(deal_repository, REPEDealProfile(deal_name="Fixture Deal"))
    client = TestClient(main.app)
    _review(client, deal_id, "review", 1)

    assert _review(client, deal_id, "approve", 1).status_code == 409


def test_an_unknown_review_action_is_a_422():
    response = _review(TestClient(main.app), uuid4(), "pending", 1)

    assert response.status_code == 422


def test_review_endpoint_404s_for_an_unknown_id():
    assert _review(TestClient(main.app), uuid4(), "approve", 1).status_code == 404


def test_reject_needs_feedback(deal_repository):
    deal_id = _save_deal(deal_repository, REPEDealProfile(deal_name="Fixture Deal"))

    response = _review(TestClient(main.app), deal_id, "reject", 1, feedback="   ")

    assert response.status_code == 400
    assert "what's wrong" in response.json()["detail"]


def test_reject_with_feedback_applies_a_correction_and_leaves_the_deal_in_draft(monkeypatch):
    def fake_apply_reviewer_feedback(pages, deal, feedback):
        assert pages[0]["file_name"] == "fixture.pdf"
        assert deal.asking_price == 1_000_000
        assert feedback == "the asking price is wrong"
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

    client = TestClient(main.app)
    deal_id = _extract(monkeypatch, client, REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000))["deal_id"]
    _review(client, deal_id, "review", 1)
    monkeypatch.setattr(main, "apply_reviewer_feedback", fake_apply_reviewer_feedback)

    response = _review(client, deal_id, "reject", 2, feedback="  the asking price is wrong ")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft"
    assert body["version"] == 4  # the rejection, then the correction
    assert body["profile"]["asking_price"] == 950_000
    assert body["profile"]["corrected_fields"] == ["asking_price"]
    assert body["profile"]["review_feedback"] == "the asking price is wrong"
    assert any(e["value"] == "950000" for e in body["profile"]["evidence"])

    history = client.get(f"/api/h9n/repe/deals/{deal_id}/history").json()
    assert [(c["action"], c["to_status"], c["note"]) for c in history["status_changes"]][-1] == (
        "reject",
        "draft",
        "the asking price is wrong",
    )
    price = next(c for c in history["corrections"] if c["field_name"] == "asking_price")
    assert (price["source"], price["feedback"], price["original_value"]) == (
        "reviewer_feedback",
        "the asking price is wrong",
        1_000_000,
    )


def test_reject_with_feedback_but_no_derivable_fix_keeps_the_rejection(monkeypatch):
    client = TestClient(main.app)
    deal_id = _extract(monkeypatch, client, REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000))["deal_id"]
    monkeypatch.setattr(
        main,
        "apply_reviewer_feedback",
        lambda pages, deal, feedback: {"corrections": {}, "updated_evidence": [], "explanation": "Not enough information."},
    )

    body = _review(client, deal_id, "reject", 1, feedback="something about this looks off").json()

    assert body["version"] == 2
    assert body["profile"]["asking_price"] == 1_000_000
    assert body["profile"]["corrected_fields"] == []
    assert body["profile"]["review_feedback"] == "something about this looks off"


def test_a_failed_feedback_correction_is_reported_but_the_rejection_is_kept(monkeypatch):
    # Milestone 1.1: a correction failure is a controlled error that says
    # what was saved - not a raw 500, and not a silent 200 that hides it.
    def unavailable(pages, deal, feedback):
        raise ExtractionUnavailableError("The model provider could not be reached. Try again shortly.")

    client = TestClient(main.app)
    deal_id = _extract(monkeypatch, client, REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000))["deal_id"]
    monkeypatch.setattr(main, "apply_reviewer_feedback", unavailable)

    response = _review(client, deal_id, "reject", 1, feedback="something about this looks off")

    assert response.status_code == 503
    assert "rejection and feedback were saved" in response.json()["detail"]
    saved = client.get(f"/api/h9n/repe/deals/{deal_id}").json()
    assert saved["version"] == 2
    assert saved["profile"]["review_feedback"] == "something about this looks off"


def test_reject_without_saved_pages_skips_the_correction(monkeypatch, deal_repository):
    # A deal with no saved source text has nothing to re-derive a fix from.
    def fail_if_called(pages, deal, feedback):
        raise AssertionError("apply_reviewer_feedback should not be called with no saved pages")

    monkeypatch.setattr(main, "apply_reviewer_feedback", fail_if_called)
    deal_id = _save_deal(deal_repository, REPEDealProfile(deal_name="Fixture Deal", asking_price=1_000_000))

    body = _review(TestClient(main.app), deal_id, "reject", 1, feedback="the asking price is wrong").json()

    assert body["profile"]["asking_price"] == 1_000_000
    assert body["profile"]["review_feedback"] == "the asking price is wrong"


@pytest.mark.parametrize("action", ["review", "approve"])
def test_other_review_actions_never_call_the_extractor(monkeypatch, deal_repository, action):
    def fail_if_called(pages, deal, feedback):
        raise AssertionError("apply_reviewer_feedback should only run for a rejection")

    monkeypatch.setattr(main, "apply_reviewer_feedback", fail_if_called)
    deal_id = _save_deal(deal_repository, REPEDealProfile(deal_name="Fixture Deal"), pages=[{"text": "x"}])

    assert _review(TestClient(main.app), deal_id, action, 1, feedback="ignored").status_code == 200


def test_deal_storage_failures_are_controlled_errors(monkeypatch, deal_repository):
    def broken_get(deal_id, organization_ids):
        raise RuntimeError("database detail that must not leak")

    monkeypatch.setattr(deal_repository, "get", broken_get)

    response = TestClient(main.app).get(f"/api/h9n/repe/deals/{uuid4()}")

    assert response.status_code == 502
    assert "must not leak" not in response.text


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
def test_extract_endpoint_turns_every_failure_into_a_controlled_error(monkeypatch, deal_repository, error, status_code):
    def failing_extract(pages):
        raise error

    monkeypatch.setattr(main, "extract_repe_deal", failing_extract)

    response = _post_pdf(TestClient(main.app), _make_pdf_bytes("Deal Name: Fixture Deal"))

    assert response.status_code == status_code
    assert "must not leak" not in response.text
    assert deal_repository.deals == {}


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
    assert saved["profile"]["withheld_values"][0]["reason"] == "no_evidence"


def test_extract_endpoint_rejects_an_upload_without_a_filename(monkeypatch, deal_repository):
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
    assert deal_repository.deals == {}


def test_extract_endpoint_rejects_an_oversized_upload_without_reading_it_all(monkeypatch, deal_repository):
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 1_000)
    monkeypatch.setattr(main, "extract_repe_deal", lambda pages: pytest.fail("should not extract"))

    response = _post_pdf(TestClient(main.app), b"%PDF-1.7" + b"0" * 5_000)

    assert response.status_code == 413
    assert deal_repository.deals == {}


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


def _saved_deal_for_feedback(deal_repository) -> str:
    deal = REPEDealProfile(
        deal_name="Fixture Deal",
        asking_price=1_000_000,
        withheld_values=[WithheldValue(field_name="noi", proposed_value=60_000, reason="model_uncertain", detail="x")],
    )
    return _save_deal(deal_repository, deal, pages=_FEEDBACK_PAGES)


def _claude_answers(monkeypatch, *responses, error=None):
    """Runs the real apply_reviewer_feedback() against a fake Claude."""
    client = fake_client(*responses, error=error)
    monkeypatch.setattr(
        main,
        "apply_reviewer_feedback",
        lambda pages, deal, feedback: repe_extractor.apply_reviewer_feedback(pages, deal, feedback, client=client),
    )


def _reject(deal_id):
    return _review(TestClient(main.app, raise_server_exceptions=False), deal_id, "reject", 1, "the price is wrong")


def _correction(corrections, updated_evidence=()):
    return tool_response({"corrections": corrections, "updated_evidence": list(updated_evidence), "explanation": "x"})


def test_a_verified_feedback_correction_is_applied(monkeypatch, deal_repository):
    citation = evidence("asking_price", 950_000, "Asking Price: $950,000")
    _claude_answers(monkeypatch, _correction({"asking_price": 950_000}, [citation]))
    deal_id = _saved_deal_for_feedback(deal_repository)

    body = _reject(deal_id).json()

    assert body["profile"]["asking_price"] == 950_000
    assert body["profile"]["evidence"][0]["snippet"] == "Asking Price: $950,000"
    assert body["profile"]["corrected_fields"] == ["asking_price"]
    assert body["status"] == "draft"


def test_an_uncited_feedback_correction_is_withheld_not_applied(monkeypatch, deal_repository):
    _claude_answers(monkeypatch, _correction({"asking_price": 99_999_999}))
    deal_id = _saved_deal_for_feedback(deal_repository)

    body = _reject(deal_id).json()

    assert body["profile"]["asking_price"] == 1_000_000
    assert body["profile"]["corrected_fields"] == []
    assert [(w["field_name"], w["reason"]) for w in body["profile"]["withheld_values"]] == [
        ("noi", "model_uncertain"),
        ("asking_price", "no_evidence"),
    ]
    assert body["status"] == "draft"


@pytest.mark.parametrize(
    "corrections",
    [
        pytest.param({"asking_price": "about ten million"}, id="malformed value"),
        pytest.param({"withheld_values": [], "evidence": []}, id="erase the review queue"),
    ],
)
def test_a_bad_feedback_correction_is_a_controlled_error_and_changes_nothing(monkeypatch, deal_repository, corrections):
    _claude_answers(monkeypatch, _correction(corrections), _correction(corrections))
    deal_id = _saved_deal_for_feedback(deal_repository)

    response = _reject(deal_id)

    assert response.status_code == 502
    assert "rejection and feedback were saved" in response.json()["detail"]
    saved = next(iter(deal_repository.deals.values()))
    assert saved.profile.asking_price == 1_000_000
    assert [w.field_name for w in saved.profile.withheld_values] == ["noi"]
    assert saved.profile.review_feedback == "the price is wrong"
    assert saved.version == 2


def test_a_provider_outage_during_feedback_is_a_controlled_error(monkeypatch, deal_repository):
    request = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
    _claude_answers(monkeypatch, error=anthropic.APIConnectionError(request=request))
    deal_id = _saved_deal_for_feedback(deal_repository)

    response = _reject(deal_id)

    assert response.status_code == 503
    assert next(iter(deal_repository.deals.values())).profile.review_feedback == "the price is wrong"
