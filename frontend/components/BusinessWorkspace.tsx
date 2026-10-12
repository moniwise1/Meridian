"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listDocuments, getOverviewColumns, getOverview, businessViewRequest, type BusinessSavedView, type DocumentSummary } from "@/lib/api";
import { loadSession } from "@/lib/auth";
import { useAccountType } from "@/lib/useAccountType";
import DashboardIcon from "@/components/DashboardIcon";
import type { Overview, OverviewInput } from "@/lib/overview";

function calendarDay(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function initialInput(): OverviewInput {
  const now = new Date();
  return { document_id: "", sheet: 0, date_column: "", revenue_column: null, expense_column: null,
    currency_column: null, currency: "", include_duplicates: false,
    start: calendarDay(new Date(now.getFullYear(), now.getMonth(), 1)), end: calendarDay(now) };
}
function amount(value: string | null, currency: string) {
  if (value === null) return "Unavailable";
  const [whole, fraction = "00"] = value.replace(/^-/, "").split(".");
  return `${currency} ${value.startsWith("-") ? "−" : ""}${BigInt(whole).toLocaleString()}.${fraction}`;
}

export default function BusinessWorkspace({ view = "overview" }: { view?: "overview" | "financial" | "performance" }) {
  const title = view === "financial" ? "Financial Analytics" : view === "performance" ? "Sales & Performance" : "Executive Overview";
  const account = useAccountType();
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [columns, setColumns] = useState<string[]>([]);
  const [input, setInput] = useState(initialInput);
  const [result, setResult] = useState<Overview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [question, setQuestion] = useState("");
  const [savedViews, setSavedViews] = useState<BusinessSavedView[]>([]);
  const [canManage, setCanManage] = useState(false);
  const [viewName, setViewName] = useState("");

  useEffect(() => {
    if (account !== "business") return;
    let live = true;
    businessViewRequest<{ can_manage: boolean; views: BusinessSavedView[] }>().then(data => {
      if (live) { setSavedViews(data.views); setCanManage(data.can_manage); }
    }).catch(error => { if (live) setError(error.message); });
    listDocuments().then((rows) => { if (live) {
      const available = rows.filter(d => ["csv", "xlsx"].includes(d.kind));
      setDocuments(available);
      const session = loadSession();
      try {
        const saved = JSON.parse(sessionStorage.getItem("meridian_business_mapping:" + session?.tenantId + ":" + session?.userId) || "null") as OverviewInput | null;
        if (saved && available.some(d => d.id === saved.document_id)) setInput(saved);
      } catch { /* Missing or obsolete local preferences do not block a new mapping. */ }
    } })
      .catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [account]);
  useEffect(() => {
    if (!input.document_id || account !== "business") return;
    let live = true;
    getOverviewColumns(input.document_id, input.sheet).then(data => { if (live) setColumns(data.columns); })
      .catch(e => { if (live) setError(e.message); });
    return () => { live = false; };
  }, [input.document_id, input.sheet, account]);

  function update<K extends keyof OverviewInput>(key: K, value: OverviewInput[K]) {
    setInput(prev => ({ ...prev, [key]: value })); setResult(null); setError("");
    if (key === "group_column") setInput(prev => ({ ...prev, group_value: null }));
    if (key === "document_id" || key === "sheet") {
      setColumns([]);
      setInput(prev => ({ ...prev, date_column: "", revenue_column: null, expense_column: null, currency_column: null, group_column: null, group_value: null }));
    }
  }
  async function calculate(ask?: string, detailDate?: string) {
    if (busy) return;
    setBusy(true); setError("");
    try {
      setResult(await getOverview({ ...input, question: ask, detail_date: detailDate, rank_by: view === "financial" ? "expenses" : "revenue" }));
      const session = loadSession();
      try { sessionStorage.setItem("meridian_business_mapping:" + session?.tenantId + ":" + session?.userId, JSON.stringify(input)); }
      catch { /* Browser storage restrictions do not invalidate a successful calculation. */ }
    }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const selectClass = "mt-1 w-full bg-panel border border-line rounded-md px-3 py-2 text-sm";
  function columnPicker(label: string, key: "date_column" | "revenue_column" | "expense_column" | "currency_column" | "group_column", required = false) {
    return <label className="text-xs text-ink-soft">{label}
      <select className={selectClass} value={input[key] ?? ""} disabled={busy || !columns.length} required={required}
        onChange={e => update(key, e.target.value || (key === "date_column" ? "" : null))}>
        <option value="">{required ? "Select a column" : "Not mapped"}</option>
        {columns.map(c => <option key={c} value={c}>{c}</option>)}
      </select>
    </label>;
  }
  if (account === null) return <p className="p-8 text-ink-soft">Checking workspace access…</p>;
  if (account !== "business") return <div className="p-8"><h1 className="text-xl">Business workspace</h1><p className="mt-2">These analytics workspaces are available to business accounts.</p><Link href="/" className="text-teal">Return to Ask Meridian</Link></div>;

  return <div className="max-w-[1440px] mx-auto p-4 sm:p-6 lg:p-7 text-ink">
    <div className="dashboard-greeting flex flex-wrap justify-between items-center gap-4 p-5 mb-5">
      <div><p className="text-xs uppercase tracking-widest text-teal mb-2">Business intelligence</p><h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="text-sm text-ink-soft mt-2">A clear view of your mapped revenue and expenses, with every figure linked to its source.</p></div>
      <Link href="/documents" className="border border-line rounded-md px-4 py-2 text-sm">Upload data</Link>
    </div>
    {!documents.length && <div className="border border-line rounded-lg p-6 mb-6"><p>Start with a CSV or Excel table containing dates and monetary amounts.</p><p className="text-sm text-ink-soft mt-2">Dates should use YYYY-MM-DD. Keep currencies separate. Nothing is assumed or filled with sample data.</p></div>}
    <section className="border border-line rounded-lg p-4 mb-4">
      <label className="text-xs text-ink-soft">Company reporting views<select className={selectClass} defaultValue="" disabled={busy} onChange={event => { const saved = savedViews.find(view => view.id === event.target.value); if (saved) { if (input.document_id !== saved.mapping.document_id || input.sheet !== saved.mapping.sheet) setColumns([]); setInput(saved.mapping); setResult(null); setError(""); } }}><option value="">Choose a saved view</option>{savedViews.map(view => <option key={view.id} value={view.id}>{view.name}</option>)}</select></label>
      {canManage && <div className="flex flex-wrap items-center gap-2 mt-3"><input aria-label="Company reporting view name" maxLength={100} className="border border-line bg-panel rounded-md p-2 text-xs flex-1" placeholder="Name this reporting view" value={viewName} disabled={busy} onChange={event => setViewName(event.target.value)} /><button type="button" disabled={busy || !viewName.trim() || !input.document_id} className="text-xs text-teal disabled:opacity-40" onClick={async () => { setBusy(true); setError(""); try { await businessViewRequest("", "POST", { name: viewName.trim(), mapping: input }); const data = await businessViewRequest<{ views: BusinessSavedView[] }>(); setSavedViews(data.views); setViewName(""); } catch (error) { setError((error as Error).message); } finally { setBusy(false); } }}>Save for the company</button></div>}
      <p className="text-xs text-ink-soft mt-2">Saved mappings and dates can be reused across the company. Each calculation still applies your current source and row permissions.</p>
      {canManage && savedViews.length > 0 && <details className="text-xs text-ink-soft mt-2"><summary className="cursor-pointer">Manage saved views</summary>{savedViews.map(view => <div className="flex justify-between gap-2 mt-2" key={view.id}><span>{view.name}</span><button disabled={busy} className="text-teal" onClick={async () => { setBusy(true); try { await businessViewRequest(`/${view.id}`, "DELETE"); setSavedViews(previous => previous.filter(item => item.id !== view.id)); } catch (error) { setError((error as Error).message); } finally { setBusy(false); } }}>Remove</button></div>)}</details>}
    </section>
    <form onSubmit={e => { e.preventDefault(); void calculate(); }} className="bg-panel border border-line rounded-xl p-5 mb-6">
      <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <label className="text-xs text-ink-soft">Source document<select required className={selectClass} value={input.document_id} disabled={busy} onChange={e => update("document_id", e.target.value)}><option value="">Choose an upload</option>{documents.map(d => <option key={d.id} value={d.id}>{d.filename}</option>)}</select></label>
        <label className="text-xs text-ink-soft">Excel sheet number<input className={selectClass} type="number" min={1} max={100} value={input.sheet + 1} disabled={busy} onChange={e => update("sheet", Number(e.target.value) - 1)} /></label>
        <label className="text-xs text-ink-soft">From<input required type="date" className={selectClass} value={input.start} disabled={busy} onChange={e => update("start", e.target.value)} /></label>
        <label className="text-xs text-ink-soft">Through<input required type="date" className={selectClass} value={input.end} disabled={busy} onChange={e => update("end", e.target.value)} /></label>
        {columnPicker("Transaction date", "date_column", true)}{columnPicker("Revenue amount", "revenue_column")}{columnPicker("Expense amount", "expense_column")}{columnPicker("Currency column (optional)", "currency_column")}{columnPicker(view === "financial" ? "Expense category (optional)" : "Product / branch / region (optional)", "group_column")}
        <label className="text-xs text-ink-soft">Confirm source currency<input required pattern="[A-Za-z]{3}" maxLength={3} placeholder="e.g. NGN" className={selectClass} value={input.currency} disabled={busy} onChange={e => update("currency", e.target.value.toUpperCase())} /></label>
      </div>
      <div className="mt-4 flex flex-wrap justify-between items-center gap-4"><label className="text-xs text-ink-soft flex items-center gap-2"><input type="checkbox" checked={input.include_duplicates} disabled={busy} onChange={e => update("include_duplicates", e.target.checked)} />I have verified that repeated rows are legitimate</label>
        <button disabled={busy || !columns.length} className="bg-teal-deep text-white rounded-md px-5 py-2 text-sm disabled:opacity-40">{busy ? "Calculating…" : "Update overview"}</button></div>
      <p className="text-xs text-ink-soft mt-3">Amounts must be plain numbers. These mappings define this view; missing values remain unavailable.</p>
    </form>
    {error && <div role="alert" className="border border-red text-red rounded-lg p-4 mb-6">{error}</div>}
    {result && <>
      <div className="text-xs text-ink-soft mb-4">{result.source.filename} · Sheet {result.source.sheet + 1} · Uploaded {new Date(result.source.uploaded_at).toLocaleString()} · Calculated {new Date(result.generated_at).toLocaleString()}<br />{result.period.start} – {result.period.end} · {result.record_count} records · Previous: {result.previous_period.start} – {result.previous_period.end}</div>
      <div className="grid sm:grid-cols-3 gap-3 mb-5">{result.metrics.map((m, index) => <article key={m.id} className="dashboard-card p-4"><div className="flex items-center gap-2.5"><span className={index === 1 ? "bg-gold-soft text-amber p-2 rounded-full" : "bg-mint-soft text-teal p-2 rounded-full"}><DashboardIcon name="chart" size={16} /></span><h2 className="text-xs text-ink-soft">{m.label}</h2></div><p className="text-[25px] font-semibold mt-3 tabular-nums break-words">{amount(m.value, result.currency)}</p><p className="text-xs mt-3 text-ink-soft">{m.change_pct !== null ? `${m.change_pct}% vs previous period` : "Comparison unavailable"}</p><details className="text-xs mt-3"><summary className="cursor-pointer text-teal">Calculation</summary><p className="mt-2">{m.formula}</p>{m.unavailable_reason && <p>{m.unavailable_reason}</p>}</details></article>)}</div>
      {result.group_column && <section className="bg-panel border border-line rounded-xl p-5 mb-6">
        <h2 className="text-lg mb-2">{view === "financial" ? "Expense categories" : "Performance breakdown"} · {result.group_column}</h2>
        <p className="text-xs text-ink-soft mb-4">{result.group_filter ? "Filtered to: " + result.group_filter : "All authorized groups"}. {result.breakdown_truncated ? "Showing the top 100 groups; totals include all groups." : "All groups shown."}</p>
        {result.group_filter && <button disabled={busy} className="text-xs text-teal mb-4" onClick={() => update("group_value", null)}>Clear group filter</button>}
        <div className="overflow-auto"><table className="w-full text-sm text-left"><thead><tr><th>Group</th><th>Records</th><th>Revenue</th><th>Expenses</th><th>Explore</th></tr></thead><tbody>{result.breakdown.map((g, i) => <tr key={i} className="border-t border-line"><td className="py-3">{g.group ?? "(No group value)"}</td><td>{g.row_count}</td><td>{amount(g.revenue, result.currency)}</td><td>{amount(g.expenses, result.currency)}</td><td>{g.group !== null && <button className="text-teal text-xs" onClick={() => update("group_value", g.group)} disabled={busy}>Filter this group</button>}</td></tr>)}</tbody></table></div>
        <p className="text-xs text-ink-soft mt-3">Choose a group, then update the workspace. Metrics and Ask answers use the same filter.</p>
      </section>}
      {view === "financial" && <section className="border border-line rounded-xl p-5 mb-6"><h2 className="text-lg mb-2">Accounting scope</h2><p className="text-sm text-ink-soft">These are mapped income and expense measures. Gross profit needs a confirmed cost-of-sales classification; net profit needs complete recognized income and costs; cash flow needs cash transaction records. Those measures remain unavailable until their inputs and definitions are established.</p></section>}
      <section className="bg-panel border border-line rounded-xl p-5 mb-6">
        <div className="flex flex-wrap justify-between gap-2"><h2 className="text-lg">Revenue over the selected period</h2><p className="text-xs text-ink-soft">Select a bar to inspect that day&apos;s records</p></div>
        {result.trend.some(t => t.revenue !== null) ? <div className="mt-4 overflow-x-auto"><svg role="img" aria-label="Daily revenue; activate a bar to inspect its records" viewBox={`0 0 ${Math.max(600, result.trend.length * 24)} 180`} className="w-full min-w-[600px] h-48">
          <title>Revenue in {result.currency} by day</title>
          {(() => {
            const width = Math.max(600, result.trend.length * 24);
            const values = result.trend.map(t => Number(t.revenue ?? 0));
            const min = Math.min(0, ...values), max = Math.max(0, ...values), span = max - min || 1;
            const y = (v: number) => 145 - ((v - min) / span) * 120;
            const zero = y(0), step = (width - 40) / Math.max(1, values.length);
            return <><line x1={20} x2={width - 20} y1={zero} y2={zero} stroke="currentColor" opacity={0.25} />{result.trend.map((t, i) => t.revenue === null ? null : <g key={t.date} role="button" tabIndex={busy ? -1 : 0} aria-label={`${t.date}: ${amount(t.revenue, result.currency)}. Inspect records.`} onClick={() => { if (!busy) void calculate(undefined, t.date); }} onKeyDown={e => { if (!busy && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); void calculate(undefined, t.date); } }} className="cursor-pointer text-teal focus:outline-teal">
              <title>{t.date}: {amount(t.revenue, result.currency)}</title><rect x={20 + i * step} y={Math.min(zero, y(values[i]))} width={Math.max(2, step - 6)} height={Math.max(2, Math.abs(zero - y(values[i])))} fill="currentColor" opacity={result.detail_date === t.date ? 1 : 0.65} />{(i === 0 || i === values.length - 1 || values.length <= 12) && <text x={20 + i * step} y={170} fontSize={10} fill="currentColor">{t.date.slice(5)}</text>}
            </g>)}</>;
          })()}
        </svg></div> : <p className="text-sm text-ink-soft mt-3">A complete revenue mapping and period records are needed for this chart.</p>}
        <p className="text-xs text-ink-soft mt-2">Missing amounts are omitted. Negative amounts extend below the zero line. Exact figures appear in Daily performance.</p>
      </section>
      <div className="grid lg:grid-cols-2 gap-6 mb-6">
        <section className="bg-panel border border-line rounded-xl p-5"><h2 className="text-lg mb-4">Daily performance</h2><div className="max-h-80 overflow-auto"><table className="w-full text-sm text-left"><thead><tr className="text-ink-soft"><th className="py-2">Date</th><th>Revenue</th><th>Expenses</th></tr></thead><tbody>{result.trend.map(t => <tr key={t.date} className="border-t border-line"><td className="py-2">{t.date}</td><td>{amount(t.revenue, result.currency)}</td><td>{amount(t.expenses, result.currency)}</td></tr>)}</tbody></table>{!result.trend.length && <p className="text-sm text-ink-soft">No records in this period.</p>}</div></section>
        <section className="bg-teal-deep text-white rounded-xl p-5"><p className="text-xs uppercase tracking-widest opacity-70">Ask Meridian</p><h2 className="text-xl mt-2">Understand these figures</h2><p className="text-sm opacity-80 mt-2">Answers use the same source, mappings and reporting dates as this overview.</p><div className="flex flex-wrap gap-2 my-4">{["Compare revenue with the previous period", "What are our mapped expenses?", ...(result.group_column ? [view === "financial" ? "Which category has the highest expenses?" : "Which group has the highest revenue?"] : ["What is revenue less mapped expenses?"])].map(q => <button key={q} disabled={busy} onClick={() => { setQuestion(q); void calculate(q); }} className="border border-white/30 rounded-full px-3 py-1 text-xs disabled:opacity-40">{q}</button>)}</div><form onSubmit={e => { e.preventDefault(); void calculate(question); }} className="flex gap-2"><input aria-label="Question about this overview" className="min-w-0 flex-1 rounded-md bg-white/10 border border-white/30 p-2 text-sm" maxLength={1000} value={question} onChange={e => setQuestion(e.target.value)} placeholder="Ask about mapped revenue or expenses" /><button disabled={busy || !question.trim()} className="rounded-md bg-white text-teal-deep px-3 disabled:opacity-40">Ask</button></form>{result.answer && <p role="status" className="text-sm leading-relaxed mt-4">{result.answer}</p>}</section>
      </div>
      <details className="bg-panel border border-line rounded-xl p-5 mb-6"><summary className="cursor-pointer">Inspect source records ({result.detail_count}){result.detail_date ? ` · ${result.detail_date}` : ""}</summary>{result.detail_date && <button onClick={() => void calculate()} disabled={busy} className="text-xs text-teal mt-3">Show all period records</button>}<p className="text-xs text-ink-soft my-3">Original spreadsheet row numbers. {result.records_truncated ? "Showing the first 100 matching records; KPIs use all authorized period records." : "All period records shown."}</p><div className="overflow-auto"><table className="w-full text-sm text-left"><thead><tr><th>Source row</th><th>Date</th><th>Revenue</th><th>Expenses</th></tr></thead><tbody>{result.records.map(r => <tr key={r.source_row} className="border-t border-line"><td className="py-2">{r.source_row}</td><td>{r.date}</td><td>{amount(r.revenue, result.currency)}</td><td>{amount(r.expenses, result.currency)}</td></tr>)}</tbody></table></div></details>
      <div className="text-xs text-ink-soft leading-relaxed"><p className="font-medium mb-2">Scope and limitations</p>{result.limitations.map(l => <p key={l}>• {l}</p>)}</div>
    </>}
  </div>;
}
