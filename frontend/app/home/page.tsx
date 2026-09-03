"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  listAnalyses,
  listArtifactHistory,
  listConnections,
  type AnalysisSummary,
  type ArtifactHistoryEntry,
  type Connection,
} from "@/lib/api";
import { loadSession } from "@/lib/auth";

const KIND_LABEL: Record<string, string> = {
  report_pdf: "Report",
  presentation_pptx: "Presentation",
  export_csv: "CSV export",
  export_xlsx: "XLSX export",
};

function StatCard({ label, value, href }: { label: string; value: number; href: string }) {
  return (
    <Link
      href={href}
      className="bg-panel border border-line rounded-[4px] px-4 py-3.5 hover:border-teal transition-colors"
    >
      <div className="text-[22px] font-medium text-ink tracking-tight tabular-nums">{value}</div>
      <div className="text-[12px] text-ink-soft mt-0.5">{label}</div>
    </Link>
  );
}

export default function HomePage() {
  const session = loadSession();
  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactHistoryEntry[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([listAnalyses(), listArtifactHistory(), listConnections()])
      .then(([a, r, c]) => {
        setAnalyses(a);
        setArtifacts(r);
        setConnections(c);
      })
      .catch((e) => setError(e.message));
  }, []);

  const greetingName = session?.email.split("@")[0] ?? "there";

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">
        Welcome back, {greetingName}
      </h1>
      <p className="text-[13.5px] text-ink-soft mb-8">
        A snapshot of what the team has connected, asked, and generated.
      </p>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}

      <div className="grid grid-cols-3 gap-3 mb-10">
        <StatCard label="Data sources" value={connections.length} href="/connections" />
        <StatCard label="Analyses run" value={analyses.length} href="/analyses" />
        <StatCard label="Artifacts generated" value={artifacts.length} href="/library" />
      </div>

      <div className="flex flex-wrap gap-2 mb-10">
        <Link
          href="/"
          className="text-[13px] px-4 py-1.5 rounded-[3px] bg-teal-deep text-white hover:bg-teal transition-colors"
        >
          Ask a question
        </Link>
        <Link
          href="/connections"
          className="text-[13px] px-4 py-1.5 rounded-[3px] border border-line text-ink hover:border-teal hover:text-teal transition-colors"
        >
          Connect a data source
        </Link>
      </div>

      <div className="grid grid-cols-2 gap-6">
        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="text-[13px] text-ink-soft">Recent analyses</div>
            <Link href="/analyses" className="text-[11.5px] text-teal hover:text-teal-deep transition-colors">
              View all
            </Link>
          </div>
          <div className="flex flex-col">
            {analyses.slice(0, 5).map((a) => (
              <Link
                key={a.query_id}
                href={`/analyses/${a.query_id}`}
                className="border-b border-line py-2.5 hover:bg-panel transition-colors -mx-2 px-2 rounded-[3px]"
              >
                <div className="text-[13px] text-ink truncate">{a.question}</div>
                <div className="text-[11px] text-ink-soft mt-0.5">
                  {new Date(a.created_at).toLocaleDateString()}
                </div>
              </Link>
            ))}
            {analyses.length === 0 && !error && (
              <div className="text-[13px] text-ink-soft py-2">No analyses yet.</div>
            )}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="text-[13px] text-ink-soft">Recent artifacts</div>
            <Link href="/library" className="text-[11.5px] text-teal hover:text-teal-deep transition-colors">
              View all
            </Link>
          </div>
          <div className="flex flex-col">
            {artifacts.slice(0, 5).map((a) => (
              <div key={a.id} className="border-b border-line py-2.5">
                <div className="text-[13px] text-ink truncate">{a.title}</div>
                <div className="text-[11px] text-ink-soft mt-0.5">
                  {KIND_LABEL[a.kind] ?? a.kind} · {new Date(a.created_at).toLocaleDateString()}
                </div>
              </div>
            ))}
            {artifacts.length === 0 && !error && (
              <div className="text-[13px] text-ink-soft py-2">Nothing generated yet.</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
