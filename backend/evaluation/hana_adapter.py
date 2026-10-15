"""Evaluate the existing production PDF extractor without database writes.

Only benchmark fields named after a REPEDealProfile field are mapped (see
fields.py): generic `noi` is never stretched over both current and pro-forma
NOI, and square_feet never stands for lot area. Other fields are reference.
The adapter never imports labels/evidence or introduces a benchmark prompt.
"""

from pathlib import Path
import os
from typing import Any

from backend.app.h9n.extraction.repe_extractor import (
    ExtractionError,
    default_model_for,
    extract_repe_deal,
    extraction_input_sha256,
    extraction_prompt_sha256,
)
from backend.app.h9n.extraction.telemetry import capture_model_usage
from backend.app.h9n.ingestion.pdf_reader import PdfReadError, read_pdf
from backend.evaluation.fields import PERCENT_FIELDS, PRODUCTION_FIELDS
from backend.evaluation.scoring import equal

# "conflicting_evidence" is M1.2's own cross-passage check; "model_conflicting"
# is the model's flag. Both mean the document disagrees with itself.
CONFLICT_REASONS = {"model_conflicting", "conflicting_evidence"}

# benchmark name -> (production name, benchmark unit, normalization factor).
# Identity only: a benchmark field scores the extractor when it is named after
# the REPEDealProfile field it tests (backend/evaluation/fields.py), so no
# alias can quietly stretch one profile field over two different facts.
# Production stores percentages as 6.5; the labels use ratios (.065).
FIELD_MAP = {name: (name, unit, .01 if name in PERCENT_FIELDS else 1)
             for name, (unit, _) in PRODUCTION_FIELDS.items()}


def profile_fields(profile, case: dict, *, incomplete_scope: bool) -> dict:
    fields = {}
    documents = {Path(d["path"]).name: d["document_id"] for d in case["documents"]}
    withheld = {item.field_name: item for item in profile.withheld_values}
    for name, spec in case["requested_fields"].items():
        mapping = FIELD_MAP.get(name)
        if mapping is None or mapping[1] != spec["unit"]:
            continue
        source, unit, factor = mapping
        value = getattr(profile, source)
        # Flags can exist even when the model left the original value null,
        # in which case integrity enforcement creates no withheld record.
        conflicting = any(note.casefold().startswith(source + ":") for note in profile.conflicting_information)
        # M1.2 keeps a value whose label shows a different figure elsewhere
        # ("possible conflict") and adds an uncertain note for the reviewer.
        # The stored value is still the extraction's answer, so it is scored
        # by its value; only other uncertain notes withhold it. getattr: the
        # field doesn't exist before M1.2 merges.
        possible = {f"{entry.field_name}: {entry.detail}".casefold()
                    for entry in getattr(profile, "possible_conflicts", None) or []}
        uncertain = any(note.casefold().startswith(source + ":") and note.casefold() not in possible
                        for note in profile.uncertain_information)
        evidence = [{"document_id": documents.get(e.source_document, e.source_document), "page": e.page_number}
                    for e in profile.evidence if e.field_name == source]
        if source in withheld:
            item = withheld[source]
            status = "conflict" if item.reason in CONFLICT_REASONS else "uncertain"
            fields[name] = {"status": status, "value": None, "unit": unit, "evidence": [], "reason": item.reason}
            # M1.2 keeps every disagreeing passage as `conflicting_values`
            # (getattr: profiles from before M1.2 don't have it). Without at
            # least two verified passages there is only one proposed value
            # and a note; never parse notes or fabricate candidates.
            passages = getattr(item, "conflicting_values", None) or []
            if status == "conflict" and len(passages) >= 2:
                candidates = []
                for passage in passages:
                    value = passage.value * factor if isinstance(passage.value, (int, float)) else passage.value
                    if not any(equal(value, seen) for seen in candidates):
                        candidates.append(value)
                if len(candidates) >= 2:
                    fields[name]["candidates"] = candidates
                    fields[name]["evidence"] = [
                        {"document_id": documents.get(p.evidence.source_document, p.evidence.source_document),
                         "page": p.evidence.page_number} for p in passages]
        elif conflicting or uncertain:
            fields[name] = {"status": "conflict" if conflicting else "uncertain", "value": None,
                            "unit": unit, "evidence": [], "reason": "Production field flag requires review"}
        elif value is None and incomplete_scope:
            fields[name] = {"status": "uncertain", "value": None, "unit": unit, "evidence": [],
                            "reason": "Some package sources could not be read by the PDF extractor"}
        else:
            normalized = value * factor if isinstance(value, (int, float)) else value
            fields[name] = {"status": "present" if value is not None else "missing",
                            "value": normalized, "unit": unit, "evidence": evidence}
    return fields


def extract(case: dict, *, client: Any = None, model: str | None = None, provider: str | None = None) -> dict:
    model = model or default_model_for(provider)
    skipped = [d["document_id"] for d in case["documents"] if Path(d["path"]).suffix.lower() != ".pdf"]
    result = {
        "fields": {}, "execution_kind": "hana_production_pdf", "usage": [],
        "metadata": {"requested_model": model,
                     "provider": provider or os.environ.get("H9N_EXTRACTION_PROVIDER", "anthropic"),
                     "prompt_sha256": extraction_prompt_sha256(),
                     "unsupported_source_documents": skipped,
                     "unsupported_schema_fields": [name for name, spec in case["requested_fields"].items()
                                                   if name not in FIELD_MAP or FIELD_MAP[name][1] != spec["unit"]],
                     "limitations": ["Production accepts PDF text only; workbook evidence is not extracted.",
                                     "Conflict candidates are scored only when production keeps every disagreeing passage (M1.2).",
                                     "Source/scenario-specific financial fields are not mapped to generic profile fields."]},
    }
    with capture_model_usage() as usage:
        try:
            pages = []
            for doc in case["documents"]:
                if doc["document_id"] not in skipped:
                    pages.extend(read_pdf(doc["path"]))
            if not pages:
                raise PdfReadError("No supported PDF input; workbook extraction is not implemented.")
            result["metadata"]["input_sha256"] = extraction_input_sha256(pages)
            options = {"provider": provider} if provider is not None else {}
            profile = extract_repe_deal(pages, client=client, model=model, **options)
            result["fields"] = profile_fields(profile, case, incomplete_scope=bool(skipped))
            # Preserve exactly what production returned for review/replay. This
            # remains extraction output; it is never used to create gold labels.
            result["profile"] = profile.model_dump(mode="json")
        except (ExtractionError, PdfReadError) as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            result["usage"] = list(usage)
    return result
