"use client";
import { useEffect, useState } from "react";
import { getFileOverview, type FileOverview } from "@/lib/api";
export default function FileOverviewCard({ documentId, filename, onQuestion, disabled = false }: {
  documentId: string; filename: string; onQuestion: (question: string) => void; disabled?: boolean;
}) {
  const [state, setState] = useState<{ id: string; overview?: FileOverview; error?: string } | null>(null);
  useEffect(() => {
    let live = true;
    getFileOverview(documentId).then(overview => { if (live) setState({ id: documentId, overview }); })
      .catch(error => { if (live) setState({ id: documentId, error: error.message }); });
    return () => { live = false; };
  }, [documentId]);
  const current = state?.id === documentId ? state : null;
  const overview = current?.overview;
  return <section className="rounded-xl border border-line bg-panel p-4 mb-4" aria-label={`File overview: ${filename}`}>
    <div className="flex flex-wrap items-center justify-between gap-2 mb-3"><div className="min-w-0"><p className="text-[10px] text-teal uppercase tracking-widest mb-1">Your file at a glance</p><h2 className="text-sm font-medium break-words">{filename}</h2></div><span className="text-[10px] text-ink-soft">Selected file snapshot</span></div>
    {!current && <p role="status" className="text-xs text-ink-soft">Checking structure and data quality…</p>}
    {current?.error && <p role="status" className="text-xs text-red">{current.error}</p>}
    {overview && <>
      {overview.mode === "table" ? <>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">{[["Parsed rows", overview.row_count], ["Fields", overview.column_count], ["Missing / invalid cells", overview.missing_cells], ["Repeated rows", overview.duplicate_rows]].map(([label, value]) => <div key={label} className="rounded-lg bg-paper p-3"><p className="text-lg font-medium">{Number(value).toLocaleString()}</p><p className="text-[10px] text-ink-soft mt-1">{label}</p></div>)}</div>
        <details className="text-xs mb-3"><summary className="cursor-pointer text-teal">Inspect detected fields</summary><div className="max-h-48 overflow-auto mt-2"><table className="w-full text-left"><thead><tr className="text-ink-soft"><th className="p-1">Field</th><th className="p-1">Type</th><th className="p-1">Missing / invalid</th></tr></thead><tbody>{overview.fields.map((field, i) => <tr key={i} className="border-t border-line"><td className="p-1 break-words">{field.name}</td><td className="p-1">{field.type}</td><td className="p-1">{field.missing}</td></tr>)}</tbody></table></div></details>
      </> : <p className="text-xs text-ink-soft mb-3">Ready for text-based questions. A usable numerical table was not detected.</p>}
      {overview.notes.map((note, i) => <p key={i} className="text-[11px] text-ink-soft mb-2 leading-5">{note}</p>)}
      <p className="text-[10px] uppercase tracking-widest text-teal mt-4 mb-2">Start with a question</p>
      <div className="flex flex-col gap-2">{overview.suggested_questions.map(question => <button key={question} type="button" disabled={disabled} onClick={() => onQuestion(question)} className="text-left text-xs rounded-lg border border-line px-3 py-2 text-teal hover:border-teal disabled:opacity-40">{question} <span aria-hidden="true">→</span></button>)}</div>
      <p className="text-[10px] text-ink-soft mt-2">Selecting a question fills the composer. Review it, then submit.</p>
    </>}
  </section>;
}
