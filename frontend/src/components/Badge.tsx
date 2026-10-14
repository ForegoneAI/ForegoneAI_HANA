import type { ReactNode } from "react";

export type BadgeTone = "neutral" | "ok" | "warn" | "error";

/** A small status pill, e.g. a deal's review status or a field's flag. */
export function Badge({ tone = "neutral", children }: { tone?: BadgeTone; children: ReactNode }) {
  return <span className={tone === "neutral" ? "badge" : `badge badge--${tone}`}>{children}</span>;
}
