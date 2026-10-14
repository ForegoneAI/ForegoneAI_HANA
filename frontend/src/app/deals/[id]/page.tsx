"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Notice } from "@/components/Notice";
import { RequireSignIn } from "@/components/RequireSignIn";
import { DealHistoryPanel } from "@/components/review/DealHistoryPanel";
import { DealReviewForm } from "@/components/review/DealReviewForm";
import { EvidencePanel, type SourceState } from "@/components/review/EvidencePanel";
import { ReviewActions } from "@/components/review/ReviewActions";
import {
  ApiError,
  correctDeal,
  getCurrentUser,
  getDeal,
  getDealSource,
  reviewDeal,
  type DealRecord,
  type ReviewAction,
} from "@/lib/api";
import { dealTitle, formatSavedAt, reviewStatusBadge } from "@/lib/deals";
import { ALL_FIELDS, valueOf } from "@/lib/dealFields";
import { linkIsFresh } from "@/lib/evidence";
import { attentionCount, reviewField } from "@/lib/fieldStatus";

const DONE: Record<ReviewAction, string> = {
  review: "Marked reviewed.",
  approve: "Approved. This deal is now the trusted input for screening and underwriting.",
  reopen: "Reopened. The deal is a draft again.",
  reject: "Rejection saved. HANA re-checked the document and applied any corrections it could verify.",
};

/**
 * The deal workspace (M2.2): the Deal Profile as an editable review form,
 * the review actions (M2.4), the deal's history, and beside the form, the
 * source of whichever field the reviewer opens (M2.3).
 */
function DealWorkspace() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [deal, setDeal] = useState<DealRecord | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<ReviewAction | null>(null);
  const [sourceField, setSourceField] = useState<string | null>(null);
  const [source, setSource] = useState<SourceState | null>(null);
  const [message, setMessage] = useState<{ tone?: "ok" | "error"; text: string; reload?: boolean } | null>(null);

  const closeSource = useCallback(() => setSourceField(null), []);

  const signInAgain = useCallback(
    () => router.replace(`/login?next=${encodeURIComponent(`/deals/${id}`)}`),
    [id, router],
  );

  const showLoadError = useCallback(
    (caught: unknown) => {
      if (caught instanceof ApiError && caught.status === 401) return signInAgain();
      setLoadError(caught instanceof Error ? caught.message : "Something went wrong.");
    },
    [signInAgain],
  );

  useEffect(() => {
    getDeal(id).then(setDeal).catch(showLoadError);
    getCurrentUser()
      .then((user) => setUserId(user.user_id))
      .catch(() => {});
  }, [id, showLoadError]);

  /** Shows the deal as it is now, e.g. after someone else changed it. */
  async function load() {
    try {
      setDeal(await getDeal(id));
    } catch (caught) {
      showLoadError(caught);
    }
  }

  /** Shows why a change failed; a 409 means reloading is the way forward. */
  async function handleFailure(caught: unknown) {
    if (caught instanceof ApiError && caught.status === 401) return signInAgain();
    const text = caught instanceof Error ? caught.message : "Something went wrong.";
    if (caught instanceof ApiError && caught.status === 409 && /changed this deal/.test(text)) {
      setMessage({ tone: "error", text, reload: true });
      return;
    }
    setMessage({ tone: "error", text });
    // Part of the request may have been saved (e.g. a rejection whose
    // re-check failed), so show the deal as it is now.
    if (caught instanceof ApiError && caught.status >= 500) await load();
  }

  /** Loads a link to the deal's PDF, the first time it's needed or once it has expired. */
  async function loadSource(dealId: string) {
    setSource({ status: "loading" });
    try {
      setSource({ status: "ready", pdf: await getDealSource(dealId) });
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) return signInAgain();
      const text = caught instanceof Error ? caught.message : "The PDF couldn't be opened.";
      setSource(caught instanceof ApiError && caught.status === 404 ? { status: "missing", message: text } : { status: "error", message: text });
    }
  }

  function showSource(field: string) {
    setSourceField(field);
    if (!deal?.has_source_pdf) return;
    const stale = source?.status === "ready" && !linkIsFresh(source.pdf);
    if (source === null || source.status === "error" || stale) void loadSource(deal.deal_id);
  }

  async function saveChanges(changes: Record<string, unknown>) {
    if (!deal) return;
    setMessage(null);
    try {
      setDeal(await correctDeal(deal.deal_id, deal.version, changes));
      setMessage({ tone: "ok", text: "Changes saved." });
    } catch (caught) {
      await handleFailure(caught);
    }
  }

  async function act(action: ReviewAction, feedback?: string) {
    if (!deal) return;
    setBusy(action);
    setMessage(null);
    try {
      setDeal(await reviewDeal(deal.deal_id, action, deal.version, feedback));
      setMessage({ tone: "ok", text: DONE[action] });
    } catch (caught) {
      await handleFailure(caught);
    } finally {
      setBusy(null);
    }
  }

  if (loadError) {
    return (
      <main className="page">
        <Notice tone="error">{loadError}</Notice>
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

  const status = reviewStatusBadge(deal.status);
  const sourceSpec = ALL_FIELDS.find((field) => field.name === sourceField) ?? null;

  return (
    <main className={sourceField ? "page page--wider" : "page page--wide"}>
      <p className="breadcrumb">
        <Link href="/deals">← All deals</Link>
      </p>
      <div className="page-head">
        <h1>{dealTitle(deal.profile)}</h1>
        <Badge tone={status.tone}>{status.label}</Badge>
      </div>
      <p className="muted mono deal-meta">
        {deal.source_filename} · version {deal.version} · last saved {formatSavedAt(deal.updated_at)}
      </p>

      <ReviewActions
        key={`actions-${deal.version}`}
        status={deal.status}
        attention={attentionCount(deal.profile)}
        dirty={dirty}
        busy={busy}
        onAction={act}
      />

      {message && (
        <Notice tone={message.tone}>
          {message.text}
          {message.reload && (
            <div className="actions">
              <Button
                size="sm"
                onClick={() => {
                  setMessage(null);
                  void load();
                }}
              >
                Reload the latest version
              </Button>
            </div>
          )}
        </Notice>
      )}

      <div className={sourceSpec ? "workspace workspace--with-source" : "workspace"}>
        <DealReviewForm
          key={`form-${deal.version}`}
          deal={deal}
          onSave={saveChanges}
          onDirtyChange={setDirty}
          sourceField={sourceField}
          onShowSource={showSource}
        />
        {sourceSpec && (
          <EvidencePanel
            field={sourceSpec}
            review={reviewField(deal.profile, sourceSpec.name)}
            value={valueOf(deal.profile, sourceSpec.name)}
            sourceFilename={deal.source_filename}
            source={deal.has_source_pdf ? source : null}
            onRetrySource={() => void loadSource(deal.deal_id)}
            onClose={closeSource}
          />
        )}
      </div>

      <DealHistoryPanel dealId={deal.deal_id} version={deal.version} currentUserId={userId} />
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
