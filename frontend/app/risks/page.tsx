"use client";

import { useEffect, useState } from "react";
import {
  listConnections,
  scanStream,
  type Connection,
  type StepEvent,
  type ScanResultEvent,
  type ScannedAnomaly,
} from "@/lib/api";
import ProgressTrace from "@/components/ProgressTrace";

function ConfidenceBadge({ level }: { level: string }) {
  const styles: Record<string, string> = {
    high: "bg-teal-deep text-white",
    moderate: "bg-amber-soft text-amber",
    low: "bg-line text-ink-soft",
  };
  return (
    <span className={`text-[11px] px-2 py-0.5 rounded-[3px] ${styles[level] ?? styles.low}`}>
      {level} confidence
    </span>
  );
}

export default function RisksPage() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [connectionId, setConnectionId] = useState("");
  const [steps, setSteps] = useState<StepEvent[]>([]);
  const [result, setResult] = useState<ScanResultEvent | null>(null);
  const [running, setRunning] = useState(false);
  const [loadError, setLoadError] = useState("");

  useEffect(() => {
    listConnections()
      .then((rows) => {
        setConnections(rows);
        if (rows.length > 0) setConnectionId(rows[0].id);
      })
      .catch((e) => setLoadError(e.message));
  }, []);

  async function handleScan() {
    if (!connectionId) return;
    setRunning(true);
    setSteps([]);
    setResult(null);
    try {
      await scanStream({ connection_id: connectionId }, (evt) => {
        if (evt.type === "step") setSteps((prev) => [...prev, evt]);
        else setResult(evt);
      });
    } catch (e) {
      setSteps((prev) => [...prev, { type: "step", step: "error", status: "error", detail: (e as Error).message }]);
    } finally {
      setRunning(false);
    }
  }

  const byTable = new Map<string, ScannedAnomaly[]>();
  for (const a of result?.anomalies ?? []) {
    byTable.set(a.table, [...(byTable.get(a.table) ?? []), a]);
  }

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Risk scan</h1>
      <p className="text-[13.5px] text-ink-soft mb-8">
        Proactively checks every authorized table on a data source for anomalies — the same
        detection Ask runs on a single question&apos;s result, applied across everything you&apos;re
        authorized to see, without having to already know what to ask about.
      </p>

      {loadError && <div className="mb-6 text-[13px] text-red">{loadError}</div>}
      {connections.length === 0 && !loadError && (
        <div className="mb-6 p-3 border border-line rounded-[4px] text-[13px] text-ink-soft">
          No data sources connected yet. Go to <span className="text-teal">Data sources</span> to connect one.
        </div>
      )}

      <div className="bg-panel border border-line rounded-[4px] p-4 mb-8">
        <div className="flex items-center gap-3">
          <label className="text-[12.5px] text-ink-soft shrink-0">Data source</label>
          <select
            value={connectionId}
            onChange={(e) => setConnectionId(e.target.value)}
            className="text-[13px] border border-line rounded-[3px] px-2 py-1 bg-panel text-ink flex-1"
          >
            {connections.length === 0 && <option value="">No data sources connected</option>}
            {connections.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.database})
              </option>
            ))}
          </select>
          <button
            onClick={handleScan}
            disabled={running || !connectionId}
            className="shrink-0 text-[13px] px-4 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-teal transition-colors"
          >
            {running ? "Scanning…" : "Scan for risks"}
          </button>
        </div>
      </div>

      {steps.length > 0 && (
        <div className="mb-8">
          <ProgressTrace steps={steps} />
        </div>
      )}

      {result && (
        <div className="flex flex-col gap-5">
          {result.anomalies.length === 0 ? (
            <div className="bg-panel border border-line rounded-[4px] p-5 text-[13px] text-ink-soft">
              No anomalies detected across {result.tables_scanned.length} scanned table(s).
            </div>
          ) : (
            Array.from(byTable.entries()).map(([table, anomalies]) => (
              <div key={table} className="bg-panel border border-line rounded-[4px] p-5">
                <div className="text-[13px] text-ink-soft mb-3 font-[family-name:var(--font-mono)]">{table}</div>
                <div className="flex flex-col gap-4">
                  {anomalies.map((a, i) => (
                    <div key={i} className={i > 0 ? "pt-4 border-t border-line" : ""}>
                      <div className="flex items-start justify-between gap-3">
                        <div className="text-[13.5px] text-ink">{a.what}</div>
                        <ConfidenceBadge level={a.confidence} />
                      </div>
                      <div className="text-[12.5px] text-ink-soft mt-1">{a.magnitude}</div>
                      <div className="text-[12px] text-ink-soft font-[family-name:var(--font-mono)] mt-1.5">
                        {a.evidence}
                      </div>
                      {a.possible_explanations.map((p, j) => (
                        <div key={j} className="text-[12.5px] text-ink-soft mt-1.5 italic">
                          {p}
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            ))
          )}

          {result.tables_skipped.length > 0 && (
            <div className="text-[12px] text-ink-soft">
              Skipped {result.tables_skipped.length} table(s) with no recognizable
              value/dimension/date columns to check: {result.tables_skipped.join(", ")}.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
