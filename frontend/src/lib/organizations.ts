import type { Organization } from "./api";

/**
 * Which organization an upload is for, or why it can't start yet.
 *
 * - "ready" with no organizationId: the user has one organization, and the
 *   API uses it (or their organizations couldn't be loaded, and the API
 *   explains if it needs one).
 * - "choose": the user belongs to several and hasn't picked one. The API
 *   refuses to guess, so the app asks.
 * - "none": the user isn't a member of any organization, so nothing can be
 *   uploaded.
 */
export type UploadTarget = { kind: "ready"; organizationId?: string } | { kind: "choose" } | { kind: "none" };

export function uploadTarget(organizations: Organization[] | null, chosenId: string | null): UploadTarget {
  if (organizations === null) return { kind: "ready" };
  if (organizations.length === 0) return { kind: "none" };
  if (organizations.length === 1) return { kind: "ready" };
  const chosen = organizations.find((organization) => organization.id === chosenId);
  return chosen ? { kind: "ready", organizationId: chosen.id } : { kind: "choose" };
}

/** Organization names by id, for labelling deals when a user has several. */
export function organizationNames(organizations: Organization[]): Map<string, string> {
  return new Map(organizations.map((organization) => [organization.id, organization.name]));
}
