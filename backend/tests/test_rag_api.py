"""API safety tests for RAG routes without live Supabase or OpenRouter clients.

Callers are signed in as a member of TEST_ORGANIZATION_ID (see conftest.py).
"""

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app import main
from backend.app.h9n.auth import get_current_user
from backend.app.h9n.rag import api
from backend.app.h9n.rag.schemas import RagSearchResponse, RagSearchResult
from backend.tests.auth_fakes import OTHER_ORGANIZATION_ID, TEST_ORGANIZATION_ID


class FailIfCalledService:
    def __getattr__(self, name):
        raise AssertionError(f"RAG service {name}() should not be reached")


def test_search_requires_a_signed_in_user(monkeypatch):
    main.app.dependency_overrides.pop(get_current_user)
    monkeypatch.setattr(api, "get_rag_service", lambda: FailIfCalledService())

    response = TestClient(main.app).post(
        "/api/h9n/rag/search",
        json={"organization_id": str(TEST_ORGANIZATION_ID), "query": "Find cap rate evidence"},
    )

    assert response.status_code == 401


def test_search_returns_cited_results_for_the_users_organization(monkeypatch):
    document_id = uuid4()

    class FakeService:
        def search(self, request):
            assert request.organization_id == TEST_ORGANIZATION_ID
            return RagSearchResponse(
                results=[
                    RagSearchResult(
                        document_id=document_id,
                        document_name="fixture.pdf",
                        source_type="deal_package",
                        is_verified_knowledge=False,
                        page_number=4,
                        chunk_index=0,
                        content="Cap rate is 6.5%.",
                        similarity=0.95,
                    )
                ]
            )

    monkeypatch.setattr(api, "get_rag_service", lambda: FakeService())

    response = TestClient(main.app).post(
        "/api/h9n/rag/search",
        json={"organization_id": str(TEST_ORGANIZATION_ID), "query": "Find cap rate evidence"},
    )

    assert response.status_code == 200
    assert response.json()["results"][0]["document_name"] == "fixture.pdf"
    assert response.json()["results"][0]["page_number"] == 4


def test_search_of_another_organization_is_refused(monkeypatch):
    monkeypatch.setattr(api, "get_rag_service", lambda: FailIfCalledService())

    response = TestClient(main.app).post(
        "/api/h9n/rag/search",
        json={"organization_id": str(OTHER_ORGANIZATION_ID), "query": "Find cap rate evidence"},
    )

    assert response.status_code == 403


def test_ingesting_into_another_organization_is_refused(monkeypatch):
    monkeypatch.setattr(api, "get_rag_service", lambda: FailIfCalledService())
    client = TestClient(main.app)

    text_response = client.post(
        "/api/h9n/rag/documents/text",
        json={
            "organization_id": str(OTHER_ORGANIZATION_ID),
            "document_name": "notes.md",
            "pages": [{"page_number": 1, "text": "Cap rate is 6.5%."}],
        },
    )
    pdf_response = client.post(
        "/api/h9n/rag/documents/pdf",
        data={"organization_id": str(OTHER_ORGANIZATION_ID)},
        files={"file": ("deal.pdf", b"%PDF-1.4 fixture", "application/pdf")},
    )

    assert text_response.status_code == 403
    assert pdf_response.status_code == 403
