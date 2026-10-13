"use client";
import type { AnalystAnalysis, AnalystTable, AnalystChart } from "@/lib/analyst";
const number = (value: string | number | null | undefined) => value == null ? "Unavailable" : typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 3 }) : value;

function FindingChart({ table, chart }: { table: AnalystTable; chart: AnalystChart }) {
  const key = chart.value_keys[0];
  const shown = table.rows.slice(0, 12);
  const finite = shown.map(row => row[key]).filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  const min = Math.min(0, ...finite), max = Math.max(0, ...finite), range = max - min || 1;
  const zero = -min / range * 100;
  const unit = table.columns.find(column => column.key === key)?.unit;
  const points = shown.map((row, i) => ({
    x: 30 + i * 500 / Math.max(1, shown.length - 1),
    y: typeof row[key] === "number" ? 150 - (Number(row[key]) - min) / range * 120 : null,
    label: String(row[chart.category_key] ?? "Unavailable"), value: row[key],
  }));
  const segments: string[][] = [[]];
  points.forEach(point => { if (point.y === null) segments.push([]); else segments[segments.length - 1].push(`${point.x},${point.y}`); });
  return <div className="rounded-xl bg-paper p-4" aria-label={chart.title}>
    <div className="flex flex-wrap justify-between gap-2 text-[11px] text-ink-soft mb-4"><span>{chart.type === "line" ? "Trend" : "Comparison"}{unit ? ` · ${unit}` : ""}</span><span>Showing {shown.length} of {table.rows.length} groups · values rounded for display</span></div>
    {chart.type === "line" ? <>
      <svg viewBox="0 0 560 175" className="w-full" role="img" aria-label={`${chart.title}. Values available below.`}>
        <line x1="30" x2="530" y1={150 - zero / 100 * 120} y2={150 - zero / 100 * 120} stroke="var(--line)" />
        {segments.filter(segment => segment.length > 1).map((segment, i) => <polyline key={i} points={segment.join(" ")} fill="none" stroke="var(--teal)" strokeWidth="3" />)}
        {points.map((point, i) => point.y === null ? null : <circle key={i} cx={point.x} cy={point.y} r="4" fill="var(--teal-deep)"><title>{point.label}: {number(point.value)} {unit ?? ""}</title></circle>)}
        <text x="3" y="30" fontSize="10" fill="var(--ink-soft)">{number(max)}</text><text x="3" y="150" fontSize="10" fill="var(--ink-soft)">{number(min)}</text>
      </svg><div className="flex justify-between text-[10px] text-ink-soft gap-2">{points.map((point, i) => <span key={i} className="truncate" title={point.label}>{point.label}</span>)}</div>
    </> : <div className="space-y-3">{shown.map((row, i) => {
      const value = typeof row[key] === "number" ? Number(row[key]) : null;
      return <div key={i} className="grid grid-cols-[minmax(65px,1fr)_2fr_auto] gap-3 items-center text-xs"><span className="truncate" title={String(row[chart.category_key])}>{number(row[chart.category_key])}</span><div className="h-5 bg-line/30 rounded relative"><span className="absolute top-0 bottom-0 border-l border-ink-soft/40" style={{left:`${zero}%`}} />{value !== null && <span className={`absolute h-5 rounded ${value < 0 ? "bg-amber" : "bg-teal"}`} style={{left:`${Math.min(zero, (value-min)/range*100)}%`,width:`${Math.abs(value)/range*100}%`}} />}</div><span className="tabular-nums text-right">{number(value)}{value !== null && unit ? ` ${unit}` : ""}</span></div>;
    })}</div>}
  </div>;
}

export default function AnalystAnswer({ analysis, onFollowUp, disabled = false }: {
  analysis: AnalystAnalysis; onFollowUp?: (question: string) => void; disabled?: boolean;
}) {
  const tables = analysis.tables.filter(table => table.id !== "metric_table");
  const limitations = [...new Set([...analysis.scope.assumptions, ...analysis.quality.limitations])];
  const sourceNames = [...new Set(analysis.evidence.map(e => e.filename ?? e.source_id))];
  function evidence(ids: string[]) {
    return analysis.evidence.filter(e => ids.includes(e.id)).map(e => <div key={e.id} className="mt-2 rounded-lg bg-paper p-3 text-[11px] leading-5 break-words"><p className="font-medium text-ink">{e.filename ?? e.source_id}</p><p>{e.method === "computed" ? "Computed from authorized records" : "Extracted source text"}</p>{e.location && <p>{e.location}</p>}<p className="text-ink-soft">Reference {e.computation_id}{e.source_version ? ` · version ${e.source_version}` : ""}</p></div>);
  }
  return <section className="rounded-2xl border border-line bg-panel overflow-hidden">
    <div className="bg-mint-soft/40 border-b border-line p-5 sm:p-6"><div className="flex flex-wrap justify-between items-center gap-2 mb-4"><span className="text-[10px] uppercase tracking-[0.16em] text-teal">Meridian findings</span><span className="text-[10px] rounded-full bg-panel border border-line px-2.5 py-1 text-ink-soft">{analysis.status.replaceAll("_", " ")}</span></div><h2 className="text-lg sm:text-xl font-medium leading-relaxed tracking-tight">{analysis.headline}</h2>{analysis.summary && <p className="text-sm text-ink-soft mt-3 leading-6 whitespace-pre-wrap">{analysis.summary}</p>}<p className="text-[11px] text-ink-soft mt-4 break-words">{sourceNames.join(" · ") || "Source not established"}</p></div>
    <div className="p-5 sm:p-6 space-y-6">
      {!!analysis.metrics.length && <div className="grid grid-cols-2 gap-3">{analysis.metrics.map(metric => <div key={metric.id} className="rounded-xl border border-line p-4"><p className="text-[11px] text-ink-soft">{metric.label}</p><p className="text-2xl font-medium mt-2 tabular-nums break-words">{number(metric.value)}<span className="text-sm ml-1">{metric.unit}</span></p><details className="mt-3 text-[11px] text-teal"><summary className="cursor-pointer">Inspect calculation</summary>{evidence(metric.evidence_ids)}</details></div>)}</div>}
      {tables.map(table => {const chart = analysis.charts.find(chart => chart.table_id === table.id);return <div key={table.id}><h3 className="text-sm font-medium mb-3">{table.title}</h3>{chart && <FindingChart table={table} chart={chart} />}<details className="mt-3 text-xs"><summary className="cursor-pointer text-teal">View values and source</summary><div className="overflow-auto max-h-72 mt-3"><table className="w-full text-left"><caption className="sr-only">{table.title}</caption><thead><tr>{table.columns.map(column => <th key={column.key} scope="col" className="p-2 bg-paper font-medium">{column.label}{column.unit ? ` (${column.unit})` : ""}</th>)}</tr></thead><tbody>{table.rows.map((row,i) => <tr key={i} className="border-t border-line">{table.columns.map(column => <td key={column.key} className="p-2 tabular-nums">{number(row[column.key])}</td>)}</tr>)}</tbody></table></div>{evidence(table.evidence_ids)}</details></div>;})}
      {!!analysis.findings.length && <div><h3 className="text-sm font-medium mb-3">What deserves attention</h3><div className="space-y-3">{analysis.findings.map(finding => <div key={finding.id} className="rounded-xl border border-line p-4"><p className={`text-[10px] uppercase tracking-wider mb-2 ${finding.kind === "hypothesis" ? "text-amber" : "text-teal"}`}>{finding.kind === "hypothesis" ? "Interpretation · verify before acting" : finding.kind}</p><p className="text-sm leading-6">{finding.text}</p><details className="mt-2 text-[11px] text-teal"><summary className="cursor-pointer">Supporting source</summary>{evidence(finding.evidence_ids)}</details></div>)}</div></div>}
      <div className="rounded-xl bg-gold-soft/40 border border-line p-4"><h3 className="text-sm font-medium mb-2">Before you decide</h3><div className="grid sm:grid-cols-2 gap-3 mb-3">{(["measurement","explanation"] as const).map(kind => <div key={kind}><p className="text-[11px] text-ink-soft capitalize">{kind} confidence: {analysis.confidence[kind].level.replaceAll("_"," ")}</p><p className="text-[11px] leading-5 mt-1">{analysis.confidence[kind].reason}</p></div>)}</div>{analysis.scope.metric_definition && <p className="text-xs leading-5">{analysis.scope.metric_definition}</p>}<details className="mt-2 text-xs"><summary className="cursor-pointer text-teal">Scope and data-quality notes ({limitations.length})</summary><ul className="list-disc pl-4 space-y-2 mt-3 text-ink-soft">{limitations.map((note,i) => <li key={i}>{note}</li>)}</ul></details></div>
      {(analysis.actions.length > 0 || analysis.follow_ups.length > 0) && <div><h3 className="text-sm font-medium mb-3">Continue the investigation</h3>{analysis.actions.map((action,i) => <p key={i} className="text-xs text-ink-soft leading-5 mb-3"><span className="font-medium text-ink">{action.label}.</span> {action.reason}</p>)}{onFollowUp && <div className="flex flex-col gap-2">{analysis.follow_ups.map((followUp,i) => <button key={i} type="button" disabled={disabled} onClick={() => onFollowUp(followUp.question)} className="text-left rounded-xl border border-teal/30 p-3 text-xs text-teal hover:bg-mint-soft disabled:opacity-40">{followUp.label} →</button>)}</div>}</div>}
      <details className="text-xs text-ink-soft"><summary className="cursor-pointer text-teal">All sources and calculation references</summary>{evidence(analysis.evidence.map(e=>e.id))}</details>
    </div>
  </section>;
}
