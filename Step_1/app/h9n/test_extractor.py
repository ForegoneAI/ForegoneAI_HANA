"""
Manual smoke test / checkpoint script for H9N Milestone 1, Part 1.

Runs the full pipeline described in the "Immediate Next Move" section of the
Milestone 1 plan: read_pdf() -> extract_repe_deal() -> validated
REPEDealProfile, with no manual data entry.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python -m Step_1.app.h9n.test_extractor path/to/taberna_cim.pdf

If no path is given, defaults to "data/test_deal.pdf" to match
test_pdf_reader.py's convention (this repo's .gitignore excludes `data/`,
so put the real Taberna CIM there locally).
"""

import json
import sys

from Step_1.app.h9n.extraction.repe_extractor import extract_repe_deal
from Step_1.app.h9n.ingestion.pdf_reader import read_pdf


def main() -> None:
    file_path = sys.argv[1] if len(sys.argv) > 1 else "data/test_deal.pdf"

    print(f"Reading: {file_path}")
    pages = read_pdf(file_path)
    print(f"Extracted {len(pages)} page(s) of text.\n")

    print("Sending page-preserved text to Claude for structured extraction...")
    deal = extract_repe_deal(pages)

    print("\nVALIDATED REPE DEAL PROFILE")
    print(json.dumps(deal.model_dump(), indent=2))

    if deal.missing_information:
        print("\nMissing information flagged by the model:")
        for note in deal.missing_information:
            print(f"  - {note}")

    if deal.conflicting_information:
        print("\nConflicting information flagged by the model:")
        for note in deal.conflicting_information:
            print(f"  - {note}")


if __name__ == "__main__":
    main()
