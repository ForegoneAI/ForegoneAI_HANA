import type { DealHistory, ReviewAction } from "./api";
import { ALL_FIELDS, formatValue, type FieldKind } from "./dealFields";

export interface HistoryEntry {
  key: string;
  at: string;
  version: number;
  who: string;
  what: string;
  /** The reviewer's feedback, for rejections and the corrections they led to. */
  note: string | null;
}

const ACTION_TEXT: Record<ReviewAction | "edit", string> = {
  review: "marked the deal reviewed",
  approve: "approved the deal",
  reopen: "reopened the deal",
  reject: "rejected the deal",
  edit: "edited a reviewed deal, so it went back to draft",
};

const FIELD_LABELS: Record<string, { label: string; kind: FieldKind }> = {
  ...Object.fromEntries(ALL_FIELDS.map((field) => [field.name, { label: field.label, kind: field.kind }])),
  withheld_values: { label: "Unverified proposals", kind: "text" },
  missing_information: { label: "Missing-information notes", kind: "text" },
  uncertain_information: { label: "Uncertainty notes", kind: "text" },
  conflicting_information: { label: "Conflict notes", kind: "text" },
  evidence: { label: "Citations", kind: "text" },
};

function shown(kind: FieldKind, value: unknown): string {
  if (value === null || value === undefined || value === "") return "empty";
  if (Array.isArray(value)) return value.length === 0 ? "none" : `${value.length} item${value.length === 1 ? "" : "s"}`;
  return formatValue(kind, value);
}

/**
 * A deal's history as one timeline, newest first (M2.4). Only user ids are
 * stored, so people show as "You" or "Another reviewer".
 */
export function historyEntries(history: DealHistory, currentUserId: string | null): HistoryEntry[] {
  const who = (userId: string) => (userId === currentUserId ? "You" : "Another reviewer");

  const changes: HistoryEntry[] = history.status_changes.map((change, index) => ({
    key: `status-${index}`,
    at: change.created_at,
    version: change.deal_version,
    who: who(change.changed_by),
    what: ACTION_TEXT[change.action],
    note: change.action === "reject" ? change.note : null,
  }));

  const corrections: HistoryEntry[] = history.corrections.map((correction, index) => {
    const field = FIELD_LABELS[correction.field_name] ?? { label: correction.field_name, kind: "text" as const };
    const fromFeedback = correction.source === "reviewer_feedback";
    return {
      key: `correction-${index}`,
      at: correction.created_at,
      version: correction.deal_version,
      who: fromFeedback ? "HANA" : who(correction.corrected_by),
      what:
        `changed ${field.label}: ${shown(field.kind, correction.original_value)} → ` +
        `${shown(field.kind, correction.corrected_value)}${fromFeedback ? " (from the reviewer's feedback)" : ""}`,
      note: null,
    };
  });

  // Newest first; within one saved version, the status change last.
  return [...changes, ...corrections].sort(
    (a, b) => b.version - a.version || Number(a.key.startsWith("status")) - Number(b.key.startsWith("status")),
  );
}
