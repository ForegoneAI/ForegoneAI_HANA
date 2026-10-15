# M1.4–M1.5 Benchmark

## What is implemented

- Integrated 96 checks across five deal families and a separate workbook diagnostic.
- Development cases: Roderick, Opulent, and Daly City. Reserved cases: Chicago
  and Corporate Place. Townhomes is the workbook diagnostic.
- Versioned case definitions, source hashes, labels, separate evidence, and a
  CSV review worksheet.
- A production PDF extraction adapter mapping existing property fields and
  preserving page identity, uncertainty, and conflict flags.
- Anthropic and OpenRouter provider selection with per-run model overrides.
- Field accuracy, missing detection, reference-based unsupported extraction
  rate, evidence-page/cell correctness, grounded accuracy, conflict accuracy,
  output coverage, and case-error metrics.
- Mean/p95 latency and model cost accounting across returned model responses,
  including schema-repair attempts.
- Saved-output replay, metric thresholds, dataset validation, and split checks.
- `in_scope_*` metrics for the fields the production schema can express, next
  to the headline metrics over every expected field.
- `--compare` against an earlier run: metric deltas and per-field flips.
- Default list-price pricing for the default models (`pricing.json`).
- Reports with run IDs, dataset/source hashes, Git revision, package versions,
  and production model/prompt/input metadata.

## Run evaluation

Run from the repository root after the [backend setup](../README.md#setup):

```bash
python -m backend.evaluation.evaluate --allow-draft --out backend/evaluation/reports/hana-dev
```

This uses the configured provider and `H9N_EXTRACTION_MODEL` to call the production
PDF extractor. `--allow-draft` enables scoring against the bundled draft labels.
Live evaluation makes billable model calls and saves reports locally. Restore
the source files first (see [Restore source files](#restore-source-files)).

After a prompt or model change, rerun and compare with the previous report:

```bash
python -m backend.evaluation.evaluate --allow-draft \
  --compare backend/evaluation/reports/hana-dev/report.json \
  --out backend/evaluation/reports/hana-dev-new-prompt
```

The comparison section of `report.md` lists every metric's change and every
field whose value or evidence outcome flipped. It warns when the dataset
version, split, or answer-key hashes differ from the baseline.

A live run saves `predictions.json` after every case. If it stops partway
(crash, timeout, Ctrl-C), rerun the same command with
`--resume <that predictions.json>`: finished cases are reused rather than paid
for again, and only failed or missing cases are extracted. A resume file
from a different model is refused.

`--provider` without `--model` uses that provider's default model.
`H9N_EXTRACTION_MODEL` applies only to the provider set in
`H9N_EXTRACTION_PROVIDER`, so an Anthropic model ID is never sent to
OpenRouter (or the reverse).

## Read the metrics

Headline metrics keep every expected field in the denominator, including
fields the production `REPEDealProfile` has no field for (for example
`lot15_pitch_land_cost` or `proforma_noi`). The adapter lists those as
`unsupported_schema_fields`, and the `in_scope_*` metrics repeat field
accuracy, grounded accuracy, evidence accuracy, and coverage for the rest.
`extractor_scope_share` is the fraction of expected fields in scope.

Dataset 0.1.0-draft has 14 in-scope fields out of 96, and only 4 of the 56
dev-split fields (all Daly City). Roderick and Opulent are development and
hospitality packages whose terms the REPE profile can't hold yet. Treat
`in_scope_*` as the signal for prompt/model changes, and grow it by adding
domain-reviewed rows named after profile fields (see
[Add fields](#add-fields)).

## Evaluate models with OpenRouter

Set your key in a local `.env` file:

```dotenv
OPENROUTER_API_KEY=your-openrouter-key
```

Select the provider and exact model ID for each run:

```bash
python -m backend.evaluation.evaluate \
  --provider openrouter --model google/gemini-2.5-flash \
  --allow-draft --out backend/evaluation/reports/gemini-flash

python -m backend.evaluation.evaluate \
  --provider openrouter --model anthropic/claude-sonnet-4.5 \
  --allow-draft --out backend/evaluation/reports/claude-sonnet
```

Choose a model supporting [tool calling](https://openrouter.ai/docs/guides/features/tool-calling).
Each run uses the same benchmark, Pydantic validation, citation checks, and
retry rules, and records the provider and model in its extraction metadata.

OpenRouter uses its [Anthropic-compatible Messages endpoint](https://openrouter.ai/docs/api/api-reference/anthropic-messages/create-messages).
To make it the default for extraction and evaluation, set
`H9N_EXTRACTION_PROVIDER=openrouter` and `H9N_EXTRACTION_MODEL=author/model` in
`.env`. CLI `--provider` and `--model` override the configured selection.

## Report files

Outputs:

- `report.md`: metrics, cases, every field's expected/predicted outcome, and any comparison.
- `report.json`: field-level comparisons, evidence, metrics, and run metadata.
- `predictions.json`: extraction output, model usage, and latency for replay.

## Restore source files

Source files and generated reports are ignored by Git. Restore inputs on a
new checkout from any of these (they can be combined):

```bash
# The supplied benchmark pack
python -m backend.evaluation.restore_inputs --archive /path/to/HANA_M1_Benchmark_Pack.zip
# A folder holding the original files under any names, such as a Drive download
python -m backend.evaluation.restore_inputs --source-dir /path/to/deal-files
# The three public broker OMs (Daly City, Chicago, Corporate Place) from their URLs
python -m backend.evaluation.restore_inputs --download-public
```

Every file is matched and checked by SHA-256 against `inputs/manifest.json`
and written to the manifest's own path. A public OM the broker has since
replaced fails its checksum and is not used, because the labels describe the
snapshot. The command prints any documents still missing. A dev run only
needs the dev documents.

## Dataset files

| File under `benchmark_data/` | Contents |
|---|---|
| `inputs/cases.json` | Cases, splits, documents, field definitions, and units |
| `inputs/manifest.json` | Source filenames, origins, and SHA-256 hashes |
| `ground_truth/labels.json` | Expected values, states, tolerances, and review metadata |
| `ground_truth/evidence.json` | PDF pages or workbook sheet/cell locations |
| `ground_truth/review.csv` | Editable review worksheet |

PDF evidence uses physical, one-indexed pages. Workbook evidence uses exact
sheet names and cells. Currency uses base units, percentages use ratios
(`15%` → `0.15`), and ranges retain both endpoints.

## Import reviewed labels

Edit `ground_truth/review.csv`, including values, evidence, review status,
reviewer name, and ISO review date. Validate and import with a new version:

```bash
python -m backend.evaluation.import_review --version 0.2.0 --check
python -m backend.evaluation.import_review --version 0.2.0
```

The importer validates the complete worksheet before replacing JSON files and
updates the version in both cases and labels. Commit the reviewed metadata diff.
Run evaluation without `--allow-draft` to enforce approved-label checks.

## Add fields

Add a row to `ground_truth/review.csv` with a field name the case doesn't
have yet and fill the extra `description` column (and `abs_tolerance` if a
numeric tolerance is needed). The importer adds the field to the case
specification, labels, and evidence. To have the production extractor scored
on it, use the `REPEDealProfile` field name, such as `noi`, `cap_rate`,
`property_type`, `address`, or `sponsor_name`. Units follow the conventions
above (`cap_rate` as a ratio, `0.079`). Other names stay benchmark-only.

## Replay saved predictions

```bash
python -m backend.evaluation.evaluate \
  --predictions saved/predictions.json \
  --allow-draft \
  --out backend/evaluation/reports/replay
```

Replay uses saved extraction latency and model usage. The JSON maps case IDs
to objects containing `fields`, `usage`, and `latency_seconds`.

## Include model cost

Evaluation and replay price usage with `backend/evaluation/pricing.json`
(list prices for the default Claude Sonnet 4.5 IDs and Gemini 2.5 Flash).
Check them against the provider pricing pages before quoting a cost, and add
any model you evaluate: `report.md` names models without a rate, and their
cost is reported as unknown. Pass `--pricing other.json` to use another
file, or `--no-pricing` to skip cost. Each key in the file is an exact
reported model identifier. Its value contains numeric USD rates per
million tokens:

- `input_per_million`
- `output_per_million`
- `cached_input_per_million` when cache reads are reported
- `cache_creation_input_per_million` when cache creation is reported

`input_tokens` includes uncached input, cache reads, and cache creations.
Reports include cost coverage and the known partial cost alongside the aggregate.

## Run reserved or diagnostic cases

```bash
python -m backend.evaluation.evaluate \
  --split holdout --unlock-holdout --allow-draft \
  --out backend/evaluation/reports/holdout

python -m backend.evaluation.evaluate \
  --split diagnostic --allow-draft \
  --out backend/evaluation/reports/diagnostic
```

`--unlock-holdout` enables the reserved split. Keep reserved cases separate from
prompt tuning when comparing frozen extraction versions.

## Apply metric thresholds

Pass `--thresholds thresholds.json` to enforce selected targets. Example:

```json
{
  "field_accuracy": {"min": 0.9},
  "case_error_rate": {"max": 0}
}
```

Exit codes: `0` for a completed run with passing configured gates, `1` for case
errors, unexpected fields, or failed gates, and `2` for invalid inputs/options.
Every expected field remains in the scoring denominator. Evidence scoring uses
curated locations; unsupported extraction compares assertions against labels.

## Use another adapter

```bash
python -m backend.evaluation.evaluate \
  --adapter your_module:extract --allow-draft \
  --out backend/evaluation/reports/custom
```

The synchronous function receives case specifications and source paths and
returns a prediction dictionary. Expected answers and evidence locations are
kept outside the adapter payload.

## Run tests

```bash
python -m pytest backend/tests -q
```

Tests cover scoring, dataset validation, review imports, source restoration,
production adapter integrity, usage accounting, replay, reports, and error paths.
