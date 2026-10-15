"""Benchmark integration tests stay offline and need no confidential inputs.

They verify leakage/approval guards, scoring denominators, production adapter
behavior, usage accounting, replay, and safe review imports, not model quality.
"""

import copy
import csv
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.app.h9n.extraction.repe_extractor import extract_repe_deal
from backend.app.h9n.extraction.telemetry import capture_model_usage
from backend.app.h9n.schemas.base_deal import WithheldValue
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.evaluation import hana_adapter
from backend.evaluation.benchmark import main, run, validate_thresholds
from backend.evaluation.dataset import DEFAULT_ROOT, load_dataset, sha256
from backend.evaluation.import_review import import_review
from backend.evaluation.scoring import model_cost, value_correct
from backend.evaluation.restore_inputs import restore
from backend.tests.extraction_fakes import evidence, fake_client, full_output, tool_response


@pytest.fixture
def dataset_root(tmp_path):
    """A tiny independent dataset exercises the runner without source PDFs."""
    (tmp_path / "inputs").mkdir()
    (tmp_path / "ground_truth").mkdir()
    source = tmp_path / "inputs/example.pdf"
    source.write_bytes(b"source snapshot for checksum testing")
    fields = {"asking_price": {"unit": "USD", "description": "Subject asking price"},
              "lp_return": {"unit": "ratio", "description": "Explicit LP return, if stated"}}
    cases = [{"case_id": "example", "family_id": "example", "split": "dev", "kind": "deal_package",
              "documents": ["example_doc"], "requested_fields": fields}]
    gold = {
        "asking_price": {"status": "present", "value": 100, "unit": "USD", "abs_tolerance": 0,
                         "review_status": "pending_domain_review", "reviewer": None, "reviewed_at": None},
        "lp_return": {"status": "missing", "value": None, "unit": "ratio", "abs_tolerance": 0,
                      "review_status": "pending_domain_review", "reviewer": None, "reviewed_at": None},
    }
    files = {
        "inputs/cases.json": {"dataset_version": "draft", "cases": cases},
        "inputs/manifest.json": [{"document_id": "example_doc", "path": "inputs/example.pdf", "sha256": sha256(source)}],
        "ground_truth/labels.json": {"dataset_version": "draft", "cases": {"example": gold}},
        "ground_truth/evidence.json": {"example": {
            "asking_price": {"locations": [{"document_id": "example_doc", "page": 3}]}, "lp_return": {"locations": []}}},
    }
    for name, payload in files.items():
        (tmp_path / name).write_text(json.dumps(payload))
    return tmp_path


def predictions():
    return {"example": {"fields": {
        "asking_price": {"status": "present", "value": 100, "unit": "USD", "evidence": [{"document_id": "example_doc", "page": 3}]},
        "lp_return": {"status": "missing", "value": None, "unit": "ratio", "evidence": []},
    }, "latency_seconds": 2.5, "execution_kind": "local_no_model", "usage": []}}


def edit(root, path, change):
    target = root / path
    data = json.loads(target.read_text())
    change(data)
    target.write_text(json.dumps(data))


def test_pack_metadata_has_five_families_and_two_reserved_cases():
    data = load_dataset()
    assert len(data.cases) == 6
    assert sum(len(fields) for fields in data.labels.values()) == 96
    assert len(data.select("holdout")) == 2
    assert len({c["family_id"] for c in data.cases if c["split"] != "diagnostic"}) == 5
    assert all(g["review_status"] == "pending_domain_review" for fs in data.labels.values() for g in fs.values())


def test_payload_is_blind_and_uses_absolute_paths(dataset_root):
    dataset = load_dataset(dataset_root)
    case = dataset.cases[0]
    case["expected"] = {"asking_price": 100}
    case["requested_fields"]["asking_price"]["review_note"] = "answer here"
    payload = dataset.payload(case)
    assert "expected" not in payload
    assert "review_note" not in payload["requested_fields"]["asking_price"]
    assert Path(payload["documents"][0]["path"]).is_absolute()
    payload["requested_fields"]["asking_price"]["unit"] = "bad"
    assert case["requested_fields"]["asking_price"]["unit"] == "USD"


def test_source_checksums_and_path_containment(dataset_root):
    dataset = load_dataset(dataset_root)
    dataset.verify_sources(dataset.cases)
    (dataset_root / "inputs/example.pdf").write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum mismatch"):
        dataset.verify_sources(dataset.cases)
    edit(dataset_root, "inputs/manifest.json", lambda m: m[0].update(path="../../outside.pdf"))
    with pytest.raises(ValueError, match="outside benchmark"):
        load_dataset(dataset_root)


@pytest.mark.parametrize("shared_family", [True, False])
def test_family_and_duplicate_hash_split_leakage(dataset_root, shared_family):
    def add_case(config):
        case = copy.deepcopy(config["cases"][0])
        case.update(case_id="holdout", split="holdout", family_id="example" if shared_family else "different")
        config["cases"].append(case)
    edit(dataset_root, "inputs/cases.json", add_case)
    edit(dataset_root, "ground_truth/labels.json", lambda g: g["cases"].update(holdout=copy.deepcopy(g["cases"]["example"])))
    edit(dataset_root, "ground_truth/evidence.json", lambda e: e.update(holdout=copy.deepcopy(e["example"])))
    with pytest.raises(ValueError, match="split leakage"):
        load_dataset(dataset_root)


def test_cli_draft_and_holdout_guard_run_before_extraction(dataset_root):
    with pytest.raises(SystemExit) as draft:
        main(["--dataset", str(dataset_root)])
    assert draft.value.code == 2
    with pytest.raises(SystemExit) as holdout:
        main(["--dataset", str(dataset_root), "--split", "holdout", "--allow-draft"])
    assert holdout.value.code == 2


def test_replay_preserves_latency_and_reports_metrics_without_raw_inputs(dataset_root):
    (dataset_root / "inputs/example.pdf").unlink()
    pred_file = dataset_root / "predictions.json"
    pred_file.write_text(json.dumps(predictions()))
    output = dataset_root / "output"
    assert main(["--dataset", str(dataset_root), "--predictions", str(pred_file), "--allow-draft", "--out", str(output)]) == 0
    report = json.loads((output / "report.json").read_text())
    saved = json.loads((output / "predictions.json").read_text())
    assert report["metrics"]["grounded_accuracy"] == 1
    assert report["metrics"]["latency_mean_seconds"] == 2.5
    assert report["metrics"]["approx_model_cost_usd"] == 0
    assert saved["example"]["latency_seconds"] == 2.5
    assert report["label_status"] == "DRAFT_NOT_DOMAIN_APPROVED"
    assert "git_commit" in report["provenance"]
    assert (output / "report.md").is_file()


def test_errors_and_omissions_cannot_improve_denominators(dataset_root):
    dataset = load_dataset(dataset_root)
    report, _ = run(dataset, dataset.cases, cached={})
    assert report["metrics"]["case_error_rate"] == 1
    assert report["metrics"]["field_accuracy"] == 0
    assert report["metrics"]["missing_detection_recall"] == 0
    assert report["metrics"]["approx_model_cost_usd"] is None
    partial = predictions()
    partial["example"]["error"] = "provider failed after partial extraction"
    report, _ = run(dataset, dataset.cases, cached=partial)
    assert report["metrics"]["field_accuracy"] == 0


def test_live_latency_is_saved_for_replay(dataset_root):
    dataset = load_dataset(dataset_root)
    report, saved = run(dataset, dataset.cases, adapter=lambda c: predictions()["example"])
    replay, _ = run(dataset, dataset.cases, cached=saved)
    assert replay["metrics"]["latency_mean_seconds"] == report["metrics"]["latency_mean_seconds"]


def test_failed_threshold_and_schema_extra_exit_nonzero(dataset_root):
    pred = predictions()
    pred["example"]["fields"]["unexpected"] = {"value": 123}
    pred_file = dataset_root / "predictions.json"
    pred_file.write_text(json.dumps(pred))
    threshold_file = dataset_root / "gates.json"
    threshold_file.write_text(json.dumps({"unexpected_field_count": {"max": 0}, "conflict_accuracy": {"min": 1}}))
    output = dataset_root / "out"
    assert main(["--dataset", str(dataset_root), "--predictions", str(pred_file), "--allow-draft",
                 "--thresholds", str(threshold_file), "--out", str(output)]) == 1
    report = json.loads((output / "report.json").read_text())
    assert set(report["threshold_failures"]) == {"unexpected_field_count", "conflict_accuracy"}


@pytest.mark.parametrize("rules", [{"typo": {"min": 1}}, {"field_accuracy": {}}, {"field_accuracy": {"min": True}},
                                  {"field_accuracy": {"min": 1, "max": 0}}])
def test_invalid_thresholds_fail_before_model_call(rules):
    with pytest.raises(ValueError):
        validate_thresholds(rules)


def test_conflict_requires_explicit_null():
    gold = {"status": "conflict", "value": None, "candidates": [100, 200], "unit": "USD", "abs_tolerance": 0}
    assert not value_correct({"status": "conflict", "candidates": [100, 200], "unit": "USD"}, gold)


def test_usage_capture_counts_repair_attempts_and_resets():
    first = tool_response({"asking_price": "bad"})
    second = tool_response(full_output())
    for response in (first, second):
        response.model = "test-model"
        response.usage = SimpleNamespace(input_tokens=10, output_tokens=5, cache_read_input_tokens=4, cache_creation_input_tokens=2)
    with capture_model_usage() as calls:
        extract_repe_deal([{"file_name": "fixture.pdf", "page_number": 1, "text": "No financial terms are stated."}],
                          client=fake_client(first, second))
    assert len(calls) == 2
    assert calls[0]["input_tokens"] == 16
    assert calls[0]["cached_input_tokens"] == 4
    rates = {"test-model": {"input_per_million": 2, "cached_input_per_million": 1,
                             "cache_creation_input_per_million": 3, "output_per_million": 4}}
    assert model_cost({"usage": calls}, rates) == pytest.approx(.0001)
    with capture_model_usage() as fresh:
        assert fresh == []
    assert len(calls) == 2


def test_unknown_or_malformed_usage_is_unknown_cost():
    for call in (None, {"model": []}, {"model": "x", "input_tokens": True, "output_tokens": 1}):
        assert model_cost({"usage": [call]}, {}) is None


def test_real_adapter_uses_production_integrity_and_page_identity(monkeypatch):
    pages = [{"file_name": "fixture.pdf", "page_number": 3, "text": "Asking price: $100.00"}]
    monkeypatch.setattr(hana_adapter, "read_pdf", lambda p: pages)
    response = tool_response(full_output(asking_price=100, evidence=[evidence("asking_price", 100, "Asking price: $100.00", page_number=3)]))
    response.usage = SimpleNamespace(input_tokens=10, output_tokens=5)
    case = {"documents": [{"document_id": "d", "path": "/local/fixture.pdf"}],
            "requested_fields": {"asking_price": {"unit": "USD"}, "lp_return": {"unit": "ratio"}}}
    result = hana_adapter.extract(case, client=fake_client(response))
    assert result["fields"]["asking_price"]["value"] == 100
    assert result["fields"]["asking_price"]["evidence"] == [{"document_id": "d", "page": 3}]
    assert "lp_return" not in result["fields"]
    assert result["usage"][0]["output_tokens"] == 5
    assert len(result["metadata"]["input_sha256"]) == 64


def test_withheld_and_incomplete_scope_are_never_missing():
    profile = REPEDealProfile(withheld_values=[WithheldValue(field_name="asking_price", proposed_value=100,
                               reason="model_conflicting", detail="Two prices")])
    case = {"documents": [], "requested_fields": {"asking_price": {"unit": "USD"}, "units": {"unit": "count"}}}
    fields = hana_adapter.profile_fields(profile, case, incomplete_scope=True)
    assert fields["asking_price"]["status"] == "conflict"
    assert "candidates" not in fields["asking_price"]
    assert fields["units"]["status"] == "uncertain"
    profile = REPEDealProfile(uncertain_information=["units: ambiguous count"])
    assert hana_adapter.profile_fields(profile, case, incomplete_scope=False)["units"]["status"] == "uncertain"


def test_percent_normalization_without_scenario_aliases():
    profile = REPEDealProfile(occupancy_rate=94, noi=100)
    case = {"documents": [], "requested_fields": {"occupancy": {"unit": "ratio"}, "current_noi": {"unit": "USD"}}}
    fields = hana_adapter.profile_fields(profile, case, incomplete_scope=False)
    assert fields["occupancy"]["value"] == pytest.approx(.94)
    assert "current_noi" not in fields


def test_workbook_only_case_is_controlled_error_without_calling_model():
    result = hana_adapter.extract({"documents": [{"document_id": "model", "path": "model.xlsx"}],
                                   "requested_fields": {"units": {"unit": "count"}}})
    assert "No supported PDF input" in result["error"]
    assert result["usage"] == []
    assert result["fields"] == {}


def review_csv(root, *, approved=False, date="2026-10-09"):
    dataset = load_dataset(root)
    path = root / "review.csv"
    columns = ["case_id", "field", "status", "expected_value", "unit", "candidates", "evidence", "review_note", "review_status", "reviewer", "reviewed_at"]
    with path.open("w", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()
        for cid, fields in dataset.labels.items():
            for name, label in fields.items():
                writer.writerow({"case_id": cid, "field": name, "status": label["status"], "expected_value": json.dumps(label["value"]),
                                 "unit": label["unit"], "candidates": "null", "evidence": json.dumps(dataset.evidence[cid][name]["locations"]),
                                 "review_note": "Reviewed source", "review_status": "approved" if approved else "pending_domain_review",
                                 "reviewer": "Domain Reviewer" if approved else "", "reviewed_at": date if approved else ""})
    return path


def test_review_import_validates_before_writing_and_versions_labels(dataset_root):
    path = review_csv(dataset_root, approved=True)
    before = (dataset_root / "ground_truth/labels.json").read_bytes()
    import_review(dataset_root, path, "1.0", check=True)
    assert (dataset_root / "ground_truth/labels.json").read_bytes() == before
    import_review(dataset_root, path, "1.0")
    dataset = load_dataset(dataset_root)
    assert dataset.version == "1.0"
    assert all(g["review_status"] == "approved" for g in dataset.labels["example"].values())


def test_invalid_approval_does_not_overwrite_labels(dataset_root):
    path = review_csv(dataset_root, approved=True, date="not-a-date")
    before = (dataset_root / "ground_truth/labels.json").read_bytes()
    with pytest.raises(ValueError, match="ISO review date"):
        import_review(dataset_root, path, "1.0")
    assert (dataset_root / "ground_truth/labels.json").read_bytes() == before


def test_review_import_requires_every_row(dataset_root):
    path = review_csv(dataset_root)
    path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n")
    with pytest.raises(ValueError, match="omitted rows"):
        import_review(dataset_root, path, "1.0")


def test_restoration_uses_manifest_checksums_and_does_not_import_zip_code(dataset_root):
    source = dataset_root / "inputs/example.pdf"
    original = source.read_bytes()
    archive = dataset_root / "pack.zip"
    with zipfile.ZipFile(archive, "w") as pack:
        pack.writestr("hana-benchmark/inputs/example.pdf", original)
        pack.writestr("../untrusted.py", "raise RuntimeError('do not execute')")
    source.unlink()
    restore(archive, dataset_root)
    assert source.read_bytes() == original
    assert not (dataset_root / "untrusted.py").exists()
    with zipfile.ZipFile(archive, "w") as pack:
        pack.writestr("hana-benchmark/inputs/example.pdf", b"incorrect source")
    with pytest.raises(ValueError, match="checksum mismatch"):
        restore(archive, dataset_root)
    assert source.read_bytes() == original


def test_cached_creation_requires_its_rate():
    call = {"model": "test", "input_tokens": 12, "output_tokens": 1, "cache_creation_input_tokens": 2}
    assert model_cost({"usage": [call]}, {"test": {"input_per_million": 1, "output_per_million": 1}}) is None


def test_nonfinite_live_prediction_is_controlled_case_failure(dataset_root):
    dataset = load_dataset(dataset_root)
    def bad_adapter(case):
        pred = predictions()["example"]
        pred["fields"]["asking_price"]["value"] = float("nan")
        return pred
    report, _ = run(dataset, dataset.cases, adapter=bad_adapter)
    assert report["metrics"]["case_error_rate"] == 1
    assert report["metrics"]["field_accuracy"] == 0


def test_real_adapter_keeps_usage_from_failed_output(monkeypatch):
    monkeypatch.setattr(hana_adapter, "read_pdf", lambda p: [{"file_name": "fixture.pdf", "page_number": 1, "text": "No terms."}])
    response = tool_response(full_output(), stop_reason="max_tokens")
    response.usage = SimpleNamespace(input_tokens=10, output_tokens=5)
    result = hana_adapter.extract({"documents": [{"document_id": "d", "path": "fixture.pdf"}],
                                   "requested_fields": {"asking_price": {"unit": "USD"}}}, client=fake_client(response))
    assert result["fields"] == {}
    assert result["usage"][0]["output_tokens"] == 5
    assert "ExtractionOutputError" in result["error"]


def test_cli_passes_model_and_provider_to_production_adapter(dataset_root, monkeypatch):
    calls = []
    def adapter(case, **options):
        calls.append(options)
        return predictions()["example"]
    monkeypatch.setattr(hana_adapter, "extract", adapter)
    assert main(["--dataset", str(dataset_root), "--allow-draft", "--provider", "openrouter",
                 "--model", "google/test-model", "--out", str(dataset_root / "out")]) == 0
    assert calls == [{"provider": "openrouter", "model": "google/test-model"}]
