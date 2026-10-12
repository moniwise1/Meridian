"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { getHealthSnapshot, listRecentErrors, type HealthSnapshot, type PlatformErrorEntry } from "@/lib/platformApi";
import { usePlatformSession } from "@/lib/useSession";
import AskLauncher from "@/components/AskLauncher";
import { saveAskDraft } from "@/lib/askDraft";
import DashboardIcon from "@/components/DashboardIcon";
import { CompositionChart, sourceDate } from "@/components/DashboardCharts";
function StatCard({ label, value, href, warn = false }: { label: string; value: number | null; href: string; warn?: boolean }) {
  return <Link href={href} className="dashboard-card p-4 hover:border-teal transition-colors"><div className="flex items-center gap-2.5"><span className={`rounded-full p-2 ${warn ? "bg-gold-soft text-amber" : "bg-mint-soft text-teal"}`}><DashboardIcon name={warn ? "shield" : "chart"} size={16} /></span><h2 className="text-[11px] text-ink-soft">{label}</h2></div><p className={`text-[25px] font-semibold mt-3 tabular-nums ${warn && value ? "text-amber" : "text-ink"}`}>{value === null ? "—" : value.toLocaleString()}</p><p className="text-[10px] text-ink-soft mt-1">View records →</p></Link>;
}
export default function PlatformDashboardPage() {
  const session = usePlatformSession();
  const [snapshot, setSnapshot] = useState<HealthSnapshot | null>(null);
  const [entries, setEntries] = useState<PlatformErrorEntry[]>([]);
  const [errorsReady, setErrorsReady] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    Promise.allSettled([getHealthSnapshot(), listRecentErrors(1)]).then(([health, errors]) => {
      if (!active) return;
      if (health.status === "fulfilled") setSnapshot(health.value);
      if (errors.status === "fulfilled") { setEntries(errors.value); setErrorsReady(true); }
      const failures = [health, errors].filter(result => result.status === "rejected").map(result => result.status === "rejected" ? result.reason.message : "");
      setError(failures.join(" · "));
    });
    return () => { active = false; };
  }, []);
  const owner = session?.role === "owner";
  return <div className="max-w-[1440px] mx-auto p-4 sm:p-6 lg:p-7">
    <div className="dashboard-greeting flex flex-wrap items-center justify-between gap-4 p-5 mb-5"><div className="relative z-10"><p className="text-[10px] uppercase tracking-[0.14em] text-teal mb-1.5">Platform operations</p><h1 className="text-xl font-semibold tracking-tight">Welcome back, {session?.email.split("@")[0] || "there"}</h1><p className="text-xs text-ink-soft mt-2">Account activity, support and service signals from your platform records.</p></div><Link href="/platform/analytics" className="relative z-10 flex items-center gap-2 bg-teal-deep text-white text-xs rounded-lg px-4 py-2.5">View analytics <DashboardIcon name="arrow" size={15} /></Link></div>
    {error && <p role="alert" className="text-sm text-red mb-4">{error}</p>}
    <div className="grid grid-cols-2 lg:grid-cols-5 gap-3 mb-5"><StatCard label="Active tenants" value={snapshot?.active_tenants ?? null} href="/platform/tenants" /><StatCard label="Total tenants" value={snapshot?.total_tenants ?? null} href="/platform/tenants" /><StatCard label="Errors, last hour" value={snapshot?.recent_errors_last_hour ?? null} href="/platform/errors" warn /><StatCard label="Open tickets" value={snapshot?.open_tickets ?? null} href="/platform/tickets" warn /><StatCard label="Open incidents" value={snapshot?.open_incidents ?? null} href="/platform/status" warn /></div>
    <div className="grid xl:grid-cols-[minmax(0,1fr)_290px] gap-5"><div className="grid lg:grid-cols-2 gap-4"><section className="dashboard-card p-5">{snapshot ? <CompositionChart caption="Accounts" label="Current account status" items={[{ label: "Active", value: snapshot.active_tenants }, { label: "Other statuses", value: Math.max(0, snapshot.total_tenants-snapshot.active_tenants) }]} /> : <p className="text-xs text-ink-soft py-12">Loading account status…</p>}<p className="text-[10px] text-ink-soft leading-5 mt-4">Active includes manually activated accounts. This count does not establish collected subscription revenue.</p></section><section className="dashboard-card p-5"><div className="flex items-center justify-between mb-4"><h2 className="text-sm font-semibold">Recent errors</h2><Link href="/platform/errors" className="text-[10px] text-teal">View all</Link></div><div className="space-y-4">{entries.slice(0,5).map(entry => <Link href="/platform/errors" key={entry.id} className="flex gap-2.5"><span className="text-amber mt-0.5"><DashboardIcon name="shield" size={15} /></span><div className="min-w-0"><p className="text-xs truncate">{entry.action.replaceAll("_", " ")}</p><p className="text-[10px] text-ink-soft mt-1">{entry.tenant_name} · {sourceDate(entry.timestamp).toLocaleTimeString(undefined,{hour:"2-digit",minute:"2-digit"})}</p></div></Link>)}{errorsReady && !entries.length && <p className="text-xs text-ink-soft">No logged errors in the last hour.</p>}</div></section><section className="dashboard-card p-5 lg:col-span-2"><h2 className="text-sm font-semibold mb-4">Manage the platform</h2><div className="grid sm:grid-cols-3 gap-3">{[["/platform/tenants","Tenants","Review accounts and subscriptions"],["/platform/tickets","Support tickets","Respond to open customer issues"],["/platform/status","Service status","Review incidents and status updates"]].map(([href,title,description]) => <Link key={href} href={href} className="border border-line rounded-lg p-3 hover:border-teal"><p className="text-xs font-medium">{title} →</p><p className="text-[10px] text-ink-soft leading-5 mt-1">{description}</p></Link>)}</div></section></div><aside className="space-y-4">{owner && <section className="dashboard-card p-4"><div className="flex items-center gap-2 text-teal mb-2"><DashboardIcon name="chat" /><h2 className="text-sm font-semibold">Ask Meridian</h2></div><p className="text-[11px] text-ink-soft leading-5 mb-4">Ask about account growth, usage, subscriptions or support.</p><AskLauncher platform />{["How many new accounts signed up?","How many support tickets are open?","Compare analysis usage with the previous period"].map(question => <Link key={question} href="/platform/ask" onClick={() => { try { saveAskDraft(question, true); } catch { /* Ask remains available without draft storage. */ } }} className="block text-[11px] text-teal border-t border-line py-2.5">{question} →</Link>)}</section>}<section className="dashboard-card p-4"><h2 className="text-sm font-semibold mb-2">Service signals</h2><p className="text-[11px] text-ink-soft leading-6">These counts come from platform records and audit logs. Pair them with external uptime monitoring to track availability across regions.</p><Link href="/platform/status" className="block text-xs text-teal mt-3">Open service status →</Link></section></aside></div>
  </div>;
}
