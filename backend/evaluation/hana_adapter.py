"""Evaluate the existing production PDF extractor without database writes.

Mappings are deliberately conservative: generic `noi` cannot stand for both
current and pro-forma NOI, and a profile's square_feet cannot stand for lot
area. Expanding production coverage requires an explicit semantic mapping.
The adapter never imports labels/evidence or introduces a benchmark prompt.
"""

from pathlib import Path
import os
from typing import Any

from backend.app.h9n.extraction.repe_extractor import (
    DEFAULT_MODEL,
    ExtractionError,
    extract_repe_deal,
    extraction_input_sha256,
    extraction_prompt_sha256,
)
from backend.app.h9n.extraction.telemetry import capture_model_usage
from backend.app.h9n.ingestion.pdf_reader import PdfReadError, read_pdf

# benchmark name -> (production name, benchmark unit, normalization factor).
# Production stores percentages as 6.5; the supplied labels use ratio .065.
FIELD_MAP = {
    "asking_price": ("asking_price", "USD", 1),
    "units": ("units", "count", 1),
    "year_built": ("year_built", "year", 1),
    "building_area": ("square_feet", "sqft", 1),
    "rentable_area": ("square_feet", "sqft", 1),
    "occupancy": ("occupancy_rate", "ratio", .01),
    "loan_amount": ("loan_amount", "USD", 1),
    "interest_rate": ("interest_rate", "ratio", .01),
    "ltv": ("ltv", "ratio", .01),
    "property_address": ("address", "text", 1),
}


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
        uncertain = any(note.casefold().startswith(source + ":") for note in profile.uncertain_information)
        evidence = [{"document_id": documents.get(e.source_document, e.source_document), "page": e.page_number}
                    for e in profile.evidence if e.field_name == source]
        if source in withheld:
            item = withheld[source]
            status = "conflict" if item.reason == "model_conflicting" else "uncertain"
            fields[name] = {"status": status, "value": None, "unit": unit, "evidence": [], "reason": item.reason}
            # Production currently retains one proposed value and a note,
            # not the full candidate/evidence set. Do not parse notes or
            # fabricate candidates to make conflict scoring pass.
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


def extract(case: dict, *, client: Any = None, model: str = DEFAULT_MODEL, provider: str | None = None) -> dict:
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
                                     "Production conflict records do not expose all candidates and citations.",
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
