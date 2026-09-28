# H9N Milestone 1 — Status

A plain-language checklist of the "H9N Phase 1 / Milestone 1 Remaining Work" plan, kept up to
date here so anyone on the team can see where things stand without reading code. The
[automated tests](../.github/workflows/backend-ci.yml) badge on every commit backs up "done" -
if the checks are green, the code behind these items actually runs.

| # | Item | Status |
|---|---|---|
| 1 | LLM Structured Extraction | ✅ Done |
| 2 | Field-Level Source Evidence | ✅ Done |
| 3 | Missing, Uncertain, and Conflicting Information | ✅ Done |
| 4 | Human Review and Correction | ✅ Done |
| 5 | Ground-Truth Evaluation Set | ✅ Done |
| 6 | Extraction Evaluation | ✅ Done |
| 7 | Unseen-Deal Testing | ✅ Done |
| 8 | Final End-to-End Demo | ✅ Done |

## 1. LLM Structured Extraction — ✅ Done

Upload a deal package PDF, get back a filled-in, schema-validated `REPEDealProfile` - no manual
data entry. Built in `app/h9n/extraction/repe_extractor.py`, exposed at `POST
/api/h9n/repe/extract`.

Checked with a synthetic test file (generate it with `python -m backend.scripts.make_sample_deal`
- it isn't checked into the repo, since `backend/data/` is entirely gitignored) and confirmed
working against a real downloaded deal document.

**Fixed 2026-09-18:** the README and `demo_end_to_end.py`'s default argument both pointed at
`backend/data/sample_deal.pdf` as if it already existed, but nothing in the repo could actually
create it - running either with no setup failed with a raw `FileNotFoundError` before extraction
ever ran, which didn't match what the docs implied. `backend/scripts/make_sample_deal.py` now
generates that file on demand, the README's fallback instructions say so, and
`demo_end_to_end.py` prints a pointer to that script instead of a bare traceback if it's missing.

## 2. Field-Level Source Evidence — ✅ Done

For the deal's most important fields, the profile now also says exactly where each value came
from: source document, page number, and a quoted snippet. See the `evidence` field on
`REPEDealProfile` and the "Source evidence" section of the [README](./README.md).

## 3. Missing, Uncertain, and Conflicting Information — ✅ Done

Unstated fields stay `null` rather than being guessed, `missing_information` flags absent required
fields, `conflicting_information` flags contradictions instead of silently picking one, and
`uncertain_information` flags a value that WAS found but isn't fully trusted - e.g. it had to be
calculated or inferred, or the wording was ambiguous. See the "Uncertainty flagging" section of
the [README](./README.md).

## 4. Human Review and Correction — ✅ Done

Every extracted deal is now saved (`app/h9n/review/store.py`, `DealStore`) and can be fetched or
corrected later by id:

- `POST /api/h9n/repe/extract` now returns `{"deal_id": ..., "profile": {...}}` instead of a bare
  profile, so the caller has something to look the deal up by afterward.
- `GET /api/h9n/repe/deals/{deal_id}` fetches a previously extracted deal.
- `PATCH /api/h9n/repe/deals/{deal_id}` lets a reviewer submit corrected values for one or more
  fields (e.g. `{"asking_price": 9500000}`). Corrections are validated the same way a fresh
  extraction would be (wrong type or unknown field is rejected, not silently accepted), and every
  corrected field is recorded on the deal's own `corrected_fields` list - so the profile itself
  shows which values are human-verified vs model-extracted, without a separate audit system.
- `POST /api/h9n/repe/deals/{deal_id}/review` lets a reviewer say whether the deal, as it now
  stands, is actually correct - `{"status": "approved"}` or `{"status": "rejected"}`. This is
  separate from PATCH above: correcting one field's value doesn't by itself mean someone has
  looked at the whole profile and signed off on it. Every deal starts out `"pending"`
  (`review_status` on the profile) until a reviewer explicitly says otherwise.

This intentionally uses a simple on-disk JSON store, not a real database - see the caveat at the
top of `store.py`. There's no reviewer UI yet; correction happens by calling the API directly
(e.g. from a script, or a tool like curl/Postman) until a frontend is built for it.

## 5. Ground-Truth Evaluation Set — ✅ Done

`backend/evaluation/cases.py` defines `GROUND_TRUTH_CASES`: synthetic deal packages (Meadowbrook
Apartments, Riverside Office Plaza), each paired with the known-correct value for every field the
text unambiguously states. Because the text and the "correct answer" are both written by hand,
the ground truth is exact by construction - no separate human verification step was needed for
these two cases.

**Real limitation, stated plainly:** a synthetic set only proves the extractor can read clearly-
stated facts back correctly. It says nothing about real CIMs' messier formatting, OCR'd/scanned
text, or genuinely ambiguous wording. Real, human-reviewed deals should be added here (or replace
these cases) as they become available - see `cases.py`'s module docstring for more.

## 6. Extraction Evaluation — ✅ Done

`backend/evaluation/evaluate.py` runs the real extractor against every ground-truth case and
scores it field by field (numbers compared with a small tolerance, strings compared case- and
whitespace-insensitively), then prints a per-field and overall accuracy report:

```powershell
python -m backend.evaluation.evaluate
```

This calls the real Claude API (needs `ANTHROPIC_API_KEY`, costs a little to run), so it's a
script you run manually rather than part of the free `pytest` suite. The *scoring logic itself* -
does it correctly mark a field right or wrong, tolerate float rounding, etc. - is covered by
`backend/tests/test_evaluate.py` with a mocked client, so that part does run for free in CI.

## 7. Unseen-Deal Testing — ✅ Done

`backend/evaluation/cases.py` also defines `HOLDOUT_CASES`: two more synthetic deals (a self-
storage facility, a retail center) that were never used while writing the extractor's prompt, and
that deliberately use different document formatting (narrative prose, a bullet/stat-sheet style)
than the ground-truth cases. Run them with:

```powershell
python -m backend.evaluation.evaluate --holdout
# or both sets, reported separately:
python -m backend.evaluation.evaluate --all
```

The discipline that keeps this meaningful going forward: if a holdout case ever starts failing,
fix the prompt's general rule, don't add a special case for that one document's exact wording -
and never move a holdout case into the ground-truth set just to make a failing run pass.

## 8. Final End-to-End Demo — ✅ Done

`backend/app/h9n/demo_end_to_end.py` runs the entire Milestone 1 pipeline against one real
document in a single script: extraction (item 1) → prints evidence (item 2) → prints missing/
conflicting/uncertain flags (item 3) → saves the deal, fetches it back, and applies an example
correction (item 4) → runs both evaluation suites and prints their accuracy reports (items 5-7).

```powershell
python -m backend.app.h9n.demo_end_to_end backend/data/taberna_cim.pdf
```

Like the evaluation script, this needs a real `ANTHROPIC_API_KEY` and costs a little to run - it's
the "does the whole thing actually work together" checkpoint, not a new capability of its own.
Run with no argument, it defaults to `backend/data/sample_deal.pdf`, which has to be generated
first with `python -m backend.scripts.make_sample_deal` (see item 1's note above) - the script now
says so itself if that file is missing, instead of failing with a bare traceback before extraction
even starts.

## How the team can check this without running anything

- **This file** - what's done, in plain language.
- **The green/red check on each commit or pull request** (`Backend tests` in the Actions tab) -
  proves the code behind the "done" items actually runs, without anyone installing Python or
  an API key.
- **The [README](./README.md)** - how the extractor works and how to run it yourself, if you do
  want to try it locally.
