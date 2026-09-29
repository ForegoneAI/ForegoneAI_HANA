"""
cases.py

H9N Milestone 1, items 5 and 7 - Ground-Truth Evaluation Set and
Unseen-Deal (Holdout) Testing.

Each case is a synthetic deal package - defined directly as page text
(the same {file_name, page_number, text} shape `read_pdf()` produces),
rather than a real PDF file - paired with the known-correct value for
every field the text unambiguously states. Because these are made up here,
the "ground truth" is exact by construction: there's no need for a human
to have separately verified a real deal to know what the right answer is.

This is a real limitation worth being upfront about: a synthetic set only
tells you whether the extractor can read clearly-stated facts back
correctly. It does NOT tell you how it performs on a real CIM's messier
formatting, unusual terminology, scanned/OCR'd text, or genuinely
ambiguous wording - that still requires periodically running
test_extractor.py against real deal packages and reviewing the output by
hand (see the README's "What's still worth doing" section). Real,
human-reviewed deals should replace or supplement these cases over time as
they become available.

GROUND_TRUTH_CASES vs HOLDOUT_CASES
------------------------------------
GROUND_TRUTH_CASES are the cases used while building and checking the
extractor's prompt (IMPORTANT_FIELDS, SYSTEM_PROMPT in repe_extractor.py).

HOLDOUT_CASES exist to catch prompt-tuning that accidentally overfits to
the exact wording of the ground-truth cases. They cover different property
types and, deliberately, different DOCUMENT FORMATTING (narrative prose,
bullet/stat-sheet style) than the ground-truth cases use. The discipline
that makes this meaningful going forward: if the extractor ever starts
missing a holdout case, fix the prompt using reasoning about the general
rule it's missing, not by adding a special case for that exact document -
and never move a holdout case's wording into the ground-truth set just to
make a failing run pass.
"""

from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------
# Ground truth - used to check the extractor while building it.
# --------------------------------------------------------------------------

GROUND_TRUTH_CASES: list[dict[str, Any]] = [
    {
        "case_id": "meadowbrook_apartments",
        "pages": [
            {
                "file_name": "meadowbrook_apartments.pdf",
                "page_number": 1,
                "text": (
                    "MEADOWBROOK APARTMENTS\n"
                    "Offering Memorandum\n\n"
                    "Property Type: Multifamily\n"
                    "Address: 4200 Meadowbrook Lane, Austin, TX 78745\n"
                    "Units: 128\n"
                    "Year Built: 1998\n\n"
                    "Asking Price: $18,500,000"
                ),
            },
            {
                "file_name": "meadowbrook_apartments.pdf",
                "page_number": 2,
                "text": (
                    "FINANCIAL SUMMARY\n\n"
                    "Annual Revenue: $2,450,000\n"
                    "Operating Expenses: $980,000\n"
                    "Net Operating Income (NOI): $1,470,000\n"
                    "Cap Rate: 7.9%\n"
                    "Occupancy Rate: 94%"
                ),
            },
        ],
        "expected": {
            "deal_name": "Meadowbrook Apartments",
            "property_name": "Meadowbrook Apartments",
            "property_type": "Multifamily",
            "address": "4200 Meadowbrook Lane, Austin, TX 78745",
            "units": 128,
            "year_built": 1998,
            "asking_price": 18_500_000,
            "annual_revenue": 2_450_000,
            "operating_expenses": 980_000,
            "noi": 1_470_000,
            "cap_rate": 7.9,
            "occupancy_rate": 94.0,
        },
    },
    {
        "case_id": "riverside_office_plaza",
        "pages": [
            {
                "file_name": "riverside_office_plaza.pdf",
                "page_number": 1,
                "text": (
                    "RIVERSIDE OFFICE PLAZA\n"
                    "Confidential Information Memorandum\n\n"
                    "Property Type: Office\n"
                    "Address: 850 Riverside Drive, Denver, CO 80203\n"
                    "Square Feet: 142,000\n"
                    "Year Built: 2005\n\n"
                    "Asking Price: $32,000,000"
                ),
            },
            {
                "file_name": "riverside_office_plaza.pdf",
                "page_number": 2,
                "text": (
                    "FINANCIAL OVERVIEW\n\n"
                    "NOI: $2,240,000\n"
                    "Cap Rate: 7.0%\n"
                    "Occupancy Rate: 88%"
                ),
            },
        ],
        "expected": {
            "deal_name": "Riverside Office Plaza",
            "property_name": "Riverside Office Plaza",
            "property_type": "Office",
            "address": "850 Riverside Drive, Denver, CO 80203",
            "square_feet": 142_000,
            "year_built": 2005,
            "asking_price": 32_000_000,
            "noi": 2_240_000,
            "cap_rate": 7.0,
            "occupancy_rate": 88.0,
        },
    },
]


# --------------------------------------------------------------------------
# Holdout - never used while writing/tuning the prompt. Different property
# types AND different document formatting than the ground-truth cases, so a
# prompt that only works on GROUND_TRUTH_CASES' exact style shows up here.
# --------------------------------------------------------------------------

HOLDOUT_CASES: list[dict[str, Any]] = [
    {
        "case_id": "cedar_ridge_self_storage",
        "pages": [
            {
                "file_name": "cedar_ridge_self_storage.pdf",
                "page_number": 1,
                "text": (
                    "Cedar Ridge Self-Storage is a self-storage facility located at "
                    "900 Cedar Ridge Road, Boise, ID 83702, built in 2010. The seller "
                    "is asking $6,750,000 for the property."
                ),
            },
            {
                "file_name": "cedar_ridge_self_storage.pdf",
                "page_number": 2,
                "text": (
                    "Operationally, the facility generated NOI of $445,000 last year "
                    "on a cap rate basis of 6.6%. Occupancy currently sits around 91%, "
                    "though management notes this fluctuates seasonally."
                ),
            },
        ],
        # occupancy_rate is deliberately left out of `expected` - "around 91%,
        # fluctuates seasonally" is genuinely fuzzy, so it isn't fair to grade
        # as a single right answer. It's a good field to eyeball manually in
        # the evaluation output instead.
        "expected": {
            "deal_name": "Cedar Ridge Self-Storage",
            "property_name": "Cedar Ridge Self-Storage",
            "property_type": "Self-Storage",
            "address": "900 Cedar Ridge Road, Boise, ID 83702",
            "year_built": 2010,
            "asking_price": 6_750_000,
            "noi": 445_000,
            "cap_rate": 6.6,
        },
    },
    {
        "case_id": "harbor_point_retail_center",
        "pages": [
            {
                "file_name": "harbor_point_retail_center.pdf",
                "page_number": 1,
                "text": (
                    "HARBOR POINT RETAIL CENTER - PROPERTY SUMMARY\n\n"
                    "- Property Type: Retail\n"
                    "- Address: 1200 Harbor Point Blvd, Tampa, FL 33602\n"
                    "- Square Feet: 68,500\n"
                    "- Year Built: 2015\n"
                    "- Asking Price: $14,200,000"
                ),
            },
            {
                "file_name": "harbor_point_retail_center.pdf",
                "page_number": 2,
                "text": (
                    "- NOI: $995,000\n"
                    "- Cap Rate: 7.0%\n"
                    "- Occupancy: 96%"
                ),
            },
        ],
        "expected": {
            "deal_name": "Harbor Point Retail Center",
            "property_name": "Harbor Point Retail Center",
            "property_type": "Retail",
            "address": "1200 Harbor Point Blvd, Tampa, FL 33602",
            "square_feet": 68_500,
            "year_built": 2015,
            "asking_price": 14_200_000,
            "noi": 995_000,
            "cap_rate": 7.0,
            "occupancy_rate": 96.0,
        },
    },
]
