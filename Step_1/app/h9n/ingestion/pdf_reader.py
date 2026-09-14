import pymupdf
from pathlib import Path

def read_pdf(file_path: str) -> list[dict]:
    """
    Reads a PDF and extracts text while preserving page numbers.
    """
    file_name = Path(file_path).name
    pages = []

    # Opens the PDF document
    with pymupdf.open(file_path) as document:

        # Reads each page individually so source location is preserved
        for page_number, page in enumerate(document, start=1):
            text = page.get_text()

            # Stores the page number and its extracted text together
            pages.append({
                "file_name": file_name,
                "page_number": page_number,
                "text": text
            })

    return pages