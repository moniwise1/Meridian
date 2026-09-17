"use client";

import type { AnalystAnalysis, AnalystConfidenceLevel } from "@/lib/analyst";

// The analyst brief. Deliberately ADDITIVE: this renders alongside
// ResultView's existing panels, never instead of them - the bar/pie charts,
// key findings, anomaly list, forecast and SQL viewer all still render
// exactly as they did. What this adds is the part the old view never had:
// the exact computed measures, measurement confidence stated separately
// from explanation confidence, the scope the numbers are actually true
// within, and which source (and which version of it) each figure came from.

function formatCell(value: string | number | null): string {
  // null is "not established", never 0 - see lib/analyst.ts.
  if (value === null) return "Unavailable";
  if (typeof value === "number") return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return value;
}

const LEVEL_STYLES: Record<AnalystConfidenceLevel, string> = {
  high: "text-teal-deep",
  medium: "text-ink",
  low: "text-amber",
  not_assessable: "text-ink-soft",
};

function ComparisonBars({
  rows,
  categoryKey,
  valueKey,
  caption,
}: {
  rows: Record<string, string | number | null>[];
  categoryKey: string;
  valueKey: string;
  caption: string;
}) {
  const shown = rows.slice(0, 12);
  // Math.max of an empty list is -Infinity, and every-value-zero would
  // divide by zero - 1 is the floor either way, which renders as empty
  // bars rather than NaN widths.
  const max = Math.max(1, ...shown.map((r) => Math.abs(Number(r[valueKey]) || 0)));
  return (
    <div
      className="mb-3 flex flex-col gap-2 bg-paper rounded-[3px] p-3"
      aria-label={`${caption}. Exact values are in the table below.`}
    >
      <div className="text-[12px] text-ink-soft">
        {caption} · showing {shown.length} of {rows.length} row(s)
      </div>
      {shown.map((row, i) => {
        const value = Number(row[valueKey]);
        const width = Number.isFinite(value) ? (Math.abs(value) / max) * 100 : 0;
        return (
          <div key={i} className="grid grid-cols-[minmax(0,1fr)_2fr_auto] items-center gap-2 text-[12px]">
            <span className="truncate" title={String(row[categoryKey] ?? "")}>
              {formatCell(row[categoryKey])}
            </span>
            <div className="h-2 rounded-full bg-line">
              <div
                className={`h-2 rounded-full ${value < 0 ? "bg-amber" : "bg-teal"}`}
                style={{ width: `${width}%` }}
              />
            </div>
            <span className="tabular-nums text-ink">{formatCell(row[valueKey])}</span>
          </div>
        );
      })}
    </div>
  );
}

export default function AnalystAnswer({ analysis }: { analysis: AnalystAnalysis }) {
  const { scope, quality, confidence } = analysis;
  // "metric_table" exists so a query with no group axis still produces a
  // structured table for the exports - on screen the measure cards above
  // already say the same thing, so it would just be the same four numbers
  // twice.
  const tables = analysis.tables.filter((t) => t.id !== "metric_table");
  const scopeNotes = [...scope.assumptions, ...quality.limitations];

  return (
    <section className="bg-panel border border-line rounded-[4px] p-5 flex flex-col gap-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="text-[11px] font-medium uppercase tracking-wider text-teal">
          Analyst brief · {analysis.status.replaceAll("_", " ")}
        </div>
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-[12px]">
          {(["measurement", "explanation"] as const).map((name) => (
            <div key={name} title={confidence[name].reason}>
              <span className="text-ink-soft capitalize">{name}: </span>
              <span className={LEVEL_STYLES[confidence[name].level]}>
                {confidence[name].level.replaceAll("_", " ")}
              </span>
            </div>
          ))}
        </div>
      </div>

      {analysis.metrics.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {analysis.metrics.map((m) => (
            <div key={m.id} className="bg-paper rounded-[3px] p-3">
              <div className="text-[12px] text-ink-soft">{m.label}</div>
              <div className="mt-1 text-[17px] tabular-nums text-ink break-words">
                {formatCell(m.value)}
                {m.unit && <span className="ml-1 text-[12px] text-ink-soft">{m.unit}</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      {tables.map((table) => {
        const chart = analysis.charts.find((c) => c.table_id === table.id);
        const valueKey = chart?.value_keys[0];
        return (
          <div key={table.id}>
            <div className="text-[13px] text-ink-soft mb-2">{table.title}</div>
            {chart && valueKey && (
              <ComparisonBars
                rows={table.rows}
                categoryKey={chart.category_key}
                valueKey={valueKey}
                caption={chart.type === "line" ? "Trend by period" : "Comparison"}
              />
            )}
            <div className="max-h-80 overflow-auto border border-line rounded-[3px]">
              <table className="w-full text-left text-[12.5px]">
                <caption className="sr-only">{table.title}</caption>
                <thead className="sticky top-0 bg-paper">
                  <tr>
                    {table.columns.map((c) => (
                      <th key={c.key} scope="col" className="p-2.5 font-medium text-ink-soft">
                        {c.label}
                        {c.unit && <span className="ml-1 font-normal">({c.unit})</span>}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {table.rows.map((row, i) => (
                    <tr key={i} className="border-t border-line">
                      {table.columns.map((c) => (
                        <td
                          key={c.key}
                          className={`p-2.5 text-ink ${c.type === "number" ? "tabular-nums" : ""}`}
                        >
                          {formatCell(row[c.key])}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}

      <details className="text-[12.5px]" open={quality.limitations.length > 0}>
        <summary className="cursor-pointer text-ink-soft hover:text-ink transition-colors">
          Scope and limitations
        </summary>
        <div className="mt-2 text-ink-soft">
          {scope.metric_definition ?? "The metric definition was not independently established."}
        </div>
        {scopeNotes.length > 0 && (
          <ul className="mt-2 flex flex-col gap-1 text-amber list-disc pl-4">
            {scopeNotes.map((note, i) => (
              <li key={i}>{note}</li>
            ))}
          </ul>
        )}
        <div className="mt-2 text-ink-soft">
          {confidence.measurement.reason} {confidence.explanation.reason}
        </div>
      </details>

      <details className="text-[12.5px]">
        <summary className="cursor-pointer text-ink-soft hover:text-ink transition-colors">
          Sources and calculation references
        </summary>
        <div className="mt-2 flex flex-col gap-2">
          {analysis.evidence.map((e) => (
            <div
              key={e.id}
              className="bg-paper rounded-[3px] p-2.5 break-all font-[family-name:var(--font-mono)] text-[11.5px] text-ink-soft"
            >
              <div className="text-ink">{e.filename ?? e.source_id}</div>
              <div>
                {e.method.replaceAll("_", " ")} · calculation {e.computation_id}
                {e.source_version && ` · version ${e.source_version}`}
              </div>
              {e.location && <div>{e.location}</div>}
            </div>
          ))}
        </div>
      </details>
    </section>
  );
}
