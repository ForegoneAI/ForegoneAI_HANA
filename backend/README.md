# H9N Milestone 1 Backend

![Backend tests](https://github.com/ForegoneAI/ForegoneAI_HANA/actions/workflows/backend-ci.yml/badge.svg)

This is the code that reads a deal document (like the Taberna CIM) and turns it into a filled-out
`REPEDealProfile` automatically, instead of someone typing the numbers in by hand - plus everything
built on top of that extraction: source evidence, uncertainty flags, human review and correction,
and an evaluation suite that scores how accurate it actually is.

**Not planning to run any of this yourself?** [`STATUS.md`](./STATUS.md) is a plain-language
checklist of what's done and what isn't, and the badge above is green when the automated tests
are passing - both readable without installing anything.

## What it does, step by step

1. `read_pdf()` (a different file, in `ingestion/`) already turns the PDF into a list of pages,
   each one just the page number and the text on that page.
2. This code joins those pages back into one piece of text, with a line marking where each page
   starts, so you can still tell which page anything came from.
3. It sends that text to Claude and asks it to fill in the fields on `REPEDealProfile` (deal
   name, property type, address, asking price, NOI, cap rate, and so on) using only what the
   document actually says.
4. For the deal's most important fields, it also asks Claude to say exactly where each value
   came from - which document, which page, and a short quote from that page - and saves that as
   `evidence` on the same profile.
5. For those same important fields, if Claude found a value but isn't fully confident it's
   correct (it had to infer or calculate it, or the wording was ambiguous), it notes that in
   `uncertain_information` so a reviewer knows which values are worth double-checking first.
6. Claude's answer is checked against the same `REPEDealProfile` model the rest of the app uses.
   If Claude gives back something that doesn't fit (wrong type, made-up field), this fails loudly
   with a normal Python error instead of quietly saving bad data.

The instructions given to Claude say: only use what's written in the document, leave a field
blank (`null`) if it's not there, write a short note in `missing_information` if something
important is missing, write a note in `conflicting_information` if the document says two
different things about the same field instead of just picking one, and turn things like
"$10.0M" or "6.5%" into plain numbers.

## Source evidence

For a fixed list of important fields - `deal_name`, `property_name`, `property_type`, `address`,
`asking_price`, `noi`, `cap_rate` (this list lives in one place, `IMPORTANT_FIELDS` in
`repe_extractor.py`, so the "what's missing" check and the "where did this come from" check can
never drift apart) - the profile's `evidence` list has one entry per field Claude actually found,
each with:

- `field_name` - which field this is evidence for, e.g. `"asking_price"`.
- `value` - the value Claude extracted, as plain text.
- `source_document` - the file name it came from.
- `page_number` - the page it came from.
- `snippet` - a short quote from that page backing up the value.

This is what lets a reviewer check "did Claude actually make this up, or is it really in the
document" without re-reading the whole CIM - they can jump straight to the page and sentence.
There's no evidence entry for a field Claude left blank, and evidence currently isn't collected
for every field on the schema, only the important ones listed above.

## Uncertainty flagging

Not every value on the profile is equally trustworthy, even when it's not missing and doesn't
contradict anything else in the document. `uncertain_information` is a list of short, plain-text
notes (same shape as `missing_information` and `conflicting_information`) for exactly that
in-between case: Claude found a value for one of the important fields, but flagged it as worth a
second look because, for example:

- it had to be **calculated or inferred** rather than read directly (e.g. a cap rate worked out
  from NOI and asking price instead of being stated outright)
- the wording was **ambiguous or approximate** (e.g. "around $10M" rather than an exact figure)
- the value came from a **less authoritative section** of the document (e.g. a marketing summary
  rather than the financial statements)

This is different from the other two lists: `missing_information` means nothing was found at all,
`conflicting_information` means the document states two different values for the same field, and
`uncertain_information` means exactly one value was extracted but shouldn't be taken at face
value. A field can only end up in one of the three - never more than one at a time.

## Human review and correction

Every extracted deal is saved (`app/h9n/review/store.py`) so it can be looked up and corrected
later, not just returned once and forgotten. `POST /api/h9n/repe/extract` now returns a `deal_id`
along with the profile; `GET /api/h9n/repe/deals/{deal_id}` fetches it again, and
`PATCH /api/h9n/repe/deals/{deal_id}` lets a reviewer submit corrected values for one or more
fields (see the curl examples above).

Every field a reviewer corrects gets added to the profile's own `corrected_fields` list, so the
JSON itself shows which values are human-verified vs still just what the model extracted -
without needing a separate audit log to answer that question. Corrections are validated the same
way a fresh extraction is (wrong type or an unknown field name is rejected, not silently
accepted).

Correcting a field's value is a different question from whether a reviewer has actually looked at
the whole profile and signed off on it, so there's a separate step for that:
`POST /api/h9n/repe/deals/{deal_id}/review` with `{"status": "approved"}` or
`{"status": "rejected"}` records the reviewer's explicit verdict in the profile's own
`review_status` field. Every freshly extracted deal starts out `"pending"` until someone submits
one of those two.

This is intentionally simple - a JSON file per deal on local disk, not a real database - and
there's no reviewer-facing UI yet, only the API itself. See the caveat at the top of `store.py`
for what a production version of this would still need (a real database, authentication, a
who/when audit trail).

## Evaluation: does it actually get things right?

Automated tests (below) prove the code doesn't crash; they don't prove an extraction is
*correct*. `backend/evaluation/` is a separate suite that scores actual extraction accuracy
against known-correct answers, using the real Claude API:

```powershell
python -m backend.evaluation.evaluate            # ground-truth cases
python -m backend.evaluation.evaluate --holdout  # unseen-deal cases
python -m backend.evaluation.evaluate --all      # both, reported separately
```

- **`cases.py` → `GROUND_TRUTH_CASES`** - synthetic deal packages written by hand, each paired
  with the known-correct value for every field the text states. Used while building and checking
  the extractor's prompt.
- **`cases.py` → `HOLDOUT_CASES`** - more synthetic deals, covering different property types and
  different document formatting, that were never used while writing the prompt. These catch a
  prompt that only works on the exact wording of the ground-truth cases instead of the general
  rule it's supposed to follow.
- **`evaluate.py`** - runs the real extractor against a set of cases and prints a per-field and
  overall accuracy report. Costs a little to run (real API calls), so it's a script you run
  manually, not part of the free `pytest` suite - though the scoring logic itself (is a numeric
  answer within tolerance, is a string match case-insensitive, etc.) is covered by
  `test_evaluate.py` with a fake client, so that part does run for free in CI.

**Worth being honest about:** these are synthetic cases with hand-written "correct" answers, not
real deals a person independently verified. They prove the extractor can read clearly-stated facts
back correctly; they don't prove much about a real CIM's messier formatting, scanned/OCR'd text,
or genuinely ambiguous wording. Real, human-reviewed deals should be added here (or replace these
cases) as they become available - see `cases.py`'s module docstring for the full reasoning, and
keep testing real documents by hand with `test_extractor.py` in the meantime.

## End-to-end demo

`demo_end_to_end.py` runs the whole pipeline above, in order, against one real document: extract →
print evidence → print missing/conflicting/uncertain flags → save the deal, fetch it back, apply
an example correction → run both evaluation suites and print their accuracy reports.

```powershell
python -m backend.app.h9n.demo_end_to_end backend/data/taberna_cim.pdf
```

Like the evaluation script, this calls the real API and costs a little to run. It's a "does the
whole thing actually work together" checkpoint, not a feature of its own - everything it exercises
is described in the sections above.

## Where this fits

```
PDF uploaded
    -> read_pdf()            turns it into page-by-page text
    -> extract_repe_deal()   sends that text to Claude, gets back deal info
    -> REPEDealProfile       the same data model used everywhere else in the app
    -> DealStore.save()      saved by id, so it can be fetched or corrected later
```

## One-time setup

1. **Get a Claude API key** at [platform.claude.com](https://platform.claude.com) (Console →
   API keys → Create key). Give it a name you'll recognize, set an expiration (e.g. 30 days —
   you'll just need to regenerate it when it lapses), and leave the scope as your default
   workspace with no Admin API access. Copy the full key the moment it's shown — the console
   only displays it once, and there's no way to view it again afterward. If you miss it, delete
   that key and create a new one.
2. **Put the key in your environment**, not in any file in this repo:
   ```powershell
   $env:ANTHROPIC_API_KEY="sk-ant-your-key-here"
   ```
   (or `setx ANTHROPIC_API_KEY "sk-ant-..."` to set it permanently instead of per-session)
3. **Install the dependencies**, from the repository root (the folder that contains `backend`,
   `Frontend`, and this repo's `.git` folder — not from inside `backend` itself) —
   `requirements.txt` lives there, not inside `backend`:
   ```powershell
   pip install -r requirements.txt -r requirements-dev.txt
   ```
   (`requirements-dev.txt` is only needed to run the automated test suite — skip it if you just
   want to run the app.)

## How to use it from the command line

`test_extractor.py` runs the whole pipeline without needing the API running. Run it from the
repository root — the folder that contains `backend`, not from inside `backend` itself — because
the code refers to itself as `backend.app...`, which only resolves correctly one level up:

```powershell
python -m backend.app.h9n.test_extractor backend/data/taberna_cim.pdf
```

It prints the pages it read, then the filled-in deal profile as JSON, anything Claude flagged as
missing, conflicting, or uncertain, and the source evidence for each important field it found (see
"Source evidence" and "Uncertainty flagging" above).

**Don't have the real CIM yet?** Generate a made-up test file at `backend/data/sample_deal.pdf`
(a fictional "Sample Estates Apartments," clearly fake numbers) and point the same command at it
instead, just to confirm the whole pipeline — reading the PDF, calling Claude, validating the
response — actually works before you have the real document. This is a generator script rather
than a file checked into the repo because `backend/data/` is entirely covered by `.gitignore`'s
`data/` rule (real deal packages can't go in a shared repo, and that rule doesn't distinguish a
harmless fake fixture from a real one):

```powershell
python -m backend.scripts.make_sample_deal
python -m backend.app.h9n.test_extractor backend/data/sample_deal.pdf
```

`demo_end_to_end.py` (see "End-to-end demo" below) also defaults to this same file when no path
is given, so run the generator once before trying that with no arguments too.

## How to use it from the API

`main.py` has four endpoints for this. Upload a PDF and you get back the filled-in deal profile,
plus an id you can use to fetch, correct, or review it later:

```bash
curl -X POST http://localhost:8000/api/h9n/repe/extract \
  -F "file=@taberna_cim.pdf"
```

```json
{
  "deal_id": "b6b6a1e2...",
  "profile": { "deal_name": "...", "asking_price": 18500000, "evidence": [...], "...": "..." }
}
```

If you upload something that isn't a PDF, you get a 400 error. If the PDF has no readable text,
or Claude doesn't return something usable, you get an error instead of an empty/blank profile.

Fetch that same deal again later by its id:

```bash
curl http://localhost:8000/api/h9n/repe/deals/b6b6a1e2...
```

And a reviewer can correct one or more fields (see "Human review and correction" below):

```bash
curl -X PATCH http://localhost:8000/api/h9n/repe/deals/b6b6a1e2... \
  -H "Content-Type: application/json" \
  -d '{"asking_price": 9500000}'
```

Once they're satisfied (or not) with the profile as it stands, they record that verdict separately
from any individual correction:

```bash
curl -X POST http://localhost:8000/api/h9n/repe/deals/b6b6a1e2.../review \
  -H "Content-Type: application/json" \
  -d '{"status": "approved"}'
```

`status` only accepts `"approved"` or `"rejected"` - `"pending"` is just the starting state a
freshly extracted deal has before anyone's reviewed it, not something you submit.

The fetch, correction, and review endpoints all 404 if the id doesn't match a saved deal. A
correction with an unknown field name or a value of the wrong type gets a 400 instead of silently
corrupting the saved deal, and a review request with anything other than `"approved"` or
`"rejected"` gets a 422.

### Recording extraction runs in Supabase (Milestone 1.3)

To keep a permanent, traceable record of an extraction, pass an `organization_id` and the internal
API key. The run is saved to Supabase with the model, a hash of the prompt, hashes of the PDF and
of the text Claude saw, the profile, and its page-level evidence:

```bash
curl -X POST http://localhost:8000/api/h9n/repe/extract \
  -H "X-H9N-API-Key: $H9N_RAG_INTERNAL_API_KEY" \
  -F "organization_id=11111111-1111-1111-1111-111111111111" \
  -F "file=@taberna_cim.pdf"
```

The response then also includes an `extraction_run_id`. A few things to know:

- **Without `organization_id`, nothing is recorded.** The endpoint works exactly as above, which
  keeps local testing possible without Supabase.
- **Failed extractions are recorded too.** If the run itself can't be saved, the request fails
  rather than returning a result that can't be traced.
- **The API key is a development gate, not real login.** Once Supabase user auth exists, the
  organization should come from the logged-in user, and recording should always happen.
- **Setup:** apply `supabase/migrations/20260921_create_h9n_rag.sql` *before*
  `20260929_create_h9n_extraction_runs.sql`, and set the Supabase variables in `.env` (see
  [RAG.md](./RAG.md)). The migration's comments describe each table and column.

## Settings

| Env var | Required? | Default | What it's for |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | — | Your Claude API key |
| `H9N_EXTRACTION_MODEL` | No | `claude-sonnet-4-5-20250929` | Which Claude model to use |

## If you edit this file (or switch providers) and Python won't pick up the change

Python caches compiled versions of each file in a `__pycache__` folder next to it. Usually it
notices when the source changed and recompiles automatically, but if you ever see an error that
doesn't match what's actually in the file (e.g. it complains about a package you removed), delete
the `__pycache__` folders under `backend/app/h9n/` and `backend/app/h9n/extraction/` and try
again.

## Automated tests (what runs on GitHub, not on your machine)

`backend/tests/` is a `pytest` suite that runs automatically on every push and pull request (see
`.github/workflows/backend-ci.yml`) — that's the checkmark you see on commits and PRs, and the
badge at the top of this file. It fakes the Claude API call (`unittest.mock`), so it needs no
`ANTHROPIC_API_KEY`, costs nothing, and never touches a real deal document — it's checking that
the code around the API call is correct (schema building, page-text joining, evidence parsing,
the review store, the upload/fetch/correct/review endpoints' error handling, the evaluation
suite's scoring logic), not grading extraction quality on a real document.

If you want to run it yourself instead of trusting the badge:

```powershell
pip install -r requirements.txt -r requirements-dev.txt
pytest -v
```

This confirmed the code builds a correct description of `REPEDealProfile` to send to Claude,
joins pages into text correctly, correctly turns Claude's answer back into a `REPEDealProfile`
(including the `evidence` and `uncertain_information` lists), that the upload/fetch/correct/review
endpoints behave correctly (rejects non-PDF files, 404s on an unknown deal id, 400s on an invalid
correction, records `corrected_fields`, records an approved/rejected `review_status`), and that
the evaluation suite's field-comparison logic is correct.

It was briefly switched to use OpenAI instead of Claude, then switched back — the version in this
file is the Claude one.

## What's still worth doing

Automated tests prove the code doesn't crash and handles the cases above; they can't tell you if
an extraction is actually *correct* on a real document. Run `test_extractor.py` (or the API
endpoint, or `demo_end_to_end.py`) on a real deal document with a real API key and read the output
and its evidence yourself, and periodically add real, human-reviewed deals to
`backend/evaluation/cases.py` as they become available — the synthetic ground-truth/holdout cases
are a floor, not a substitute for that.

## What this doesn't do (on purpose, for now)

This covers extraction with source evidence and uncertainty flags, human review and correction via
the API, and an evaluation suite scored against known-correct (if currently synthetic) answers. It
doesn't yet:
- track evidence or uncertainty for every field, only the important ones listed above
- offer a reviewer-facing UI - correction only happens through the API directly for now
- evaluate against real, human-reviewed deals - the ground-truth and holdout sets are synthetic

Those are separate pieces of work for whenever this milestone's follow-up work is picked up.
