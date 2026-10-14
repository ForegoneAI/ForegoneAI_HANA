"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/Badge";
import { ButtonLink } from "@/components/Button";
import { Notice } from "@/components/Notice";
import { RequireSignIn } from "@/components/RequireSignIn";
import { ApiError, getCurrentUser, listDeals, type DealSummary } from "@/lib/api";
import { dealTitle, formatSavedAt, reviewStatusBadge } from "@/lib/deals";
import { organizationNames } from "@/lib/organizations";

/** Every deal the user's organizations own, so a saved deal can be reopened. */
function DealList() {
  const router = useRouter();
  const [deals, setDeals] = useState<DealSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Set only for a member of several organizations, to label each deal.
  const [orgNames, setOrgNames] = useState<Map<string, string> | null>(null);

  useEffect(() => {
    // Labels are a nicety: the list still shows if this fails.
    getCurrentUser()
      .then((user) => {
        if (user.organizations.length > 1) setOrgNames(organizationNames(user.organizations));
      })
      .catch(() => {});
    listDeals()
      .then(setDeals)
      .catch((caught) => {
        if (caught instanceof ApiError && caught.status === 401) {
          router.replace(`/login?next=${encodeURIComponent("/deals")}`);
          return;
        }
        setError(caught instanceof Error ? caught.message : "Something went wrong.");
      });
  }, [router]);

  return (
    <main className="page">
      <div className="page-head">
        <h1>Deals</h1>
        <ButtonLink href="/deals/new" size="sm">
          Upload a deal
        </ButtonLink>
      </div>

      {error && <Notice tone="error">{error}</Notice>}
      {!error && !deals && <p className="muted">Loading your deals…</p>}
      {deals && deals.length === 0 && (
        <Notice>
          No deals yet. <Link href="/deals/new">Upload a deal package</Link> to extract its first Deal Profile.
        </Notice>
      )}
      {deals && deals.length > 0 && (
        <ul className="deal-list">
          {deals.map((deal) => {
            const status = reviewStatusBadge(deal.review_status);
            return (
              <li key={deal.deal_id}>
                <Link href={`/deals/${deal.deal_id}`} className="deal-list__item">
                  <span className="deal-list__name">
                    {dealTitle(deal)}
                    {deal.deal_name && deal.property_name && <span className="muted"> · {deal.property_name}</span>}
                  </span>
                  <span className="deal-list__meta">
                    {orgNames && <span className="muted">{orgNames.get(deal.organization_id)}</span>}
                    <Badge tone={status.tone}>{status.label}</Badge>
                    <span className="muted mono">{formatSavedAt(deal.saved_at)}</span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </main>
  );
}

export default function DealsPage() {
  return (
    <RequireSignIn>
      <DealList />
    </RequireSignIn>
  );
}
