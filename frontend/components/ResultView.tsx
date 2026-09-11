"use client";

import { useState } from "react";
import type { ResultEvent, Investigation, Forecast } from "@/lib/api";
import ArtifactActions from "@/components/ArtifactActions";

function ConfidenceBadge({ level }: { level: string }) {
  const styles: Record<string, string> = {
    high: "bg-teal-deep text-white",
    moderate: "bg-amber-soft text-amber",
    low: "bg-line text-ink-soft",
  };
  return (
    <span className={`text-[11px] px-2 py-0.5 rounded-[3px] ${styles[level] ?? styles.low}`}>
      {level} confidence
    </span>
  );
}

function GroupBars({ data }: { data: { group: string; total: number }[] }) {
  const max = Math.max(...data.map((d) => d.total), 1);
  return (
    <div className="flex flex-col gap-2">
      {data.slice(0, 8).map((d) => (
        <div key={d.group} className="flex items-center gap-3">
          <div className="w-28 text-[12.5px] text-ink-soft truncate shrink-0">{d.group}</div>
          <div className="flex-1 h-4 bg-paper rounded-[2px] overflow-hidden">
            <div
              className="h-full bg-slate rounded-[2px]"
              style={{ width: `${(d.total / max) * 100}%` }}
            />
          </div>
          <div className="w-24 text-right text-[12px] font-[family-name:var(--font-mono)] text-ink-soft shrink-0">
            {d.total.toLocaleString(undefined, { maximumFractionDigits: 0 })}
          </div>
        </div>
      ))}
    </div>
  );
}

// Cycles through the app's existing brand tokens rather than introducing
// new colors - fine up to 8 slices (GroupBars' own display cap, so the
// two always describe the same groups) before a color repeats.
const PIE_COLORS = ["var(--teal)", "var(--teal-deep)", "var(--slate)", "var(--amber)", "var(--red)", "var(--ink-soft)"];

// A dependency-free pie chart (a CSS conic-gradient circle plus a legend)
// - no charting library exists anywhere in this codebase, consistent with
// GroupBars above and the platform analytics dashboard's own bar charts.
// Negative totals (a "loss" figure some questions produce) can't be
// represented as a pie slice, so they're clamped to zero here rather than
// producing a nonsensical negative-angle slice; the bar chart above still
// shows the true signed value.
function PieChart({ data }: { data: { group: string; total: number }[] }) {
  const slices = data.slice(0, 8);
  const total = slices.reduce((sum, d) => sum + Math.max(0, d.total), 0);
  if (total <= 0) return null;

  // Cumulative slice totals (bounds[i] = sum of slices 0..i), built by
  // pushing to a local array rather than reassigning a `let` across
  // .map() calls - the latter is flagged by React's render-purity rule.
  const bounds: number[] = [];
  slices.forEach((d) => bounds.push((bounds[bounds.length - 1] ?? 0) + Math.max(0, d.total)));
  const stops = slices.map((d, i) => {
    const start = ((i === 0 ? 0 : bounds[i - 1]) / total) * 360;
    const end = (bounds[i] / total) * 360;
    return `${PIE_COLORS[i % PIE_COLORS.length]} ${start}deg ${end}deg`;
  });

  return (
    <div className="flex items-center gap-6">
      <div
        className="w-28 h-28 rounded-full shrink-0"
        style={{ background: `conic-gradient(${stops.join(", ")})` }}
      />
      <div className="flex flex-col gap-1.5 min-w-0 flex-1">
        {slices.map((d, i) => (
          <div key={d.group} className="flex items-center gap-2 text-[12px]">
            <span
              className="w-2.5 h-2.5 rounded-full shrink-0"
              style={{ background: PIE_COLORS[i % PIE_COLORS.length] }}
            />
            <span className="text-ink truncate">{d.group}</span>
            <span className="text-ink-soft shrink-0 ml-auto tabular-nums">
              {((Math.max(0, d.total) / total) * 100).toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// Dependency-free line chart (a plain SVG polyline) - the "line" option
// alongside GroupBars/PieChart above for a v2 document-only chart (see
// insight_agent.py's render_chart tool) whose chart_type is "line",
// typically a time-based trend. No charting library exists anywhere in
// this codebase (see PieChart's own comment) - this follows the same
// convention rather than introducing one for a single chart type.
function LineChart({ labels, values }: { labels: string[]; values: number[] }) {
  const points = labels.map((label, i) => ({ label, value: values[i] ?? 0 })).slice(0, 20);
  if (points.length === 0) return null;
  const width = 560;
  const height = 140;
  const pad = 24;
  const max = Math.max(...points.map((p) => p.value), 1);
  const min = Math.min(...points.map((p) => p.value), 0);
  const range = max - min || 1;
  const stepX = (width - pad * 2) / Math.max(points.length - 1, 1);
  const coords = points.map((p, i) => ({
    x: pad + i * stepX,
    y: height - pad - ((p.value - min) / range) * (height - pad * 2),
  }));

  return (
    <div className="overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full max-w-xl" style={{ height: `${height}px` }}>
        <polyline
          points={coords.map((c) => `${c.x},${c.y}`).join(" ")}
          fill="none"
          stroke="var(--teal-deep)"
          strokeWidth={2}
        />
        {coords.map((c, i) => (
          <circle key={points[i].label} cx={c.x} cy={c.y} r={3} fill="var(--teal-deep)" />
        ))}
      </svg>
      <div className="flex justify-between text-[11px] text-ink-soft mt-1 px-1 gap-1">
        {points.map((p) => (
          <span key={p.label} className="truncate max-w-[80px]">
            {p.label}
          </span>
        ))}
      </div>
    </div>
  );
}

const TREND_ARROW: Record<string, string> = { up: "↑", down: "↓", flat: "→" };
const TREND_COLOR: Record<string, string> = { up: "text-teal", down: "text-red", flat: "text-ink-soft" };

function ForecastPanel({ forecasts }: { forecasts: Forecast[] }) {
  if (forecasts.length === 0) return null;
  return (
    <div className="bg-panel border border-line rounded-[4px] p-5">
      <div className="text-[13px] text-ink-soft mb-1">Projected trend</div>
      <div className="text-[11.5px] text-ink-soft mb-4 italic">
        A straight-line projection of the recent trend, not a forecast — see the caveat under
        each group.
      </div>
      <div className="flex flex-col gap-4">
        {forecasts.map((f, i) => {
          const max = Math.max(...f.points.map((p) => Math.abs(p.projected_value)), 1);
          return (
            <div key={f.group} className={i > 0 ? "pt-4 border-t border-line" : ""}>
              <div className="flex items-center justify-between gap-3 mb-2">
                <div className="text-[13.5px] text-ink">{f.group}</div>
                <span className={`text-[12px] font-medium ${TREND_COLOR[f.trend_direction] ?? "text-ink-soft"}`}>
                  {TREND_ARROW[f.trend_direction] ?? ""} {f.trend_direction}
                </span>
              </div>
              <div className="flex flex-col gap-1.5">
                {f.points.map((p) => (
                  <div key={p.period} className="flex items-center gap-3">
                    <div className="w-20 text-[12px] text-ink-soft shrink-0">{p.period}</div>
                    <div className="flex-1 h-4 bg-paper rounded-[2px] overflow-hidden">
                      <div
                        className="h-full rounded-[2px] border border-dashed border-slate bg-slate/10"
                        style={{ width: `${(Math.abs(p.projected_value) / max) * 100}%` }}
                      />
                    </div>
                    <div className="w-24 text-right text-[12px] font-[family-name:var(--font-mono)] text-ink-soft shrink-0">
                      ~{p.projected_value.toLocaleString(undefined, { maximumFractionDigits: 0 })}
                    </div>
                  </div>
                ))}
              </div>
              <div className="text-[11.5px] text-ink-soft mt-2 italic leading-relaxed">{f.caveat}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function InvestigationCascade({ investigation }: { investigation: Investigation[] }) {
  if (investigation.length === 0) return null;
  return (
    <div className="mt-3 flex flex-col gap-4">
      {investigation.map((inv, idx) => {
        const parent = idx > 0 ? investigation[idx - 1] : null;
        const parentTop = parent?.breakdown[0]?.group;
        return (
          <div key={inv.dimension} className={idx > 0 ? "pl-4 border-l border-line" : ""}>
            <div className="text-[12px] text-ink-soft mb-2">
              {parent ? `Within ${parentTop}, breakdown by ${inv.dimension}:` : `Breakdown by ${inv.dimension}:`}
            </div>
            <GroupBars data={inv.breakdown} />
          </div>
        );
      })}
    </div>
  );
}

// One named chart from a v2 document-only result's `charts` array,
// rendered by type - bar/pie reuse GroupBars/PieChart above (adapting
// {labels, values} into the {group, total}[] shape they already take),
// "line" gets the new LineChart. Mirrors the existing by_group panels'
// layout (a titled panel, optionally a pie alongside a bar) but per-chart
// rather than one hard-coded pair.
function ChartPanel({ chart }: { chart: NonNullable<ResultEvent["charts"]>[number] }) {
  const data = chart.labels.map((label, i) => ({ group: label, total: chart.values[i] ?? 0 }));
  const canShowPie = chart.chart_type === "pie" && data.some((d) => d.total > 0);

  return (
    <div className="bg-panel border border-line rounded-[4px] p-5">
      <div className="text-[13px] text-ink-soft mb-3">{chart.title || "Breakdown"}</div>
      {chart.chart_type === "line" ? (
        <LineChart labels={chart.labels} values={chart.values} />
      ) : chart.chart_type === "pie" ? (
        canShowPie && <PieChart data={data} />
      ) : (
        <GroupBars data={data} />
      )}
      {chart.insight && <div className="text-[12.5px] text-ink-soft mt-3 italic">{chart.insight}</div>}
      {chart.location && (
        <div className="text-[11px] text-ink-soft font-[family-name:var(--font-mono)] mt-1.5">{chart.location}</div>
      )}
    </div>
  );
}

// A v2 document-only result's key_findings/flagged_items (see
// app/agents/insight_agent.py's DocumentInsight) - each finding cites
// where in the source document it came from, with its own confidence
// tag reusing ConfidenceBadge, same as an anomaly's confidence badge
// below. Rendered only when there's at least one of either, same
// "don't show an empty panel" convention every other section here uses.
function KeyFindingsList({
  findings, flaggedItems,
}: {
  findings: { finding: string; location: string; confidence: string }[];
  flaggedItems: string[];
}) {
  if (findings.length === 0 && flaggedItems.length === 0) return null;
  return (
    <div className="bg-panel border border-line rounded-[4px] p-5">
      {findings.length > 0 && (
        <>
          <div className="text-[13px] text-ink-soft mb-3">Key findings</div>
          <div className="flex flex-col gap-3">
            {findings.map((f, i) => (
              <div key={i} className={i > 0 ? "pt-3 border-t border-line" : ""}>
                <div className="flex items-start justify-between gap-3">
                  <div className="text-[13.5px] text-ink">{f.finding}</div>
                  <ConfidenceBadge level={f.confidence} />
                </div>
                {f.location && (
                  <div className="text-[12px] text-ink-soft font-[family-name:var(--font-mono)] mt-1">
                    {f.location}
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      )}
      {flaggedItems.length > 0 && (
        <ul className={`text-[12.5px] text-amber flex flex-col gap-1 ${findings.length > 0 ? "mt-4 pt-4 border-t border-line" : ""}`}>
          {flaggedItems.map((item, i) => (
            <li key={i}>{item}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function AnomalyList({ result }: { result: ResultEvent }) {
  if (result.anomalies.length === 0) return null;

  return (
    <div className="bg-panel border border-line rounded-[4px] p-5">
      <div className="text-[13px] text-ink-soft mb-3">Anomalies detected</div>
      <div className="flex flex-col gap-4">
        {result.anomalies.map((a, i) => (
          <div key={i} className={i > 0 ? "pt-4 border-t border-line" : ""}>
            <div className="flex items-start justify-between gap-3">
              <div className="text-[13.5px] text-ink">{a.what}</div>
              <ConfidenceBadge level={a.confidence} />
            </div>
            <div className="text-[12.5px] text-ink-soft mt-1">{a.magnitude}</div>
            <div className="text-[12px] text-ink-soft font-[family-name:var(--font-mono)] mt-1.5">{a.evidence}</div>
            {a.possible_explanations.map((p, j) => (
              <div key={j} className="text-[12.5px] text-ink-soft mt-1.5 italic">
                {p}
              </div>
            ))}
            {i === 0 && <InvestigationCascade investigation={result.investigation} />}
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ResultView({ result }: { result: ResultEvent }) {
  const [showSql, setShowSql] = useState(false);
  const insight = "error" in result.insight ? null : result.insight;
  // A pie slice can't represent a negative value (a "loss" figure some
  // questions produce) - PieChart itself clamps those to zero, but if
  // EVERY group is <= 0 there's nothing left to divide a circle by, so
  // skip the panel entirely rather than showing an empty one.
  const canShowPie = (result.by_group ?? []).some((d) => d.total > 0);

  return (
    <div className="flex flex-col gap-5">
      {insight ? (
        <div className="bg-panel border border-line rounded-[4px] p-5">
          <div className="flex items-center justify-between gap-4 mb-3">
            <div className="text-[15px] font-medium text-ink leading-snug">{insight.what}</div>
            <ConfidenceBadge level={insight.confidence} />
          </div>

          {insight.extraction_summary ? (
            // A v2 document-only result (see DocumentInsight in
            // insight_agent.py) - the extraction summary here, key
            // findings/flagged items rendered separately below in their
            // own panel (KeyFindingsList), same reasoning as `body` below
            // for why this doesn't force an open-ended document answer
            // into the Where/When/Contributors template.
            <div className="text-[13px] text-ink-soft">
              {insight.extraction_summary.total_rows_or_items} row(s)/item(s) across{" "}
              {insight.extraction_summary.sheets_or_pages_or_slides} sheet(s)/page(s)/slide(s) —
              extraction confidence: {insight.extraction_summary.extraction_confidence}
              {insight.extraction_summary.flags.length > 0 && (
                <ul className="mt-2 flex flex-col gap-1 text-amber">
                  {insight.extraction_summary.flags.map((flag, i) => (
                    <li key={i}>{flag}</li>
                  ))}
                </ul>
              )}
            </div>
          ) : insight.body ? (
            // The OLD document-only shape (see the comment on
            // ResultEvent["charts"] in lib/api.ts) - a real, organized
            // answer, kept working purely so a QueryRecord written before
            // the v2 rebuild still reopens correctly. The
            // Where/When/Contributors template below is built for
            // explaining a single computed database metric and is a bad
            // fit for an open-ended document question, which is what
            // produced a genuinely disorganized report before this
            // existed. pre-wrap preserves the model's own blank-line/"- "
            // bullet structure without needing a markdown renderer.
            <div className="text-[13.5px] text-ink whitespace-pre-wrap leading-relaxed">{insight.body}</div>
          ) : (
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2.5 text-[13px]">
              <div>
                <dt className="text-ink-soft">Where</dt>
                <dd className="text-ink mt-0.5">{insight.where}</dd>
              </div>
              <div>
                <dt className="text-ink-soft">When</dt>
                <dd className="text-ink mt-0.5">{insight.when}</dd>
              </div>
              <div className="col-span-2">
                <dt className="text-ink-soft">What contributed</dt>
                <dd className="text-ink mt-0.5">{insight.contributors}</dd>
              </div>
            </dl>
          )}

          <div className="mt-4 pt-4 border-t border-line text-[13px]">
            <div className="text-ink-soft">Data quality</div>
            <div className="text-ink mt-0.5">{insight.data_quality_caveat}</div>
          </div>
          <div className="mt-4 pt-4 border-t border-line text-[13px]">
            <span className="text-ink-soft">Next: </span>
            <span className="text-ink">{insight.next_question}</span>
          </div>
        </div>
      ) : (
        <div className="bg-panel border border-line rounded-[4px] p-5 text-[13px] text-ink-soft">
          The analysis ran, but the explanation step is unavailable.
        </div>
      )}

      {result.charts && result.charts.length > 0 ? (
        // v2 document-only charts (see the comment on ResultEvent["charts"]
        // in lib/api.ts) - one panel per named chart, rather than the
        // single implicit bar+pie pair below (which this result doesn't
        // have - by_group is null whenever charts is populated).
        result.charts.map((chart, i) => <ChartPanel key={i} chart={chart} />)
      ) : (
        <>
          {result.by_group && result.by_group.length > 0 && (
            <div className="bg-panel border border-line rounded-[4px] p-5">
              <div className="text-[13px] text-ink-soft mb-3">By group</div>
              <GroupBars data={result.by_group} />
            </div>
          )}

          {result.by_group && canShowPie && (
            <div className="bg-panel border border-line rounded-[4px] p-5">
              <div className="text-[13px] text-ink-soft mb-3">Share of total</div>
              <PieChart data={result.by_group} />
            </div>
          )}
        </>
      )}

      {insight && (
        <KeyFindingsList findings={insight.key_findings ?? []} flaggedItems={insight.flagged_items ?? []} />
      )}

      <ForecastPanel forecasts={result.forecast} />

      <AnomalyList result={result} />

      <ArtifactActions queryId={result.query_id} />

      <div className="bg-panel border border-line rounded-[4px] p-5">
        <div className="text-[13px] text-ink-soft mb-3">Evidence</div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-[12.5px] font-[family-name:var(--font-mono)]">
          <div>
            <div className="text-ink-soft">Query ID</div>
            <div className="text-ink">{result.query_id}</div>
          </div>
          <div>
            <div className="text-ink-soft">Rows analysed</div>
            <div className="text-ink">{result.row_count.toLocaleString()}</div>
          </div>
          <div>
            <div className="text-ink-soft">Duration</div>
            <div className="text-ink">{result.duration_ms} ms</div>
          </div>
          <div>
            <div className="text-ink-soft">Completeness</div>
            <div className="text-ink">{result.data_quality.completeness_pct}%</div>
          </div>
        </div>

        {result.documents_used.length > 0 && (
          <div className="mt-4 pt-4 border-t border-line text-[12.5px] text-ink-soft">
            Referenced document(s): {result.documents_used.join(", ")}
          </div>
        )}

        {result.data_quality.notes.length > 0 && (
          <ul className="mt-4 pt-4 border-t border-line text-[12.5px] text-amber flex flex-col gap-1">
            {result.data_quality.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        )}

        <button
          onClick={() => setShowSql((v) => !v)}
          className="mt-4 text-[12.5px] text-teal hover:text-teal-deep transition-colors"
        >
          {showSql ? "Hide query" : "View query"}
        </button>
        {showSql && (
          <pre className="mt-2 p-3 bg-paper rounded-[3px] text-[12px] font-[family-name:var(--font-mono)] text-ink overflow-x-auto">
            {result.sql}
          </pre>
        )}
      </div>
    </div>
  );
}
