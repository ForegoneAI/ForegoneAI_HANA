"""Automated tests for read_pdf(). Builds its own tiny throwaway PDF at test
time (via pymupdf) instead of checking in a fixture file, since real deal
packages are intentionally excluded from the repo."""

import pymupdf
import pytest

from backend.app.h9n.ingestion.pdf_reader import read_pdf


@pytest.fixture
def two_page_pdf(tmp_path):
    path = tmp_path / "fixture_deal.pdf"
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "Deal Name: Fixture Plaza")
    doc.new_page().insert_text((72, 72), "Asking Price: $5,000,000")
    doc.save(str(path))
    doc.close()
    return path


def test_read_pdf_preserves_page_numbers_and_file_name(two_page_pdf):
    pages = read_pdf(str(two_page_pdf))

    assert len(pages) == 2
    assert pages[0]["file_name"] == "fixture_deal.pdf"
    assert pages[0]["page_number"] == 1
    assert "Fixture Plaza" in pages[0]["text"]
    assert pages[1]["page_number"] == 2
    assert "5,000,000" in pages[1]["text"]
