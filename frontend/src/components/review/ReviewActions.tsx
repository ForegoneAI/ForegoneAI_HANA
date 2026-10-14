"use client";

import { useState } from "react";

import { Button } from "@/components/Button";
import type { ReviewAction, ReviewStatus } from "@/lib/api";

interface ReviewActionsProps {
  status: ReviewStatus;
  /** Fields still flagged for attention, as a reminder before approving. */
  attention: number;
  /** Unsaved edits: actions wait for them to be saved or discarded. */
  dirty: boolean;
  /** The action in progress, if any. */
  busy: ReviewAction | null;
  onAction: (action: ReviewAction, feedback?: string) => void;
}

/**
 * The review actions for the whole deal (M2.4): mark reviewed, approve,
 * reopen, or reject with feedback. Which ones show depends on the status:
 * draft -> reviewed -> approved, and an approved deal can only be reopened.
 */
export function ReviewActions({ status, attention, dirty, busy, onAction }: ReviewActionsProps) {
  const [rejecting, setRejecting] = useState(false);
  const [feedback, setFeedback] = useState("");
  const disabled = dirty || busy !== null;

  if (rejecting) {
    return (
      <form
        className="reject-form"
        onSubmit={(event) => {
          event.preventDefault();
          onAction("reject", feedback);
        }}
      >
        <label htmlFor="reject-feedback">What&apos;s wrong with this deal?</label>
        <textarea
          id="reject-feedback"
          rows={3}
          value={feedback}
          onChange={(event) => setFeedback(event.target.value)}
          placeholder="e.g. The asking price is wrong; page 4 says $9.5M."
          disabled={busy !== null}
        />
        <p className="muted">
          HANA re-reads the document using your note and corrects the fields it can verify. The deal stays a draft.
        </p>
        <div className="actions">
          <Button type="submit" size="sm" disabled={disabled || !feedback.trim()}>
            {busy === "reject" ? "Re-checking the document…" : "Send rejection"}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setRejecting(false)} disabled={busy !== null}>
            Cancel
          </Button>
        </div>
      </form>
    );
  }

  const buttons: { action: ReviewAction; label: string; primary?: boolean }[] =
    status === "draft"
      ? [
          { action: "review", label: "Mark reviewed", primary: true },
          { action: "approve", label: "Approve" },
        ]
      : status === "reviewed"
        ? [
            { action: "approve", label: "Approve", primary: true },
            { action: "reopen", label: "Reopen" },
          ]
        : [{ action: "reopen", label: "Reopen to edit" }];

  return (
    <div className="review-actions">
      <div className="actions" style={{ marginTop: 0 }}>
        {buttons.map(({ action, label, primary }) => (
          <Button
            key={action}
            size="sm"
            variant={primary ? "primary" : "ghost"}
            disabled={disabled}
            onClick={() => onAction(action)}
          >
            {busy === action ? "Saving…" : label}
          </Button>
        ))}
        {status !== "approved" && (
          <Button size="sm" variant="ghost" disabled={disabled} onClick={() => setRejecting(true)}>
            Reject…
          </Button>
        )}
      </div>
      {dirty && <p className="muted">Save or discard your changes first.</p>}
      {!dirty && status !== "approved" && attention > 0 && (
        <p className="muted">
          {attention} field{attention === 1 ? " is" : "s are"} still flagged. You can approve anyway; the flags stay on
          record.
        </p>
      )}
    </div>
  );
}
