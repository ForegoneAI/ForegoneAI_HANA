"use client";

import { useEffect, useRef } from "react";

import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import type { SourcePdf } from "@/lib/api";
import { formatValue, type FieldSpec, type FieldValue } from "@/lib/dealFields";
import { citationFor, pdfPageUrl, verificationText } from "@/lib/evidence";
import { STATUS_DISPLAY, type FieldReview } from "@/lib/fieldStatus";

/** Where the deal's PDF link stands; loaded once, the first time it's needed. */
export type SourceState =
  | { status: "loading" }
  | { status: "ready"; pdf: SourcePdf }
  | { status: "missing"; message: string }
  | { status: "error"; message: string };

interface EvidencePanelProps {
  field: FieldSpec;
  review: FieldReview;
  value: FieldValue;
  sourceFilename: string;
  /** Null when the deal has no kept PDF. */
  source: SourceState | null;
  onRetrySource: () => void;
  onClose: () => void;
}

/**
 * Where a field's value came from (M2.3): the document, page and quoted
 * text, beside the original PDF opened at that page - so a reviewer can
 * check a value in a few seconds. Without a kept PDF, the quote alone.
 */
export function EvidencePanel({ field, review, value, sourceFilename, source, onRetrySource, onClose }: EvidencePanelProps) {
  const heading = useRef<HTMLHeadingElement>(null);
  const found = citationFor(review);
  const page = found?.citation.page_number ?? null;
  const status = STATUS_DISPLAY[review.status];

  // Move focus here when a field is opened, and let Escape close the panel.
  useEffect(() => {
    heading.current?.focus();
  }, [field.name]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside className="evidence" aria-labelledby="evidence-heading">
      <div className="evidence__head">
        <h2 id="evidence-heading" ref={heading} tabIndex={-1}>
          {field.label}
        </h2>
        <Badge tone={status.tone}>{status.label}</Badge>
        <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close the source panel">
          Close
        </Button>
      </div>

      <p className="evidence__value">
        {value === null ? <span className="muted">No value</span> : formatValue(field.kind, value)}
      </p>

      {found ? (
        <section className={found.verified ? "citation" : "citation citation--unverified"}>
          <p className="muted mono citation__where">
            {found.citation.source_document ?? sourceFilename}
            {page != null && ` · page ${page}`}
          </p>
          {found.citation.snippet && <blockquote>{found.citation.snippet}</blockquote>}
          <p className="muted citation__check">{verificationText(found.citation, found.verified)}</p>
        </section>
      ) : (
        <p className="muted">No citation for this value{value === null ? "" : "; check it against the document"}.</p>
      )}

      {source === null ? (
        <p className="muted">The original PDF wasn&apos;t kept for this deal, so only the quoted text is shown.</p>
      ) : source.status === "loading" ? (
        <p className="muted">Opening the PDF…</p>
      ) : source.status === "missing" ? (
        <p className="muted">{source.message} Only the quoted text is shown.</p>
      ) : source.status === "error" ? (
        <div className="muted">
          <p>{source.message}</p>
          <Button variant="ghost" size="sm" onClick={onRetrySource}>
            Try again
          </Button>
        </div>
      ) : (
        <div className="evidence__pdf">
          <a href={pdfPageUrl(source.pdf.url, page)} target="_blank" rel="noreferrer">
            Open {source.pdf.filename}
            {page != null ? ` at page ${page}` : ""} in a new tab
          </a>
          <iframe
            // A new frame per page: viewers don't reliably follow a #page change.
            key={page ?? "start"}
            src={pdfPageUrl(source.pdf.url, page)}
            title={`${source.pdf.filename}${page != null ? `, page ${page}` : ""}`}
          />
        </div>
      )}
    </aside>
  );
}
