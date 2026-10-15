"""Import domain-reviewed CSV rows, validating everything before writing.

    python -m backend.evaluation.import_review --version 0.2.0 --check   # dry run
    python -m backend.evaluation.import_review --version 0.2.0           # write

Requires an explicit dataset version change. This command never approves rows
automatically and never reads extraction predictions. Regenerate the CSV from
the JSON files with export_review.py.

Rows marked `to_label` are skipped: they list H9N production fields a case has
no answer for yet. A reviewer fills one in (status, expected_value, evidence)
and changes its review_status to `pending_domain_review` or `approved`, and the
import adds the field to the case. Any other row for a field the case doesn't
have is also added when it fills the `description` column. Fields named after
a REPEDealProfile field (fields.py) are `production` scope and count in the
score; others are `reference`.
"""

import argparse
import csv
import json
import math
import re
import tempfile
from collections import Counter
from pathlib import Path

from backend.evaluation.dataset import DEFAULT_ROOT, load_dataset, read_json
from backend.evaluation.fields import default_scope

TO_LABEL = "to_label"


def _tolerance(text: str | None, key) -> float | None:
    if text is None or not text.strip():
        return None
    value = json.loads(text)
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError(f"Invalid abs_tolerance for {key}")
    return value


def import_review(root: Path, csv_path: Path, new_version: str, *, check: bool = False) -> dict:
    """Returns counts of what was (or, with check, would be) imported."""
    original = load_dataset(root)
    if not new_version.strip() or new_version == original.version:
        raise ValueError("Specify a new dataset version for the reviewed labels")
    config = read_json(root / "inputs/cases.json")
    labels = read_json(root / "ground_truth/labels.json")
    evidence = read_json(root / "ground_truth/evidence.json")
    expected = {(cid, name) for cid, fields in labels["cases"].items() for name in fields}
    specs = {case["case_id"]: case["requested_fields"] for case in config["cases"]}
    seen, added, summary = set(), set(), Counter()
    with csv_path.open(newline="", encoding="utf-8-sig") as source:
        for line, row in enumerate(csv.DictReader(source), start=2):
            key = (row["case_id"], row["field"])
            cid, name = key
            try:
                if key in seen or key in added:
                    raise ValueError("Duplicate review row")
                if row["review_status"] == TO_LABEL:
                    if key in expected:
                        raise ValueError("A labelled field can't go back to to_label")
                    summary["to_label"] += 1
                    continue
                description = (row.get("description") or "").strip()
                if key in expected:
                    seen.add(key)
                else:
                    if cid not in specs or not description or not re.fullmatch(r"[a-z][a-z0-9_]*", name):
                        raise ValueError("Unknown review row: new fields need a known case, a snake_case "
                                         "field name, and a description")
                    specs[cid][name] = {"unit": row["unit"], "description": description}
                    labels["cases"][cid][name] = {"abs_tolerance": 0}
                    added.add(key)
                spec, gold = specs[cid][name], labels["cases"][cid][name]
                spec["unit"] = row["unit"]
                if description:
                    spec["description"] = description
                spec["scope"] = (row.get("scope") or "").strip() or spec.get("scope") or default_scope(name)
                tolerance = _tolerance(row.get("abs_tolerance"), key)
                if tolerance is not None:
                    gold["abs_tolerance"] = tolerance
                gold.update(status=row["status"], value=json.loads(row["expected_value"]), unit=row["unit"],
                            review_status=row["review_status"], reviewer=row["reviewer"].strip() or None,
                            reviewed_at=row["reviewed_at"].strip() or None)
                candidates = json.loads(row["candidates"] or "null")
                if candidates is None:
                    gold.pop("candidates", None)
                else:
                    gold["candidates"] = candidates
                evidence[cid][name] = {"locations": json.loads(row["evidence"] or "[]"), "review_note": row["review_note"]}
                summary[row["review_status"]] += 1
            except (ValueError, KeyError, TypeError) as exc:
                # Name the spreadsheet line, so a reviewer can find the cell.
                raise ValueError(f"review.csv line {line} ({cid}.{name}): {exc}") from None
    if seen != expected:
        raise ValueError(f"Review CSV omitted rows: {sorted(expected - seen)[:5]}")
    config["dataset_version"] = labels["dataset_version"] = new_version
    updates = {"inputs/cases.json": config, "ground_truth/labels.json": labels, "ground_truth/evidence.json": evidence}
    # Stage a complete metadata snapshot so bad dates, units, scopes, evidence,
    # split leakage, or invalid states cannot partially overwrite gold files.
    with tempfile.TemporaryDirectory() as directory:
        staged = Path(directory)
        for name, payload in {**updates, "inputs/manifest.json": list(original.documents.values())}.items():
            path = staged / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        load_dataset(staged)
        if not check:
            for name in updates:
                path = root / name
                temporary = path.with_suffix(".json.tmp")
                temporary.write_bytes((staged / name).read_bytes())
                temporary.replace(path)
    summary["added_fields"] = len(added)
    return dict(summary)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        summary = import_review(args.dataset, args.csv or args.dataset / "ground_truth/review.csv", args.version,
                                check=args.check)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    counts = (f"{summary.get('approved', 0)} approved, {summary.get('pending_domain_review', 0)} pending review, "
              f"{summary.get('added_fields', 0)} new fields, {summary.get('to_label', 0)} still to label")
    print(f"Review validated ({counts}). Nothing written." if args.check
          else f"Review imported ({counts}). Inspect and commit the label/evidence/version diff.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
