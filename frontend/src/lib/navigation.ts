/**
 * The page to return to after signing in. Only paths inside this app are
 * allowed, so a crafted link like /login?next=https://evil.example can't use
 * the sign-in page to send someone to another site.
 */
export function safeNextPath(next: string | null): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) {
    return "/deals";
  }
  return next;
}
