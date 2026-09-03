"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listAnalyses, type AnalysisSummary } from "@/lib/api";

export default function AnalysesPage() {
  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    listAnalyses()
      .then(setAnalyses)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Analyses</h1>
      <p className="text-[13.5px] text-ink-soft mb-8">
        Every question the team has asked, with the evidence behind the answer — reopen any of
        these instead of re-running the same question.
      </p>

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
          </Link>
        ))}
        {analyses.length === 0 && !error && (
          <div className="text-[13px] text-ink-soft">No analyses yet — ask a question to get started.</div>
        )}
      </div>
    </div>
  );
}
