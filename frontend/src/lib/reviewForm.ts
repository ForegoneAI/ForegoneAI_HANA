import type { DealProfile, WithheldValue } from "./api";
import { ALL_FIELDS, parseInput, sameValue, toInput, valueOf } from "./dealFields";

/** What a reviewer has typed, field by field, before saving. */
export type Inputs = Record<string, string>;

/** Every field's input box, filled from the saved profile. */
export function initialInputs(profile: DealProfile): Inputs {
  return Object.fromEntries(ALL_FIELDS.map((field) => [field.name, toInput(valueOf(profile, field.name))]));
}

/**
 * The PATCH `changes` for what the reviewer did: only fields whose value
 * actually changed, plus the withheld list without any proposals they
 * accepted or dismissed (`resolved`). Fields that can't be read come back
 * in `errors` instead, and nothing should be saved while there are any.
 */
export function buildChanges(
  profile: DealProfile,
  inputs: Inputs,
  resolved: ReadonlySet<string>,
): { changes: Record<string, unknown>; errors: Record<string, string> } {
  const changes: Record<string, unknown> = {};
  const errors: Record<string, string> = {};

  for (const field of ALL_FIELDS) {
    const raw = inputs[field.name] ?? "";
    const parsed = parseInput(field, raw);
    if ("error" in parsed) {
      errors[field.name] = parsed.error;
    } else if (!sameValue(parsed.value, valueOf(profile, field.name))) {
      changes[field.name] = parsed.value;
    }
  }

  const remaining = profile.withheld_values.filter((entry) => !resolved.has(entry.field_name));
  if (remaining.length !== profile.withheld_values.length) changes.withheld_values = remaining;

  return { changes, errors };
}

/** Accepting a proposed value: fill it into the field and resolve the proposal. */
export function acceptProposal(
  inputs: Inputs,
  resolved: ReadonlySet<string>,
  proposal: WithheldValue,
): { inputs: Inputs; resolved: Set<string> } {
  return {
    inputs: { ...inputs, [proposal.field_name]: toInput(proposal.proposed_value) },
    resolved: new Set(resolved).add(proposal.field_name),
  };
}

/** Dismissing a proposed value: the field keeps whatever it has. */
export function dismissProposal(resolved: ReadonlySet<string>, proposal: WithheldValue): Set<string> {
  return new Set(resolved).add(proposal.field_name);
}

/**
 * How many fields the reviewer has touched, for the save bar. Accepting a
 * proposal changes the field and the withheld list, but it's one change.
 */
export function changeCount(changes: Record<string, unknown>, resolved: ReadonlySet<string>): number {
  const touched = new Set(Object.keys(changes).filter((name) => name !== "withheld_values"));
  if ("withheld_values" in changes) resolved.forEach((name) => touched.add(name));
  return touched.size;
}
