import type { BadgeTone } from "@/components/Badge";
import type { DealProfile, FieldEvidence, WithheldValue } from "./api";
import { ALL_FIELDS } from "./dealFields";

/**
 * How much a reviewer can trust one field (M2.2), most urgent first:
 *
 * - corrected: a reviewer set or confirmed this value.
 * - conflicting: the document gives different values.
 * - uncertain: a value was found but the extractor doubts it.
 * - unverified: a value was proposed but its citation didn't check out, so
 *   it's held back for the reviewer to accept or dismiss.
 * - missing: no value.
 * - supported: a value with a verified citation.
 * - unsupported: a value with no citation (e.g. from an older extraction).
 */
export type FieldStatus =
  | "corrected"
  | "conflicting"
  | "uncertain"
  | "unverified"
  | "missing"
  | "supported"
  | "unsupported";

export interface FieldReview {
  status: FieldStatus;
  /** The extractor's notes about this field (missing, uncertain, conflicting). */
  notes: string[];
  /** A proposed value waiting for the reviewer, if any. */
  withheld: WithheldValue | null;
  evidence: FieldEvidence | null;
}

export const STATUS_DISPLAY: Record<FieldStatus, { label: string; tone: BadgeTone }> = {
  corrected: { label: "Corrected", tone: "ok" },
  conflicting: { label: "Conflicting", tone: "error" },
  uncertain: { label: "Uncertain", tone: "warn" },
  unverified: { label: "Unverified", tone: "warn" },
  missing: { label: "Missing", tone: "neutral" },
  supported: { label: "Cited", tone: "neutral" },
  unsupported: { label: "No citation", tone: "warn" },
};

/** Statuses a reviewer should look at before approving. */
export function needsAttention(status: FieldStatus): boolean {
  return status === "conflicting" || status === "uncertain" || status === "unverified" || status === "missing";
}

/**
 * Whether an extractor note is about `field`. Notes start with the field's
 * name, e.g. "cap_rate: not stated" or "cap rate not stated" - the same rule
 * the backend uses to match missing-field notes (extraction_output.py).
 *
 * This reads today's free-text flag lists. When M1.2 adds a structured
 * status per field, reviewField() should read that instead.
 */
export function noteNamesField(note: string, field: string): boolean {
  const folded = note.trim().toLowerCase();
  return [field, field.replace(/_/g, " ")].some((label) => {
    if (!folded.startsWith(label)) return false;
    const next = folded.charAt(label.length);
    return !/[a-z0-9_]/.test(next);
  });
}

/** A note without its leading field name: "cap_rate: not stated" -> "not stated". */
export function noteText(note: string, field: string): string {
  for (const label of [field, field.replace(/_/g, " ")]) {
    if (note.trim().toLowerCase().startsWith(label)) {
      const rest = note.trim().slice(label.length).replace(/^[\s:\-–—]+/, "");
      return rest || note;
    }
  }
  return note;
}

export function reviewField(profile: DealProfile, field: string): FieldReview {
  const about = (notes: string[]) => notes.filter((note) => noteNamesField(note, field));
  const conflicting = about(profile.conflicting_information);
  const uncertain = about(profile.uncertain_information);
  const missing = about(profile.missing_information);
  const withheld = profile.withheld_values.find((entry) => entry.field_name === field) ?? null;
  const evidence = profile.evidence.find((entry) => entry.field_name === field) ?? null;
  const value = profile[field];
  const hasValue = value !== null && value !== undefined && value !== "";

  let status: FieldStatus;
  if (profile.corrected_fields.includes(field)) status = "corrected";
  else if (conflicting.length) status = "conflicting";
  else if (uncertain.length) status = "uncertain";
  else if (withheld) status = "unverified";
  else if (!hasValue) status = "missing";
  else if (evidence) status = "supported";
  else status = "unsupported";

  return {
    status,
    notes: [...conflicting, ...uncertain, ...missing].map((note) => noteText(note, field)),
    withheld,
    evidence,
  };
}

/** Extractor notes that aren't about any one field (e.g. "No rent roll provided"). */
export function generalNotes(profile: DealProfile): string[] {
  const notes = [...profile.missing_information, ...profile.uncertain_information, ...profile.conflicting_information];
  return notes.filter((note) => !ALL_FIELDS.some((field) => noteNamesField(note, field.name)));
}

/** How many fields need a reviewer's attention. */
export function attentionCount(profile: DealProfile): number {
  return ALL_FIELDS.filter((field) => needsAttention(reviewField(profile, field.name).status)).length;
}
