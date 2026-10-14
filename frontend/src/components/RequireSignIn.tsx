"use client";

import type { Session } from "@supabase/supabase-js";
import { usePathname, useRouter } from "next/navigation";
import { Suspense, useEffect, useState, type ReactNode } from "react";

import { getSupabase, supabaseConfigError } from "@/lib/supabase";
import { AppHeader } from "./AppHeader";
import { Notice } from "./Notice";

function Checking() {
  return (
    <main className="page">
      <p className="muted">Checking your sign-in…</p>
    </main>
  );
}

/**
 * Shows its children only to a signed-in user; anyone else is sent to
 * /login and brought back here afterwards. This is a convenience, not the
 * security boundary - the H9N API rejects requests without a valid session
 * whatever the browser does (Milestone 2.5).
 */
export function RequireSignIn({ children }: { children: ReactNode }) {
  // Pages under this read the URL (path, deal id), which is only known in
  // the browser, so they render behind a Suspense boundary.
  return (
    <Suspense fallback={<Checking />}>
      <SignInGate>{children}</SignInGate>
    </Suspense>
  );
}

function SignInGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [configError] = useState(supabaseConfigError);
  const [session, setSession] = useState<Session | null | undefined>(undefined);

  useEffect(() => {
    if (configError) return;
    const supabase = getSupabase();
    supabase.auth.getSession().then(({ data }) => setSession(data.session));
    const { data: listener } = supabase.auth.onAuthStateChange((_event, next) => setSession(next));
    return () => listener.subscription.unsubscribe();
  }, [configError]);

  useEffect(() => {
    if (session === null) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [session, pathname, router]);

  if (configError) {
    return (
      <main className="page">
        <Notice tone="error">{configError}</Notice>
      </main>
    );
  }
  if (!session) return <Checking />;

  return (
    <>
      <AppHeader email={session.user.email ?? "Signed in"} />
      {children}
    </>
  );
}
