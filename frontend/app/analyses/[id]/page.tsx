"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getAnalysis, type ResultEvent } from "@/lib/api";
import ResultView from "@/components/ResultView";

export default function AnalysisDetailPage() {
  const params = useParams<{ id: string }>();
  const [result, setResult] = useState<ResultEvent | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!params.id) return;
    getAnalysis(params.id)
      .then(setResult)
      .catch((e) => setError(e.message));
  }, [params.id]);

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <div className="mb-8">
        <Link href="/analyses" className="text-[12.5px] text-teal hover:text-teal-deep transition-colors">
          ← All analyses
        </Link>
        {result && (
          <h1 className="text-[22px] font-medium text-ink tracking-tight mt-2">
            {result.resolved_question}
          </h1>
        )}
      </div>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}
      {!result && !error && <div className="text-[13px] text-ink-soft">Loading…</div>}
      {result && <ResultView result={result} />}
    </div>
  );
}
