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

  let cursor = 0;
  const stops = slices.map((d, i) => {
    const start = (cursor / total) * 360;
    cursor += Math.max(0, d.total);
    const end = (cursor / total) * 360;
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
            <div className="col-span-2">
              <dt className="text-ink-soft">Data quality</dt>
              <dd className="text-ink mt-0.5">{insight.data_quality_caveat}</dd>
            </div>
          </dl>
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
