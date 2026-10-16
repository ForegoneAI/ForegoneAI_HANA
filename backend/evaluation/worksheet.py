"""How review.csv cells are written, so reviewers type what a spreadsheet shows
instead of JSON:

    expected_value   2100000   $2,100,000   5.87% (ratio fields)   Multifamily
    candidates       1.41; 1.43
    evidence         daly_city p3; townhomes_model Sheet1!N15

Units and bounds are checked by the dataset loader (fields.check_value).
A cell a spreadsheet left out of a short row reads as None, the same as blank.
Text conflict candidates can't contain ";".
"""

import json
import re
from decimal import Decimal

from backend.evaluation.scoring import location_key

# Thousands separators only in groups of three, so "1,5" is never read as 15.
# Exponents too: JSON writes 0.00005 as 5e-05, and spreadsheets 2.1E+06.
_NUMBER = re.compile(r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][-+]?\d+)?")
_PAGE = re.compile(r"p\s*(\d+)", re.IGNORECASE)


def parse_value(text: str, unit: str):
    """A cell as a value in `unit`; None when blank."""
    text = (text or "").strip()
    if not text or unit == "text":
        return text or None
    raw = text.removeprefix("$")
    percent = unit == "ratio" and raw.endswith("%")
    raw = raw.removesuffix("%") if percent else raw
    if not _NUMBER.fullmatch(raw):
        raise ValueError(f"{text!r} is not a number")
    # Decimal so "5.87%" is exactly 0.0587, not 0.058699999999999995.
    number = Decimal(raw.replace(",", "")) / (100 if percent else 1)
    return int(number) if number == number.to_integral_value() else float(number)


def format_value(value) -> str:
    return "" if value is None else value if isinstance(value, str) else json.dumps(value)


def parse_candidates(text: str, unit: str) -> list | None:
    values = [parse_value(part, unit) for part in (text or "").split(";") if part.strip()]
    return values or None


def format_candidates(values: list | None) -> str:
    return "; ".join(format_value(v) for v in values or [])


def parse_locations(text: str) -> list[dict]:
    locations = []
    for item in filter(None, (part.strip() for part in (text or "").split(";"))):
        document_id, _, where = item.partition(" ")
        page = _PAGE.fullmatch(where.strip())
        sheet, _, cell = where.strip().rpartition("!")
        if page:
            locations.append({"document_id": document_id, "page": int(page.group(1))})
        elif sheet and cell:
            locations.append({"document_id": document_id, "sheet": sheet, "cell": cell.upper()})  # as exported
        else:
            raise ValueError(f"Evidence {item!r} must look like 'daly_city p3' or 'townhomes_model Sheet1!N15'")
    return locations


def format_locations(locations: list) -> str:
    keys = [location_key(loc) for loc in locations]
    return "; ".join(f"{k[0]} p{k[2]}" if k[1] == "page" else f"{k[0]} {k[2]}!{k[3]}" for k in keys)
