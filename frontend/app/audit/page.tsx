"use client";

import { useEffect, useState } from "react";
import { listAudit, verifyAuditChain, type AuditEntry, type AuditVerification } from "@/lib/api";

export default function AuditPage() {
  const [entries, setEntries] = useState<AuditEntry[]>([]);
  const [verification, setVerification] = useState<AuditVerification | null>(null);
  const [verifying, setVerifying] = useState(false);
  const [verifyError, setVerifyError] = useState("");

  useEffect(() => {
    listAudit().then(setEntries).catch(() => {});
  }, []);

  async function handleVerify() {
    setVerifying(true);
    setVerifyError("");
    setVerification(null);
    try {
      setVerification(await verifyAuditChain());
    } catch (e) {
      setVerifyError((e as Error).message);
    } finally {
      setVerifying(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <div className="flex items-start justify-between gap-4 mb-1.5">
        <h1 className="text-[22px] font-medium text-ink tracking-tight">Audit log</h1>
        <button
          onClick={handleVerify}
          disabled={verifying}
          className="shrink-0 text-[12.5px] px-3 py-1.5 rounded-[3px] border border-line text-ink hover:border-teal hover:text-teal transition-colors disabled:opacity-40"
        >
          {verifying ? "Verifying…" : "Verify integrity"}
        </button>
      </div>
      <p className="text-[13.5px] text-ink-soft mb-3">
        Every query, connection, and policy decision, in order. Each entry is chained to a hash
        of the one before it, so any edit or deletion breaks the chain from that point on —{" "}
        <span className="italic">verifying detects tampering, it doesn&apos;t prevent someone with
        direct database access from rewriting the chain consistently.</span>
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
