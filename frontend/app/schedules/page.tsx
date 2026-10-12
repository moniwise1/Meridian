"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { listConnections, listDocuments, scheduleRequest, type AnalysisSchedule } from "@/lib/api";

function tomorrow() {
  const date = new Date(); date.setDate(date.getDate() + 1); date.setHours(9, 0, 0, 0);
  return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}T09:00`;
}
export default function SchedulesPage() {
  const [rows, setRows] = useState<AnalysisSchedule[]>([]);
  const [sources, setSources] = useState<{ key: string; label: string }[]>([]);
  const [source, setSource] = useState("");
  const [question, setQuestion] = useState("");
  const [frequency, setFrequency] = useState("weekly");
  const [firstRun, setFirstRun] = useState(tomorrow);
  const [pdf, setPdf] = useState(true);
  const [metric, setMetric] = useState("");
  const [comparison, setComparison] = useState("above");
  const [threshold, setThreshold] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let active = true;
    Promise.allSettled([listConnections(), listDocuments(), scheduleRequest<AnalysisSchedule[]>()]).then(([dbs, files, schedules]) => {
      if (!active) return;
      const options = [...(dbs.status === "fulfilled" ? dbs.value.map(row => ({ key: `conn:${row.id}`, label: `${row.name} · database` })) : []),
        ...(files.status === "fulfilled" ? files.value.map(row => ({ key: `doc:${row.id}`, label: `${row.filename} · upload snapshot` })) : [])];
      setSources(options); setSource(options[0]?.key ?? "");
      if (schedules.status === "fulfilled") setRows(schedules.value);
      else setError(schedules.reason.message);
    });
    return () => { active = false; };
  }, []);
  async function act(action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(true); setError("");
    try { await action(); setRows(await scheduleRequest<AnalysisSchedule[]>()); }
    catch (error) { setError((error as Error).message); }
    finally { setBusy(false); }
  }
  const field = "mt-1 w-full rounded-md border border-line bg-panel px-3 py-2 text-sm";
  return <div className="max-w-4xl mx-auto px-4 sm:px-8 py-10">
    <h1 className="text-2xl font-medium text-ink">Scheduled analyses</h1>
    <p className="text-sm text-ink-soft mt-2 mb-6">Repeat a question about any supported source. Results and PDFs stay private to you. Each run uses your current permissions and counts towards your plan allowances.</p>
    <div className="text-xs text-ink-soft border border-line rounded-lg p-4 mb-6">Database runs query the current records. Uploaded files remain snapshots; re-running an upload does not fetch a newer version. Times below use your device&apos;s timezone. Guaranteed runs while everyone is offline require the scheduled runner to be configured by the platform owner.</div>
    {error && <p role="alert" className="text-sm text-red mb-4">{error}</p>}
    <form className="bg-panel border border-line rounded-xl p-5 mb-8" onSubmit={event => {
      event.preventDefault();
      void act(async () => { await scheduleRequest("", "POST", { source_key: source, question: question.trim(), frequency,
        first_run_at: new Date(firstRun).toISOString(), generate_pdf: pdf,
        ...(metric.trim() ? { alert_metric: metric.trim(), alert_above: comparison, alert_threshold: threshold } : {}) }); setQuestion(""); });
    }}>
      <div className="grid sm:grid-cols-3 gap-4">
        <label className="text-xs text-ink-soft">Source<select className={field} value={source} required disabled={busy} onChange={event => setSource(event.target.value)}><option value="">Choose a source</option>{sources.map(row => <option key={row.key} value={row.key}>{row.label}</option>)}</select></label>
        <label className="text-xs text-ink-soft">Repeat<select className={field} value={frequency} disabled={busy} onChange={event => setFrequency(event.target.value)}><option value="daily">Daily</option><option value="weekly">Weekly</option></select></label>
        <label className="text-xs text-ink-soft">First run<input type="datetime-local" className={field} value={firstRun} required disabled={busy} onChange={event => setFirstRun(event.target.value)} /></label>
      </div>
      <label className="block text-xs text-ink-soft mt-4">Question<textarea className={field} value={question} required maxLength={8000} rows={3} disabled={busy} onChange={event => setQuestion(event.target.value)} placeholder="Compare customer wait times by branch over the past seven days" /></label>
      <label className="flex items-center gap-2 mt-3 text-xs text-ink-soft"><input type="checkbox" checked={pdf} disabled={busy} onChange={event => setPdf(event.target.checked)} />Generate a PDF when the analysis completes</label>
      <details className="mt-4 text-xs text-ink-soft"><summary className="cursor-pointer">Optional metric alert</summary><p className="my-3">Use the exact label of a computed metric from an existing analysis. Alerts fire when a value crosses the threshold; missing or unverified figures do not trigger an alert.</p><div className="grid sm:grid-cols-3 gap-3"><label>Exact metric label<input className={field} value={metric} maxLength={150} disabled={busy} onChange={event => setMetric(event.target.value)} placeholder="Average of Wait" /></label><label>Condition<select className={field} value={comparison} disabled={busy} onChange={event => setComparison(event.target.value)}><option value="above">Above</option><option value="below">Below</option></select></label><label>Threshold<input className={field} type="number" step="any" value={threshold} required={!!metric.trim()} disabled={busy} onChange={event => setThreshold(event.target.value)} placeholder="15" /></label></div></details>
      <button disabled={busy || !source} className="bg-teal-deep text-white rounded-md px-4 py-2 text-sm mt-5 disabled:opacity-40">{busy ? "Saving…" : "Create schedule"}</button>
    </form>
    <div className="flex justify-between items-center mb-4"><h2 className="text-lg text-ink">Your schedules</h2><button disabled={busy} className="text-xs text-teal" onClick={() => void act(() => scheduleRequest("/check-due", "POST"))}>Check due analyses</button></div>
    {!rows.length && <p className="text-sm text-ink-soft">No scheduled analyses yet.</p>}
    <div className="space-y-3">{rows.map(row => <article key={row.id} className="border border-line rounded-lg p-4"><p className="text-sm font-medium text-ink whitespace-pre-wrap">{row.question}</p><p className="text-xs text-ink-soft mt-2">{row.frequency} · {row.enabled ? `Next: ${new Date(row.next_run_at).toLocaleString()}` : "Paused"} · {row.status}</p>{row.last_message && <p className="text-xs text-ink-soft mt-2">{row.last_message}</p>}<div className="flex gap-4 mt-3 text-xs text-teal">{row.last_query_id && <Link href={`/analyses/${row.last_query_id}`}>Open latest analysis</Link>}<button disabled={busy} onClick={() => void act(() => scheduleRequest(`/${row.id}`, "PATCH", { enabled: !row.enabled }))}>{row.enabled ? "Pause" : "Resume"}</button><button disabled={busy || row.status === "running"} onClick={() => void act(() => scheduleRequest(`/${row.id}`, "DELETE"))}>Remove</button></div></article>)}</div>
  </div>;
}
