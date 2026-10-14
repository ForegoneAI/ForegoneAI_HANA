"""Tests for Milestone 2.3 - keeping each deal's PDF for the evidence viewer.

The uploaded PDF is stored privately; GET /deals/{id}/source returns a
short-lived link to it, for the deal's own organization only (Milestone 2.5:
another organization can't reach a deal's PDF).
"""

import io
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pymupdf
import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.h9n.auth import get_current_user
from backend.app.h9n.rag.config import RagConfigurationError
from backend.app.h9n.review.files import SupabaseDealFileStore, source_pdf_path
from backend.app.h9n.review.models import NewDeal
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.tests.auth_fakes import OTHER_ORGANIZATION_ID, TEST_ORGANIZATION_ID, TEST_USER
from backend.tests.test_auth import _settings


def _pdf() -> bytes:
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Asking Price: $10,000,000")
    content = doc.tobytes()
    doc.close()
    return content


def _upload(monkeypatch, content: bytes):
    monkeypatch.setattr(main, "extract_repe_deal", lambda pages: REPEDealProfile(deal_name="Elm"))
    return TestClient(main.app).post(
        "/api/h9n/repe/extract", files={"file": ("Elm Court OM.pdf", io.BytesIO(content), "application/pdf")}
    )


def _saved_deal(deal_repository, organization_id=TEST_ORGANIZATION_ID, *, with_pdf=True) -> str:
    deal_id = uuid4()
    deal_repository.create(
        NewDeal(
            id=deal_id,
            organization_id=organization_id,
            profile=REPEDealProfile(deal_name="Elm"),
            source_filename="Elm Court OM.pdf",
            source_storage_path=source_pdf_path(organization_id, deal_id) if with_pdf else None,
            created_by=TEST_USER.user_id,
        )
    )
    return str(deal_id)


# --- Keeping the PDF ----------------------------------------------------------


def test_an_uploaded_pdf_is_kept_under_its_organization(monkeypatch, deal_files, deal_repository):
    content = _pdf()

    body = _upload(monkeypatch, content).json()

    path = f"{TEST_ORGANIZATION_ID}/{body['deal_id']}/source.pdf"
    assert deal_files.files == {path: content}
    [saved] = deal_repository.deals.values()
    assert saved.source_storage_path == path
    fetched = TestClient(main.app).get(f"/api/h9n/repe/deals/{body['deal_id']}").json()
    assert fetched["has_source_pdf"] is True
    # Where it's stored is the server's business.
    assert "source_storage_path" not in fetched


def test_a_pdf_that_cannot_be_kept_does_not_lose_the_deal(monkeypatch, deal_files, deal_repository, caplog):
    deal_files.fail_upload = True

    response = _upload(monkeypatch, _pdf())

    assert response.status_code == 200
    deal_id = response.json()["deal_id"]
    assert TestClient(main.app).get(f"/api/h9n/repe/deals/{deal_id}").json()["has_source_pdf"] is False
    assert "Couldn't store the source PDF" in caplog.text


def test_a_kept_pdf_is_removed_if_its_deal_cannot_be_saved(monkeypatch, deal_files, deal_repository):
    def broken_create(deal):
        raise RuntimeError("database down")

    monkeypatch.setattr(deal_repository, "create", broken_create)

    response = _upload(monkeypatch, _pdf())

    assert response.status_code == 502
    assert deal_files.files == {}
    assert len(deal_files.removed) == 1


# --- Opening it -------------------------------------------------------------


def test_the_source_route_returns_a_short_lived_link(deal_files, deal_repository):
    deal_id = _saved_deal(deal_repository)

    before = datetime.now(timezone.utc)
    response = TestClient(main.app).get(f"/api/h9n/repe/deals/{deal_id}/source")

    assert response.status_code == 200
    body = response.json()
    path = f"{TEST_ORGANIZATION_ID}/{deal_id}/source.pdf"
    assert body["url"] == f"https://storage.example/{path}?token=signed"
    assert body["filename"] == "Elm Court OM.pdf"
    assert deal_files.signed == [(path, main.SOURCE_URL_SECONDS)]
    expires_at = datetime.fromisoformat(body["expires_at"])
    assert timedelta(minutes=9) < expires_at - before <= timedelta(minutes=10, seconds=5)


def test_another_organizations_pdf_cannot_be_reached(deal_files, deal_repository):
    deal_id = _saved_deal(deal_repository, OTHER_ORGANIZATION_ID)

    response = TestClient(main.app).get(f"/api/h9n/repe/deals/{deal_id}/source")

    assert response.status_code == 404
    assert response.json()["detail"] == "No deal found with that id."
    assert deal_files.signed == []


def test_the_source_route_requires_sign_in(deal_files, deal_repository):
    deal_id = _saved_deal(deal_repository)
    main.app.dependency_overrides.pop(get_current_user)

    assert TestClient(main.app).get(f"/api/h9n/repe/deals/{deal_id}/source").status_code == 401
    assert deal_files.signed == []


def test_a_deal_without_a_kept_pdf_says_so(deal_repository):
    deal_id = _saved_deal(deal_repository, with_pdf=False)

    response = TestClient(main.app).get(f"/api/h9n/repe/deals/{deal_id}/source")

    assert response.status_code == 404
    assert "original PDF wasn't kept" in response.json()["detail"]


def test_a_storage_failure_is_a_controlled_error(deal_files, deal_repository, caplog):
    deal_files.fail_sign = True
    deal_id = _saved_deal(deal_repository)

    with caplog.at_level(logging.ERROR):
        response = TestClient(main.app).get(f"/api/h9n/repe/deals/{deal_id}/source")

    assert response.status_code == 502
    assert "must not leak" not in response.text


def test_unconfigured_storage_is_a_503(monkeypatch, deal_repository):
    def unconfigured():
        raise RagConfigurationError("Supabase is not configured.")

    monkeypatch.setattr(main, "get_deal_file_store", unconfigured)
    deal_id = _saved_deal(deal_repository)

    assert TestClient(main.app).get(f"/api/h9n/repe/deals/{deal_id}/source").status_code == 503


# --- What is sent to Supabase Storage ----------------------------------------


class RecordingStorage:
    def __init__(self, signed=None):
        self.calls = []
        self._signed = signed
        self.storage = self

    def from_(self, bucket):
        self.calls.append(("bucket", bucket))
        return self

    def upload(self, path, file, file_options):
        self.calls.append(("upload", path, file_options))

    def remove(self, paths):
        self.calls.append(("remove", paths))

    def create_signed_url(self, path, expires_in):
        self.calls.append(("sign", path, expires_in))
        return {"signedURL": self._signed, "signedUrl": self._signed}


def _store(client) -> SupabaseDealFileStore:
    return SupabaseDealFileStore(_settings(), client=client)


def test_pdfs_go_to_the_private_bucket_as_pdfs_and_never_overwrite():
    client = RecordingStorage()

    _store(client).upload("org/deal/source.pdf", b"%PDF")

    assert client.calls == [
        ("bucket", "test-bucket"),
        ("upload", "org/deal/source.pdf", {"content-type": "application/pdf", "upsert": "false"}),
    ]


def test_a_signed_url_is_read_from_storages_reply():
    client = RecordingStorage(signed="https://x.supabase.co/storage/v1/object/sign/b/p?token=t")

    assert _store(client).signed_url("org/deal/source.pdf", 600) == "https://x.supabase.co/storage/v1/object/sign/b/p?token=t"
    assert ("sign", "org/deal/source.pdf", 600) in client.calls


def test_a_missing_signed_url_is_an_error_not_an_empty_link():
    with pytest.raises(RuntimeError):
        _store(RecordingStorage(signed=None)).signed_url("org/deal/source.pdf", 600)


def test_pdf_paths_sit_under_their_organization():
    organization_id, deal_id = uuid4(), uuid4()

    assert source_pdf_path(organization_id, deal_id) == f"{organization_id}/{deal_id}/source.pdf"
