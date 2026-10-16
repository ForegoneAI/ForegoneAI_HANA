"""Write ground_truth/review.csv from the versioned labels, for domain review.

    python -m backend.evaluation.export_review

One row per labelled field, plus a `to_label` row for every extractor field
(fields.py) a case doesn't have a label for yet, so the domain team can add
the answers the extractor is scored on. Reviewers edit the CSV and import it
with import_review.py, which rewrites it; run this only after editing the
JSON files by hand. Cells use worksheet.py's format. It never reads
extraction output.
"""

import argparse
import csv
from pathlib import Path

from backend.evaluation.dataset import DEFAULT_ROOT, load_dataset
from backend.evaluation.fields import PRODUCTION_FIELDS
from backend.evaluation.worksheet import format_candidates, format_locations, format_value

COLUMNS = ["case_id", "field", "description", "review_status", "status", "expected_value", "unit",
           "candidates", "abs_tolerance", "evidence", "review_note", "reviewer", "reviewed_at"]
TO_LABEL = "to_label"


def review_rows(root: Path) -> list[dict]:
    dataset = load_dataset(root)
    rows = []
    for case in dataset.cases:
        cid = case["case_id"]
        for name, spec in case["requested_fields"].items():
            gold, ev = dataset.labels[cid][name], dataset.evidence[cid][name]
            rows.append({
                "case_id": cid, "field": name, "description": spec["description"],
                "review_status": gold["review_status"], "status": gold["status"],
                "expected_value": format_value(gold["value"]), "unit": gold["unit"],
                "candidates": format_candidates(gold.get("candidates")), "abs_tolerance": format_value(gold["abs_tolerance"]),
                "evidence": format_locations(ev["locations"]), "review_note": ev.get("review_note") or "",
                "reviewer": gold.get("reviewer") or "", "reviewed_at": gold.get("reviewed_at") or "",
            })
        for name, (unit, description) in PRODUCTION_FIELDS.items():
            if name not in case["requested_fields"]:
                rows.append({
                    "case_id": cid, "field": name, "description": description,
                    "review_status": TO_LABEL, "status": "", "expected_value": "", "unit": unit,
                    "candidates": "", "abs_tolerance": "0", "evidence": "", "review_note": "",
                    "reviewer": "", "reviewed_at": "",
                })
    return rows


def export_review(root: Path, path: Path) -> list[dict]:
    rows = review_rows(root)
    temporary = path.with_suffix(".csv.tmp")
    with temporary.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)
    return rows


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args(argv)
    try:
        rows = export_review(args.dataset, args.csv or args.dataset / "ground_truth/review.csv")
    except (OSError, ValueError, KeyError) as exc:
        parser.error(str(exc))
    todo = sum(r["review_status"] == TO_LABEL for r in rows)
    print(f"Wrote {len(rows)} rows: {len(rows) - todo} labelled, {todo} fields to label.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
