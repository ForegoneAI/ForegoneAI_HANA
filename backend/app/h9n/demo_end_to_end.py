"""
demo_end_to_end.py

H9N Milestone 1, item 8 - Final End-to-End Demo.

Ties together everything built for Milestone 1 into one run against a real
deal package:

  1. Reads the PDF (item 1's read_pdf()).
  2. Extracts a validated REPEDealProfile (item 1's extract_repe_deal()).
  3. Prints the source evidence for each important field (item 2).
  4. Prints anything flagged as missing, conflicting, or uncertain (item 3).
  5. Saves the deal to the review store and fetches it back by id, applies
     one example correction to show it taking effect and being recorded in
     corrected_fields, then actually PAUSES and asks whoever is running this
     to look at everything printed above and type whether it's correct -
     that answer is recorded as an "approved"/"rejected" review_status
     verdict (item 4's "Approve and save the validated Deal Profile" step).
     Answering "n" pauses again to ask *what's* wrong, in plain language -
     that feedback is sent to Claude along with the original document text
     to re-derive and apply the corrected field(s) automatically, putting
     the deal back to "pending" for another look (rather than the reviewer
     having to work out and PATCH the exact value themselves).
  6. Runs the ground-truth and holdout evaluation suites and prints their
     accuracy reports (items 5-7).

This script is the "does the whole Milestone 1 pipeline actually work
together, end to end" checkpoint - it doesn't add any new capability of its
own, it just exercises items 1-7 in sequence on one real document. It needs
a real ANTHROPIC_API_KEY (extraction and both evaluation suites all call
the real API) and costs a little to run - this isn't part of the free,
mocked `pytest` suite. Because step 5 waits on real keyboard input, this
script also isn't meant to be run non-interactively (piped, from CI, etc.)
- it'll just skip the review verdict and move on if there's no terminal
attached.

Usage:
    export ANTHROPIC_API_KEY=sk-ant-...
    python -m backend.app.h9n.demo_end_to_end path/to/taberna_cim.pdf

If no path is given, defaults to backend/data/sample_deal.pdf - which isn't
checked into the repo (backend/data/ is gitignored), so generate it once
first with:
    python -m backend.scripts.make_sample_deal
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from backend.app.h9n.extraction.repe_extractor import (
    apply_reviewer_feedback,
    extract_repe_deal,
    merge_evidence,
)
from backend.app.h9n.ingestion.pdf_reader import read_pdf
from backend.app.h9n.review.store import DealStore
from backend.evaluation.cases import GROUND_TRUTH_CASES, HOLDOUT_CASES
from backend.evaluation.evaluate import format_report, run_evaluation


def _section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def main() -> None:
    used_default_path = len(sys.argv) <= 1
    file_path = sys.argv[1] if not used_default_path else "backend/data/sample_deal.pdf"

    _section("ITEM 1 - LLM STRUCTURED EXTRACTION")
    if used_default_path and not Path(file_path).exists():
        # The default fixture isn't checked in (backend/data/ is entirely
        # gitignored - see make_sample_deal.py's docstring for why), so it
        # has to be generated once before this default path will work.
        print(
            f"{file_path} doesn't exist yet. Generate it first with:\n"
            "    python -m backend.scripts.make_sample_deal\n"
            "or pass the path to a real deal package instead, e.g.:\n"
            "    python -m backend.app.h9n.demo_end_to_end backend/data/taberna_cim.pdf"
        )
        sys.exit(1)

    print(f"Reading: {file_path}")
    pages = read_pdf(file_path)
    print(f"Read {len(pages)} page(s).")
    print("Sending page-preserved text to Claude for structured extraction...")
    deal = extract_repe_deal(pages)
    print(json.dumps(deal.model_dump(), indent=2))

    _section("ITEM 2 - FIELD-LEVEL SOURCE EVIDENCE")
    if deal.evidence:
        for item in deal.evidence:
            print(f"  - {item.field_name} = {item.value!r}")
            print(f'      {item.source_document}, page {item.page_number}: "{item.snippet}"')
    else:
        print("  (no evidence returned for this document)")

    _section("ITEM 3 - MISSING / CONFLICTING / UNCERTAIN INFORMATION")
    print(f"Missing:     {deal.missing_information or '(none)'}")
    print(f"Conflicting: {deal.conflicting_information or '(none)'}")
    print(f"Uncertain:   {deal.uncertain_information or '(none)'}")

    _section("ITEM 4 - HUMAN REVIEW AND CORRECTION")
    store = DealStore()
    deal_id = store.save(deal)
    # So a rejection below can have Claude re-derive a fix from the actual
    # document text, instead of only accepting a value the reviewer already
    # worked out themselves.
    store.save_pages(deal_id, pages)
    print(f"Saved deal with id: {deal_id}")

    fetched = store.get(deal_id)
    print(f"Fetched it back by id - deal_name matches: {fetched.deal_name == deal.deal_name}")

    print(f"review_status right after extraction: {fetched.review_status!r}")

    if deal.asking_price is not None:
        # A token example correction (nudge the price down by $1) just to
        # demonstrate the mechanism - not a real reviewer judgment call.
        example_correction = deal.asking_price - 1
        corrected = store.apply_corrections(deal_id, {"asking_price": example_correction})
        print(
            f"Applied an example correction: asking_price "
            f"{deal.asking_price} -> {corrected.asking_price}"
        )
        print(f"corrected_fields now shows: {corrected.corrected_fields}")
    else:
        print("(skipped the example correction - asking_price wasn't extracted for this document)")

    # The plan's "Approve and save the validated Deal Profile" step: a
    # reviewer's explicit yes/no verdict, separate from just correcting a
    # value above. This actually asks whoever is running the demo to look
    # at the deal profile, evidence, and flags printed above (in ITEMS 1-3)
    # and decide - it isn't guessed or hardcoded.
    print(
        "\nLook back at the deal profile, source evidence, and missing/conflicting/uncertain "
        "flags printed above (and the correction just applied, if any)."
    )
    try:
        answer = input("Is this deal profile correct? [y/n]: ").strip().lower()
    except EOFError:
        # No interactive terminal attached (e.g. output piped somewhere) -
        # skip rather than crash after all the API calls already made above.
        print("(no input available - leaving review_status as 'pending')")
    else:
        status = "approved" if answer in ("y", "yes") else "rejected"
        reviewed = store.set_review_status(deal_id, status)
        print(f"Reviewer verdict recorded: review_status is now {reviewed.review_status!r}")

        if status == "rejected":
            # This is the part a bare y/n verdict can't do on its own: let
            # the reviewer actually say what's wrong, in their own words,
            # instead of just flagging that *something* is.
            try:
                feedback = input(
                    "What's wrong with it? (describe the field(s) to fix, "
                    "or press enter to skip): "
                ).strip()
            except EOFError:
                feedback = ""

            if not feedback:
                print("(no feedback given - leaving review_status as 'rejected')")
            else:
                reviewed = store.apply_corrections(deal_id, {"review_feedback": feedback})
                print("Asking Claude to re-derive a fix from the original document text...")
                try:
                    result = apply_reviewer_feedback(pages, reviewed, feedback)
                except ValueError as exc:
                    print(f"(couldn't derive a correction from that feedback: {exc})")
                else:
                    print(f"Explanation: {result['explanation']}")
                    if not result["corrections"]:
                        print("(Claude didn't find a field it could confidently correct)")
                    else:
                        reviewed = store.apply_corrections(deal_id, result["corrections"])
                        print(f"Applied correction: {result['corrections']}")
                        print(f"corrected_fields now shows: {reviewed.corrected_fields}")
                        if result["updated_evidence"]:
                            merged_evidence = merge_evidence(reviewed.evidence, result["updated_evidence"])
                            reviewed = store.apply_corrections(deal_id, {"evidence": merged_evidence})
                        # Something just changed automatically - it needs
                        # another look, not to sit "rejected" as if nothing
                        # happened.
                        reviewed = store.apply_corrections(deal_id, {"review_status": "pending"})
                        print(f"review_status is now {reviewed.review_status!r} (ready for another look)")

    _section("ITEMS 5-7 - GROUND-TRUTH AND HOLDOUT EVALUATION")
    print(format_report(run_evaluation(GROUND_TRUTH_CASES), label="Ground truth (item 5)"))
    print()
    print(format_report(run_evaluation(HOLDOUT_CASES), label="Holdout / unseen-deal (item 7)"))

    _section("DONE - Milestone 1 items 1-7 all exercised end to end on one run")


if __name__ == "__main__":
    main()
