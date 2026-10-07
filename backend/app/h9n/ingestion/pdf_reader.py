"""
pdf_reader.py

Turns a deal package PDF into page-preserved text for extraction.

Milestone 1.1 hardens this into a stable, safe input step: every page's text
is normalized the same way every time (so M1.3's input fingerprint is
reproducible), blank pages are skipped without renumbering the rest (so
citations still point at the real page), and a file that can't be read -
not a PDF, encrypted, too large, too long, or scanned with no text layer -
raises a `PdfReadError` with a message that's safe to show a customer,
instead of a raw parser exception (the parser's own error goes to the server
log).
"""

import logging
import re
import unicodedata
from pathlib import Path

import pymupdf

logger = logging.getLogger(__name__)

# Generous ceilings for a single deal package; anything bigger is almost
# certainly not a CIM and would not fit in one extraction request anyway.
DEFAULT_MAX_PAGES = 500
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

# Control characters other than newline and tab (e.g. NUL, form feed) carry
# no meaning for extraction and would only make the input hash unstable.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
# Soft hyphens and zero-width characters are invisible in the PDF but would
# stop a quote of the visible text from matching.
_INVISIBLE_CHARS = re.compile("[\u00ad\u200b\u200c\u200d\u2060\ufeff]")
_TRAILING_SPACES = re.compile(r"[ \t]+\n")


class PdfReadError(ValueError):
    """A customer-safe error for unreadable, encrypted, oversized, or textless PDFs."""


def _normalize_page_text(text: str) -> str:
    """Deterministic cleanup so the same PDF always yields the same text."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_CHARS.sub("", text)
    text = _INVISIBLE_CHARS.sub("", text)
    text = _TRAILING_SPACES.sub("\n", text)
    return text.strip()


def read_pdf_bytes(
    file_bytes: bytes,
    file_name: str,
    *,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> list[dict]:
    """
    Reads a PDF held in memory and returns one {"file_name", "page_number",
    "text"} dict per page that has text, keeping original page numbers.
    """
    if len(file_bytes) > max_bytes:
        raise PdfReadError(f"PDFs may be at most {max_bytes // (1024 * 1024)} MB.")
    try:
        with pymupdf.open(stream=file_bytes, filetype="pdf") as document:
            if document.is_encrypted:
                raise PdfReadError("Encrypted PDFs are not supported.")
            if len(document) > max_pages:
                raise PdfReadError(f"PDFs may contain at most {max_pages} pages.")

            pages = []
            # Reads each page individually so source location is preserved
            for page_number, page in enumerate(document, start=1):
                text = _normalize_page_text(page.get_text())
                if text:
                    pages.append({
                        "file_name": file_name,
                        "page_number": page_number,
                        "text": text,
                    })
    except PdfReadError:
        raise
    except Exception as exc:
        # Do not expose parser internals or local file paths to API callers;
        # the real cause goes to the server log.
        logger.warning("Could not read %r as a PDF", file_name, exc_info=True)
        raise PdfReadError("The uploaded file could not be read as a PDF.") from exc

    if not pages:
        raise PdfReadError(
            "No readable text was found in the PDF. Scanned documents need OCR, "
            "which is not supported yet."
        )
    return pages


def read_pdf(file_path: str) -> list[dict]:
    """
    Reads a PDF and extracts text while preserving page numbers.
    """
    path = Path(file_path)
    try:
        file_bytes = path.read_bytes()
    except OSError as exc:
        raise PdfReadError(f"Could not open {path.name}.") from exc
    return read_pdf_bytes(file_bytes, path.name)
