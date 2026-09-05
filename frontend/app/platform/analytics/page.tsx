"use client";

import { useEffect, useState } from "react";
import { getAnalytics, type Analytics, type DailyCount } from "@/lib/platformApi";

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="bg-panel border border-line rounded-[4px] px-4 py-3.5">
      <div className="text-[22px] font-medium tracking-tight tabular-nums text-ink">{value}</div>
      <div className="text-[12px] text-ink-soft mt-0.5">{label}</div>
    </div>
  );
}

// Dependency-free bar chart — CSS divs sized by percentage of the series
// max, matching this codebase's general preference for avoiding heavy
// libraries for a job plain HTML/CSS already does (same reasoning as the
// PDF/PPTX export code not pulling in matplotlib). No charting library
// exists anywhere in this frontend today; this stays consistent with that.
function DailyBarChart({ series, label }: { series: DailyCount[]; label: string }) {
  const max = Math.max(1, ...series.map((d) => d.count));
  return (
    <div className="bg-panel border border-line rounded-[4px] p-4">
      <div className="text-[12.5px] text-ink mb-3">{label}</div>
      <div className="flex items-end gap-[3px] h-24">
        {series.map((d) => (
          <div key={d.date} className="flex-1 group relative" title={`${d.date}: ${d.count}`}>
            <div
              className="bg-teal rounded-t-[1px] w-full hover:bg-teal-deep transition-colors"
              style={{ height: `${Math.max(2, (d.count / max) * 100)}%` }}
            />
          </div>
        ))}
      </div>
      <div className="flex justify-between text-[10.5px] text-ink-soft mt-1.5">
        <span>{series[0]?.date}</span>
        <span>{series[series.length - 1]?.date}</span>
      </div>
    </div>
  );
}

function BreakdownList({ title, data }: { title: string; data: Record<string, number> }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const total = entries.reduce((sum, [, v]) => sum + v, 0) || 1;
  return (
    <div className="bg-panel border border-line rounded-[4px] p-4">
      <div className="text-[12.5px] text-ink mb-3">{title}</div>
      <div className="flex flex-col gap-2">
        {entries.length === 0 && <div className="text-[12px] text-ink-soft">No data yet.</div>}
        {entries.map(([key, value]) => (
          <div key={key} className="flex items-center gap-2">
            <div className="w-20 shrink-0 text-[12px] text-ink-soft capitalize truncate">{key}</div>
            <div className="flex-1 h-2 bg-paper rounded-[2px] overflow-hidden">
              <div className="h-full bg-teal" style={{ width: `${(value / total) * 100}%` }} />
            </div>
            <div className="w-8 shrink-0 text-[12px] text-ink text-right tabular-nums">{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function FunnelStep({ label, value, of, first }: { label: string; value: number; of: number; first?: boolean }) {
  const pct = of > 0 ? Math.round((value / of) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <div className="w-40 shrink-0 text-[12.5px] text-ink-soft">{label}</div>
      <div className="flex-1 h-6 bg-paper rounded-[3px] overflow-hidden">
        <div
          className="h-full bg-teal flex items-center justify-end pr-2"
          style={{ width: `${Math.max(4, pct)}%` }}
        >
          <span className="text-[11px] text-white tabular-nums">{value}</span>
        </div>
      </div>
      <div className="w-12 shrink-0 text-[11.5px] text-ink-soft text-right tabular-nums">
        {first ? "" : `${pct}%`}
      </div>
    </div>
  );
}

export default function PlatformAnalyticsPage() {
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getAnalytics()
      .then(setData)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Analytics</h1>
      <p className="text-[13.5px] text-ink-soft mb-8">
        Aggregated, cross-tenant business metrics built entirely from data Meridian already collects
        for its own operation — no third-party analytics SDK, no user behavioral data leaving this
        platform. Never a single row of one tenant&apos;s actual business data.
      </p>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}

      {data && (
        <>
          <div className="grid grid-cols-4 gap-3 mb-8">
            <StatCard label="Total tenants" value={data.total_tenants} />
            <StatCard label="Active, 7d" value={data.active_tenants_7d} />
            <StatCard label="Active, 30d" value={data.active_tenants_30d} />
            <StatCard label="Total questions" value={data.total_questions} />
          </div>

          <div className="grid grid-cols-2 gap-3 mb-8">
            <DailyBarChart series={data.signups_by_day} label="Signups, last 30 days" />
            <DailyBarChart series={data.questions_by_day} label="Questions asked, last 30 days" />
          </div>

          <div className="bg-panel border border-line rounded-[4px] p-4 mb-8">
            <div className="text-[12.5px] text-ink mb-3">Activation funnel (all-time)</div>
            <div className="flex flex-col gap-2.5">
              <FunnelStep label="Registered" value={data.funnel.registered} of={data.funnel.registered} first />
              <FunnelStep
                label="Connected or uploaded"
                value={data.funnel.connected_or_uploaded}
                of={data.funnel.registered}
              />
              <FunnelStep label="Asked a question" value={data.funnel.asked_a_question} of={data.funnel.registered} />
              <FunnelStep label="Subscribed" value={data.funnel.subscribed} of={data.funnel.registered} />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-3 mb-8">
            <BreakdownList title="Tenants by tier" data={data.tenants_by_tier} />
            <BreakdownList title="Tenants by plan" data={data.tenants_by_plan} />
            <BreakdownList title="Artifacts by kind" data={data.artifacts_by_kind} />
          </div>

          <div className="bg-panel border border-line rounded-[4px] p-4">
            <div className="text-[12.5px] text-ink mb-3">Recent signups</div>
            <div className="flex flex-col gap-1.5">
              {data.recent_signups.length === 0 && (
                <div className="text-[12px] text-ink-soft">No signups yet.</div>
              )}
              {data.recent_signups.map((t, i) => (
                <div key={i} className="flex items-center justify-between text-[12.5px]">
                  <span className="text-ink">{t.tenant_name}</span>
                  <span className="text-ink-soft">
                    {t.subdomain} · {t.created_at ? new Date(t.created_at).toLocaleDateString() : "—"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
