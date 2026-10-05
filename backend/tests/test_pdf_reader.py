"""Automated tests for read_pdf(). Builds its own tiny throwaway PDF at test
time (via pymupdf) instead of checking in a fixture file, since real deal
packages are intentionally excluded from the repo."""

import pymupdf
import pytest

from backend.app.h9n.ingestion.pdf_reader import PdfReadError, _normalize_page_text, read_pdf, read_pdf_bytes


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


# --- Milestone 1.1: stable, safe page-preserved input -------------------------

def _pdf_bytes(*page_texts: str, **save_options) -> bytes:
    doc = pymupdf.open()
    for text in page_texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    pdf_bytes = doc.tobytes(**save_options)
    doc.close()
    return pdf_bytes


def test_read_pdf_bytes_skips_blank_pages_without_renumbering():
    pages = read_pdf_bytes(_pdf_bytes("Cover", "", "Asking Price: $5,000,000"), "deal.pdf")

    assert [page["page_number"] for page in pages] == [1, 3]
    assert all(page["file_name"] == "deal.pdf" for page in pages)
    assert "5,000,000" in pages[1]["text"]


def test_read_pdf_bytes_is_deterministic():
    pdf_bytes = _pdf_bytes("Deal Name: Fixture Plaza", "NOI: $400,000")

    assert read_pdf_bytes(pdf_bytes, "deal.pdf") == read_pdf_bytes(pdf_bytes, "deal.pdf")


def test_read_pdf_bytes_rejects_a_file_that_is_not_a_pdf():
    with pytest.raises(PdfReadError, match="could not be read as a PDF"):
        read_pdf_bytes(b"just some notes, renamed to .pdf", "notes.pdf")


def test_read_pdf_bytes_rejects_a_pdf_with_no_text():
    # What a scanned document without an OCR text layer looks like.
    with pytest.raises(PdfReadError, match="OCR"):
        read_pdf_bytes(_pdf_bytes("", ""), "scan.pdf")


def test_read_pdf_bytes_rejects_an_encrypted_pdf():
    encrypted = _pdf_bytes(
        "Confidential", encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user"
    )

    with pytest.raises(PdfReadError, match="Encrypted"):
        read_pdf_bytes(encrypted, "locked.pdf")


def test_read_pdf_bytes_rejects_too_many_pages():
    with pytest.raises(PdfReadError, match="at most 2 pages"):
        read_pdf_bytes(_pdf_bytes("a", "b", "c"), "long.pdf", max_pages=2)


def test_page_text_normalization_removes_noise_but_keeps_line_structure():
    raw = "  Asking Price:\t$5M   \r\nNOI\x00: $400K\x0c\r\n\n "

    assert _normalize_page_text(raw) == "Asking Price:\t$5M\nNOI: $400K"
    # Composed and decomposed accents normalize to the same text (NFC).
    assert _normalize_page_text("cafe\u0301") == "caf\u00e9"
    # Invisible soft hyphens and zero-width spaces are dropped.
    assert _normalize_page_text("occu\u00adpancy\u200b rate") == "occupancy rate"


def test_read_pdf_bytes_rejects_an_oversized_file():
    with pytest.raises(PdfReadError, match="at most"):
        read_pdf_bytes(_pdf_bytes("Cover"), "big.pdf", max_bytes=10)


def test_an_unreadable_file_is_logged_for_the_server(caplog):
    with pytest.raises(PdfReadError):
        read_pdf_bytes(b"not a pdf", "notes.pdf")

    assert "notes.pdf" in caplog.text


def test_read_pdf_reports_a_missing_file_as_a_read_error(tmp_path):
    with pytest.raises(PdfReadError, match="missing.pdf"):
        read_pdf(str(tmp_path / "missing.pdf"))
