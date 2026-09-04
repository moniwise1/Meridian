"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getAnalysis, pinAnalysis, unpinAnalysis, type ResultEvent } from "@/lib/api";
import ResultView from "@/components/ResultView";

export default function AnalysisDetailPage() {
  const params = useParams<{ id: string }>();
  const [result, setResult] = useState<ResultEvent | null>(null);
  const [error, setError] = useState("");
  const [pinBusy, setPinBusy] = useState(false);

  useEffect(() => {
    if (!params.id) return;
    getAnalysis(params.id)
      .then(setResult)
      .catch((e) => setError(e.message));
  }, [params.id]);

  async function togglePin() {
    if (!result || pinBusy) return;
    setPinBusy(true);
    const nextPinned = !result.pinned;
    try {
      if (nextPinned) {
        await pinAnalysis(result.query_id);
      } else {
        await unpinAnalysis(result.query_id);
      }
      setResult({ ...result, pinned: nextPinned });
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setPinBusy(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <div className="mb-8">
        <Link href="/analyses" className="text-[12.5px] text-teal hover:text-teal-deep transition-colors">
          ← All analyses
        </Link>
        {result && (
          <div className="flex items-start justify-between gap-4 mt-2">
            <h1 className="text-[22px] font-medium text-ink tracking-tight">
              {result.resolved_question}
            </h1>
            <button
              onClick={togglePin}
              disabled={pinBusy}
              aria-label={result.pinned ? "Unpin this analysis" : "Pin this analysis"}
              title={result.pinned ? "Unpin" : "Pin"}
              className={`shrink-0 text-[20px] leading-none mt-1 transition-colors disabled:opacity-40 ${
                result.pinned ? "text-teal" : "text-ink-soft/40 hover:text-ink-soft"
              }`}
            >
              {result.pinned ? "★" : "☆"}
            </button>
          </div>
        )}
      </div>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}
      {!result && !error && <div className="text-[13px] text-ink-soft">Loading…</div>}
      {result && <ResultView result={result} />}
    </div>
  );
}
