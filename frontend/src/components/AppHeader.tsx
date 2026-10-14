"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { getSupabase } from "@/lib/supabase";

export function AppHeader({ email }: { email: string }) {
  const router = useRouter();

  async function signOut() {
    await getSupabase().auth.signOut();
    router.replace("/login");
  }

  return (
    <header className="app-header">
      <Link href="/deals/new" className="app-header__brand">
        HANA <span className="muted">· H9N</span>
      </Link>
      <nav className="app-header__nav">
        <Link href="/deals/new">Upload a deal</Link>
        <span className="muted app-header__email">{email}</span>
        <button type="button" className="btn btn--ghost btn--sm" onClick={signOut}>
          Sign out
        </button>
      </nav>
    </header>
  );
}
