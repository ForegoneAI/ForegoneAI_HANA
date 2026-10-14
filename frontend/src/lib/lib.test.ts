import { describe, expect, it } from "vitest";

import { errorMessageFrom } from "./api";
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
    "replaces %j with the upload page",
    (next) => {
      expect(safeNextPath(next)).toBe("/deals/new");
    },
  );
});
