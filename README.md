# HANA

HANA is an institutional intelligence platform. Its H9N backend extracts
structured real-estate deal profiles from PDFs, preserves source evidence,
supports review and corrections, records extraction runs, and evaluates
results against a versioned benchmark.

## Run locally

From the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -r requirements-dev.txt
```

Configure Anthropic or OpenRouter credentials and the extraction model in your
environment or local `.env` file using [`.env.example`](.env.example) and the
[backend setup](backend/README.md#setup) as references, then start the API:

```bash
python -m uvicorn backend.app.main:app --reload
```

Open `http://localhost:8000/docs` for API usage.

Run the extraction benchmark:

```bash
python -m backend.evaluation.evaluate --allow-draft --out backend/evaluation/reports/hana-dev
```

Evaluate a specific model using your OpenRouter key:

```bash
python -m backend.evaluation.evaluate \
  --provider openrouter --model google/gemini-2.5-flash \
  --allow-draft --out backend/evaluation/reports/gemini-flash
```

Run tests:

```bash
python -m pytest backend/tests -q
```

See the [backend guide](backend/README.md) for extraction and API commands,
the [benchmark guide](backend/evaluation/README.md) for dataset and report
commands, and the [RAG guide](backend/RAG.md) for retrieval setup.
