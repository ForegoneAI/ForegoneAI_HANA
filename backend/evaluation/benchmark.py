"""M1.5: run production extraction or replay saved predictions and score M1.4.

One command from the repository root:
    python -m backend.evaluation.evaluate --allow-draft
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import statistics
import subprocess
import time
import uuid
from functools import partial
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from backend.evaluation.dataset import DEFAULT_ROOT, approved, load_dataset, read_json, sha256
from backend.evaluation.scoring import model_cost, ratio, score_case, summarize

DEFAULT_ADAPTER = "backend.evaluation.hana_adapter:extract"
REPO_ROOT = Path(__file__).resolve().parents[2]


def provenance() -> dict:
    def git(*args):
        try:
            result = subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5)
            return result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    packages = {}
    for name in ("pymupdf", "pydantic", "anthropic"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    # Exclude private input paths and filenames from repository provenance.
    status = git("status", "--porcelain", "--untracked-files=normal")
    return {"git_commit": git("rev-parse", "HEAD"), "git_dirty": bool(status) if status is not None else None,
            "package_versions": packages}


def validate_thresholds(rules: dict) -> None:
    allowed = set(summarize([])) - {"counts"}
    allowed |= {"macro_case_accuracy", "latency_mean_seconds", "latency_p95_seconds", "approx_model_cost_usd",
                "known_partial_model_cost_usd", "cost_coverage", "latency_coverage", "case_error_rate", "unexpected_field_count"}
    if not isinstance(rules, dict):
        raise ValueError("Thresholds must be a metric-to-rule object")
    for name, rule in rules.items():
        if name not in allowed or not isinstance(rule, dict) or not rule or set(rule) - {"min", "max"}:
            raise ValueError(f"Invalid threshold rule: {name}")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in rule.values()):
            raise ValueError(f"Non-numeric threshold: {name}")
        if "min" in rule and "max" in rule and rule["min"] > rule["max"]:
            raise ValueError(f"Inverted threshold: {name}")


def run(dataset, cases: list[dict], *, adapter=None, cached=None, pricing=None, thresholds=None) -> tuple[dict, dict]:
    results, predictions, all_rows = [], {}, []
    for case in cases:
        cid = case["case_id"]
        start = time.perf_counter()
        error = None
        pred = {"fields": {}}
        try:
            if adapter:
                pred = adapter(dataset.payload(case))
            else:
                if cid not in cached:
                    raise ValueError("Saved predictions omitted case")
                pred = cached[cid]
            if not isinstance(pred, dict) or not isinstance(pred.get("fields"), dict):
                raise ValueError("Prediction must contain a fields object")
            if any(not isinstance(name, str) for name in pred["fields"]):
                raise ValueError("Prediction field names must be strings")
            # Non-JSON model objects/NaN are controlled case failures, not a
            # crash after an otherwise expensive batch has finished.
            json.dumps(pred, allow_nan=False)
            if pred.get("error"):
                error = str(pred["error"])
        except Exception as exc:  # Batch isolation; every failed case is scored.
            pred = {"fields": {}}
            error = f"{type(exc).__name__}: {exc}"
        latency = time.perf_counter() - start if adapter else pred.get("latency_seconds")
        if type(latency) not in (int, float) or not math.isfinite(latency) or latency < 0:
            latency = None
        pred["latency_seconds"] = latency
        if error:
            pred["error"] = error
        # A partial result with an error cannot earn accuracy, and its billed
        # usage is a lower bound only (provider failures may omit token data).
        scored = {"fields": {}} if error else pred
        rows, extras = score_case(scored, dataset.labels[cid], dataset.evidence[cid])
        all_rows.extend(rows)
        partial_cost = model_cost(pred, pricing or {})
        results.append({"case_id": cid, "metrics": summarize(rows), "latency_seconds": latency,
                        "approx_model_cost_usd": partial_cost if not error else None,
                        "known_partial_model_cost_usd": partial_cost,
                        "error": error, "unexpected_fields": extras, "fields": rows,
                        "extraction_metadata": pred.get("metadata", {})})
        predictions[cid] = pred
    metrics = summarize(all_rows)
    latencies = [r["latency_seconds"] for r in results if r["latency_seconds"] is not None]
    costs = [r["approx_model_cost_usd"] for r in results if r["approx_model_cost_usd"] is not None]
    partial = [r["known_partial_model_cost_usd"] for r in results if r["known_partial_model_cost_usd"] is not None]
    metrics.update({
        "macro_case_accuracy": statistics.mean(r["metrics"]["field_accuracy"] for r in results),
        "latency_mean_seconds": statistics.mean(latencies) if latencies else None,
        "latency_p95_seconds": sorted(latencies)[math.ceil(.95 * len(latencies)) - 1] if latencies else None,
        "latency_coverage": ratio(len(latencies), len(results)),
        "approx_model_cost_usd": sum(costs) if len(costs) == len(results) else None,
        "known_partial_model_cost_usd": sum(partial), "cost_coverage": ratio(len(costs), len(results)),
        "case_error_rate": ratio(sum(r["error"] is not None for r in results), len(results)),
        "unexpected_field_count": sum(len(r["unexpected_fields"]) for r in results),
    })
    failures = [key for key, rule in (thresholds or {}).items()
                if metrics.get(key) is None or ("min" in rule and metrics[key] < rule["min"])
                or ("max" in rule and metrics[key] > rule["max"])]
    return {"metrics": metrics, "threshold_failures": failures, "cases": results}, predictions


def write_report(out: Path, report: dict, predictions: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, value in (("report.json", report), ("predictions.json", predictions)):
        (out / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["# Extraction evaluation", f"\nStatus: **{report['label_status']}** | Split: {report['split']}",
             f"\nDataset: {report['dataset_version']} | Run: {report['run_id']}", "\n| Metric | Value |", "|---|---|"]
    for key, value in report["metrics"].items():
        if key != "counts":
            lines.append(f"| {key} | {value if value is not None else 'N/A'} |")
    lines += ["\n## Cases", "| Case | Accuracy | Latency (s) | Model cost (USD) | Error |", "|---|---:|---:|---:|---|"]
    for case in report["cases"]:
        error = (case["error"] or "").replace("|", "/").replace("\n", " ")
        lines.append(f"| {case['case_id']} | {case['metrics']['field_accuracy']:.3f} | {case['latency_seconds']} | {case['approx_model_cost_usd']} | {error} |")
    for case in report["cases"]:
        metadata = case["extraction_metadata"]
        if isinstance(metadata, dict) and metadata.get("unsupported_schema_fields"):
            lines.append(f"\nUnmapped fields ({case['case_id']}): {metadata['unsupported_schema_fields']}\n")
    lines += ["\n## Interpretation"] + ["- " + item for item in report["limitations"]]
    lines += ["\nThreshold failures: " + (", ".join(report["threshold_failures"]) or "none / no thresholds supplied")]
    (out / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--split", choices=["dev", "holdout", "diagnostic"], default="dev")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--adapter", help=f"module:function (default: {DEFAULT_ADAPTER})")
    mode.add_argument("--predictions", type=Path, help="Replay a saved predictions.json without model calls")
    parser.add_argument("--provider", choices=["anthropic", "openrouter"], help="Extraction provider for the production adapter")
    parser.add_argument("--model", help="Model ID for the production adapter; use author/model for OpenRouter")
    parser.add_argument("--pricing", type=Path)
    parser.add_argument("--thresholds", type=Path)
    parser.add_argument("--allow-draft", action="store_true")
    parser.add_argument("--unlock-holdout", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if (args.model or args.provider) and (args.predictions or (args.adapter and args.adapter != DEFAULT_ADAPTER)):
        parser.error("--provider and --model apply to the production extraction adapter only.")
    if args.split == "holdout" and not args.unlock_holdout:
        parser.error("Holdout is locked. Freeze prompts/models, then pass --unlock-holdout.")
    try:
        dataset = load_dataset(args.dataset)
        cases = dataset.select(args.split)
        is_approved = all(approved(g) for case in cases for g in dataset.labels[case["case_id"]].values())
        if not is_approved and not args.allow_draft:
            parser.error("Labels await domain approval; use --allow-draft for provisional reports.")
        thresholds = read_json(args.thresholds) if args.thresholds else {}
        validate_thresholds(thresholds)
        pricing = read_json(args.pricing) if args.pricing else {}
        if not isinstance(pricing, dict):
            raise ValueError("Pricing must be a model-to-rates object")
        cached = read_json(args.predictions) if args.predictions else {}
        if not isinstance(cached, dict):
            raise ValueError("Saved predictions must map case IDs to predictions")
        adapter, adapter_name = None, args.adapter or DEFAULT_ADAPTER
        if not args.predictions:
            dataset.verify_sources(cases)
            module, name = adapter_name.rsplit(":", 1)
            adapter = getattr(importlib.import_module(module), name)
            if not callable(adapter):
                raise ValueError("Adapter must be callable")
            options = {}
            if args.provider:
                options["provider"] = args.provider
            if args.model:
                options["model"] = args.model
            elif args.provider:
                from backend.app.h9n.extraction.repe_extractor import (
                    DEFAULT_ANTHROPIC_MODEL, DEFAULT_MODEL, DEFAULT_OPENROUTER_MODEL,
                )
                configured_provider = os.environ.get("H9N_EXTRACTION_PROVIDER", "anthropic").strip().lower()
                options["model"] = DEFAULT_MODEL if args.provider == configured_provider else (
                    DEFAULT_OPENROUTER_MODEL if args.provider == "openrouter" else DEFAULT_ANTHROPIC_MODEL
                )
            if options:
                adapter = partial(adapter, **options)
    except (ValueError, KeyError, TypeError, OSError, ImportError, AttributeError) as exc:
        parser.error(str(exc))
    # Fingerprint labels before extraction so a long run cannot silently
    # attach metadata for a changed answer key to its in-memory labels.
    paths = ["ground_truth/labels.json", "ground_truth/evidence.json", "inputs/cases.json", "inputs/manifest.json"]
    hashes = {name: sha256(dataset.root / name) for name in paths}
    context = provenance()
    report, predictions = run(dataset, cases, adapter=adapter, cached=cached, pricing=pricing, thresholds=thresholds)
    report.update({
        "run_id": str(uuid.uuid4()), "dataset_version": dataset.version, "split": args.split,
        "label_status": "domain_approved" if is_approved else "DRAFT_NOT_DOMAIN_APPROVED",
        "run_kind": "live_adapter" if adapter else "saved_predictions", "adapter": adapter_name if adapter else None,
        "requested_provider": args.provider, "requested_model": args.model,
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "provenance": context,
        "dataset_sha256": hashes, "pricing": pricing, "thresholds": thresholds,
        "predictions_source_sha256": sha256(args.predictions) if args.predictions else None,
        "limitations": [
            "Draft labels are provisional until the domain team approves them; holdout novelty needs team confirmation.",
            "Reference disagreement is a proxy for unsupported extraction, not a semantic entailment judgment.",
            "Evidence scoring checks exact physical PDF pages or workbook cells, not quote entailment.",
            "Omitted fields and failed cases are scored as failures, not successful missing detections.",
            "Latency includes parsing/extraction; replay uses saved latency. p95 is unstable for small sets.",
            "Cost uses reported model tokens and supplied rates; unknown cost is null. Failed-run cost is partial.",
            "Reports contain answer keys; keep holdout reports outside prompt tuning and retrieval indexes.",
        ],
    })
    out = args.out or Path(__file__).parent / "reports" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + report["run_id"][:8])
    write_report(out, report, predictions)
    print(json.dumps({"status": report["label_status"], "metrics": report["metrics"], "report": str(out / "report.md")}, indent=2))
    return int(bool(report["threshold_failures"] or any(c["error"] or c["unexpected_fields"] for c in report["cases"])))


if __name__ == "__main__":
    raise SystemExit(main())
