import { describe, expect, it } from "vitest";

import { errorMessageFrom } from "./api";
import { dealTitle, formatSavedAt, reviewStatusBadge } from "./deals";
import { safeNextPath } from "./navigation";
import { MAX_UPLOAD_BYTES, formatBytes, validatePdf } from "./upload";

describe("validatePdf", () => {
  const pdf = (overrides: Partial<File> = {}) => ({ name: "deal.pdf", size: 1024, type: "application/pdf", ...overrides });

  it("accepts a normal PDF", () => {
    expect(validatePdf(pdf())).toBeNull();
  });

  it("accepts a .pdf even when the browser reports no type", () => {
    expect(validatePdf(pdf({ type: "" }))).toBeNull();
  });

  it("rejects files that aren't PDFs", () => {
    expect(validatePdf(pdf({ name: "notes.docx", type: "application/msword" }))).toMatch(/Only PDF/);
  });

  it("rejects empty files", () => {
    expect(validatePdf(pdf({ size: 0 }))).toMatch(/empty/);
  });

  it("rejects files over the API's limit", () => {
    expect(validatePdf(pdf({ size: MAX_UPLOAD_BYTES + 1 }))).toMatch(/at most 50 MB/);
  });
});

describe("formatBytes", () => {
  it("formats sizes for people", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
  });
});

describe("errorMessageFrom", () => {
  it("uses the API's own explanation when it gives one", () => {
    expect(errorMessageFrom(422, { detail: "No text could be extracted from the uploaded PDF." })).toBe(
      "No text could be extracted from the uploaded PDF.",
    );
  });

  it("uses the first message of a validation error list", () => {
    expect(errorMessageFrom(422, { detail: [{ msg: "Field required", loc: ["body", "file"] }] })).toBe(
      "Field required",
    );
  });

  it("falls back to a plain message when the body is unusable", () => {
    expect(errorMessageFrom(401, null)).toMatch(/sign in again/);
    expect(errorMessageFrom(404, "<html>")).toMatch(/could not be found/);
    expect(errorMessageFrom(503, {})).toMatch(/having trouble/);
    expect(errorMessageFrom(418, {})).toBe("The request failed (status 418).");
  });
});

describe("safeNextPath", () => {
  it("keeps paths inside the app", () => {
    expect(safeNextPath("/deals/abc")).toBe("/deals/abc");
  });

  it.each([null, "", "https://evil.example", "//evil.example", "/\\evil.example", "deals"])(
    "replaces %j with the deal list",
    (next) => {
      expect(safeNextPath(next)).toBe("/deals");
    },
  );
});

describe("reviewStatusBadge", () => {
  it("labels each review status for people", () => {
    expect(reviewStatusBadge("pending")).toEqual({ label: "Needs review", tone: "warn" });
    expect(reviewStatusBadge("approved")).toEqual({ label: "Approved", tone: "ok" });
    expect(reviewStatusBadge("rejected")).toEqual({ label: "Rejected", tone: "error" });
  });
});

describe("dealTitle", () => {
  it("prefers the deal name, then the property name", () => {
    expect(dealTitle({ deal_name: "Fund IV · Elm", property_name: "Elm Court" })).toBe("Fund IV · Elm");
    expect(dealTitle({ deal_name: null, property_name: "Elm Court" })).toBe("Elm Court");
    expect(dealTitle({ deal_name: null, property_name: null })).toBe("Untitled deal");
  });
});

describe("formatSavedAt", () => {
  it("shows the date and time the deal was saved", () => {
    expect(formatSavedAt("2026-10-14T12:00:00Z", "en-US")).toMatch(/Oct 14, 2026/);
  });
});
