"use client";

import { useEffect, useState } from "react";

import { getDealHistory, type DealHistory } from "@/lib/api";
import { formatSavedAt } from "@/lib/deals";
import { historyEntries } from "@/lib/history";

/**
 * Everything reviewers have done to the deal, newest first (M2.4): each
 * corrected field with its old and new value, and each status change.
 * Reloads whenever the deal's version changes.
 */
export function DealHistoryPanel({
  dealId,
  version,
  currentUserId,
}: {
  dealId: string;
  version: number;
  currentUserId: string | null;
}) {
  const [history, setHistory] = useState<DealHistory | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let current = true;
    getDealHistory(dealId)
      .then((loaded) => {
        if (current) {
          setHistory(loaded);
          setError(null);
        }
      })
      .catch((caught) => current && setError(caught instanceof Error ? caught.message : "Couldn't load the history."));
    return () => {
      current = false;
    };
  }, [dealId, version]);

  const entries = history ? historyEntries(history, currentUserId) : [];

  return (
    <details className="history">
      <summary>
        <h2>History</h2>
        {history && <span className="muted"> · {entries.length === 0 ? "no changes yet" : `${entries.length} entries`}</span>}
      </summary>
      {error && <p className="muted">{error}</p>}
      {!history && !error && <p className="muted">Loading…</p>}
      {history && entries.length === 0 && <p className="muted">Nobody has changed this deal since it was extracted.</p>}
      {entries.length > 0 && (
        <ol className="history__list">
          {entries.map((entry) => (
            <li key={entry.key}>
              <span className="muted mono history__when">
                v{entry.version} · {formatSavedAt(entry.at)}
              </span>
              <span>
                <strong>{entry.who}</strong> {entry.what}
                {entry.note && <q className="history__note">{entry.note}</q>}
              </span>
            </li>
          ))}
        </ol>
      )}
    </details>
  );
}
