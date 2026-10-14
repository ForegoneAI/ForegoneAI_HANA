import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { formatValue, parseInput, sameValue, type FieldSpec, type FieldValue } from "@/lib/dealFields";
import { STATUS_DISPLAY, type FieldReview } from "@/lib/fieldStatus";

interface FieldRowProps {
  field: FieldSpec;
  review: FieldReview;
  /** The saved value. */
  saved: FieldValue;
  input: string;
  error?: string;
  /** The proposal was accepted or dismissed (not yet saved). */
  proposalResolved: boolean;
  readOnly: boolean;
  onInput: (value: string) => void;
  onAcceptProposal: () => void;
  onDismissProposal: () => void;
}

/** One Deal Profile field: its value, how trustworthy it is, and why (M2.2). */
export function FieldRow({
  field,
  review,
  saved,
  input,
  error,
  proposalResolved,
  readOnly,
  onInput,
  onAcceptProposal,
  onDismissProposal,
}: FieldRowProps) {
  const id = `field-${field.name}`;
  const parsed = parseInput(field, input);
  const edited = "value" in parsed && !sameValue(parsed.value, saved);
  const status = STATUS_DISPLAY[review.status];
  const numeric = field.kind !== "text" && field.kind !== "longtext";
  const preview = numeric && "value" in parsed && parsed.value !== null ? formatValue(field.kind, parsed.value) : "";
  const page = review.evidence?.page_number;
  const describedBy = [error && `${id}-error`, review.notes.length > 0 && `${id}-notes`].filter(Boolean).join(" ");

  const inputProps = {
    id,
    value: input,
    readOnly,
    onChange: (event: { target: { value: string } }) => onInput(event.target.value),
    "aria-invalid": error ? true : undefined,
    "aria-describedby": describedBy || undefined,
  };

  return (
    <div className="review-field" data-status={review.status} data-edited={edited || undefined}>
      <div className="review-field__head">
        <label htmlFor={id}>{field.label}</label>
        <Badge tone={status.tone}>{status.label}</Badge>
        {page != null && (
          <span className="muted mono review-field__source" title={review.evidence?.snippet ?? undefined}>
            p. {page}
          </span>
        )}
      </div>

      {field.kind === "longtext" ? (
        <textarea rows={3} {...inputProps} />
      ) : (
        <input type="text" inputMode={numeric ? "decimal" : undefined} autoComplete="off" {...inputProps} />
      )}

      {(preview || edited) && (
        <p className="review-field__meta muted">
          {preview && <span>{preview}</span>}
          {edited && <span>Edited · was {saved === null ? "empty" : formatValue(field.kind, saved)}</span>}
        </p>
      )}
      {error && (
        <p className="review-field__error" id={`${id}-error`}>
          {error}
        </p>
      )}
      {review.notes.length > 0 && (
        <ul className="review-field__notes" id={`${id}-notes`}>
          {review.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}

      {review.withheld && !proposalResolved && (
        <div className="proposal">
          <p>
            <strong>Proposed: {formatValue(field.kind, review.withheld.proposed_value)}</strong>
            {review.withheld.evidence?.page_number != null && (
              <span className="muted"> · p. {review.withheld.evidence.page_number}</span>
            )}
          </p>
          <p className="muted">{review.withheld.detail}</p>
          {!readOnly && (
            <div className="actions">
              <Button size="sm" onClick={onAcceptProposal}>
                Use this value
              </Button>
              <Button size="sm" variant="ghost" onClick={onDismissProposal}>
                Dismiss
              </Button>
            </div>
          )}
        </div>
      )}
      {review.withheld && proposalResolved && (
        <p className="review-field__meta muted">Proposal resolved · saved when you save your changes</p>
      )}
    </div>
  );
}
