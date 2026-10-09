# H9N Backend

![Backend tests](https://github.com/ForegoneAI/ForegoneAI_HANA/actions/workflows/backend-ci.yml/badge.svg)

H9N extracts real-estate deal profiles from PDFs using Python, FastAPI,
Pydantic, and models through Anthropic or OpenRouter.

## What is implemented

- PDF text extraction with stable physical page numbers and normalized text.
- Strict structured output with explicit nulls, schema validation, retries,
  timeouts, and controlled errors.
- Source document, page, and quote checks for extracted values. Values requiring
  review are retained in `withheld_values` with uncertainty or conflict notes.
- API endpoints to extract, fetch, correct, and review deal profiles.
- Supabase extraction-run records containing organization/deal IDs, model,
  timestamps, source and prompt hashes, profile, and evidence.
- A versioned benchmark containing 96 checks across five deal families and one
  workbook diagnostic, with separate labels, evidence, and two reserved cases.
- Evaluation with JSON/Markdown reports, saved-output replay, threshold checks,
  latency measurement, and model token-cost accounting.

## Setup

Run commands from the repository root using Python 3.12:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Choose a provider in your environment or local `.env` file. For OpenRouter:

```dotenv
OPENROUTER_API_KEY=your-openrouter-key
H9N_EXTRACTION_PROVIDER=openrouter
H9N_EXTRACTION_MODEL=google/gemini-2.5-flash
```

For direct Anthropic access, set `H9N_EXTRACTION_PROVIDER=anthropic`,
`ANTHROPIC_API_KEY`, and an Anthropic model ID. Configuration examples are in
[`.env.example`](../.env.example).

## Run the API

```bash
python -m uvicorn backend.app.main:app --reload
```

Open `http://localhost:8000/docs` for interactive API documentation.

Upload a PDF:

```bash
curl -X POST http://localhost:8000/api/h9n/repe/extract \
  -F "file=@/path/to/deal.pdf"
```

The response includes `deal_id`, `profile`, and an `extraction_run_id` when
Supabase run recording is enabled.

Fetch, correct, and review a saved profile:

```bash
curl http://localhost:8000/api/h9n/repe/deals/DEAL_ID

curl -X PATCH http://localhost:8000/api/h9n/repe/deals/DEAL_ID \
  -H "Content-Type: application/json" \
  -d '{"asking_price": 9500000}'

curl -X POST http://localhost:8000/api/h9n/repe/deals/DEAL_ID/review \
  -H "Content-Type: application/json" \
  -d '{"status": "approved"}'
```

To record extraction runs in Supabase, apply
`supabase/migrations/20260921_create_h9n_rag.sql` followed by
`supabase/migrations/20260929_create_h9n_extraction_runs.sql`, and configure the
Supabase variables described in [RAG.md](RAG.md). Include the organization and
internal API key:

```bash
curl -X POST http://localhost:8000/api/h9n/repe/extract \
  -H "X-H9N-API-Key: $H9N_RAG_INTERNAL_API_KEY" \
  -F "organization_id=11111111-1111-1111-1111-111111111111" \
  -F "file=@/path/to/deal.pdf"
```

## Run extraction from the command line

```bash
python -m backend.app.h9n.test_extractor /path/to/deal.pdf
```

Generate and extract a fictional sample:

```bash
python -m backend.scripts.make_sample_deal
python -m backend.app.h9n.test_extractor backend/data/sample_deal.pdf
```

Run the extraction, review, and correction demo:

```bash
python -m backend.app.h9n.demo_end_to_end /path/to/deal.pdf
```

## Run the benchmark

```bash
python -m backend.evaluation.evaluate --allow-draft --out backend/evaluation/reports/hana-dev
```

Select an OpenRouter model for a particular run:

```bash
python -m backend.evaluation.evaluate \
  --provider openrouter --model google/gemini-2.5-flash \
  --allow-draft --out backend/evaluation/reports/gemini-flash
```

Use the exact OpenRouter model ID and a model supporting tool calling. Changing
`--model` and the output directory produces a separate evaluation for comparison.

The command writes `report.md`, `report.json`, and `predictions.json`. It reports
field accuracy, missing-data detection, reference-based unsupported extraction
rate, evidence correctness, output coverage, latency, and approximate model cost
when pricing is supplied.

See [evaluation/README.md](evaluation/README.md) for source restoration,
review/import, pricing, replay, reserved cases, and threshold options.

## Extraction settings

| Environment variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Set in environment or `.env` | Claude credentials |
| `OPENROUTER_API_KEY` | Set in environment or `.env` | OpenRouter credentials |
| `H9N_EXTRACTION_PROVIDER` | `anthropic` | `anthropic` or `openrouter` |
| `H9N_EXTRACTION_MODEL` | Provider-specific Claude default | Extraction model ID |
| `H9N_EXTRACTION_TIMEOUT_SECONDS` | `300` | Total extraction time budget |
| `H9N_EXTRACTION_MAX_RETRIES` | `2` | Transient provider retries |
| `H9N_EXTRACTION_MAX_INPUT_CHARS` | `600000` | Input text limit |

Extraction and live evaluation commands make billable model calls.

## Run tests

```bash
python -m pytest backend/tests -q
```

Tests use fake model responses to check extraction validation, evidence checks,
API behavior, review/correction, run persistence, and benchmark behavior.
The GitHub backend workflow runs them on relevant pushes and pull requests.
