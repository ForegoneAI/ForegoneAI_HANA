import { describe, expect, it } from "vitest";

import type { DealHistory, DealProfile, WithheldValue } from "./api";
import { ALL_FIELDS, FIELD_GROUPS, formatValue, parseInput, type FieldSpec } from "./dealFields";
import { citationFor, linkIsFresh, pdfPageUrl, verificationText } from "./evidence";
import { attentionCount, generalNotes, noteNamesField, noteText, reviewField } from "./fieldStatus";
import { historyEntries } from "./history";
import { acceptProposal, buildChanges, changeCount, dismissProposal, initialInputs } from "./reviewForm";

function profile(overrides: Partial<DealProfile> = {}): DealProfile {
  return {
    deal_name: null,
    property_name: null,
    missing_information: [],
    conflicting_information: [],
    uncertain_information: [],
    withheld_values: [],
    evidence: [],
    corrected_fields: [],
    review_feedback: null,
    review_status: "draft",
    ...overrides,
  };
}

const field = (name: string): FieldSpec => ALL_FIELDS.find((spec) => spec.name === name)!;

const cite = (field_name: string, page_number = 3) => ({
  field_name,
  value: "x",
  source_document: "deal.pdf",
  page_number,
  snippet: "Asking Price: $10,000,000",
  verification: "value_matched" as const,
});

const proposal: WithheldValue = {
  field_name: "noi",
  proposed_value: 650000,
  reason: "model_uncertain",
  detail: "The model said the NOI was approximate.",
  evidence: null,
};

describe("the field catalogue", () => {
  it("groups fields the way the milestone asks", () => {
    expect(FIELD_GROUPS.map((group) => group.id)).toEqual([
      "property",
      "transaction",
      "operations",
      "financing",
      "sponsor",
      "assumptions",
    ]);
  });

  it("lists each REPEDealProfile value field once", () => {
    const names = ALL_FIELDS.map((spec) => spec.name);
    expect(new Set(names).size).toBe(names.length);
    // 4 in BaseDeal + 21 in REPEDealProfile (backend/app/h9n/schemas/).
    expect(names).toHaveLength(25);
  });
});

describe("parseInput", () => {
  it("reads money with symbols and commas", () => {
    expect(parseInput(field("asking_price"), " $12,500,000 ")).toEqual({ value: 12500000 });
  });

  it("treats an empty box as no value", () => {
    expect(parseInput(field("asking_price"), "  ")).toEqual({ value: null });
    expect(parseInput(field("deal_name"), "")).toEqual({ value: null });
  });

  it("keeps text as typed, trimmed", () => {
    expect(parseInput(field("deal_name"), "  Elm Court ")).toEqual({ value: "Elm Court" });
  });

  it("reads percentages as the number itself", () => {
    expect(parseInput(field("cap_rate"), "6.5%")).toEqual({ value: 6.5 });
    expect(parseInput(field("cap_rate"), "650")).toMatchObject({ error: expect.stringMatching(/between 0 and 100/) });
  });

  it("refuses things that aren't numbers", () => {
    expect(parseInput(field("noi"), "about a million")).toEqual({ error: "Enter a number." });
    expect(parseInput(field("noi"), "1.2.3")).toEqual({ error: "Enter a number." });
  });

  it("allows a negative NOI but no other negative money", () => {
    expect(parseInput(field("noi"), "-50,000")).toEqual({ value: -50000 });
    expect(parseInput(field("asking_price"), "-1")).toMatchObject({ error: expect.any(String) });
  });

  it("needs whole numbers and real years where they apply", () => {
    expect(parseInput(field("units"), "12.5")).toMatchObject({ error: "Enter a whole number." });
    expect(parseInput(field("year_built"), "98")).toMatchObject({ error: expect.stringMatching(/year/) });
    expect(parseInput(field("year_built"), "1998")).toEqual({ value: 1998 });
  });
});

describe("formatValue", () => {
  it("shows values the way reviewers read them", () => {
    expect(formatValue("money", 12500000)).toBe("$12,500,000");
    expect(formatValue("percent", 6.5)).toBe("6.5%");
    expect(formatValue("year", 1998)).toBe("1998");
    expect(formatValue("money", null)).toBe("");
  });
});

describe("noteNamesField", () => {
  it("matches notes that start with the field's name, either spelling", () => {
    expect(noteNamesField("cap_rate: not stated", "cap_rate")).toBe(true);
    expect(noteNamesField("Cap rate not stated anywhere", "cap_rate")).toBe(true);
  });

  it("doesn't match a longer field name that starts the same way", () => {
    expect(noteNamesField("noi_margin: n/a", "noi")).toBe(false);
    expect(noteNamesField("No rent roll provided", "noi")).toBe(false);
  });

  it("drops the field name when showing the note", () => {
    expect(noteText("cap_rate: not stated", "cap_rate")).toBe("not stated");
  });
});

describe("reviewField", () => {
  it("marks a cited value as supported, with its citation", () => {
    const review = reviewField(profile({ asking_price: 10000000, evidence: [cite("asking_price")] }), "asking_price");
    expect(review.status).toBe("supported");
    expect(review.evidence?.page_number).toBe(3);
  });

  it("marks an empty field as missing, with the extractor's note", () => {
    const review = reviewField(profile({ missing_information: ["cap_rate: not stated"] }), "cap_rate");
    expect(review).toMatchObject({ status: "missing", notes: ["not stated"] });
  });

  it("ranks conflicting above uncertain above unverified", () => {
    const flagged = profile({
      conflicting_information: ["noi: $650k on p.2, $700k on p.9"],
      uncertain_information: ["noi: approximate"],
      withheld_values: [proposal],
    });
    expect(reviewField(flagged, "noi").status).toBe("conflicting");
    expect(reviewField({ ...flagged, conflicting_information: [] }, "noi").status).toBe("uncertain");
    expect(reviewField({ ...flagged, conflicting_information: [], uncertain_information: [] }, "noi")).toMatchObject({
      status: "unverified",
      withheld: proposal,
    });
  });

  it("treats a reviewer's correction as settled, but keeps the notes visible", () => {
    const review = reviewField(
      profile({ noi: 650000, corrected_fields: ["noi"], uncertain_information: ["noi: approximate"] }),
      "noi",
    );
    expect(review).toMatchObject({ status: "corrected", notes: ["approximate"] });
  });

  it("flags a value with no citation", () => {
    expect(reviewField(profile({ deal_name: "Elm" }), "deal_name").status).toBe("unsupported");
  });

  it("counts the fields that need attention", () => {
    const deal = profile({ asking_price: 1, evidence: [cite("asking_price")], uncertain_information: ["noi: ~"] });
    // noi is uncertain; every other field except asking_price is empty.
    expect(attentionCount(deal)).toBe(ALL_FIELDS.length - 1);
  });

  it("collects notes that aren't about any one field", () => {
    expect(generalNotes(profile({ missing_information: ["No rent roll provided", "noi: not stated"] }))).toEqual([
      "No rent roll provided",
    ]);
  });
});

describe("buildChanges", () => {
  const saved = profile({ deal_name: "Elm", asking_price: 10000000, withheld_values: [proposal] });

  it("sends nothing when nothing changed", () => {
    expect(buildChanges(saved, initialInputs(saved), new Set())).toEqual({ changes: {}, errors: {} });
  });

  it("sends only the fields whose value changed, parsed", () => {
    const inputs = { ...initialInputs(saved), asking_price: "$9,500,000", deal_name: "Elm " };
    expect(buildChanges(saved, inputs, new Set()).changes).toEqual({ asking_price: 9500000 });
  });

  it("sends a cleared field as null", () => {
    const inputs = { ...initialInputs(saved), deal_name: "" };
    expect(buildChanges(saved, inputs, new Set()).changes).toEqual({ deal_name: null });
  });

  it("reports fields that can't be read", () => {
    const inputs = { ...initialInputs(saved), asking_price: "lots" };
    expect(buildChanges(saved, inputs, new Set()).errors).toEqual({ asking_price: "Enter a number." });
  });

  it("accepting a proposal fills the field and drops it from the withheld list", () => {
    const accepted = acceptProposal(initialInputs(saved), new Set(), proposal);
    const { changes } = buildChanges(saved, accepted.inputs, accepted.resolved);

    expect(changes).toEqual({ noi: 650000, withheld_values: [] });
    expect(changeCount(changes, accepted.resolved)).toBe(1);
  });

  it("dismissing a proposal only drops it from the withheld list", () => {
    const resolved = dismissProposal(new Set(), proposal);
    const { changes } = buildChanges(saved, initialInputs(saved), resolved);

    expect(changes).toEqual({ withheld_values: [] });
    expect(changeCount(changes, resolved)).toBe(1);
  });
});

describe("historyEntries", () => {
  const me = "user-me";
  const history: DealHistory = {
    corrections: [
      {
        field_name: "asking_price",
        original_value: 10000000,
        corrected_value: 9500000,
        evidence: null,
        source: "reviewer",
        feedback: null,
        corrected_by: me,
        deal_version: 2,
        created_at: "2026-10-14T12:00:00Z",
      },
      {
        field_name: "noi",
        original_value: null,
        corrected_value: 650000,
        evidence: null,
        source: "reviewer_feedback",
        feedback: "NOI is on page 9",
        corrected_by: "someone-else",
        deal_version: 4,
        created_at: "2026-10-14T12:03:00Z",
      },
    ],
    status_changes: [
      {
        action: "reject",
        from_status: "draft",
        to_status: "draft",
        note: "NOI is on page 9",
        changed_by: "someone-else",
        deal_version: 3,
        created_at: "2026-10-14T12:02:00Z",
      },
    ],
  };

  it("reads as a timeline, newest first", () => {
    const entries = historyEntries(history, me);

    expect(entries.map((entry) => [entry.version, entry.who, entry.what])).toEqual([
      [4, "HANA", "changed NOI: empty → $650,000 (from the reviewer's feedback)"],
      [3, "Another reviewer", "rejected the deal"],
      [2, "You", "changed Asking price: $10,000,000 → $9,500,000"],
    ]);
    expect(entries[1].note).toBe("NOI is on page 9");
  });

  it("describes resolved proposals by count", () => {
    const entries = historyEntries(
      {
        corrections: [{ ...history.corrections[0], field_name: "withheld_values", original_value: [proposal], corrected_value: [] }],
        status_changes: [],
      },
      me,
    );
    expect(entries[0].what).toBe("changed Unverified proposals: 1 item → none");
  });
});

describe("evidence helpers", () => {
  const verified = cite("asking_price", 3);
  const reviewOf = (deal: DealProfile, name: string) => reviewField(deal, name);

  it("prefers a field's verified citation, then a held-back value's", () => {
    expect(citationFor(reviewOf(profile({ asking_price: 1, evidence: [verified] }), "asking_price"))).toEqual({
      citation: verified,
      verified: true,
    });
    const held = { ...proposal, evidence: cite("noi", 9) };
    expect(citationFor(reviewOf(profile({ withheld_values: [held] }), "noi"))).toMatchObject({ verified: false });
    expect(citationFor(reviewOf(profile(), "noi"))).toBeNull();
  });

  it("says what was checked", () => {
    expect(verificationText(verified, true)).toMatch(/contains this value/);
    expect(verificationText({ ...verified, verification: "quote_only" }, true)).toMatch(/summarizes/);
    expect(verificationText(verified, false)).toMatch(/didn't check out/);
  });

  it("opens the PDF at a page", () => {
    expect(pdfPageUrl("https://x/doc.pdf?token=t", 4)).toBe("https://x/doc.pdf?token=t#page=4");
    expect(pdfPageUrl("https://x/doc.pdf?token=t#page=2", 4)).toBe("https://x/doc.pdf?token=t#page=4");
    expect(pdfPageUrl("https://x/doc.pdf?token=t", null)).toBe("https://x/doc.pdf?token=t");
  });

  it("treats a link about to expire as stale", () => {
    const now = Date.parse("2026-10-14T12:00:00Z");
    const at = (seconds: number) => ({ url: "u", filename: "f", expires_at: new Date(now + seconds * 1000).toISOString() });
    expect(linkIsFresh(at(600), now)).toBe(true);
    expect(linkIsFresh(at(10), now)).toBe(false);
  });
});
