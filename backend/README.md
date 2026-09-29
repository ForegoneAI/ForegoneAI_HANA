# repe_extractor.py

![Backend tests](https://github.com/ForegoneAI/ForegoneAI_HANA/actions/workflows/backend-ci.yml/badge.svg)

This is the code that reads a deal document (like the Taberna CIM) and turns it into a filled-out
`REPEDealProfile` automatically, instead of someone typing the numbers in by hand.

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
5. Claude's answer is checked against the same `REPEDealProfile` model the rest of the app uses.
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

## Where this fits

```
PDF uploaded
    -> read_pdf()            turns it into page-by-page text
    -> extract_repe_deal()   sends that text to Claude, gets back deal info
    -> REPEDealProfile       the same data model used everywhere else in the app
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
missing or conflicting, and the source evidence for each important field it found (see "Source
evidence" above).

**Don't have the real CIM yet?** There's a made-up test file at `backend/data/sample_deal.pdf`
(a fictional "Sample Estates Apartments," clearly fake numbers) you can point the same command
at instead, just to confirm the whole pipeline — reading the PDF, calling Claude, validating the
response — actually works before you have the real document:

```powershell
python -m backend.app.h9n.test_extractor backend/data/sample_deal.pdf
```

## How to use it from the API

`main.py` has a second endpoint, `POST /api/h9n/repe/extract`. Upload a PDF and you get back the
filled-in deal profile as JSON:

```bash
curl -X POST http://localhost:8000/api/h9n/repe/extract \
  -F "file=@taberna_cim.pdf"
```

If you upload something that isn't a PDF, you get a 400 error. If the PDF has no readable text,
or Claude doesn't return something usable, you get an error instead of an empty/blank profile.

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
`ANTHROPIC_API_KEY`, costs nothing, and never touches the real Taberna CIM — it's checking that
the code around the API call is correct (schema building, page-text joining, evidence parsing,
the upload endpoint's error handling), not grading extraction quality on a real document.

If you want to run it yourself instead of trusting the badge:

```powershell
pip install -r requirements.txt -r requirements-dev.txt
pytest -v
```

This confirmed the code builds a correct description of `REPEDealProfile` to send to Claude,
joins pages into text correctly, correctly turns Claude's answer back into a `REPEDealProfile`
(including the `evidence` list), and that the upload endpoint correctly saves the file, reads it,
and rejects non-PDF files.

It was briefly switched to use OpenAI instead of Claude, then switched back — the version in this
file is the Claude one.

## What's still worth doing

Automated tests prove the code doesn't crash and handles the cases above; they can't tell you if
an extraction is actually *correct*. Run `test_extractor.py` (or the API endpoint) on the real
Taberna CIM with a real API key and read the output and its evidence yourself — that's the real
checkpoint, not "the tests are green."

## What this doesn't do (on purpose, for now)

This covers turning a document into a filled-in deal profile with source evidence for the
important fields. It doesn't yet:
- track evidence for every field, only the important ones listed above
- flag which extractions Claude wasn't sure about, beyond the missing/conflicting lists
- let someone review and correct the values in a UI
- get tested against a set of deals with known-correct answers
- get tested on deals it hasn't seen before

Those are separate pieces of work planned for later.
