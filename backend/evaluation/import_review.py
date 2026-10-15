"""Import domain-reviewed CSV rows, validating everything before writing.

Requires an explicit dataset version change. This command never approves rows
automatically and never reads extraction predictions. Use --check for a dry run.
"""

import argparse
import csv
import json
import tempfile
from pathlib import Path

from backend.evaluation.dataset import DEFAULT_ROOT, load_dataset, read_json


def import_review(root: Path, csv_path: Path, new_version: str, *, check: bool = False) -> None:
    original = load_dataset(root)
    if not new_version.strip() or new_version == original.version:
        raise ValueError("Specify a new dataset version for the reviewed labels")
    config = read_json(root / "inputs/cases.json")
    labels = read_json(root / "ground_truth/labels.json")
    evidence = read_json(root / "ground_truth/evidence.json")
    expected = {(cid, name) for cid, fields in labels["cases"].items() for name in fields}
    seen = set()
    with csv_path.open(newline="", encoding="utf-8-sig") as source:
        for row in csv.DictReader(source):
            key = (row["case_id"], row["field"])
            if key not in expected or key in seen:
                raise ValueError(f"Unknown or duplicate review row: {key}")
            seen.add(key)
            cid, name = key
            gold = labels["cases"][cid][name]
            gold.update(status=row["status"], value=json.loads(row["expected_value"]), unit=row["unit"],
                        review_status=row["review_status"], reviewer=row["reviewer"].strip() or None,
                        reviewed_at=row["reviewed_at"].strip() or None)
            candidates = json.loads(row["candidates"])
            if candidates is None:
                gold.pop("candidates", None)
            else:
                gold["candidates"] = candidates
            evidence[cid][name] = {"locations": json.loads(row["evidence"]), "review_note": row["review_note"]}
    if seen != expected:
        raise ValueError("Review CSV omitted rows")
    config["dataset_version"] = labels["dataset_version"] = new_version
    updates = {"inputs/cases.json": config, "ground_truth/labels.json": labels, "ground_truth/evidence.json": evidence}
    # Stage a complete metadata snapshot so bad dates, units, evidence,
    # split leakage, or invalid states cannot partially overwrite gold files.
    with tempfile.TemporaryDirectory() as directory:
        staged = Path(directory)
        for name, payload in {**updates, "inputs/manifest.json": list(original.documents.values())}.items():
            path = staged / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        load_dataset(staged)
        if check:
            return
        for name in updates:
            path = root / name
            temporary = path.with_suffix(".json.tmp")
            temporary.write_bytes((staged / name).read_bytes())
            temporary.replace(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    try:
        import_review(args.dataset, args.csv or args.dataset / "ground_truth/review.csv", args.version, check=args.check)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    print("Review validated." if args.check else "Review imported. Inspect and commit the label/evidence/version diff.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
