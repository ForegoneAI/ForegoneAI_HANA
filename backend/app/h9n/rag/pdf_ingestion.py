"""Safe PDF-to-page-text conversion used only by the RAG ingestion endpoint."""

from __future__ import annotations

import pymupdf

from .schemas import PageText


class PdfIngestionError(ValueError):
    """A customer-safe error for unreadable, encrypted, or textless PDFs."""


def extract_pages_from_pdf_bytes(file_bytes: bytes, *, max_pages: int = 1_000) -> list[PageText]:
    """Read a PDF in memory and retain actual source page numbers.

    Empty pages are omitted because they contain nothing useful for semantic
    retrieval; page numbers are not renumbered, so citations still point to
    the original document.
    """
    try:
        with pymupdf.open(stream=file_bytes, filetype="pdf") as document:
            if document.is_encrypted:
                raise PdfIngestionError("Encrypted PDFs are not supported for RAG ingestion.")
            if len(document) > max_pages:
                raise PdfIngestionError(f"PDFs may contain at most {max_pages} pages.")

            pages = []
            for page_number, page in enumerate(document, start=1):
                text = page.get_text().strip()
                if text:
                    pages.append(PageText(page_number=page_number, text=text))
    except PdfIngestionError:
        raise
    except Exception as exc:
        # Do not expose parser internals or local filesystem information to API callers.
        raise PdfIngestionError("The uploaded file could not be read as a PDF.") from exc

    if not pages:
        raise PdfIngestionError(
            "No readable text was found. Run OCR before indexing a scanned PDF."
        )
    return pages
