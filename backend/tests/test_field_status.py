"""Tests for Milestone 1.2 - one trust status per extracted field.

REPEDealProfile.field_statuses tells an API caller or UI, field by field,
whether a value can be relied on ("supported") or needs a human
("uncertain", "missing", "conflicting"), and why. It is computed from the
rest of the profile, so it follows every correction without being stored.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.h9n.extraction.extraction_output import VALUE_FIELDS, REPEExtractionOutput, enforce_integrity
from backend.app.h9n.schemas.base_deal import (
    POSSIBLE_CONFLICT_PREFIX,
    ConflictingValue,
    FieldEvidence,
    PossibleConflict,
    WithheldValue,
)
from backend.app.h9n.schemas.field_status import (
    BOOKKEEPING_FIELDS,
    assess_field,
    note_names_field,
    note_text,
    value_fields,
)
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.tests.extraction_fakes import evidence, full_output


def _cite(field_name, value, verification="value_matched", page_number=1, snippet=None):
    return FieldEvidence(
        field_name=field_name,
        value=str(value),
        source_document="deal.pdf",
        page_number=page_number,
        snippet=snippet or f"{field_name}: {value}",
        verification=verification,
    )


def _status(profile, field_name):
    return profile.field_statuses[field_name]


# --- The four statuses ----------------------------------------------------------


def test_a_value_with_a_verified_citation_is_supported():
    deal = REPEDealProfile(asking_price=10_000_000, evidence=[_cite("asking_price", 10_000_000)])

    report = _status(deal, "asking_price")

    assert report.status == "supported"
    assert report.needs_review is False
    assert [reason.code for reason in report.reasons] == ["verified_citation"]
    assert report.evidence == deal.evidence


def test_a_field_with_no_value_is_missing():
    deal = REPEDealProfile(missing_information=["cap_rate: not stated in the document"])

    cap_rate = _status(deal, "cap_rate")
    noi = _status(deal, "noi")

    assert (cap_rate.status, cap_rate.needs_review) == ("missing", True)
    assert [(r.code, r.message) for r in cap_rate.reasons] == [("listed_as_missing", "not stated in the document")]
    assert [r.code for r in noi.reasons] == ["not_stated"]


@pytest.mark.parametrize(
    "deal, code",
    [
        # The model doubted it (the value is withheld, the note explains why).
        (
            REPEDealProfile(
                uncertain_information=["noi: the OM says approximately $650k"],
                withheld_values=[
                    WithheldValue(
                        field_name="noi", proposed_value=650_000, reason="model_uncertain", detail="approximately"
                    )
                ],
            ),
            "model_flagged_uncertain",
        ),
        # Its citation didn't check out.
        (
            REPEDealProfile(
                withheld_values=[
                    WithheldValue(field_name="noi", proposed_value=650_000, reason="snippet_not_on_page", detail="x")
                ]
            ),
            "unverified_value",
        ),
        # The model both gave it and listed it as missing.
        (
            REPEDealProfile(
                withheld_values=[
                    WithheldValue(
                        field_name="noi", proposed_value=650_000, reason="model_listed_as_missing", detail="x"
                    )
                ]
            ),
            "listed_as_missing",
        ),
        # A value with no citation at all (e.g. saved before Milestone 1.1).
        (REPEDealProfile(noi=650_000), "no_citation"),
        # A value whose citation was never verified.
        (REPEDealProfile(noi=650_000, evidence=[_cite("noi", 650_000, verification=None)]), "unverified_value"),
    ],
)
def test_values_that_shouldnt_be_relied_on_yet_are_uncertain(deal, code):
    report = _status(deal, "noi")

    assert report.status == "uncertain"
    assert report.needs_review is True
    assert code in [reason.code for reason in report.reasons]


def test_a_withheld_value_is_offered_as_the_proposed_value():
    deal = REPEDealProfile(
        withheld_values=[WithheldValue(field_name="noi", proposed_value=650_000, reason="no_evidence", detail="x")]
    )

    assert _status(deal, "noi").proposed_value == 650_000
    assert _status(deal, "cap_rate").proposed_value is None


def test_a_narrative_field_with_a_quote_only_citation_is_uncertain():
    # extraction_output.QUOTE_ONLY_FIELDS: the quote was found but the
    # summarized value can't be matched word for word, so a human should look.
    deal = REPEDealProfile(
        business_plan="Renovate units and raise rents",
        evidence=[_cite("business_plan", "Renovate units and raise rents", verification="quote_only")],
    )

    report = _status(deal, "business_plan")

    assert report.status == "uncertain"
    assert [reason.code for reason in report.reasons] == ["quote_only_citation"]


def test_a_conflict_carries_every_passage_and_its_value():
    passages = [
        ConflictingValue(value=10_000_000, evidence=_cite("asking_price", 10_000_000)),
        ConflictingValue(value=9_500_000, evidence=_cite("asking_price", 9_500_000, page_number=5)),
    ]
    deal = REPEDealProfile(
        conflicting_information=["asking_price: The document gives different values: ..."],
        withheld_values=[
            WithheldValue(
                field_name="asking_price",
                proposed_value=10_000_000,
                reason="conflicting_evidence",
                detail="The document gives different values: ...",
                evidence=_cite("asking_price", 10_000_000, verification=None),
                conflicting_values=passages,
            )
        ],
    )

    report = _status(deal, "asking_price")

    assert (report.status, report.needs_review) == ("conflicting", True)
    assert report.conflicting_values == passages
    # One reason, not the same text twice from the withheld entry and its note.
    assert [r.code for r in report.reasons] == ["conflicting_values"]
    # Every citation in one place, de-duplicated (the withheld entry's own
    # citation is the same passage as the first conflicting value).
    assert [(e.page_number, e.snippet) for e in report.evidence] == [
        (1, "asking_price: 10000000"),
        (5, "asking_price: 9500000"),
    ]


def test_a_conflict_note_alone_makes_a_field_conflicting():
    # The model flagged the conflict but left the field null, so there's no
    # withheld entry - only its note.
    deal = REPEDealProfile(conflicting_information=["Cap rate: 6.5% in the summary, 6.25% in the financials"])

    report = _status(deal, "cap_rate")

    assert report.status == "conflicting"
    assert [(r.code, r.message) for r in report.reasons] == [
        ("model_flagged_conflicting", "6.5% in the summary, 6.25% in the financials")
    ]


def test_conflicting_outranks_uncertain_outranks_missing():
    deal = REPEDealProfile(
        conflicting_information=["noi: $650k on p.2, $700k on p.9"],
        uncertain_information=["noi: approximate"],
        missing_information=["noi: not stated"],
    )

    assert _status(deal, "noi").status == "conflicting"
    deal.conflicting_information = []
    assert _status(deal, "noi").status == "uncertain"
    deal.uncertain_information = []
    assert _status(deal, "noi").status == "missing"


# --- Reviewer corrections ----------------------------------------------------------


def test_a_reviewer_corrected_value_is_trusted_whatever_the_extractor_said():
    deal = REPEDealProfile(
        noi=700_000,
        corrected_fields=["noi"],
        conflicting_information=["noi: $650k on p.2, $700k on p.9"],
        uncertain_information=["noi: approximate"],
    )

    report = _status(deal, "noi")

    assert report.status == "supported"
    assert report.needs_review is False
    assert report.reviewer_corrected is True
    assert [r.code for r in report.reasons] == ["reviewer_corrected"]


def test_a_newer_proposal_for_a_corrected_field_needs_review_again():
    # E.g. the extractor re-derived the field after reviewer feedback but
    # couldn't verify the new value: it waits in withheld_values.
    deal = REPEDealProfile(
        noi=700_000,
        corrected_fields=["noi"],
        conflicting_information=["noi: $650k on p.2, $700k on p.9"],
        withheld_values=[
            WithheldValue(field_name="noi", proposed_value=650_000, reason="snippet_not_on_page", detail="Not found.")
        ],
    )

    report = _status(deal, "noi")

    assert (report.status, report.needs_review, report.reviewer_corrected) == ("uncertain", True, True)
    assert report.proposed_value == 650_000
    # Notes from before the correction no longer count; the proposal does.
    assert [r.code for r in report.reasons] == ["unverified_value", "reviewer_corrected"]

    # Accepting or dismissing it (the review form drops the entry) settles it.
    deal.withheld_values = []
    assert _status(deal, "noi").needs_review is False


def test_a_possible_conflict_flags_a_stored_value_as_uncertain():
    passages = [
        ConflictingValue(value=1_200_000, evidence=_cite("noi", 1_200_000)),
        ConflictingValue(value=1_500_000, evidence=_cite("noi", 1_500_000, page_number=7)),
    ]
    detail = f"{POSSIBLE_CONFLICT_PREFIX}: 1200000 (deal.pdf p.1), 1500000 (deal.pdf p.7). Confirm which."
    deal = REPEDealProfile(
        noi=1_200_000,
        evidence=[_cite("noi", 1_200_000)],
        uncertain_information=[f"noi: {detail}"],
        possible_conflicts=[PossibleConflict(field_name="noi", detail=detail, conflicting_values=passages)],
    )

    report = _status(deal, "noi")

    assert (report.status, report.needs_review) == ("uncertain", True)
    # One reason, not the same text again from its note.
    assert [r.code for r in report.reasons] == ["same_label_different_value"]
    assert report.conflicting_values == passages
    assert [e.page_number for e in report.evidence] == [1, 7]

    # A reviewer dismissing it settles it, even though its note remains...
    dismissed = deal.model_copy(update={"possible_conflicts": []})
    assert _status(dismissed, "noi").status == "supported"
    # ...and so does a reviewer confirming the value.
    deal.corrected_fields.append("noi")
    assert _status(deal, "noi").needs_review is False


def test_a_field_a_reviewer_cleared_is_missing_but_needs_no_review():
    deal = REPEDealProfile(corrected_fields=["noi"])

    report = _status(deal, "noi")

    assert (report.status, report.needs_review, report.reviewer_corrected) == ("missing", False, True)


def test_the_status_follows_the_profile_as_it_changes():
    deal = REPEDealProfile(
        withheld_values=[WithheldValue(field_name="noi", proposed_value=650_000, reason="model_uncertain", detail="x")]
    )
    assert _status(deal, "noi").status == "uncertain"

    # A reviewer accepts the proposal (as the review workflow does it).
    deal.noi = 650_000
    deal.withheld_values = []
    deal.corrected_fields.append("noi")

    assert _status(deal, "noi").status == "supported"


# --- Coverage and serialization ---------------------------------------------------


def test_every_extracted_value_field_has_a_status_and_nothing_else_does():
    deal = REPEDealProfile()

    assert list(deal.field_statuses) == VALUE_FIELDS
    assert value_fields(deal) == VALUE_FIELDS
    assert not BOOKKEEPING_FIELDS & set(deal.field_statuses)


def test_a_fresh_extraction_gets_a_status_for_every_field():
    pages = [{"file_name": "deal.pdf", "page_number": 1, "text": "Asking Price: $10,000,000\nUnits: 128"}]
    output = full_output(
        asking_price=10_000_000,
        units=130,
        evidence=[
            evidence("asking_price", 10_000_000, "Asking Price: $10,000,000", source_document="deal.pdf"),
            evidence("units", 130, "Units: 128", source_document="deal.pdf"),
        ],
        missing_information=["cap_rate: not stated"],
    )

    deal = enforce_integrity(REPEExtractionOutput.model_validate(output), pages)
    statuses = {name: report.status for name, report in deal.field_statuses.items()}

    assert statuses["asking_price"] == "supported"
    assert statuses["units"] == "uncertain"  # its citation says 128
    assert statuses["cap_rate"] == "missing"
    needing_review = [name for name, report in deal.field_statuses.items() if report.needs_review]
    assert "asking_price" not in needing_review
    assert {"units", "cap_rate"} <= set(needing_review)


def test_field_statuses_is_in_every_dump_and_ignored_on_the_way_back_in():
    deal = REPEDealProfile(asking_price=10_000_000, evidence=[_cite("asking_price", 10_000_000)])

    dumped = deal.model_dump(mode="json")
    assert dumped["field_statuses"]["asking_price"]["status"] == "supported"

    # A stored or client-sent copy is ignored and recomputed, so a stale or
    # forged status can't be loaded with a profile.
    dumped["field_statuses"]["asking_price"]["status"] = "missing"
    dumped["field_statuses"]["noi"]["status"] = "supported"
    reloaded = REPEDealProfile.model_validate(dumped)
    assert reloaded.field_statuses["asking_price"].status == "supported"
    assert reloaded.field_statuses["noi"].status == "missing"


def test_field_statuses_cant_be_set_directly():
    deal = REPEDealProfile()

    with pytest.raises(AttributeError):
        deal.field_statuses = {}
    assert "field_statuses" not in REPEDealProfile.model_fields


def test_an_api_response_includes_the_statuses():
    # Any route returning a profile includes them, with no route changes.
    app = FastAPI()

    @app.get("/profile", response_model=REPEDealProfile)
    def profile():
        return REPEDealProfile(asking_price=10_000_000, evidence=[_cite("asking_price", 10_000_000)])

    body = TestClient(app).get("/profile").json()

    assert body["field_statuses"]["asking_price"]["status"] == "supported"
    assert body["field_statuses"]["noi"] == {
        "status": "missing",
        "needs_review": True,
        "reviewer_corrected": False,
        "reasons": [{"code": "not_stated", "message": "No value was found in the document."}],
        "proposed_value": None,
        "conflicting_values": [],
        "evidence": [],
    }
    schemas = app.openapi()["components"]["schemas"]
    profile_schema = next(schema for name, schema in schemas.items() if name.startswith("REPEDealProfile"))
    assert "field_statuses" in profile_schema["properties"]


def test_the_extraction_tool_schema_does_not_ask_the_model_for_statuses():
    # Statuses are H9N's judgment of the model's output, never the model's.
    assert "field_statuses" not in REPEExtractionOutput.model_fields


# --- Reading notes ------------------------------------------------------------------


@pytest.mark.parametrize(
    "note, field_name, expected",
    [
        ("cap_rate: not stated", "cap_rate", True),
        ("Cap rate not stated", "cap_rate", True),
        ("NOI - approximate", "noi", True),
        ("units: 128 or 132", "units", True),
        ("units_renovated: none", "units", False),
        ("unitsx", "units", False),
        ("No rent roll provided", "noi", False),
    ],
)
def test_a_note_names_a_field_when_it_starts_with_its_name(note, field_name, expected):
    assert note_names_field(note, field_name) is expected


def test_note_text_drops_the_field_name():
    assert note_text("cap_rate: not stated", "cap_rate") == "not stated"
    assert note_text("Cap rate - 6.5% vs 6.25%", "cap_rate") == "6.5% vs 6.25%"
    assert note_text("cap_rate", "cap_rate") == "cap_rate"


def test_assess_field_works_on_any_deal_profile():
    deal = REPEDealProfile(units=128, evidence=[_cite("units", 128)])

    assert assess_field(deal, "units").status == "supported"


# --- The model never sees or produces statuses ---------------------------------------


def test_the_feedback_prompt_shows_the_profile_without_statuses():
    from backend.app.h9n.extraction.repe_extractor import apply_reviewer_feedback
    from backend.tests.extraction_fakes import fake_client, tool_response

    client = fake_client(tool_response({"corrections": {}, "updated_evidence": [], "explanation": "No change."}))
    deal = REPEDealProfile(asking_price=1_000_000, evidence=[_cite("asking_price", 1_000_000)])
    pages = [{"file_name": "deal.pdf", "page_number": 1, "text": "Asking Price: $950,000."}]

    apply_reviewer_feedback(pages, deal, "price is wrong", client=client)

    prompt = client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert '"asking_price": 1000000.0' in prompt
    assert "field_statuses" not in prompt


def test_bookkeeping_fields_are_defined_once_and_never_extracted():
    from backend.app.h9n.extraction import extraction_output
    from backend.app.h9n.schemas import base_deal

    # field_status, the extractor and the profile all use the one list in
    # base_deal, so a bookkeeping field added there can't get a status or be
    # asked of the model by mistake.
    assert BOOKKEEPING_FIELDS is base_deal.BOOKKEEPING_FIELDS
    assert set(VALUE_FIELDS) == set(REPEDealProfile.model_fields) - BOOKKEEPING_FIELDS
    assert extraction_output.NON_EXTRACTABLE_FIELDS == BOOKKEEPING_FIELDS - extraction_output._META_FIELDS
    assert "possible_conflicts" in extraction_output.NON_EXTRACTABLE_FIELDS
    assert BOOKKEEPING_FIELDS <= set(REPEDealProfile.model_fields)
