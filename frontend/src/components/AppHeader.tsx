"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { getSupabase } from "@/lib/supabase";
import { Button } from "./Button";

const NAV = [
  { href: "/deals", label: "Deals" },
  { href: "/deals/new", label: "Upload a deal" },
];

export function AppHeader({ email }: { email: string }) {
  const router = useRouter();
  const pathname = usePathname();

  async function signOut() {
    await getSupabase().auth.signOut();
    router.replace("/login");
  }

  return (
    <header className="app-header">
      <Link href="/deals" className="app-header__brand">
        HANA <span className="muted">· H9N</span>
      </Link>
      <nav className="app-header__nav">
        {NAV.map(({ href, label }) => (
          <Link key={href} href={href} aria-current={pathname === href ? "page" : undefined}>
            {label}
          </Link>
        ))}
        <span className="muted app-header__email">{email}</span>
        <Button variant="ghost" size="sm" onClick={signOut}>
          Sign out
        </Button>
      </nav>
    </header>
  );
}
