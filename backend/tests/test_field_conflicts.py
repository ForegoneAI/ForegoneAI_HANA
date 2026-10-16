"""Tests for Milestone 1.2 - detecting conflicting source passages.

Two checks, both keeping every passage they find so a reviewer sees each side:
- passages the model cited for one field that verify with different values
  are a conflict: the value is withheld ("conflicting_evidence");
- a stored value whose label introduces a different figure elsewhere is a
  *possible* conflict (deal packages reuse labels across in-place / pro forma
  sections and across loans): the value is kept and flagged for review.
"""

import pytest

from backend.app.h9n.extraction.extraction_output import (
    MAX_CONFLICT_PASSAGES,
    REPEExtractionOutput,
    enforce_integrity,
    snippet_supports_value,
)
from backend.app.h9n.schemas.repe_deal import REPEDealProfile
from backend.tests.extraction_fakes import evidence, full_output


def _page(text, page_number=1, file_name="deal.pdf"):
    return {"file_name": file_name, "page_number": page_number, "text": text}


def _enforce(pages, **overrides):
    return enforce_integrity(REPEExtractionOutput.model_validate(full_output(**overrides)), pages)


def _asking_price(pages, value=10_000_000, snippet="Asking Price: $10,000,000", page_number=1, **extra):
    return _enforce(
        pages,
        asking_price=value,
        evidence=[evidence("asking_price", value, snippet, page_number=page_number, source_document="deal.pdf")],
        **extra,
    )


# --- The same label with a different figure: a possible conflict -----------------


def test_the_same_label_with_a_different_figure_keeps_the_value_and_flags_it():
    pages = [
        _page("Executive Summary\nAsking Price: $10,000,000\nUnits: 128"),
        _page("Pricing\nAsking Price: $9,500,000", page_number=5),
    ]

    deal = _asking_price(pages)

    # The verified value is kept - the label may belong to another section.
    assert deal.asking_price == 10_000_000
    assert [e.field_name for e in deal.evidence] == ["asking_price"]
    assert deal.withheld_values == []
    [possible] = deal.possible_conflicts
    assert possible.field_name == "asking_price"
    # Both pieces of evidence are preserved, each with its own value and page.
    assert [(c.value, c.evidence.page_number, c.evidence.snippet) for c in possible.conflicting_values] == [
        (10_000_000, 1, "Asking Price: $10,000,000"),
        (9_500_000, 5, "Asking Price: $9,500,000"),
    ]
    assert all(c.evidence.verification == "value_matched" for c in possible.conflicting_values)
    assert possible.detail.startswith(
        "The same label gives a different figure elsewhere in the document: "
        "10000000 (deal.pdf p.1), 9500000 (deal.pdf p.5)."
    )
    # The entry is the only record of the flag; no note repeats it.
    assert deal.uncertain_information == []
    assert deal.conflicting_information == []
    report = deal.field_statuses["asking_price"]
    assert (report.status, report.needs_review) == ("uncertain", True)
    assert [r.code for r in report.reasons] == ["same_label_different_value"]
    assert report.conflicting_values == possible.conflicting_values


@pytest.mark.parametrize(
    "page_one, page_two, fields",
    [
        # In-place vs pro forma figures under the same labels.
        (
            "In-Place Financials\nNOI: $1,200,000\nOccupancy: 92%",
            "Pro Forma\nNOI: $1,500,000\nOccupancy: 95%",
            {"noi": (1_200_000, "NOI: $1,200,000"), "occupancy_rate": (92, "Occupancy: 92%")},
        ),
        # A senior and a mezzanine loan with the same labels.
        (
            "Senior Loan\nLoan Amount: $20,000,000\nInterest Rate: 6.0%",
            "Mezzanine Loan\nLoan Amount: $5,000,000\nInterest Rate: 11.0%",
            {"loan_amount": (20_000_000, "Loan Amount: $20,000,000"), "interest_rate": (6.0, "Interest Rate: 6.0%")},
        ),
    ],
)
def test_figures_from_other_sections_never_withhold_a_correct_value(page_one, page_two, fields):
    pages = [_page(page_one), _page(page_two, page_number=7)]

    deal = _enforce(
        pages,
        **{name: value for name, (value, _) in fields.items()},
        evidence=[evidence(name, value, line, source_document="deal.pdf") for name, (value, line) in fields.items()],
    )

    for name, (value, _) in fields.items():
        assert getattr(deal, name) == value
    assert deal.withheld_values == []
    assert sorted(p.field_name for p in deal.possible_conflicts) == sorted(fields)
    assert {deal.field_statuses[name].status for name in fields} == {"uncertain"}


def test_conflicting_passages_are_found_across_documents():
    pages = [
        _page("Asking Price: $10,000,000", file_name="om.pdf"),
        _page("Teaser\nAsking Price: $9.0M", page_number=2, file_name="teaser.pdf"),
    ]

    deal = _enforce(
        pages,
        asking_price=10_000_000,
        evidence=[evidence("asking_price", 10_000_000, "Asking Price: $10,000,000", source_document="om.pdf")],
    )

    [possible] = deal.possible_conflicts
    assert [(c.value, c.evidence.source_document) for c in possible.conflicting_values] == [
        (10_000_000, "om.pdf"),
        (9_000_000, "teaser.pdf"),
    ]


def test_the_same_value_stated_again_is_corroboration_not_a_conflict():
    pages = [
        _page("Asking Price: $10,000,000"),
        _page("Summary\nAsking Price: $10.0M\nAsking Price - 10,000,000 USD", page_number=2),
    ]

    deal = _asking_price(pages)

    assert deal.asking_price == 10_000_000
    assert deal.withheld_values == []
    assert deal.possible_conflicts == []
    assert deal.uncertain_information == []
    assert deal.field_statuses["asking_price"].status == "supported"


def test_when_there_is_a_conflict_every_passage_is_kept_including_agreeing_ones():
    pages = [
        _page("Asking Price: $10,000,000"),
        _page("Asking Price: $10,000,000", page_number=2),
        _page("Asking Price: $9,500,000", page_number=3),
    ]

    [possible] = _asking_price(pages).possible_conflicts

    assert [(c.value, c.evidence.page_number) for c in possible.conflicting_values] == [
        (10_000_000, 1),
        (10_000_000, 2),
        (9_500_000, 3),
    ]
    assert "10000000 (deal.pdf p.1; deal.pdf p.2)" in possible.detail


def test_the_passage_cap_never_drops_the_disagreeing_passage():
    # Many pages repeat the extracted figure; the one that differs is last.
    pages = [_page("Asking Price: $10,000,000", page_number=n) for n in range(1, 31)]
    pages.append(_page("Asking Price: $9,500,000", page_number=31))

    [possible] = _asking_price(pages).possible_conflicts

    assert len(possible.conflicting_values) == MAX_CONFLICT_PASSAGES + 1  # plus the value's own
    assert possible.conflicting_values[-1].value == 9_500_000
    assert possible.conflicting_values[-1].evidence.page_number == 31


@pytest.mark.parametrize(
    "field_name, value, cited_line, other_line",
    [
        ("cap_rate", 6.5, "Cap Rate: 6.5%", "Cap Rate: 6.25%"),
        ("occupancy_rate", 94, "Occupancy: 94%", "Occupancy: 0.89"),
        ("units", 128, "Units: 128", "Units: 132"),
        ("noi", -150_000, "NOI: ($150,000)", "NOI: $150,000"),
        ("year_built", 1998, "Year Built: 1998", "Year Built: 2001"),
        ("loan_amount", 6_500_000, "Loan Amount ... $6,500,000", "Loan Amount: $7,000,000"),
    ],
)
def test_possible_conflicts_are_detected_for_each_kind_of_number(field_name, value, cited_line, other_line):
    pages = [_page(f"Overview\n{cited_line}"), _page(f"Details\n{other_line}", page_number=4)]

    deal = _enforce(
        pages, **{field_name: value}, evidence=[evidence(field_name, value, cited_line, source_document="deal.pdf")]
    )

    assert getattr(deal, field_name) == value
    [possible] = deal.possible_conflicts
    assert len(possible.conflicting_values) == 2
    assert possible.conflicting_values[1].evidence.snippet == other_line


# --- What doesn't count ---------------------------------------------------------


@pytest.mark.parametrize(
    "other_line",
    [
        # A different, longer label that merely contains this one.
        "Pro Forma Asking Price: $12,000,000",
        "Asking Price per Unit: $78,125",
        # The label mid-sentence, not introducing a figure.
        "We believe the asking price of $11,000,000 quoted by others is stale.",
        # A row of figures after the label (years, scenarios) or a range.
        "Asking Price: $9,500,000 $9,800,000 $10,100,000",
        "Asking Price: $9,500,000 - $10,500,000",
        # A figure of the wrong kind for the field.
        "Asking Price: 4 offers received",
        # A figure that isn't directly after the label.
        "Asking Price: see page 7 for the $9,500,000 guidance",
    ],
)
def test_passages_that_dont_clearly_restate_the_field_are_not_conflicts(other_line):
    pages = [_page("Asking Price: $10,000,000"), _page(other_line, page_number=2)]

    deal = _asking_price(pages)

    assert deal.asking_price == 10_000_000
    assert deal.possible_conflicts == []
    assert deal.field_statuses["asking_price"].status == "supported"


@pytest.mark.parametrize(
    "cited_line",
    [
        # Too generic to say which figure it introduces.
        "Total: $10,000,000",
        "Price: $10,000,000",
        # No label in front of the figure at all.
        "$10,000,000 asking price",
    ],
)
def test_a_value_without_a_specific_label_is_not_scanned_for(cited_line):
    pages = [_page(cited_line), _page(cited_line.replace("10,000,000", "9,500,000"), page_number=2)]

    deal = _asking_price(pages, snippet=cited_line)

    assert deal.asking_price == 10_000_000
    assert deal.possible_conflicts == []


def test_text_fields_are_not_scanned_for_conflicts():
    pages = [_page("Property Name: Meadowbrook Apartments"), _page("Property Name: Meadowbrook", page_number=2)]

    deal = _enforce(
        pages,
        property_name="Meadowbrook Apartments",
        evidence=[
            evidence(
                "property_name",
                "Meadowbrook Apartments",
                "Property Name: Meadowbrook Apartments",
                source_document="deal.pdf",
            )
        ],
    )

    assert deal.property_name == "Meadowbrook Apartments"
    assert deal.withheld_values == []
    assert deal.possible_conflicts == []


# --- Passages the model cited: a conflict, the value is withheld ---------------------------------------------------


def test_a_second_citation_with_a_different_value_is_a_conflict():
    # No shared label here; the model itself cited both passages.
    pages = [_page("The seller is asking $10,000,000 for the property."), _page("Guidance is $9.5M.", page_number=3)]

    deal = _enforce(
        pages,
        asking_price=10_000_000,
        evidence=[
            evidence("asking_price", 10_000_000, "asking $10,000,000 for the property", source_document="deal.pdf"),
            evidence("asking_price", "$9.5M", "Guidance is $9.5M.", page_number=3, source_document="deal.pdf"),
        ],
    )

    assert deal.asking_price is None
    [withheld] = deal.withheld_values
    assert withheld.reason == "conflicting_evidence"
    assert withheld.proposed_value == 10_000_000
    assert [(c.value, c.evidence.page_number) for c in withheld.conflicting_values] == [(10_000_000, 1), (9_500_000, 3)]
    assert all(c.evidence.verification == "value_matched" for c in withheld.conflicting_values)
    # The citation's value text becomes the field's own normalized value.
    assert withheld.conflicting_values[1].evidence.value == "9500000"
    assert withheld.detail == "The document gives different values: 10000000 (deal.pdf p.1), 9500000 (deal.pdf p.3)."
    # Noted in the same "field: ..." form as the model's own flags, so the
    # M2.2 form marks it conflicting without any change.
    assert deal.conflicting_information == [f"asking_price: {withheld.detail}"]
    assert deal.field_statuses["asking_price"].status == "conflicting"


def test_a_second_citation_that_doesnt_check_out_is_not_a_conflict():
    pages = [_page("Asking Price: $10,000,000")]

    deal = _enforce(
        pages,
        asking_price=10_000_000,
        evidence=[
            evidence("asking_price", 10_000_000, "Asking Price: $10,000,000", source_document="deal.pdf"),
            # Not on the page, and on a page that doesn't exist.
            evidence("asking_price", 9_500_000, "Asking Price: $9,500,000", source_document="deal.pdf"),
            evidence("asking_price", 9_000_000, "Asking Price: $9,000,000", page_number=8, source_document="deal.pdf"),
        ],
    )

    assert deal.asking_price == 10_000_000
    assert deal.withheld_values == []


def test_a_model_flagged_conflict_keeps_the_other_passage_it_cited():
    pages = [_page("Property Name: Meadowbrook Apartments"), _page("Property Name: Brookside Commons", page_number=2)]

    deal = _enforce(
        pages,
        property_name="Meadowbrook Apartments",
        evidence=[
            evidence(
                "property_name",
                "Meadowbrook Apartments",
                "Property Name: Meadowbrook Apartments",
                source_document="deal.pdf",
            ),
            evidence(
                "property_name",
                "Brookside Commons",
                "Property Name: Brookside Commons",
                page_number=2,
                source_document="deal.pdf",
            ),
        ],
        field_flags=[
            {"field_name": "property_name", "flag": "conflicting", "note": "page 2 names it Brookside Commons"}
        ],
    )

    [withheld] = deal.withheld_values
    # The model's flag keeps its reason and note; the passages are attached.
    assert withheld.reason == "model_conflicting"
    assert withheld.detail == "page 2 names it Brookside Commons"
    assert [c.value for c in withheld.conflicting_values] == ["Meadowbrook Apartments", "Brookside Commons"]
    assert deal.conflicting_information == ["property_name: page 2 names it Brookside Commons"]


def test_a_model_flagged_conflict_without_other_passages_is_unchanged():
    pages = [_page("Asking Price: $10,000,000")]

    deal = _asking_price(
        pages,
        field_flags=[{"field_name": "asking_price", "flag": "conflicting", "note": "the teaser says $9.5M"}],
    )

    [withheld] = deal.withheld_values
    assert withheld.reason == "model_conflicting"
    assert withheld.conflicting_values == []
    assert deal.conflicting_information == ["asking_price: the teaser says $9.5M"]


def test_a_detected_conflict_outranks_an_uncertain_flag_and_keeps_its_note():
    pages = [_page("Asking Price: $10,000,000"), _page("Guidance is $9.5M.", page_number=2)]

    deal = _enforce(
        pages,
        asking_price=10_000_000,
        evidence=[
            evidence("asking_price", 10_000_000, "Asking Price: $10,000,000", source_document="deal.pdf"),
            evidence("asking_price", 9_500_000, "Guidance is $9.5M.", page_number=2, source_document="deal.pdf"),
        ],
        field_flags=[{"field_name": "asking_price", "flag": "uncertain", "note": "marketing summary"}],
    )

    [withheld] = deal.withheld_values
    assert withheld.reason == "conflicting_evidence"
    assert withheld.detail.endswith("Also flagged: marketing summary")
    assert deal.uncertain_information == ["asking_price: marketing summary"]
    assert deal.field_statuses["asking_price"].status == "conflicting"


def test_a_value_whose_own_citation_fails_still_records_the_conflict():
    pages = [_page("The seller is asking $10,000,000."), _page("Guidance is $9.5M.", page_number=2)]

    deal = _enforce(
        pages,
        asking_price=10_000_000,
        evidence=[
            evidence("asking_price", 10_000_000, "not on the page at all", source_document="deal.pdf"),
            evidence("asking_price", 9_500_000, "Guidance is $9.5M.", page_number=2, source_document="deal.pdf"),
        ],
    )

    [withheld] = deal.withheld_values
    assert withheld.reason == "conflicting_evidence"
    # Only the passage that verified is kept; the failed citation stays as
    # the withheld entry's own evidence.
    assert [c.value for c in withheld.conflicting_values] == [9_500_000]
    assert withheld.evidence.snippet == "not on the page at all"
    # The explanation names both values and why the extracted one failed,
    # rather than listing only the other side.
    assert withheld.detail == (
        "The document gives 9500000 (deal.pdf p.2), not the extracted 10000000, whose citation didn't "
        "check out: The quoted snippet was not found on the cited page."
    )


def test_every_kept_passage_passes_the_same_evidence_check_as_a_citation():
    pages = [
        _page("Asking Price: $10,000,000\nCap Rate: 6.5%"),
        _page("Asking   Price :  $9,500,000\nCap Rate: 6.25%", page_number=2),
    ]
    deal = _enforce(
        pages,
        asking_price=10_000_000,
        cap_rate=6.5,
        evidence=[
            evidence("asking_price", 10_000_000, "Asking Price: $10,000,000", source_document="deal.pdf"),
            evidence("cap_rate", 6.5, "Cap Rate: 6.5%", source_document="deal.pdf"),
        ],
    )

    passages = [c for possible in deal.possible_conflicts for c in possible.conflicting_values]
    assert len(passages) == 4
    for passage in passages:
        page = next(p for p in pages if p["page_number"] == passage.evidence.page_number)
        assert snippet_supports_value(
            passage.evidence.field_name, passage.value, passage.evidence.snippet, page["text"]
        )


def test_a_long_paragraph_is_quoted_by_sentence():
    filler = "The property sits on a well-located corner lot with strong visibility. " * 6
    pages = [
        _page("Asking Price: $10,000,000"),
        _page(f"{filler}Asking Price: $9,500,000. More text follows here.", page_number=2),
    ]

    [possible] = _asking_price(pages).possible_conflicts

    assert possible.conflicting_values[1].evidence.snippet == "Asking Price: $9,500,000."


def test_conflicts_survive_a_round_trip_through_json():
    pages = [
        _page("Asking Price: $10,000,000\nNOI: $650,000"),
        _page("Asking Price: $9,500,000\nGuidance NOI of $700,000.", page_number=2),
    ]
    deal = _enforce(
        pages,
        asking_price=10_000_000,
        noi=650_000,
        evidence=[
            evidence("asking_price", 10_000_000, "Asking Price: $10,000,000", source_document="deal.pdf"),
            evidence("noi", 650_000, "NOI: $650,000", source_document="deal.pdf"),
            evidence("noi", 700_000, "Guidance NOI of $700,000.", page_number=2, source_document="deal.pdf"),
        ],
    )

    reloaded = REPEDealProfile.model_validate_json(deal.model_dump_json())

    assert reloaded.withheld_values == deal.withheld_values
    assert reloaded.possible_conflicts == deal.possible_conflicts
    assert reloaded.field_statuses["noi"].conflicting_values[1].value == 700_000
    assert reloaded.field_statuses["asking_price"].conflicting_values[1].value == 9_500_000


def test_a_long_document_is_checked_quickly():
    # The document is indexed once and lines are only parsed for numbers when
    # the label is on them, so this stays well under a second.
    import time

    body = "\n".join(f"Line {i}: {i * 3} spaces and ${i * 1000:,} in reserves as of 2024." for i in range(40))
    pages = [_page(f"Asking Price: $10,000,000\nNOI: $650,000\n{body}", page_number=n) for n in range(1, 301)]
    pages[-1]["text"] += "\nNOI: $700,000"

    started = time.perf_counter()
    deal = _enforce(
        pages,
        asking_price=10_000_000,
        noi=650_000,
        evidence=[
            evidence("asking_price", 10_000_000, "Asking Price: $10,000,000", source_document="deal.pdf"),
            evidence("noi", 650_000, "NOI: $650,000", source_document="deal.pdf"),
        ],
    )

    assert time.perf_counter() - started < 2
    assert [p.field_name for p in deal.possible_conflicts] == ["noi"]


@pytest.mark.parametrize(
    "cited_value, snippet, expected",
    [
        ("0.5%", "Going-in cap rate of 0.5% on page two", 0.5),
        ("6.25%", "Going-in cap rate of 6.25% on page two", 6.25),
        ("0.0625", "Going-in cap rate of 0.0625 on page two", 6.25),
    ],
)
def test_a_cited_percentage_is_read_the_way_its_passage_states_it(cited_value, snippet, expected):
    pages = [_page("Cap Rate: 6.5%"), _page(snippet, page_number=2)]

    deal = _enforce(
        pages,
        cap_rate=6.5,
        evidence=[
            evidence("cap_rate", 6.5, "Cap Rate: 6.5%", source_document="deal.pdf"),
            evidence("cap_rate", cited_value, snippet, page_number=2, source_document="deal.pdf"),
        ],
    )

    [withheld] = deal.withheld_values
    assert [c.value for c in withheld.conflicting_values] == [6.5, expected]
