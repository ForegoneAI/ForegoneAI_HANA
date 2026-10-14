"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type ChangeEvent, type DragEvent } from "react";

import { RequireSignIn } from "@/components/RequireSignIn";
import { ApiError, uploadDeal, type ExtractResponse } from "@/lib/api";
import { formatBytes, validatePdf } from "@/lib/upload";

type Stage =
  | { name: "idle" }
  | { name: "uploading"; fraction: number }
  | { name: "processing" }
  | { name: "done"; result: ExtractResponse }
  | { name: "failed"; message: string };

const STEPS = [
  { key: "uploading", label: "Uploading" },
  { key: "processing", label: "Reading the PDF and extracting the deal" },
  { key: "done", label: "Deal Profile ready" },
] as const;

function stepState(step: (typeof STEPS)[number]["key"], stage: Stage["name"]): "done" | "active" | "waiting" {
  const order = ["uploading", "processing", "done"];
  const current = order.indexOf(stage);
  const index = order.indexOf(step);
  if (current < 0) return "waiting";
  if (index < current || stage === "done") return "done";
  return index === current ? "active" : "waiting";
}

function UploadDeal() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [stage, setStage] = useState<Stage>({ name: "idle" });
  const [dragging, setDragging] = useState(false);

  const busy = stage.name === "uploading" || stage.name === "processing";

  function choose(chosen: File | undefined) {
    if (!chosen || busy) return;
    setFile(chosen);
    setFileError(validatePdf(chosen));
    setStage({ name: "idle" });
  }

  function handleDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    choose(event.dataTransfer.files[0]);
  }

  async function start() {
    if (!file || fileError) return;
    setStage({ name: "uploading", fraction: 0 });
    try {
      const result = await uploadDeal(file, {
        onProgress: (fraction) => setStage({ name: "uploading", fraction }),
        onUploaded: () => setStage({ name: "processing" }),
      });
      setStage({ name: "done", result });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        router.replace(`/login?next=${encodeURIComponent("/deals/new")}`);
        return;
      }
      const message = error instanceof Error ? error.message : "Something went wrong.";
      setStage({ name: "failed", message });
    }
  }

  return (
    <main className="page">
      <h1>Upload a deal package</h1>
      <p className="muted">
        Upload a text-based PDF (CIM or offering memorandum). HANA extracts a Deal Profile with page
        citations for you to review.
      </p>

      <label
        className={`dropzone${dragging ? " dropzone--active" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={handleDrop}
      >
        <input
          type="file"
          accept="application/pdf,.pdf"
          disabled={busy}
          onChange={(event: ChangeEvent<HTMLInputElement>) => choose(event.target.files?.[0])}
        />
        <strong>Drop a PDF here, or click to choose one</strong>
        <span className="muted">Up to 50 MB</span>
      </label>

      {file && (
        <div className="file-row">
          <span className="file-row__name">
            {file.name} <span className="muted">· {formatBytes(file.size)}</span>
          </span>
          {stage.name !== "done" && (
            <button type="button" className="btn" onClick={start} disabled={busy || Boolean(fileError)}>
              {stage.name === "failed" ? "Try again" : "Extract deal"}
            </button>
          )}
        </div>
      )}

      {fileError && (
        <p className="notice notice--error" role="alert">
          {fileError}
        </p>
      )}

      {stage.name !== "idle" && stage.name !== "failed" && (
        <section aria-live="polite">
          <ol className="steps">
            {STEPS.map((step) => (
              <li key={step.key} data-state={stepState(step.key, stage.name)}>
                <span aria-hidden>{stepState(step.key, stage.name) === "done" ? "✓" : "•"}</span>
                {step.label}
                {step.key === "uploading" && stage.name === "uploading" && (
                  <span className="muted mono">{Math.round(stage.fraction * 100)}%</span>
                )}
              </li>
            ))}
          </ol>
          {busy && (
            <div className="progress" aria-hidden>
              {stage.name === "uploading" ? (
                <div className="progress__bar" style={{ width: `${Math.round(stage.fraction * 100)}%` }} />
              ) : (
                <div className="progress__bar progress__bar--indeterminate" />
              )}
            </div>
          )}
          {stage.name === "processing" && (
            <p className="muted">This usually takes under a minute. Keep this page open.</p>
          )}
        </section>
      )}

      {stage.name === "failed" && (
        <p className="notice notice--error" role="alert">
          {stage.message}
        </p>
      )}

      {stage.name === "done" && (
        <div className="notice notice--ok">
          <p style={{ margin: 0 }}>
            <strong>{stage.result.profile.deal_name ?? "Your deal"}</strong> is ready for review.
          </p>
          <p style={{ margin: "12px 0 0", display: "flex", gap: 12, flexWrap: "wrap" }}>
            <Link className="btn btn--sm" href={`/deals/${stage.result.deal_id}`}>
              Open deal workspace
            </Link>
            <button
              type="button"
              className="btn btn--ghost btn--sm"
              onClick={() => {
                setFile(null);
                setStage({ name: "idle" });
              }}
            >
              Upload another
            </button>
          </p>
        </div>
      )}
    </main>
  );
}

export default function NewDealPage() {
  return (
    <RequireSignIn>
      <UploadDeal />
    </RequireSignIn>
  );
}
