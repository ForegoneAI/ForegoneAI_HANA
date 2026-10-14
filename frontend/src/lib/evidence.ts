import type { FieldEvidence, SourcePdf } from "./api";
import type { FieldReview } from "./fieldStatus";

/**
 * The citation to show for a field (M2.3): its verified one, or else the
 * citation the extractor gave for a value it proposed but couldn't verify -
 * shown with a warning, since it didn't check out.
 */
export function citationFor(review: FieldReview): { citation: FieldEvidence; verified: boolean } | null {
  if (review.evidence) return { citation: review.evidence, verified: true };
  if (review.withheld?.evidence) return { citation: review.withheld.evidence, verified: false };
  return null;
}

/** What the extractor checked about a citation, in plain words. */
export function verificationText(citation: FieldEvidence, verified: boolean): string {
  if (!verified) return "This citation didn't check out against the document, so the value was held back.";
  if (citation.verification === "value_matched") return "The quoted text contains this value.";
  if (citation.verification === "quote_only") return "The quote was found on this page; the value summarizes it.";
  return "Cited by the extractor.";
}

/** A link that opens the PDF at a page (browsers' built-in viewers read #page=N). */
export function pdfPageUrl(url: string, page: number | null): string {
  const base = url.split("#")[0];
  return page ? `${base}#page=${page}` : base;
}

/** Whether a PDF link still works for long enough to be worth using. */
export function linkIsFresh(source: SourcePdf, now: number = Date.now(), marginMs = 30_000): boolean {
  return new Date(source.expires_at).getTime() - now > marginMs;
}
