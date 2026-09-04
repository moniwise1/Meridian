"use client";

import { useState } from "react";
import { generateReport, generatePresentation, generateExport, emailArtifact, API_BASE, type Artifact } from "@/lib/api";
import { loadSession } from "@/lib/auth";

type Busy = "report" | "presentation" | "csv" | "xlsx" | "email" | null;

export default function ArtifactActions({ queryId }: { queryId: string }) {
  const [busy, setBusy] = useState<Busy>(null);
  const [lastArtifact, setLastArtifact] = useState<Artifact | null>(null);
  const [error, setError] = useState("");
  const [showEmail, setShowEmail] = useState(false);
  const [recipient, setRecipient] = useState("");
  const [emailStatus, setEmailStatus] = useState<{ status: string; reason: string } | null>(null);

  async function run(kind: Busy, fn: () => Promise<Artifact>) {
    setBusy(kind);
    setError("");
    try {
      const artifact = await fn();
      setLastArtifact(artifact);
      window.open(`${API_BASE}${artifact.url}`, "_blank");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function handleEmail(confirmed = false) {
    setBusy("email");
    setError("");
    try {
      const result = await emailArtifact(queryId, recipient, lastArtifact?.id, confirmed);
      setEmailStatus(result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const session = loadSession();

  return (
    <div className="bg-panel border border-line rounded-[4px] p-5">
      <div className="text-[13px] text-ink-soft mb-3">Create from this analysis</div>
      <div className="flex flex-wrap gap-2">
        <ActionButton label="Presentation" busy={busy === "presentation"} onClick={() => run("presentation", () => generatePresentation(queryId))} />
        <ActionButton label="Report (PDF)" busy={busy === "report"} onClick={() => run("report", () => generateReport(queryId))} />
        <ActionButton label="Export CSV" busy={busy === "csv"} onClick={() => run("csv", () => generateExport(queryId, "csv"))} />
        <ActionButton label="Export XLSX" busy={busy === "xlsx"} onClick={() => run("xlsx", () => generateExport(queryId, "xlsx"))} />
        <ActionButton label="Email report" busy={false} onClick={() => setShowEmail((v) => !v)} />
      </div>

      {showEmail && (
        <div className="mt-4 pt-4 border-t border-line">
          <div className="flex items-center gap-2">
            <input
              type="email"
              value={recipient}
              onChange={(e) => setRecipient(e.target.value)}
              placeholder={session?.email ?? "recipient@company.com"}
              className="text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 flex-1"
            />
            <button
              onClick={() => handleEmail(false)}
              disabled={!recipient.trim() || busy === "email"}
              className="text-[13px] px-3 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
            >
              Send
            </button>
          </div>
          {emailStatus && emailStatus.status === "pending_confirmation" && (
            <div className="mt-2 text-[12.5px] text-amber flex items-center gap-2">
              <span>{emailStatus.reason}</span>
              <button onClick={() => handleEmail(true)} className="text-teal hover:text-teal-deep underline">
                Send anyway
              </button>
            </div>
          )}
          {emailStatus && emailStatus.status === "sent" && (
            <div className="mt-2 text-[12.5px] text-teal">Sent to {recipient}.</div>
          )}
          {emailStatus && emailStatus.status === "failed" && (
            <div className="mt-2 text-[12.5px] text-red">{emailStatus.reason}</div>
          )}
        </div>
      )}

      {error && <div className="mt-3 text-[12.5px] text-red">{error}</div>}
    </div>
  );
}

function ActionButton({ label, busy, onClick }: { label: string; busy: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="text-[12.5px] px-3 py-1.5 rounded-[3px] border border-line text-ink hover:border-teal hover:text-teal transition-colors disabled:opacity-40"
    >
      {busy ? "Working…" : label}
    </button>
  );
}
