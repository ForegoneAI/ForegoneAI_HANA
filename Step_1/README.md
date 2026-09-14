# repe_extractor.py

This is the code that reads a deal document (like the Taberna CIM) and turns it into a filled-out
`REPEDealProfile` automatically, instead of someone typing the numbers in by hand.

## What it does, step by step

1. `read_pdf()` (a different file, in `ingestion/`) already turns the PDF into a list of pages,
   each one just the page number and the text on that page.
2. This code joins those pages back into one piece of text, with a line marking where each page
   starts, so you can still tell which page anything came from.
3. It sends that text to Claude and asks it to fill in the fields on `REPEDealProfile` (deal
   name, property type, address, asking price, NOI, cap rate, and so on) using only what the
   document actually says.
4. Claude's answer is checked against the same `REPEDealProfile` model the rest of the app uses.
   If Claude gives back something that doesn't fit (wrong type, made-up field), this fails loudly
   with a normal Python error instead of quietly saving bad data.

The instructions given to Claude say: only use what's written in the document, leave a field
blank (`null`) if it's not there, write a short note in `missing_information` if something
important is missing, write a note in `conflicting_information` if the document says two
different things about the same field instead of just picking one, and turn things like
"$10.0M" or "6.5%" into plain numbers.

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
3. **Install the dependencies**, from the `Step_1` folder:
   ```powershell
   pip install -r requirements.txt
   ```

## How to use it from the command line

`test_extractor.py` runs the whole pipeline without needing the API running. Run it from the
`HANA` folder — the one that contains `Step_1`, not from inside `Step_1` itself — because the
code refers to itself as `Step_1.app...`, which only resolves correctly one level up:

```powershell
python -m Step_1.app.h9n.test_extractor Step_1/data/taberna_cim.pdf
```

It prints the pages it read, then the filled-in deal profile as JSON, plus anything Claude
flagged as missing or conflicting.

**Don't have the real CIM yet?** There's a made-up test file at `Step_1/data/sample_deal.pdf`
(a fictional "Sample Estates Apartments," clearly fake numbers) you can point the same command
at instead, just to confirm the whole pipeline — reading the PDF, calling Claude, validating the
response — actually works before you have the real document:

```powershell
python -m Step_1.app.h9n.test_extractor Step_1/data/sample_deal.pdf
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
the `__pycache__` folders under `Step_1/app/h9n/` and `Step_1/app/h9n/extraction/` and try
again.

## What's been tested and what hasn't

The code was originally built and tested with a fake Anthropic client and a short made-up test
page (no real API key or CIM was available at the time), which confirmed the code builds a
correct description of `REPEDealProfile` to send to Claude, joins pages into text correctly,
correctly turns Claude's answer back into a `REPEDealProfile`, and that the upload endpoint
correctly saves the file, reads it, and rejects non-PDF files.

It was briefly switched to use OpenAI instead of Claude, then switched back — the version in this
file is the Claude one.

What's still worth doing: run `test_extractor.py` (or the API endpoint) on the real Taberna CIM
with a real API key and check the output actually makes sense — that's the real checkpoint, not
just "the code runs without erroring."

## What this doesn't do (on purpose, for now)

This only covers turning a document into a filled-in deal profile. It doesn't yet:
- keep track of which page/sentence each value came from
- flag which extractions Claude wasn't sure about
- let someone review and correct the values in a UI
- get tested against a set of deals with known-correct answers
- get tested on deals it hasn't seen before

Those are separate pieces of work planned for later.
