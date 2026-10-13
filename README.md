# HANA

HANA is an AI-powered institutional intelligence platform.

## Current Focus

The first development phase is H9N, focused on private-market and real-estate deal intelligence.

Milestone 1 goals:
- Upload deal packages
- Extract structured deal information
- Flag missing or uncertain data
- Preserve source evidence
- Allow human review and correction

## Backend

- Python 3.12
- FastAPI
- Uvicorn

## Run Locally

Activate the virtual environment:

```bash
source projectvenv/bin/activate
```

## Website

foregone.ai is built from `web/` — a Next.js static export. Pushing to `master`
builds it and deploys it to GitHub Pages; there is no manual publish step. See
`web/README.md`.

`site/` is the hand-written HTML the React version was ported from. It is no
longer published and is kept for reference only.
