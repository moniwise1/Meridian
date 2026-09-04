"use client";

import { useEffect, useState } from "react";
import {
  listPlatformAudit, verifyPlatformAudit, publishAuditCheckpoint, getLatestAuditCheckpoint,
  type PlatformAuditEntry, type PlatformAuditVerification,
  type PublishCheckpointResult, type CheckpointVerification,
} from "@/lib/platformApi";
import { loadPlatformSession } from "@/lib/platformAuth";

export default function PlatformAuditPage() {
  const [entries, setEntries] = useState<PlatformAuditEntry[]>([]);
  const [verification, setVerification] = useState<PlatformAuditVerification | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState("");

  const [publishing, setPublishing] = useState(false);
  const [publishResult, setPublishResult] = useState<PublishCheckpointResult | null>(null);
  const [publishError, setPublishError] = useState("");

  const [checkpointVerification, setCheckpointVerification] = useState<CheckpointVerification | null>(null);
  const [checkpointVerifying, setCheckpointVerifying] = useState(false);
  const [checkpointError, setCheckpointError] = useState("");

  const isOwner = loadPlatformSession()?.role === "owner";

  useEffect(() => {
    listPlatformAudit().then(setEntries).catch(() => {});
  }, []);

  async function handleVerify() {
    setVerifying(true);
    setVerifyError("");
    setVerification(null);
    try {
      setVerification(await verifyPlatformAudit());
    } catch (e) {
      setVerifyError((e as Error).message);
    } finally {
      setVerifying(false);
    }
  }

  async function handlePublishCheckpoint() {
    setPublishing(true);
    setPublishError("");
    setPublishResult(null);
    try {
      setPublishResult(await publishAuditCheckpoint());
    } catch (e) {
      setPublishError((e as Error).message);
    } finally {
      setPublishing(false);
    }
  }

  async function handleVerifyCheckpoint() {
    setCheckpointVerifying(true);
    setCheckpointError("");
    setCheckpointVerification(null);
    try {
      setCheckpointVerification(await getLatestAuditCheckpoint());
    } catch (e) {
      setCheckpointError((e as Error).message);
    } finally {
      setCheckpointVerifying(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <div className="flex items-start justify-between gap-4 mb-1.5">
        <h1 className="text-[22px] font-medium text-ink tracking-tight">Activity</h1>
        <button
          onClick={handleVerify}
          disabled={verifying}
          className="shrink-0 text-[12.5px] px-3 py-1.5 rounded-[3px] border border-line text-ink hover:border-teal hover:text-teal transition-colors disabled:opacity-40"
        >
          {verifying ? "Verifying…" : "Verify integrity"}
        </button>
      </div>
      <p className="text-[13.5px] text-ink-soft mb-3">
        Every staff login and every action taken from this panel — who did what, and when. Same
        hash-chained log as a tenant&apos;s own audit trail, just scoped to Meridian&apos;s
        internal team instead of one organization&apos;s activity.
      </p>

      {verifyError && <div className="mb-6 text-[13px] text-red">{verifyError}</div>}
      {verification && (
        <div
          className={`mb-8 p-3 rounded-[4px] border text-[13px] ${
            verification.intact ? "border-line bg-panel text-ink-soft" : "border-red bg-panel text-red"
          }`}
        >
          {verification.intact
            ? `Chain intact — ${verification.checked} entries checked, no tampering detected.`
            : `Chain broken at entry ${verification.broken_at} (${verification.checked} entries checked): ${verification.reason}`}
        </div>
      )}

      <div className="bg-panel border border-line rounded-[4px] p-4 mb-8">
        <div className="text-[13.5px] text-ink mb-1">External anchor</div>
        <p className="text-[12.5px] text-ink-soft mb-3">
          &quot;Verify integrity&quot; above only proves the log is internally consistent — it
          can&apos;t tell an untouched history apart from a fabricated-but-consistent replacement
          someone with database access built from scratch. Publishing a checkpoint anchors every
          tenant&apos;s current chain head to a real commit in an external GitHub repo, outside
          this database entirely; verifying checks whether that anchored hash still exists in
          today&apos;s chain.
        </p>

        <div className="flex flex-wrap items-center gap-2 mb-3">
          {isOwner && (
            <button
              onClick={handlePublishCheckpoint}
              disabled={publishing}
              className="text-[12.5px] px-3 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
            >
              {publishing ? "Publishing…" : "Publish checkpoint"}
            </button>
          )}
          <button
            onClick={handleVerifyCheckpoint}
            disabled={checkpointVerifying}
            className="text-[12.5px] px-3 py-1.5 rounded-[3px] border border-line text-ink hover:border-teal hover:text-teal transition-colors disabled:opacity-40"
          >
            {checkpointVerifying ? "Checking…" : "Verify against latest checkpoint"}
          </button>
        </div>

        {!isOwner && (
          <div className="text-[12px] text-ink-soft mb-2">Only an owner can publish a new checkpoint.</div>
        )}

        {publishError && <div className="text-[12.5px] text-red mb-2">{publishError}</div>}
        {publishResult && (
          <div className="text-[12.5px] text-teal mb-2">
            Published — root hash <code className="font-[family-name:var(--font-mono)]">{publishResult.checkpoint.root_hash.slice(0, 16)}…</code>{" "}
            (<a href={publishResult.commit_url} target="_blank" rel="noreferrer" className="underline hover:no-underline">view commit</a>)
          </div>
        )}

        {checkpointError && <div className="text-[12.5px] text-red mb-2">{checkpointError}</div>}
        {checkpointVerification && (
          <div
            className={`p-3 rounded-[4px] border text-[12.5px] ${
              checkpointVerification.verified ? "border-line bg-paper text-ink-soft" : "border-red bg-paper text-red"
            }`}
          >
            <div className="mb-1">
              {checkpointVerification.verified
                ? "Verified — every anchored tenant chain still traces back to this checkpoint."
                : "Not verified — at least one tenant's chain no longer matches its anchored checkpoint."}
            </div>
            <div className="text-[11px] font-[family-name:var(--font-mono)] text-ink-soft">
              anchored {new Date(checkpointVerification.checkpoint.generated_at).toLocaleString()} · root{" "}
              {checkpointVerification.checkpoint.root_hash.slice(0, 16)}…
            </div>
          </div>
        )}
      </div>

      <div className="flex flex-col">
        {entries.map((e) => (
          <div key={e.id} className="border-b border-line py-3 flex items-start gap-4">
            <div className="w-40 shrink-0 text-[11.5px] text-ink-soft font-[family-name:var(--font-mono)] pt-0.5">
              {new Date(e.timestamp).toLocaleString()}
            </div>
            <div className="flex-1">
              <div className="flex items-center gap-2">
                <span className="text-[13px] text-ink">{e.action.replace(/_/g, " ")}</span>
                <span
                  className={`text-[10.5px] px-1.5 py-0.5 rounded-[2px] ${
                    e.status === "ok" ? "bg-line text-ink-soft" : "bg-amber-soft text-amber"
                  }`}
                >
                  {e.status}
                </span>
              </div>
              {Object.keys(e.detail).length > 0 && (
                <div className="text-[12px] text-ink-soft font-[family-name:var(--font-mono)] mt-1">
                  {JSON.stringify(e.detail)}
                </div>
              )}
            </div>
          </div>
        ))}
        {entries.length === 0 && (
          <div className="text-[13px] text-ink-soft">No activity recorded yet.</div>
        )}
      </div>
    </div>
  );
}
