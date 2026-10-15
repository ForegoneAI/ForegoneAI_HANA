"""M1.5: run production extraction or replay saved predictions and score M1.4.

One command from the repository root:
    python -m backend.evaluation.evaluate --allow-draft
"""

from __future__ import annotations

import argparse
import importlib
import json
import math
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
# Published per-million-token list prices for the default models, used when
# --pricing isn't given so one command reports approximate cost. Unpriced
# models stay unknown (null), never free; see evaluation/README.md.
DEFAULT_PRICING = Path(__file__).parent / "pricing.json"
# Reference-field metrics repeated in the flat metrics table.
REFERENCE_METRICS = ("field_accuracy", "grounded_accuracy", "output_coverage")


def unsupported_fields(pred: dict) -> set[str]:
    """Fields the adapter declared it cannot express. A production-scope
    field in this set is a mapping gap (reported), not a model error."""
    metadata = pred.get("metadata")
    names = metadata.get("unsupported_schema_fields") if isinstance(metadata, dict) else None
    return {n for n in names if isinstance(n, str)} if isinstance(names, list) else set()


def production(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["scope"] == "production"]


def reference(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["scope"] == "reference"]


def unpriced_models(predictions: dict, pricing: dict) -> list[str]:
    """Reported models with no rate, either under their own name or (as
    model_cost falls back to) the model that was requested."""
    missing = set()
    for pred in predictions.values():
        for call in pred.get("usage") or []:
            if not isinstance(call, dict) or not isinstance(call.get("model"), str):
                continue
            if not any(isinstance(pricing.get(name), dict) for name in (call["model"], call.get("requested_model"))
                       if isinstance(name, str)):
                missing.add(call["model"])
    return sorted(missing)


def resumable(saved: dict, cid: str) -> dict | None:
    """A completed, error-free prediction from an interrupted run."""
    pred = saved.get(cid) if isinstance(saved, dict) else None
    return pred if isinstance(pred, dict) and isinstance(pred.get("fields"), dict) and not pred.get("error") else None


def write_json_atomic(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


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
                "known_partial_model_cost_usd", "cost_coverage", "latency_coverage", "case_error_rate", "unexpected_field_count",
                "production_field_share", "mapping_gap_count"} | {"reference_" + name for name in REFERENCE_METRICS}
    if not isinstance(rules, dict):
        raise ValueError("Thresholds must be a metric-to-rule object")
    for name, rule in rules.items():
        if name not in allowed or not isinstance(rule, dict) or not rule or set(rule) - {"min", "max"}:
            raise ValueError(f"Invalid threshold rule: {name}")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in rule.values()):
            raise ValueError(f"Non-numeric threshold: {name}")
        if "min" in rule and "max" in rule and rule["min"] > rule["max"]:
            raise ValueError(f"Inverted threshold: {name}")


def run(dataset, cases: list[dict], *, adapter=None, cached=None, pricing=None, thresholds=None,
        resume=None, on_prediction=None) -> tuple[dict, dict]:
    """`resume` reuses completed cases of an interrupted live run instead of
    paying for them again; `on_prediction` sees the predictions after every
    case so a crash or Ctrl-C keeps what has been extracted so far."""
    results, predictions, all_rows = [], {}, []
    for case in cases:
        cid = case["case_id"]
        start = time.perf_counter()
        error = None
        pred = {"fields": {}}
        reused = resumable(resume, cid) if adapter else None
        try:
            if reused is not None:
                pred = reused
            elif adapter:
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
        latency = time.perf_counter() - start if adapter and reused is None else pred.get("latency_seconds")
        if type(latency) not in (int, float) or not math.isfinite(latency) or latency < 0:
            latency = None
        pred["latency_seconds"] = latency
        if error:
            pred["error"] = error
        # A partial result with an error cannot earn accuracy, and its billed
        # usage is a lower bound only (provider failures may omit token data).
        scored = {"fields": {}} if error else pred
        rows, extras = score_case(scored, dataset.labels[cid], dataset.evidence[cid])
        unsupported = unsupported_fields(pred)
        for row in rows:
            row["scope"] = dataset.scope(cid, row["field"])
        gaps = sorted(r["field"] for r in production(rows) if r["field"] in unsupported)
        all_rows.extend(rows)
        partial_cost = model_cost(pred, pricing or {})
        results.append({"case_id": cid, "metrics": summarize(production(rows)),
                        "reference_metrics": summarize(reference(rows)), "mapping_gaps": gaps,
                        "latency_seconds": latency,
                        "approx_model_cost_usd": partial_cost if not error else None,
                        "known_partial_model_cost_usd": partial_cost,
                        "error": error, "unexpected_fields": extras, "fields": rows,
                        "extraction_metadata": pred.get("metadata", {})})
        predictions[cid] = pred
        if on_prediction:
            on_prediction(predictions)
    # Headline metrics count only production fields: what H9N's extractor is
    # meant to produce. Reference fields (labelled facts with no profile
    # field) are reported separately and never drag the score down.
    metrics = summarize(production(all_rows))
    latencies = [r["latency_seconds"] for r in results if r["latency_seconds"] is not None]
    costs = [r["approx_model_cost_usd"] for r in results if r["approx_model_cost_usd"] is not None]
    partial = [r["known_partial_model_cost_usd"] for r in results if r["known_partial_model_cost_usd"] is not None]
    metrics.update({
        "macro_case_accuracy": statistics.mean(scores) if (scores := [
            r["metrics"]["field_accuracy"] for r in results if r["metrics"]["field_accuracy"] is not None]) else None,
        "latency_mean_seconds": statistics.mean(latencies) if latencies else None,
        "latency_p95_seconds": sorted(latencies)[math.ceil(.95 * len(latencies)) - 1] if latencies else None,
        "latency_coverage": ratio(len(latencies), len(results)),
        "approx_model_cost_usd": sum(costs) if len(costs) == len(results) else None,
        "known_partial_model_cost_usd": sum(partial), "cost_coverage": ratio(len(costs), len(results)),
        "case_error_rate": ratio(sum(r["error"] is not None for r in results), len(results)),
        "unexpected_field_count": sum(len(r["unexpected_fields"]) for r in results),
    })
    reference_summary = summarize(reference(all_rows))
    metrics["production_field_share"] = ratio(len(production(all_rows)), len(all_rows))
    metrics["mapping_gap_count"] = sum(len(r["mapping_gaps"]) for r in results)
    metrics.update({"reference_" + name: reference_summary[name] for name in REFERENCE_METRICS})
    failures = [key for key, rule in (thresholds or {}).items()
                if metrics.get(key) is None or ("min" in rule and metrics[key] < rule["min"])
                or ("max" in rule and metrics[key] > rule["max"])]
    return {"metrics": metrics, "reference_fields": reference_summary, "threshold_failures": failures,
            "cases": results}, predictions


def compare(report: dict, baseline: dict) -> dict:
    """Metric deltas and per-field flips against an earlier report.json, so a
    rerun after a prompt/model change shows exactly what moved."""
    warnings = []
    for key in ("dataset_version", "split", "dataset_sha256"):
        if baseline.get(key) != report.get(key):
            warnings.append(f"{key} differs from the baseline; deltas may not be like-for-like.")
    deltas = {}
    for key, value in report["metrics"].items():
        old = baseline.get("metrics", {}).get(key)
        if type(value) in (int, float) and type(old) in (int, float):
            deltas[key] = {"baseline": old, "current": value, "delta": value - old}
        elif key != "counts":
            deltas[key] = {"baseline": old, "current": value, "delta": None}

    def outcomes(source: dict) -> dict:
        return {(case.get("case_id"), row.get("field")): (row.get("value_correct"), row.get("evidence_correct"))
                for case in source.get("cases", []) if isinstance(case, dict)
                for row in case.get("fields", []) if isinstance(row, dict)}

    before, after = outcomes(baseline), outcomes(report)
    flips = [{"case_id": cid, "field": name, "baseline_value_correct": before[(cid, name)][0],
              "value_correct": after[(cid, name)][0], "baseline_evidence_correct": before[(cid, name)][1],
              "evidence_correct": after[(cid, name)][1]}
             for cid, name in sorted(set(before) & set(after)) if before[(cid, name)] != after[(cid, name)]]
    return {"baseline_run_id": baseline.get("run_id"), "baseline_model": baseline.get("requested_model"),
            "warnings": warnings, "metric_deltas": deltas, "field_changes": flips}


def _fmt(value) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.4f}" if abs(value) < 1 else f"{value:.3f}"
    return str(value)


def _cell(value) -> str:
    text = json.dumps(value) if not isinstance(value, str) else value
    return text.replace("|", "/").replace("\n", " ")


def write_report(out: Path, report: dict, predictions: dict) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for name, value in (("report.json", report), ("predictions.json", predictions)):
        write_json_atomic(out / name, value)
    model = report.get("requested_model") or (report["cases"][0]["extraction_metadata"].get("requested_model")
                                              if report["cases"] and isinstance(report["cases"][0]["extraction_metadata"], dict) else None)
    lines = ["# Extraction evaluation", f"\nStatus: **{report['label_status']}** | Split: {report['split']}",
             f"\nDataset: {report['dataset_version']} | Run: {report['run_id']} | Model: {model or 'N/A'}",
             "\n| Metric | Value |", "|---|---|"]
    for key, value in report["metrics"].items():
        if key != "counts":
            lines.append(f"| {key} | {_fmt(value)} |")
    counts = report["metrics"].get("counts", {})
    lines.append(f"\nScores count the {counts.get('fields', 0)} production fields (named after REPEDealProfile fields). "
                 f"`reference_*` covers labelled facts the extractor has no field for; they never lower the score.")
    gaps = [f"{c['case_id']}.{f}" for c in report["cases"] for f in c.get("mapping_gaps", [])]
    if gaps:
        lines.append(f"\n**Mapping gaps** (production fields the adapter didn't map; scored as wrong): {', '.join(gaps)}")
    if report.get("unpriced_models"):
        lines.append(f"\nNo pricing for: {', '.join(report['unpriced_models'])}. Add rates with --pricing to report cost.")
    lines += ["\n## Cases", "| Case | Production fields | Accuracy | Reference fields | Latency (s) | Model cost (USD) | Error |",
              "|---|---:|---:|---:|---:|---:|---|"]
    for case in report["cases"]:
        lines.append(f"| {case['case_id']} | {case['metrics']['counts']['fields']} | {_fmt(case['metrics']['field_accuracy'])} | "
                     f"{case['reference_metrics']['counts']['fields']} | {_fmt(case['latency_seconds'])} | "
                     f"{_fmt(case['approx_model_cost_usd'])} | {_cell(case['error'] or '')} |")
    comparison = report.get("comparison")
    if comparison:
        lines += [f"\n## Compared with run {comparison['baseline_run_id']} ({comparison['baseline_model'] or 'model N/A'})"]
        lines += ["- " + w for w in comparison["warnings"]]
        lines += ["\n| Metric | Baseline | Current | Change |", "|---|---:|---:|---:|"]
        for key, row in comparison["metric_deltas"].items():
            delta = row["delta"]
            lines.append(f"| {key} | {_fmt(row['baseline'])} | {_fmt(row['current'])} | "
                         f"{'N/A' if delta is None else ('+' if delta > 0 else '') + _fmt(delta)} |")
        if comparison["field_changes"]:
            lines += ["\n| Case | Field | Value correct (before → now) | Evidence correct (before → now) |", "|---|---|---|---|"]
            for flip in comparison["field_changes"]:
                lines.append(f"| {flip['case_id']} | {flip['field']} | {flip['baseline_value_correct']} → {flip['value_correct']} | "
                             f"{flip['baseline_evidence_correct']} → {flip['evidence_correct']} |")
        else:
            lines.append("\nNo field-level outcome changed.")
    lines += ["\n## Fields", "Expected values are answer keys: keep holdout reports out of prompt tuning."]
    for case in report["cases"]:
        lines += [f"\n### {case['case_id']}", "| Field | Expected | Predicted | Value | Evidence | Scope |",
                  "|---|---|---|:-:|:-:|:-:|"]
        for row in case["fields"]:
            exp, pred = row["expected"], row["prediction"]
            expected = exp["status"] if exp["status"] == "missing" else (
                exp.get("candidates") if exp["status"] == "conflict" else exp["value"])
            predicted = "(not returned)" if not isinstance(pred, dict) else (
                pred.get("status") if pred.get("value") is None and not pred.get("candidates")
                else pred.get("candidates") or pred.get("value"))
            lines.append(f"| {row['field']} | {_cell(expected)} | {_cell(predicted)} | {'✓' if row['value_correct'] else '✗'} | "
                         f"{'✓' if row['evidence_correct'] else '✗'} | {row['scope']} |")
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
    parser.add_argument("--resume", type=Path,
                        help="predictions.json from an interrupted live run; completed cases aren't extracted again")
    parser.add_argument("--provider", choices=["anthropic", "openrouter"], help="Extraction provider for the production adapter")
    parser.add_argument("--model", help="Model ID for the production adapter; use author/model for OpenRouter")
    pricing_group = parser.add_mutually_exclusive_group()
    pricing_group.add_argument("--pricing", type=Path, help=f"Model-to-rates JSON (default: {DEFAULT_PRICING.name})")
    pricing_group.add_argument("--no-pricing", action="store_true", help="Report cost as unknown")
    parser.add_argument("--compare", type=Path, help="Earlier report.json to show metric and field changes against")
    parser.add_argument("--thresholds", type=Path)
    parser.add_argument("--allow-draft", action="store_true")
    parser.add_argument("--unlock-holdout", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.resume and args.predictions:
        parser.error("--resume continues a live run; --predictions replays one. Use one of them.")
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
        pricing_path = None if args.no_pricing else (args.pricing or (DEFAULT_PRICING if DEFAULT_PRICING.is_file() else None))
        pricing = read_json(pricing_path) if pricing_path else {}
        if not isinstance(pricing, dict):
            raise ValueError("Pricing must be a model-to-rates object")
        baseline = read_json(args.compare) if args.compare else None
        if baseline is not None and (not isinstance(baseline, dict) or not isinstance(baseline.get("metrics"), dict)):
            raise ValueError("--compare needs a report.json written by this command")
        cached = read_json(args.predictions) if args.predictions else {}
        if not isinstance(cached, dict):
            raise ValueError("Saved predictions must map case IDs to predictions")
        resume = read_json(args.resume) if args.resume else None
        if resume is not None and not isinstance(resume, dict):
            raise ValueError("--resume needs a predictions.json written by this command")
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
                # Same rule production uses, so a run names the model it really called.
                from backend.app.h9n.extraction.repe_extractor import default_model_for
                options["model"] = default_model_for(args.provider)
            if resume and adapter_name == DEFAULT_ADAPTER:
                # Never mix two models' outputs in one report.
                from backend.app.h9n.extraction.repe_extractor import default_model_for
                model = options.get("model") or default_model_for(options.get("provider"))
                other = sorted({str(pred.get("metadata", {}).get("requested_model")) for cid, pred in resume.items()
                                if resumable(resume, cid) and pred.get("metadata", {}).get("requested_model") != model})
                if other:
                    raise ValueError(f"--resume file was extracted with {', '.join(other)}, not {model}")
            if options:
                adapter = partial(adapter, **options)
    except (ValueError, KeyError, TypeError, OSError, ImportError, AttributeError) as exc:
        parser.error(str(exc))
    # Fingerprint labels before extraction so a long run cannot silently
    # attach metadata for a changed answer key to its in-memory labels.
    paths = ["ground_truth/labels.json", "ground_truth/evidence.json", "inputs/cases.json", "inputs/manifest.json"]
    hashes = {name: sha256(dataset.root / name) for name in paths}
    context = provenance()
    run_id = str(uuid.uuid4())
    out = args.out or Path(__file__).parent / "reports" / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + run_id[:8])
    # Saved after every case: a crash, timeout or Ctrl-C mid-run keeps the
    # paid-for extractions, and --resume picks up from this file.
    save_progress = (lambda predictions: write_json_atomic(out / "predictions.json", predictions)) if adapter else None
    report, predictions = run(dataset, cases, adapter=adapter, cached=cached, pricing=pricing, thresholds=thresholds,
                              resume=resume, on_prediction=save_progress)
    report.update({
        "run_id": run_id, "resumed_cases": sorted(c["case_id"] for c in cases if adapter and resumable(resume, c["case_id"])),
        "dataset_version": dataset.version, "split": args.split,
        "label_status": "domain_approved" if is_approved else "DRAFT_NOT_DOMAIN_APPROVED",
        "run_kind": "live_adapter" if adapter else "saved_predictions", "adapter": adapter_name if adapter else None,
        "requested_provider": args.provider, "requested_model": args.model,
        "created_at_utc": datetime.now(timezone.utc).isoformat(), "provenance": context,
        "dataset_sha256": hashes, "pricing": pricing, "thresholds": thresholds,
        "pricing_source": str(pricing_path) if pricing_path else None,
        "unpriced_models": unpriced_models(predictions, pricing),
        "predictions_source_sha256": sha256(args.predictions) if args.predictions else None,
        "limitations": [
            "Draft labels are provisional until the domain team approves them; holdout novelty needs team confirmation.",
            "Reference disagreement is a proxy for unsupported extraction, not a semantic entailment judgment.",
            "Evidence scoring checks exact physical PDF pages or workbook cells, not quote entailment.",
            "Omitted fields and failed cases are scored as failures, not successful missing detections.",
            "Latency includes parsing/extraction; replay uses saved latency. p95 is unstable for small sets.",
            "Cost uses reported model tokens and supplied rates; unknown cost is null. Failed-run cost is partial.",
            "Reports contain answer keys; keep holdout reports outside prompt tuning and retrieval indexes.",
            "Headline metrics cover production fields only; reference_* fields are labelled facts H9N has no field for.",
            "Few production fields are labelled until the domain team fills the to_label rows in review.csv.",
        ],
    })
    if baseline is not None:
        report["comparison"] = compare(report, baseline)
    write_report(out, report, predictions)
    print(json.dumps({"status": report["label_status"], "metrics": report["metrics"], "report": str(out / "report.md")}, indent=2))
    return int(bool(report["threshold_failures"] or any(c["error"] or c["unexpected_fields"] for c in report["cases"])))


if __name__ == "__main__":
    raise SystemExit(main())
