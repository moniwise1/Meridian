"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE, listArtifactHistory, type ArtifactHistoryEntry } from "@/lib/api";

const TABS: { label: string; kind?: string }[] = [
  { label: "All" },
  { label: "Reports", kind: "report_pdf" },
  { label: "Presentations", kind: "presentation_pptx" },
  { label: "Exports", kind: "export_csv,export_xlsx" },
];

const KIND_LABEL: Record<string, string> = {
  report_pdf: "Report",
  presentation_pptx: "Presentation",
  export_csv: "CSV export",
  export_xlsx: "XLSX export",
};

export default function LibraryPage() {
  const [tab, setTab] = useState(0);
  const [artifacts, setArtifacts] = useState<ArtifactHistoryEntry[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    const kind = TABS[tab].kind;
    // Exports span two backend kinds; fetch unfiltered and narrow client-side for that tab.
    const fetchKind = kind && !kind.includes(",") ? kind : undefined;
    listArtifactHistory(fetchKind)
      .then((rows) => {
        if (kind && kind.includes(",")) {
          const allowed = new Set(kind.split(","));
          setArtifacts(rows.filter((r) => allowed.has(r.kind)));
        } else {
          setArtifacts(rows);
        }
      })
      .catch((e) => setError(e.message));
  }, [tab]);

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Library</h1>
      <p className="text-[13.5px] text-ink-soft mb-6">
        Reports, presentations, and exports the team has generated from past analyses.
      </p>

      <div className="flex items-center gap-1 mb-6 border-b border-line">
        {TABS.map((t, i) => (
          <button
            key={t.label}
            onClick={() => setTab(i)}
            className={`text-[13px] px-3 py-2 -mb-px border-b-2 transition-colors ${
              tab === i ? "border-teal-deep text-ink" : "border-transparent text-ink-soft hover:text-ink"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}

      <div className="flex flex-col">
        {artifacts.map((a) => (
          <div key={a.id} className="border-b border-line py-3 flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="text-[13.5px] text-ink truncate">{a.title}</div>
              <div className="text-[11.5px] text-ink-soft font-[family-name:var(--font-mono)] mt-0.5">
                {KIND_LABEL[a.kind] ?? a.kind} · {new Date(a.created_at).toLocaleString()}
              </div>
            </div>
            <div className="flex items-center gap-3 shrink-0">
              {a.source_query_id && (
                <Link
                  href={`/analyses/${a.source_query_id}`}
                  className="text-[12px] text-teal hover:text-teal-deep transition-colors"
                >
                  Source analysis
                </Link>
              )}
              <a
                href={`${API_BASE}${a.url}`}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[12px] px-2.5 py-1 rounded-[3px] border border-line text-ink hover:border-teal hover:text-teal transition-colors"
              >
                Download
              </a>
            </div>
          </div>
        ))}
        {artifacts.length === 0 && !error && (
          <div className="text-[13px] text-ink-soft">Nothing generated yet.</div>
        )}
      </div>
    </div>
  );
}
