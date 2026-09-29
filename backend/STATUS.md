# H9N Milestone 1 — Status

A plain-language checklist of the "H9N Phase 1 / Milestone 1 Remaining Work" plan, kept up to
date here so anyone on the team can see where things stand without reading code. The
[automated tests](../.github/workflows/backend-ci.yml) badge on every commit backs up "done" -
if the checks are green, the code behind these items actually runs.

| # | Item | Status |
|---|---|---|
| 1 | LLM Structured Extraction | ✅ Done |
| 2 | Field-Level Source Evidence | ✅ Done |
| 3 | Missing, Uncertain, and Conflicting Information | 🟡 Partial |
| 4 | Human Review and Correction | ⬜ Not started |
| 5 | Ground-Truth Evaluation Set | ⬜ Not started |
| 6 | Extraction Evaluation | ⬜ Not started |
| 7 | Unseen-Deal Testing | ⬜ Not started |
| 8 | Final End-to-End Demo | ⬜ Not started |

## 1. LLM Structured Extraction — ✅ Done

Upload a deal package PDF, get back a filled-in, schema-validated `REPEDealProfile` - no manual
data entry. Built in `app/h9n/extraction/repe_extractor.py`, exposed at `POST
/api/h9n/repe/extract`.

Checked with a synthetic test file (`data/sample_deal.pdf`) end to end. **Still needs a run
against the real Taberna CIM** to call the original checkpoint fully done.

## 2. Field-Level Source Evidence — ✅ Done

For the deal's most important fields, the profile now also says exactly where each value came
from: source document, page number, and a quoted snippet. See the `evidence` field on
`REPEDealProfile` and the "Source evidence" section of the [README](./README.md).

## 3. Missing, Uncertain, and Conflicting Information — 🟡 Partial

Already working: unstated fields stay `null` rather than being guessed, `missing_information`
flags absent required fields, `conflicting_information` flags contradictions instead of silently
picking one.

Not yet built: a way to mark an extraction as merely *uncertain* (the model found something, but
isn't confident in it) - right now a value is either present or explicitly flagged, with nothing
in between.

## 4–8 — Not started

Human review and correction, the ground-truth evaluation set, scored extraction accuracy,
unseen-deal testing, and the final end-to-end demo are all still ahead. These depend on having a
reviewer-facing way to see and correct a Deal Profile (item 4), which is the natural next step
after evidence.

## How the team can check this without running anything

- **This file** - what's done, in plain language.
- **The green/red check on each commit or pull request** (`Backend tests` in the Actions tab) -
  proves the code behind the "done" items actually runs, without anyone installing Python or
  an API key.
- **The [README](./README.md)** - how the extractor works and how to run it yourself, if you do
  want to try it locally.
