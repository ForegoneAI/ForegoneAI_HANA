"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/Badge";
import { Notice } from "@/components/Notice";
import { RequireSignIn } from "@/components/RequireSignIn";
import { ApiError, getDeal, type DealProfile } from "@/lib/api";
import { dealTitle, reviewStatusBadge } from "@/lib/deals";

const KEY_FIELDS: { field: keyof DealProfile; label: string; format?: (value: number) => string }[] = [
  { field: "property_name", label: "Property" },
  { field: "property_type", label: "Property type" },
  { field: "address", label: "Address" },
  { field: "asking_price", label: "Asking price", format: (v) => `$${v.toLocaleString("en-US")}` },
  { field: "noi", label: "NOI", format: (v) => `$${v.toLocaleString("en-US")}` },
  { field: "cap_rate", label: "Cap rate", format: (v) => `${v}%` },
];

/**
 * The deal workspace M2.1 links into. For now it shows the key extracted
 * values and how many need attention; the editable review form (M2.2) and
 * evidence viewer (M2.3) replace this summary.
 */
function DealWorkspace() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [deal, setDeal] = useState<DealProfile | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getDeal(id)
      .then(setDeal)
      .catch((caught) => {
        if (caught instanceof ApiError && caught.status === 401) {
          router.replace(`/login?next=${encodeURIComponent(`/deals/${id}`)}`);
          return;
        }
        setError(caught instanceof Error ? caught.message : "Something went wrong.");
      });
  }, [id, router]);

  if (error) {
    return (
      <main className="page">
        <Notice tone="error">{error}</Notice>
        <p>
          <Link href="/deals">Back to all deals</Link>
        </p>
      </main>
    );
  }
  if (!deal) {
    return (
      <main className="page">
        <p className="muted">Loading the deal…</p>
      </main>
    );
  }

  const flags = [
    { label: "missing", count: deal.missing_information.length },
    { label: "uncertain", count: deal.uncertain_information.length },
    { label: "conflicting", count: deal.conflicting_information.length },
    { label: "withheld", count: deal.withheld_values.length },
  ];

  const status = reviewStatusBadge(deal.review_status);

  return (
    <main className="page">
      <p className="breadcrumb">
        <Link href="/deals">← All deals</Link>
      </p>
      <div className="page-head">
        <h1>{dealTitle(deal)}</h1>
        <Badge tone={status.tone}>{status.label}</Badge>
      </div>

      <dl className="facts">
        {KEY_FIELDS.map(({ field, label, format }) => {
          const value = deal[field];
          const shown =
            value === null || value === undefined
              ? "Not found in the document"
              : typeof value === "number" && format
                ? format(value)
                : String(value);
          return (
            <div className="fact" key={String(field)}>
              <dt>{label}</dt>
              <dd className={value === null || value === undefined ? "muted" : undefined}>{shown}</dd>
            </div>
          );
        })}
      </dl>

      <h2>Needs attention</h2>
      <div className="flags">
        {flags.map(({ label, count }) => (
          <Badge key={label} tone={count > 0 ? "warn" : "neutral"}>
            {count} {label}
          </Badge>
        ))}
      </div>

      <Notice>
        The full review form, with editing and source evidence for each field, is coming next. For now
        this page confirms the deal was extracted and saved.
      </Notice>
    </main>
  );
}

export default function DealPage() {
  return (
    <RequireSignIn>
      <DealWorkspace />
    </RequireSignIn>
  );
}
