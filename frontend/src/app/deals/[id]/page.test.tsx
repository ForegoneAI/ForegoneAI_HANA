// @vitest-environment jsdom
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DealProfile, DealRecord } from "@/lib/api";

const api = vi.hoisted(() => ({
  getDeal: vi.fn(),
  correctDeal: vi.fn(),
  reviewDeal: vi.fn(),
  getCurrentUser: vi.fn(),
  getDealHistory: vi.fn(),
}));

vi.mock("@/lib/api", async (importOriginal) => ({ ...(await importOriginal<object>()), ...api }));
// Like Next's, the router is the same object on every render.
const router = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "deal-1" }),
  useRouter: () => router,
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...props }: { href: string; children: ReactNode }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));
// The sign-in gate needs Supabase; these tests are about the page itself.
vi.mock("@/components/RequireSignIn", () => ({ RequireSignIn: ({ children }: { children: ReactNode }) => children }));

const { ApiError } = await import("@/lib/api");
const { default: DealPage } = await import("./page");

function profile(overrides: Partial<DealProfile> = {}): DealProfile {
  return {
    deal_name: "Elm Court",
    property_name: null,
    asking_price: 10000000,
    noi: null,
    missing_information: [],
    conflicting_information: [],
    uncertain_information: ["noi: the OM says approximately $650k"],
    withheld_values: [
      {
        field_name: "noi",
        proposed_value: 650000,
        reason: "model_uncertain",
        detail: "The model said the NOI was approximate.",
        evidence: null,
      },
    ],
    evidence: [
      {
        field_name: "asking_price",
        value: "10000000",
        source_document: "elm.pdf",
        page_number: 3,
        snippet: "Asking Price: $10,000,000",
        verification: "value_matched",
      },
    ],
    corrected_fields: [],
    review_feedback: null,
    review_status: "draft",
    ...overrides,
  };
}

function deal(overrides: Partial<DealRecord> = {}, profileOverrides: Partial<DealProfile> = {}): DealRecord {
  return {
    deal_id: "deal-1",
    organization_id: "org-1",
    status: "draft",
    version: 1,
    source_filename: "elm.pdf",
    extraction_run_id: null,
    created_by: "user-me",
    created_at: "2026-10-14T12:00:00Z",
    updated_at: "2026-10-14T12:00:00Z",
    profile: profile(profileOverrides),
    ...overrides,
  };
}

async function openDeal(record: DealRecord = deal()) {
  api.getDeal.mockResolvedValue(record);
  render(<DealPage />);
  await screen.findByRole("heading", { name: "Elm Court" });
  return userEvent.setup();
}

const field = (label: string) => screen.getByLabelText(label) as HTMLInputElement;

beforeEach(() => {
  api.getCurrentUser.mockResolvedValue({ user_id: "user-me", organizations: [] });
  api.getDealHistory.mockResolvedValue({ corrections: [], status_changes: [] });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("the deal review form", () => {
  it("shows every group and marks each field by how far it can be trusted", async () => {
    await openDeal();

    for (const group of ["Property", "Transaction", "Operations", "Financing", "Sponsor", "Strategy & assumptions"]) {
      expect(screen.getByRole("group", { name: new RegExp(`^${group}`) })).toBeTruthy();
    }
    const price = field("Asking price").closest(".review-field") as HTMLElement;
    expect(within(price).getByText("Cited")).toBeTruthy();
    expect(within(price).getByText("p. 3")).toBeTruthy();
    const noi = field("NOI").closest(".review-field") as HTMLElement;
    expect(within(noi).getByText("Uncertain")).toBeTruthy();
    expect(within(noi).getByText("the OM says approximately $650k")).toBeTruthy();
    expect(within(noi).getByText(/Proposed: \$650,000/)).toBeTruthy();
  });

  it("saves only what changed, against the version on screen", async () => {
    const user = await openDeal();
    api.correctDeal.mockResolvedValue(deal({ version: 2 }, { asking_price: 9500000, corrected_fields: ["asking_price"] }));

    await user.clear(field("Asking price"));
    await user.type(field("Asking price"), "$9,500,000");
    expect(screen.getByText("Edited · was $10,000,000")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(api.correctDeal).toHaveBeenCalledWith("deal-1", 1, { asking_price: 9500000 });
    expect(await screen.findByText("Changes saved.")).toBeTruthy();
    expect(field("Asking price").value).toBe("9500000");
    const price = field("Asking price").closest(".review-field") as HTMLElement;
    expect(within(price).getByText("Corrected")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
  });

  it("accepting a proposed value fills the field and resolves the proposal", async () => {
    const user = await openDeal();
    api.correctDeal.mockResolvedValue(deal({ version: 2 }));

    await user.click(screen.getByRole("button", { name: "Use this value" }));
    expect(field("NOI").value).toBe("650000");
    expect(screen.getByText("1 unsaved change")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(api.correctDeal).toHaveBeenCalledWith("deal-1", 1, { noi: 650000, withheld_values: [] });
  });

  it("won't save a value it can't read", async () => {
    const user = await openDeal();

    await user.clear(field("Cap rate"));
    await user.type(field("Cap rate"), "six percent");
    expect(screen.getByText("Enter a number.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    expect(api.correctDeal).not.toHaveBeenCalled();
    expect(screen.getByText("Fix the highlighted fields before saving.")).toBeTruthy();
  });

  it("discarding puts every field back", async () => {
    const user = await openDeal();

    await user.type(field("Deal name"), " II");
    await user.click(screen.getByRole("button", { name: "Discard" }));

    expect(field("Deal name").value).toBe("Elm Court");
  });

  it("when someone else saved first, says so and offers to reload", async () => {
    const user = await openDeal();
    api.correctDeal.mockRejectedValue(
      new ApiError(409, "Someone else changed this deal since you opened it. Reload it to see their changes."),
    );

    await user.type(field("Deal name"), " II");
    await user.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText(/Someone else changed this deal/)).toBeTruthy();

    api.getDeal.mockResolvedValue(deal({ version: 2 }, { deal_name: "Elm Court (theirs)" }));
    await user.click(screen.getByRole("button", { name: "Reload the latest version" }));

    await screen.findByRole("heading", { name: "Elm Court (theirs)" });
    expect(field("Deal name").value).toBe("Elm Court (theirs)");
  });
});

describe("review actions", () => {
  it("offers the actions that fit a draft, and approves", async () => {
    const user = await openDeal();
    api.reviewDeal.mockResolvedValue(deal({ status: "approved", version: 2 }, { review_status: "approved" }));

    expect(screen.getByRole("button", { name: "Mark reviewed" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Approve" }));

    expect(api.reviewDeal).toHaveBeenCalledWith("deal-1", "approve", 1, undefined);
    expect(await screen.findByText(/Approved\. This deal is now the trusted input/)).toBeTruthy();
  });

  it("waits for unsaved changes before any action", async () => {
    const user = await openDeal();

    await user.type(field("Deal name"), " II");

    expect((screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Save or discard your changes first.")).toBeTruthy();
  });

  it("shows an approved deal read-only, with only Reopen", async () => {
    await openDeal(deal({ status: "approved" }, { review_status: "approved" }));

    expect(field("Asking price").readOnly).toBe(true);
    expect(screen.getByText(/This deal is approved, so it's locked/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reopen to edit" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Approve" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Use this value" })).toBeNull();
  });

  it("rejects with the reviewer's own words", async () => {
    const user = await openDeal();
    api.reviewDeal.mockResolvedValue(deal({ version: 3 }, { review_feedback: "NOI is on page 9" }));

    await user.click(screen.getByRole("button", { name: "Reject…" }));
    const send = screen.getByRole("button", { name: "Send rejection" }) as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    await user.type(screen.getByLabelText("What's wrong with this deal?"), "NOI is on page 9");
    await user.click(send);

    expect(api.reviewDeal).toHaveBeenCalledWith("deal-1", "reject", 1, "NOI is on page 9");
    expect(await screen.findByText(/Rejection saved/)).toBeTruthy();
  });

  it("when the re-check after a rejection fails, says what was saved and shows the deal as it is now", async () => {
    const user = await openDeal();
    api.reviewDeal.mockRejectedValue(
      new ApiError(503, "The rejection and feedback were saved, but the automatic correction failed: try again."),
    );
    api.getDeal.mockResolvedValue(deal({ version: 2 }, { review_feedback: "NOI is on page 9" }));

    await user.click(screen.getByRole("button", { name: "Reject…" }));
    await user.type(screen.getByLabelText("What's wrong with this deal?"), "NOI is on page 9");
    await user.click(screen.getByRole("button", { name: "Send rejection" }));

    expect(await screen.findByText(/The rejection and feedback were saved/)).toBeTruthy();
    await waitFor(() => expect(api.getDeal).toHaveBeenCalledTimes(2));
  });
});
