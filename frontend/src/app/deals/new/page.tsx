"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, type ChangeEvent, type DragEvent } from "react";

import { Button, ButtonLink } from "@/components/Button";
import { Notice } from "@/components/Notice";
import { RequireSignIn } from "@/components/RequireSignIn";
import { ApiError, getCurrentUser, uploadDeal, type ExtractResponse, type Organization } from "@/lib/api";
import { uploadTarget } from "@/lib/organizations";
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
  // undefined while loading; null if they couldn't be loaded, in which case
  // the upload goes ahead and the API says if it needs an organization.
  const [organizations, setOrganizations] = useState<Organization[] | null | undefined>(undefined);
  const [organizationId, setOrganizationId] = useState<string | null>(null);

  useEffect(() => {
    getCurrentUser()
      .then((user) => setOrganizations(user.organizations))
      .catch((caught) => {
        if (caught instanceof ApiError && caught.status === 401) {
          router.replace(`/login?next=${encodeURIComponent("/deals/new")}`);
          return;
        }
        setOrganizations(null);
      });
  }, [router]);

  const busy = stage.name === "uploading" || stage.name === "processing";
  const target = uploadTarget(organizations ?? null, organizationId);
  const canStart = organizations !== undefined && target.kind === "ready";

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
    if (!file || fileError || target.kind !== "ready") return;
    setStage({ name: "uploading", fraction: 0 });
    try {
      const result = await uploadDeal(file, {
        organizationId: target.organizationId,
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

      {target.kind === "none" && (
        <Notice tone="error">
          Your account isn&apos;t a member of any organization yet, so deals can&apos;t be uploaded. Ask your
          administrator to add you.
        </Notice>
      )}

      {organizations && organizations.length > 1 && (
        <div className="field">
          <label htmlFor="organization">Organization</label>
          <select
            id="organization"
            value={organizationId ?? ""}
            disabled={busy}
            onChange={(event) => setOrganizationId(event.target.value || null)}
          >
            <option value="">Choose who this deal is for…</option>
            {organizations.map((organization) => (
              <option key={organization.id} value={organization.id}>
                {organization.name}
              </option>
            ))}
          </select>
        </div>
      )}

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
            <span className="file-row__action">
              {target.kind === "choose" && <span className="muted">Choose an organization first</span>}
              <Button onClick={start} disabled={busy || Boolean(fileError) || !canStart}>
                {stage.name === "failed" ? "Try again" : "Extract deal"}
              </Button>
            </span>
          )}
        </div>
      )}

      {fileError && <Notice tone="error">{fileError}</Notice>}

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

      {stage.name === "failed" && <Notice tone="error">{stage.message}</Notice>}

      {stage.name === "done" && (
        <Notice tone="ok">
          <p style={{ margin: 0 }}>
            <strong>{stage.result.profile.deal_name ?? "Your deal"}</strong> is ready for review.
          </p>
          <div className="actions">
            <ButtonLink size="sm" href={`/deals/${stage.result.deal_id}`}>
              Open deal workspace
            </ButtonLink>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                setFile(null);
                setStage({ name: "idle" });
              }}
            >
              Upload another
            </Button>
          </div>
        </Notice>
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
