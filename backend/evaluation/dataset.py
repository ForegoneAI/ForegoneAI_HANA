"""Versioned labels/evidence and leakage checks for M1.4.

Raw sources are local snapshots. Metadata and answer keys can be versioned
separately; adapters receive only case specifications and source paths.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from backend.evaluation.scoring import location_key

DEFAULT_ROOT = Path(__file__).parent / "benchmark_data"


def read_json(path: Path):
    """Reject nonstandard JSON NaN/Infinity, including in saved predictions."""
    def invalid(value: str):
        raise ValueError(f"Non-finite JSON number: {value}")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid, object_pairs_hook=unique)


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def approved(label: dict) -> bool:
    reviewer, reviewed_at = label.get("reviewer"), label.get("reviewed_at")
    if label.get("review_status") != "approved" or not isinstance(reviewer, str) or not reviewer.strip():
        return False
    try:
        return isinstance(reviewed_at, str) and date.fromisoformat(reviewed_at).isoformat() == reviewed_at
    except ValueError:
        return False


@dataclass
class Dataset:
    root: Path
    version: str
    cases: list[dict]
    documents: dict[str, dict]
    labels: dict
    evidence: dict

    def select(self, split: str) -> list[dict]:
        cases = [case for case in self.cases if case["split"] == split]
        if not cases:
            raise ValueError(f"No cases in split {split!r}")
        return cases

    def verify_sources(self, cases: list[dict]) -> None:
        # A dev run need not mount holdout documents. Metadata leakage checks
        # still cover the entire manifest before any selected input is read.
        for did in {did for case in cases for did in case["documents"]}:
            doc = self.documents[did]
            path = self.root / doc["path"]
            if not path.is_file():
                raise ValueError(f"Missing source {did}: restore inputs from HANA_M1_Benchmark_Pack.zip to {self.root}")
            if sha256(path) != doc["sha256"]:
                raise ValueError(f"Source checksum mismatch: {did}")

    def payload(self, case: dict) -> dict:
        # Explicit allowlist rather than copying arbitrary dataset properties:
        # future review notes/expected values cannot accidentally reach the LLM.
        return {
            "case_id": case["case_id"], "family_id": case["family_id"],
            "split": case["split"], "kind": case["kind"],
            "requested_fields": {name: {"unit": spec["unit"], "description": spec["description"]}
                                 for name, spec in case["requested_fields"].items()},
            "documents": [{"document_id": did, "path": str((self.root / self.documents[did]["path"]).resolve())}
                          for did in case["documents"]],
        }


def load_dataset(root: Path = DEFAULT_ROOT) -> Dataset:
    root = root.resolve()
    config = read_json(root / "inputs/cases.json")
    label_file = read_json(root / "ground_truth/labels.json")
    evidence = read_json(root / "ground_truth/evidence.json")
    manifest = read_json(root / "inputs/manifest.json")
    if not config.get("dataset_version") or config["dataset_version"] != label_file.get("dataset_version"):
        raise ValueError("Dataset versions in cases and labels must match")
    documents = {doc["document_id"]: doc for doc in manifest}
    if len(documents) != len(manifest):
        raise ValueError("Duplicate document IDs")
    for doc in documents.values():
        path = (root / doc["path"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("Source outside benchmark root")
        if not re.fullmatch(r"[a-f0-9]{64}", doc["sha256"]):
            raise ValueError("Invalid source SHA-256")

    cases, labels = config["cases"], label_file["cases"]
    ids = [case["case_id"] for case in cases]
    if len(set(ids)) != len(ids) or set(ids) != set(labels) or set(ids) != set(evidence):
        raise ValueError("Case IDs must be unique and match labels/evidence")
    families, hash_splits = {}, {}
    for case in cases:
        cid, split, family = case["case_id"], case["split"], case["family_id"]
        if split not in ("dev", "holdout", "diagnostic"):
            raise ValueError("Invalid split")
        if family in families and families[family] != split:
            raise ValueError("Family split leakage")
        families[family] = split
        if not case["documents"] or len(set(case["documents"])) != len(case["documents"]):
            raise ValueError("Case needs unique source document IDs")
        if not case["requested_fields"] or set(case["requested_fields"]) != set(labels[cid]) or set(labels[cid]) != set(evidence[cid]):
            raise ValueError("Field/evidence schema mismatch")
        for did in case["documents"]:
            digest = documents[did]["sha256"]
            if digest in hash_splits and hash_splits[digest] != split:
                raise ValueError("Duplicate source split leakage")
            hash_splits[digest] = split
        for name, gold in labels[cid].items():
            locs = evidence[cid][name]["locations"]
            status, value = gold["status"], gold["value"]
            tolerance = gold["abs_tolerance"]
            if status not in ("present", "missing", "conflict"):
                raise ValueError("Invalid label status")
            if not isinstance(gold.get("unit"), str) or not gold["unit"] or gold["unit"] != case["requested_fields"][name]["unit"]:
                raise ValueError("Label/spec unit mismatch")
            if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance < 0:
                raise ValueError("Invalid tolerance")
            if status == "present" and (value is None or gold.get("candidates")):
                raise ValueError("Present label requires value and no candidates")
            if status == "conflict":
                candidates = gold.get("candidates")
                if value is not None or not isinstance(candidates, list) or len(candidates) < 2 or any(v is None for v in candidates):
                    raise ValueError("Conflict requires null value and multiple candidates")
            if status == "missing" and (value is not None or locs or gold.get("candidates")):
                raise ValueError("Malformed missing label")
            if not isinstance(locs, list) or (status != "missing" and not locs):
                raise ValueError("Missing evidence")
            for loc in locs:
                if location_key(loc) is None or loc["document_id"] not in case["documents"]:
                    raise ValueError("Invalid evidence locator")
                suffix = Path(documents[loc["document_id"]]["path"]).suffix.lower()
                if ("page" in loc and suffix != ".pdf") or ("cell" in loc and suffix != ".xlsx"):
                    raise ValueError("Evidence type does not match source")
                if "cell" in loc and not re.fullmatch(r"[A-Za-z]+[1-9][0-9]*", loc["cell"]):
                    raise ValueError("Invalid workbook cell")
            if gold["review_status"] not in ("pending_domain_review", "approved"):
                raise ValueError("Invalid review status")
            if gold["review_status"] == "approved" and not approved(gold):
                raise ValueError("Approval requires reviewer and ISO review date")
    return Dataset(root, config["dataset_version"], cases, documents, labels, evidence)
