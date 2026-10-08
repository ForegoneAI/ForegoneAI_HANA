"""Shared test setup."""

import pytest

from backend.app import main
from backend.app.h9n.auth import get_current_user
from backend.app.h9n.extraction import repe_extractor
from backend.tests.auth_fakes import TEST_USER, FakeRunRepository


@pytest.fixture(autouse=True)
def _signed_in_user():
    """API tests run as a signed-in member of TEST_ORGANIZATION_ID. Tests of
    sign-in itself remove this override (see test_auth.py)."""
    main.app.dependency_overrides[get_current_user] = lambda: TEST_USER
    yield
    main.app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture(autouse=True)
def run_repository(monkeypatch) -> FakeRunRepository:
    """Every extraction records a run (Milestone 1.3); tests record it here."""
    fake = FakeRunRepository()
    monkeypatch.setattr(main, "get_extraction_run_repository", lambda: fake)
    return fake


@pytest.fixture(autouse=True)
def _isolated_extraction_settings(monkeypatch):
    # repe_extractor loads .env on import, so a developer's local extraction
    # settings would otherwise change test results.
    for name in ("H9N_EXTRACTION_TIMEOUT_SECONDS", "H9N_EXTRACTION_MAX_RETRIES", "H9N_EXTRACTION_MAX_INPUT_CHARS"):
        monkeypatch.delenv(name, raising=False)
    # Retry backoff is real time; tests that retry shouldn't wait for it.
    monkeypatch.setattr(repe_extractor, "_sleep", lambda seconds: None)
