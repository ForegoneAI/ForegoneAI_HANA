"""Shared test setup."""

import pytest

from backend.app.h9n.extraction import repe_extractor


@pytest.fixture(autouse=True)
def _isolated_extraction_settings(monkeypatch):
    # repe_extractor loads .env on import, so a developer's local extraction
    # settings would otherwise change test results.
    for name in ("H9N_EXTRACTION_TIMEOUT_SECONDS", "H9N_EXTRACTION_MAX_RETRIES", "H9N_EXTRACTION_MAX_INPUT_CHARS"):
        monkeypatch.delenv(name, raising=False)
    # Retry backoff is real time; tests that retry shouldn't wait for it.
    monkeypatch.setattr(repe_extractor, "_sleep", lambda seconds: None)
