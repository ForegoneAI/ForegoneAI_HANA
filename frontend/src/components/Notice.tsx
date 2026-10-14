import type { ReactNode } from "react";

/**
 * A boxed message. Errors are announced to screen readers as soon as they
 * appear (role="alert"); other notices are read in page order.
 */
export function Notice({ tone, children }: { tone?: "error" | "ok"; children: ReactNode }) {
  return (
    <div className={tone ? `notice notice--${tone}` : "notice"} role={tone === "error" ? "alert" : undefined}>
      {children}
    </div>
  );
}
