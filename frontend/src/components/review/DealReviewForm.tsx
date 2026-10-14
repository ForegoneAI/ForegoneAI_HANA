"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/Button";
import { Notice } from "@/components/Notice";
import type { DealRecord } from "@/lib/api";
import { FIELD_GROUPS, valueOf } from "@/lib/dealFields";
import { generalNotes, needsAttention, reviewField } from "@/lib/fieldStatus";
import { acceptProposal, buildChanges, changeCount, dismissProposal, initialInputs } from "@/lib/reviewForm";
import { FieldRow } from "./FieldRow";

interface DealReviewFormProps {
  deal: DealRecord;
  /** Saves `changes` against the deal's current version; resolves when saved. */
  onSave: (changes: Record<string, unknown>) => Promise<void>;
  /** Told whether there are unsaved changes, so review actions can wait for them. */
  onDirtyChange: (dirty: boolean) => void;
  /** The field whose source is open in the evidence panel (M2.3). */
  sourceField: string | null;
  onShowSource: (field: string) => void;
}

/**
 * The editable Deal Profile (M2.2), grouped by property, transaction,
 * operations, financing, sponsor and assumptions, with each field marked by
 * how far it can be trusted. Approved deals are shown read-only.
 *
 * Remount it (key={deal.version}) when the deal changes, so the inputs start
 * from the saved values again.
 */
export function DealReviewForm({ deal, onSave, onDirtyChange, sourceField, onShowSource }: DealReviewFormProps) {
  const profile = deal.profile;
  const readOnly = deal.status === "approved";
  const initial = useMemo(() => initialInputs(profile), [profile]);
  const [inputs, setInputs] = useState(initial);
  const [resolved, setResolved] = useState<Set<string>>(() => new Set());
  const [onlyAttention, setOnlyAttention] = useState(false);
  const [showErrors, setShowErrors] = useState(false);
  const [saving, setSaving] = useState(false);

  const reviews = useMemo(
    () => Object.fromEntries(FIELD_GROUPS.flatMap((g) => g.fields).map((f) => [f.name, reviewField(profile, f.name)])),
    [profile],
  );
  const { changes, errors } = buildChanges(profile, inputs, resolved);
  const count = changeCount(changes, resolved);
  const hasErrors = Object.keys(errors).length > 0;
  const dirty = count > 0 || hasErrors;
  const attention = Object.values(reviews).filter((review) => needsAttention(review.status)).length;
  const notes = generalNotes(profile);

  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange]);

  function discard() {
    setInputs(initial);
    setResolved(new Set());
    setShowErrors(false);
  }

  async function save() {
    if (hasErrors) {
      setShowErrors(true);
      return;
    }
    setSaving(true);
    try {
      await onSave(changes);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form
      className="review-form"
      onSubmit={(event) => {
        event.preventDefault();
        void save();
      }}
    >
      <div className="review-form__toolbar">
        <p className="muted" style={{ margin: 0 }}>
          {attention === 0
            ? "No fields are flagged for attention."
            : `${attention} field${attention === 1 ? "" : "s"} need${attention === 1 ? "s" : ""} attention.`}
        </p>
        <label className="toggle">
          <input type="checkbox" checked={onlyAttention} onChange={(event) => setOnlyAttention(event.target.checked)} />
          Only show fields that need attention
        </label>
      </div>

      {readOnly && <Notice>This deal is approved, so it&apos;s locked. Reopen it to make changes.</Notice>}

      {notes.length > 0 && (
        <section className="review-notes">
          <h2>Other notes from the extraction</h2>
          <ul>
            {notes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </section>
      )}

      {FIELD_GROUPS.map((group) => {
        const fields = group.fields.filter((field) => !onlyAttention || needsAttention(reviews[field.name].status));
        if (fields.length === 0) return null;
        const groupAttention = group.fields.filter((field) => needsAttention(reviews[field.name].status)).length;
        return (
          <fieldset key={group.id} className="review-group">
            <legend>
              {group.title}
              {groupAttention > 0 && <span className="muted"> · {groupAttention} to check</span>}
            </legend>
            <div className="review-group__fields">
              {fields.map((field) => (
                <FieldRow
                  key={field.name}
                  field={field}
                  review={reviews[field.name]}
                  saved={valueOf(profile, field.name)}
                  input={inputs[field.name] ?? ""}
                  // Shown once the field has been edited, or after trying to save.
                  error={showErrors || inputs[field.name] !== initial[field.name] ? errors[field.name] : undefined}
                  proposalResolved={resolved.has(field.name)}
                  readOnly={readOnly || saving}
                  selected={sourceField === field.name}
                  onShowSource={() => onShowSource(field.name)}
                  onInput={(value) => setInputs((current) => ({ ...current, [field.name]: value }))}
                  onAcceptProposal={() => {
                    const proposal = reviews[field.name].withheld;
                    if (!proposal) return;
                    const next = acceptProposal(inputs, resolved, proposal);
                    setInputs(next.inputs);
                    setResolved(next.resolved);
                  }}
                  onDismissProposal={() => {
                    const proposal = reviews[field.name].withheld;
                    if (proposal) setResolved(dismissProposal(resolved, proposal));
                  }}
                />
              ))}
            </div>
          </fieldset>
        );
      })}

      {!readOnly && dirty && (
        <div className="save-bar" role="region" aria-label="Unsaved changes">
          <span>
            {hasErrors && showErrors
              ? "Fix the highlighted fields before saving."
              : `${count} unsaved change${count === 1 ? "" : "s"}`}
          </span>
          <span className="actions" style={{ marginTop: 0 }}>
            <Button variant="ghost" size="sm" onClick={discard} disabled={saving}>
              Discard
            </Button>
            <Button type="submit" size="sm" disabled={saving}>
              {saving ? "Saving…" : "Save changes"}
            </Button>
          </span>
        </div>
      )}
    </form>
  );
}
