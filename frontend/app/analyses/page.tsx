"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listAnalyses, pinAnalysis, unpinAnalysis, type AnalysisSummary } from "@/lib/api";

export default function AnalysesPage() {
  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([]);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<"all" | "saved">("all");
  // Tracks in-flight pin toggles so a fast double-click can't fire two
  // overlapping requests for the same row.
  const [pinning, setPinning] = useState<Set<string>>(new Set());

  function refresh(f: "all" | "saved") {
    listAnalyses(f === "saved")
      .then(setAnalyses)
      .catch((e) => setError(e.message));
  }

  useEffect(() => refresh(filter), [filter]);

  async function togglePin(a: AnalysisSummary, e: React.MouseEvent) {
    e.preventDefault(); // rows are links — don't navigate on the star click
    e.stopPropagation();
    if (pinning.has(a.query_id)) return;
    setPinning((prev) => new Set(prev).add(a.query_id));
    const nextPinned = !a.pinned;
    try {
      if (nextPinned) {
        await pinAnalysis(a.query_id);
      } else {
        await unpinAnalysis(a.query_id);
      }
      if (filter === "saved" && !nextPinned) {
        // Unpinning while viewing the Saved tab drops the row entirely.
        setAnalyses((prev) => prev.filter((x) => x.query_id !== a.query_id));
      } else {
        setAnalyses((prev) =>
          prev.map((x) => (x.query_id === a.query_id ? { ...x, pinned: nextPinned } : x)),
        );
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPinning((prev) => {
        const next = new Set(prev);
        next.delete(a.query_id);
        return next;
      });
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Analyses</h1>
      <p className="text-[13.5px] text-ink-soft mb-6">
        Every question the team has asked, with the evidence behind the answer — reopen any of
        these instead of re-running the same question. Star one to keep it in Saved for quick access.
      </p>

      <div className="flex items-center gap-1 mb-6">
        {(["all", "saved"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`text-[12.5px] px-2.5 py-1 rounded-[3px] transition-colors ${
              filter === f ? "bg-panel text-ink border border-line" : "text-ink-soft hover:text-ink"
            }`}
          >
            {f === "all" ? "All" : "Saved"}
          </button>
        ))}
      </div>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}

      <div className="flex flex-col">
        {analyses.map((a) => (
          <Link
            key={a.query_id}
            href={`/analyses/${a.query_id}`}
            className="border-b border-line py-3 flex items-start justify-between gap-4 hover:bg-panel transition-colors -mx-2 px-2 rounded-[3px]"
          >
            <div className="min-w-0">
              <div className="text-[13.5px] text-ink truncate">{a.question}</div>
              <div className="text-[11.5px] text-ink-soft font-[family-name:var(--font-mono)] mt-0.5">
                {new Date(a.created_at).toLocaleString()} · {a.row_count.toLocaleString()} rows ·{" "}
                {a.duration_ms} ms
              </div>
            </div>
            <button
              onClick={(e) => togglePin(a, e)}
              aria-label={a.pinned ? "Unpin this analysis" : "Pin this analysis"}
              title={a.pinned ? "Unpin" : "Pin"}
              className={`shrink-0 text-[16px] leading-none mt-0.5 transition-colors ${
                a.pinned ? "text-teal" : "text-ink-soft/40 hover:text-ink-soft"
              }`}
            >
              {a.pinned ? "★" : "☆"}
            </button>
          </Link>
        ))}
        {analyses.length === 0 && !error && (
          <div className="text-[13px] text-ink-soft">
            {filter === "saved"
              ? "No saved analyses yet — star one from All to keep it here."
              : "No analyses yet — ask a question to get started."}
          </div>
        )}
      </div>
    </div>
  );
}
