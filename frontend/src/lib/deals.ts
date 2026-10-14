import type { BadgeTone } from "@/components/Badge";
import type { ReviewStatus } from "./api";

/** How a deal's review status reads in the app, and the badge colour for it. */
export function reviewStatusBadge(status: ReviewStatus): { label: string; tone: BadgeTone } {
  switch (status) {
    case "approved":
      return { label: "Approved", tone: "ok" };
    case "reviewed":
      return { label: "Reviewed", tone: "neutral" };
    default:
      return { label: "Draft", tone: "warn" };
  }
}

/** A deal's name for lists and headings, falling back to the property's. */
export function dealTitle(deal: { deal_name: string | null; property_name: string | null }): string {
  return deal.deal_name ?? deal.property_name ?? "Untitled deal";
}

/** e.g. "Oct 14, 2026, 3:05 PM" in the viewer's own time zone. */
export function formatSavedAt(iso: string, locale?: string): string {
  return new Intl.DateTimeFormat(locale, { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}
