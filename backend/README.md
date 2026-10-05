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
4. For every value it finds, Claude must also say exactly where it came from - which document,
   which page, and a short verbatim quote from that page.
5. If Claude found a value but isn't fully confident in it (ambiguous or approximate wording), or
   the document states two different values, it flags that field.
6. Claude's answer is checked against a strict schema: every field present (an explicit `null`
   when the document doesn't say), no made-up or reviewer-only fields, no placeholders like
   `"N/A"`, no impossible numbers. An answer that doesn't fit is sent back once with the list of
   problems; if it still doesn't fit, the extraction fails with a clear error and nothing is saved.
7. Every value is then checked against the document itself. Only values whose quoted passage is
   really on the cited page, really contains the value, and that Claude didn't flag are stored.
   Everything else is left `null` and listed in `withheld_values` for a human reviewer - see
   "Extraction reliability" below.

The instructions given to Claude say: only use what's written in the document (never guess or
calculate), set a field to `null` if it's not there, list an important field that isn't stated in
`missing_information` (starting with the field name), flag a field as `conflicting` if the
document says two different things about it instead of silently picking one, use the document's
own words for text values (trimmed and recapitalized, never swapped for other words), and turn
things like "$10.0M" or "6.5%" into plain numbers.

## Extraction reliability (Milestone 1.1)

The rule: **a profile's value fields hold only values whose cited passage of the document contains
them.** Model output that is malformed never reaches the database, and model output that is
well-formed but unsupported never reaches a value field. That holds for the reviewer-feedback
correction path too.

Every value Claude returns ends up in exactly one place:

| What Claude returned | Stored in the field | Recorded in `withheld_values` |
|---|---|---|
| A value whose quote is on the cited page and contains the value, not flagged | the value, plus its `evidence` | - |
| A value whose citation doesn't hold up: page not in the document, quote under 8 characters, quote not on that page, or the quoted passage doesn't contain the value | `null` | the proposed value, the citation, and why it failed |
| A value Claude flagged as uncertain or conflicting | `null` | the proposed value, the citation, and Claude's note |
| A value Claude also listed in `missing_information` | `null` | the proposed value, reason `model_listed_as_missing` |
| A value with no citation at all | `null` | the proposed value, reason `no_evidence` |
| Nothing (not stated in the document) | `null` | - (a `missing_information` note if it's an important field) |

Each `withheld_values` entry has `field_name`, `proposed_value`, `reason` (`no_evidence`,
`page_not_in_document`, `snippet_too_short`, `snippet_not_on_page`, `value_not_in_snippet`,
`model_uncertain`, `model_conflicting`, or `model_listed_as_missing`), a plain-language `detail`,
and the `evidence` Claude gave, if any. `missing_information` only ever lists what the document
doesn't state; withheld values are not repeated there.

**Why null instead of keeping the value with a note:** if a reviewer misses a note, a null field
stays "unknown" - later screening treats it as unknown rather than acting on a guess. A value
kept beside a note could be approved by accident and flow into screening and underwriting as if
it were fact. A null field with a proposed value next to it is also much harder to overlook in a
review form.

**Resolving a withheld value (Milestone 2):** accept it by setting the field and clearing the
entry (`PATCH /api/h9n/repe/deals/{deal_id}` with e.g.
`{"asking_price": 10000000, "withheld_values": [...remaining entries...]}` - the field is then
recorded in `corrected_fields` as human-verified), or dismiss it by clearing the entry and
leaving the field `null`. A dedicated resolve endpoint, and blocking approval while entries are
unresolved, are recommended for M2.4.

**How a quote is matched to the page:** case, spacing and line breaks, curly vs straight quotes,
dashes, ligatures, invisible characters (soft hyphens, zero-width spaces), and a word hyphenated
across a line are all tolerated. Letters and digits that touch in the quote must touch on the page,
so "2400" can't be matched against "2" and "400" on separate lines, and a quote can't start or end
mid-word. "..." may join pieces of a quote that are at most 150 characters apart (a table label and
its value: `"Units ... 400"`); for a numeric field the skipped text may not contain another number.

**How the value is matched to the quote:**
- **Numbers** are read from the page itself, with their context: sign (`-$150,000`,
  `($150,000)`), scale (`$10.0M`, `950K`, `18.5 million`), `%`, `$`, and a unit word after them
  (`128 units`, `85,000 SF`, `10-year`). The value must equal one of the quoted numbers exactly
  (a percentage may also be a fraction: `0.94` supports 94), and the number must be the right kind
  for the field: an asking price can't come from "128 units", a cap rate can't come from "$6.5M".
- **Text fields** must appear in the quoted passage as whole words, ignoring case and dashes
  ("Self-Storage" matches "self-storage facility"). A reworded value ("Multifamily" quoted from
  "apartment community") is withheld; normalized vocabularies are left to M1.4.
- **`business_plan` and `investment_strategy`** are summaries, so only their quote is checked;
  their evidence is labelled `verification: "quote_only"`, against `"value_matched"` for every
  other stored value. Treat quote-only values as needing a human look.

**Controlled errors:** every failure is an `ExtractionError` (a `ValueError`) with a message that
is safe to show a caller - no model output, keys, or provider internals:

| Problem | Error | HTTP status from `/extract` |
|---|---|---|
| Upload larger than 50 MB | - | 413 |
| File isn't a readable PDF, is encrypted, has no text (scanned), or has more than 500 pages | `PdfReadError` | 422 |
| Pages malformed or the document is longer than `H9N_EXTRACTION_MAX_INPUT_CHARS` | `ExtractionInputError` | 422 |
| Output cut off (`max_tokens`), or still invalid after a retry | `ExtractionOutputError` | 502 |
| Claude declined the request | `ExtractionRefusedError` | 502 |
| Timeout, connection failure, rate limit, provider 5xx, or the time budget ran out (after H9N's retries) | `ExtractionUnavailableError` | 503 |
| Missing/invalid API key, unknown model, invalid setting | `ExtractionConfigurationError` | 503 (details only in the server log) |
| Anything unexpected | - | 500 (details only in the server log) |

**Retries and the time budget:** timeouts, connection failures, 408/409/429 and 5xx responses are
retried with backoff (1s, 2s, 4s...) up to `H9N_EXTRACTION_MAX_RETRIES` times. The SDK's own
retries are switched off, so `H9N_EXTRACTION_TIMEOUT_SECONDS` is a hard budget for the whole
extraction - every request, retry and backoff - rather than a per-request limit that retries
multiply.

When the request includes an `organization_id` (M1.3), every one of these that happens after the
PDF is read is recorded as a failed extraction run, with the error type.

**Reviewer-feedback corrections** (`POST /deals/{id}/review` with `rejected` + `feedback`) go
through the same machinery: the same strict validation (Claude can change only deal value fields -
never `review_status`, `withheld_values` or `evidence` directly), retries, time budget and
evidence checks. A corrected value is applied only if its citation verifies; otherwise it's added
to `withheld_values`. Clearing a field to `null` needs no citation. If the correction step fails,
the response is a 502/503 whose message says the rejection and feedback were still saved.

**Stable input:** the PDF is read in memory, each page's text is normalized the same way every
time (Unicode, line endings, control characters, invisible characters, trailing spaces), and blank
pages are skipped without renumbering the rest - so the M1.3 input fingerprint is reproducible and
citations still point at the real page.

## Source evidence

Every stored value has an entry in the profile's `evidence` list (since Milestone 1.1 - before
that, only the important fields did), each with:

- `field_name` - which field this is evidence for, e.g. `"asking_price"`.
- `value` - the stored value, as plain text.
- `source_document` - the file name it came from.
- `page_number` - the page it came from.
- `snippet` - a short quote from that page backing up the value.
- `verification` - `"value_matched"` (the quote contains the value) or `"quote_only"` (narrative
  fields, where only the quote is checked).

This is what lets a reviewer check "did Claude actually make this up, or is it really in the
document" without re-reading the whole CIM - they can jump straight to the page and sentence.
There's no evidence entry for a field left blank; a value whose citation didn't check out keeps
its citation in `withheld_values` instead (see "Extraction reliability" above).

`IMPORTANT_FIELDS` in `repe_extractor.py` (`deal_name`, `property_name`, `property_type`,
`address`, `asking_price`, `noi`, `cap_rate`) now only decides which absent fields get a
`missing_information` note.

## Uncertainty flagging

Not every value is equally trustworthy, even when it's stated and cited. Claude flags a field as
**uncertain** when, for example:

- the wording was **ambiguous or approximate** (e.g. "around $10M" rather than an exact figure)
- the value came from a **less authoritative section** of the document (e.g. a marketing summary
  rather than the financial statements)

and as **conflicting** when the document states two different values for it. Since Milestone 1.1
a flagged value is **not stored** in its field: it is left `null` and put in `withheld_values`
with Claude's note, for a reviewer to accept or dismiss. The notes also still appear as plain
text in `uncertain_information` / `conflicting_information`.

Values that would have to be **calculated or inferred** (e.g. a cap rate worked out from NOI and
asking price when the document never states one) are no longer extracted at all - the field is
left `null`.

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
2. **Put the key in your environment or in `.env`**, not in any tracked file in this repo:
   ```powershell
   $env:ANTHROPIC_API_KEY="sk-ant-your-key-here"
   ```
   (or `setx ANTHROPIC_API_KEY "sk-ant-..."` to set it permanently instead of per-session).
   Alternatively copy `.env.example` to `.env` (gitignored) and set `ANTHROPIC_API_KEY` there;
   the extractor reads `.env` without overriding variables already set in the environment.
3. **Install the dependencies**, from the repository root (the folder that contains `backend`,
   `Frontend`, and this repo's `.git` folder — not from inside `backend` itself) —
   `requirements.txt` lives there, not inside `backend`:
   ```powershell
   pip install -r requirements.txt -r requirements-dev.txt
   ```
   (`requirements-dev.txt` is only needed to run the automated test suite — skip it if you just
   want to run the app.)

   **macOS / Linux:** `anthropic` 1.x needs Python 3.10+ (CI uses 3.12), so use a virtual
   environment on 3.12:
   ```bash
   brew install python@3.12            # macOS, if python3.12 isn't installed
   python3.12 -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt -r requirements-dev.txt
   cp .env.example .env                # then set ANTHROPIC_API_KEY in .env
   pytest -v
   ```

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

If you upload something that isn't a PDF, you get a 400 error. A file that can't be read as a PDF,
or has no readable text, gets a 422; if Claude doesn't return something usable, or can't be
reached, you get a 502 or 503 with a plain explanation instead of an empty/blank profile (see the
error table under "Extraction reliability").

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
| `H9N_EXTRACTION_MODEL` | No | `claude-sonnet-4-5-20250929` | Which Claude model to use (re-run the held-out evaluation after changing it) |
| `H9N_EXTRACTION_TIMEOUT_SECONDS` | No | `300` | Time budget for one whole extraction or correction, retries included (1-3600) |
| `H9N_EXTRACTION_MAX_RETRIES` | No | `2` | How many times H9N retries a timeout, connection error, rate limit, or 5xx response (0-10) |
| `H9N_EXTRACTION_MAX_INPUT_CHARS` | No | `600000` | Longest document text (roughly 150k tokens) sent in one extraction; longer packages get a 422 |

## If you edit this file (or switch providers) and Python won't pick up the change

Python caches compiled versions of each file in a `__pycache__` folder next to it. Usually it
notices when the source changed and recompiles automatically, but if you ever see an error that
doesn't match what's actually in the file (e.g. it complains about a package you removed), delete
the `__pycache__` folders under `backend/app/h9n/` and `backend/app/h9n/extraction/` and try
again.

## Automated tests (what runs on GitHub, not on your machine)

`backend/tests/` is a `pytest` suite that runs automatically on every push and pull request (see
`.github/workflows/backend-ci.yml`) — that's the checkmark you see on commits and PRs, and the
badge at the top of this file. It fakes the Claude API call (`backend/tests/extraction_fakes.py`), so it needs no
`ANTHROPIC_API_KEY`, costs nothing, and never touches a real deal document — it's checking that
the code around the API call is correct (schema building, page-text joining, evidence parsing,
the review store, the upload/fetch/correct/review endpoints' error handling, the evaluation
suite's scoring logic, and - since Milestone 1.1 - strict output validation, retries, controlled
errors, and the evidence checks in `test_extraction_reliability.py`), not grading extraction
quality on a real document.

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
- normalize wording (property types, investment strategies, state abbreviations) - a reworded value
  is withheld for now; vocabularies belong to M1.4
- tell which table column a value came from - a table quote that skips over another number is
  withheld rather than guessed
- read scanned PDFs (no OCR) or packages longer than one extraction request
- offer a reviewer-facing UI - correction only happens through the API directly for now
- evaluate against real, human-reviewed deals - the ground-truth and holdout sets are synthetic

Those are separate pieces of work for whenever this milestone's follow-up work is picked up.
