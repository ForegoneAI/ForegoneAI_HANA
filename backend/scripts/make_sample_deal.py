"""
make_sample_deal.py

Generates backend/data/sample_deal.pdf: the fictional "Sample Estates
Apartments" deal package that the README and demo_end_to_end.py's default
argument both refer to, so someone without a real CIM yet can still run

    python -m backend.app.h9n.test_extractor backend/data/sample_deal.pdf
    python -m backend.app.h9n.demo_end_to_end

and see the whole pipeline (extraction, evidence, uncertainty flags, review,
evaluation) run against something.

Why this is a generator script instead of a checked-in PDF: backend/data/ is
entirely covered by .gitignore's `data/` rule, because real deal packages
can't go in a public/shared repo. That rule doesn't distinguish "real,
confidential CIM" from "fake, harmless fixture" - it just excludes the whole
directory - so even a made-up fixture never gets committed. backend/tests/
already solves this the same way for its own PDF fixture (see
test_pdf_reader.py's two_page_pdf, built with pymupdf at test time instead of
checked in); this script does the same thing, just as something a person
runs once by hand instead of something pytest runs automatically.

All numbers below are invented for this fixture and don't describe a real
property. A couple of fields are deliberately written to exercise Milestone
1 item 3 (missing/uncertain/conflicting information), not just item 1:
  - year_built is never stated (tests "missing").
  - occupancy_rate is stated as both "94%" and "96%" on different pages
    (tests "conflicting").
  - cap_rate has to be worked out from NOI and asking price rather than
    being stated outright (tests "uncertain").

Usage:
    python -m backend.scripts.make_sample_deal
"""

from __future__ import annotations

from pathlib import Path

import pymupdf

OUTPUT_PATH = "backend/data/sample_deal.pdf"

PAGE_1 = """SAMPLE ESTATES APARTMENTS
Offering Memorandum (Fictional - For Testing Only)

Deal Name: Sample Estates Apartments
Property Type: Multifamily
Location: Springfield, OH
Units: 120
Square Feet: 98,000

Asking Price: $10,000,000

This is a fictional deal package used only to smoke-test the extraction
pipeline. None of the figures in this document describe a real property.
"""

PAGE_2 = """SAMPLE ESTATES APARTMENTS
Financial Summary

Annual Revenue: $1,450,000
Operating Expenses: $650,000
Net Operating Income (NOI): $800,000

Occupancy is currently 94%, based on the June rent roll.

Loan Amount: $6,500,000
Interest Rate: 5.25%
Loan Term: 10 years
"""

PAGE_3 = """SAMPLE ESTATES APARTMENTS
Sponsor & Business Plan

Sponsor: Fictional Capital Partners
Sponsor Equity: $3,500,000
Investment Strategy: Value-add
Business Plan: Renovate unit interiors and common areas over 24 months to
push rents to market.

Note: the property manager's report elsewhere in this package lists
occupancy at 96% as of the same month - see rent roll for the figure this
package treats as authoritative.
"""


def make_sample_deal(output_path: str = OUTPUT_PATH) -> str:
    """Builds the fictional Sample Estates Apartments PDF and writes it to
    `output_path` (creating backend/data/ if needed), returning that path."""
    doc = pymupdf.open()
    for page_text in (PAGE_1, PAGE_2, PAGE_3):
        doc.new_page().insert_textbox(
            pymupdf.Rect(56, 56, 540, 780), page_text, fontsize=11
        )
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(output_path)
    doc.close()
    return output_path


def main() -> None:
    path = make_sample_deal()
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
