"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { getMe, listAnalyses, listArtifactHistory, listConnections, listDocuments, type AnalysisSummary, type ArtifactHistoryEntry, type Connection, type DocumentSummary } from "@/lib/api";
import { loadSession } from "@/lib/auth";
import AskLauncher from "@/components/AskLauncher";
import { saveAskDraft } from "@/lib/askDraft";
import DashboardIcon from "@/components/DashboardIcon";
import { ActivityChart, CompositionChart, sourceDate } from "@/components/DashboardCharts";
const KIND_LABEL: Record<string,string> = { report_pdf: "Reports", presentation_pptx: "Presentations", export_csv: "CSV exports", export_xlsx: "Excel exports" };
function StatCard({ label, value, href, icon, tone }: { label: string; value: number | null; href: string; icon: string; tone: string }) {
  return <Link href={href} className="dashboard-card p-4 hover:border-teal transition-colors"><div className="flex items-center gap-3"><span className={`rounded-full p-2 ${tone}`}><DashboardIcon name={icon} /></span><p className="text-[11px] text-ink-soft">{label}</p></div><p className="text-[25px] font-semibold tracking-tight tabular-nums mt-3">{value === null ? "—" : value.toLocaleString()}</p><p className="text-[10px] text-ink-soft mt-1">Open details →</p></Link>;
}
export default function HomePage() {
  const session = loadSession();
  const [analyses, setAnalyses] = useState<AnalysisSummary[]>([]);
  const [artifacts, setArtifacts] = useState<ArtifactHistoryEntry[]>([]);
  const [connections, setConnections] = useState<Connection[]>([]);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [ready, setReady] = useState({ analyses: false, artifacts: false, connections: false, documents: false });
  const [error, setError] = useState("");
  const [displayName, setDisplayName] = useState<string | null>(null);
  const [accountType, setAccountType] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    Promise.allSettled([listAnalyses(), listArtifactHistory(), listConnections(), listDocuments()]).then(([a,r,c,d]) => {
      if (!active) return;
      if (a.status === "fulfilled") setAnalyses(a.value);
      if (r.status === "fulfilled") setArtifacts(r.value);
      if (c.status === "fulfilled") setConnections(c.value);
      if (d.status === "fulfilled") setDocuments(d.value);
      setReady({ analyses:a.status === "fulfilled", artifacts:r.status === "fulfilled", connections:c.status === "fulfilled", documents:d.status === "fulfilled" });
      const errors = [a,r,c,d].filter(result => result.status === "rejected").map(result => result.status === "rejected" ? result.reason.message : "");
      setError(errors.join(" · "));
    });
    getMe().then(me => { if (active) { setDisplayName(me.display_name); setAccountType(me.account_type); } }).catch(() => {});
    return () => { active = false; };
  }, []);
  const name = displayName || session?.email.split("@")[0] || "there";
  const pinned = analyses.filter(analysis => analysis.pinned);
  const greeting = new Date().getHours() < 12 ? "Good morning" : new Date().getHours() < 18 ? "Good afternoon" : "Good evening";
  return <div className="max-w-[1440px] mx-auto p-4 sm:p-6 lg:p-7">
    <div className="dashboard-greeting flex flex-wrap justify-between items-center gap-4 px-5 py-5 mb-5"><div className="relative z-10"><p className="text-[10px] uppercase tracking-[0.14em] text-teal mb-1.5">{accountType === "business" ? "Business workspace" : accountType === "individual" ? "Individual workspace" : "Your workspace"}</p><h1 className="text-xl font-semibold tracking-tight">{greeting}, {name}</h1><p className="text-xs text-ink-soft mt-2">Your data, recent findings and next questions in one place.</p></div><Link href="/" className="relative z-10 flex items-center gap-2 bg-teal-deep text-white rounded-lg px-4 py-2.5 text-xs">Ask Meridian <DashboardIcon name="arrow" size={15} /></Link></div>
    {error && <p role="alert" className="text-sm text-red mb-4">{error}</p>}
    <div className="grid grid-cols-2 xl:grid-cols-4 gap-3 mb-5"><StatCard label="Connected databases" value={ready.connections ? connections.length : null} href="/connections" icon="source" tone="bg-mint-soft text-teal" /><StatCard label="Uploaded files" value={ready.documents ? documents.length : null} href="/documents" icon="file" tone="bg-gold-soft text-amber" /><StatCard label="Recent analyses" value={ready.analyses ? analyses.length : null} href="/analyses" icon="chart" tone="bg-mint-soft text-teal" /><StatCard label="Recent reports & exports" value={ready.artifacts ? artifacts.length : null} href="/library" icon="folder" tone="bg-gold-soft text-amber" /></div>
    <div className="grid xl:grid-cols-[minmax(0,1fr)_290px] gap-5"><div className="min-w-0"><div className="grid lg:grid-cols-[1.4fr_1fr] gap-4 mb-4"><section className="dashboard-card p-5">{ready.analyses ? <ActivityChart analyses={analyses} /> : <p className="text-xs text-ink-soft py-16">Loading analysis activity…</p>}</section><section className="dashboard-card p-5">{ready.artifacts ? <CompositionChart label="Reports & exports" items={Object.entries(KIND_LABEL).map(([kind,label]) => ({ label, value:artifacts.filter(row => row.kind === kind).length }))} /> : <p className="text-xs text-ink-soft py-16">Loading reports…</p>}</section></div>
      <div className="grid lg:grid-cols-3 gap-4"><section className="dashboard-card p-4"><div className="flex items-center justify-between mb-3"><h2 className="text-sm font-semibold">Your data sources</h2><Link href="/connections" className="text-[10px] text-teal">Manage</Link></div><div className="space-y-3">{connections.slice(0,3).map(source => <Link href="/connections" key={source.id} className="flex items-center gap-2.5"><span className="text-teal bg-mint-soft p-2 rounded-full"><DashboardIcon name="source" size={14} /></span><div className="min-w-0"><p className="text-xs truncate">{source.name}</p><p className="text-[10px] text-ink-soft mt-1">{source.kind} · {source.verified_read_only ? "Read-only setup verified" : "Setup unverified"}</p></div></Link>)}{documents.slice(0,2).map(file => <Link href="/documents" key={file.id} className="flex items-center gap-2.5"><span className="text-amber bg-gold-soft p-2 rounded-full"><DashboardIcon name="file" size={14} /></span><div className="min-w-0"><p className="text-xs truncate">{file.filename}</p><p className="text-[10px] text-ink-soft mt-1">{file.kind.toUpperCase()} · Upload snapshot</p></div></Link>)}{ready.connections && ready.documents && !connections.length && !documents.length && <p className="text-xs text-ink-soft">Connect a database or upload your first file.</p>}</div></section>
      <section className="dashboard-card p-4"><div className="flex items-center justify-between mb-3"><h2 className="text-sm font-semibold">Saved analyses</h2><Link href="/analyses" className="text-[10px] text-teal">View all</Link></div><div className="space-y-3">{pinned.slice(0,4).map(analysis => <Link className="block" href={`/analyses/${analysis.query_id}`} key={analysis.query_id}><p className="text-xs truncate">{analysis.question}</p><p className="text-[10px] text-ink-soft mt-1">{sourceDate(analysis.created_at).toLocaleDateString()}</p></Link>)}{ready.analyses && !pinned.length && <p className="text-xs text-ink-soft">Star an analysis to keep it close at hand.</p>}</div></section>
      <section className="dashboard-card p-4"><div className="flex items-center justify-between mb-3"><h2 className="text-sm font-semibold">Recent reports</h2><Link href="/library" className="text-[10px] text-teal">View all</Link></div><div className="space-y-3">{artifacts.slice(0,4).map(artifact => <Link href={artifact.source_query_id ? `/analyses/${artifact.source_query_id}` : "/library"} className="block" key={artifact.id}><p className="text-xs truncate">{artifact.title}</p><p className="text-[10px] text-ink-soft mt-1">{KIND_LABEL[artifact.kind] ?? artifact.kind} · {sourceDate(artifact.created_at).toLocaleDateString()}</p></Link>)}{ready.artifacts && !artifacts.length && <p className="text-xs text-ink-soft">Reports and exports appear here after you generate them.</p>}</div></section></div>
    </div><aside className="space-y-4 min-w-0"><section className="dashboard-card p-4 bg-mint-soft/40"><div className="flex items-center gap-2 mb-2 text-teal"><DashboardIcon name="chat" /><h2 className="text-sm font-semibold">Ask Meridian</h2></div><p className="text-[11px] text-ink-soft leading-5 mb-3">Follow a question through your files or database records.</p><AskLauncher /><p className="text-[10px] text-ink-soft mb-2">Try asking</p>{["Which patterns or exceptions stand out?", "Compare the relevant groups", "What should I verify in these records?"].map(question => <Link key={question} href="/" onClick={() => { try { saveAskDraft(question); } catch { /* Ask remains available without draft storage. */ } }} className="block text-[11px] text-teal border-t border-line/60 py-2">{question} →</Link>)}</section><section className="dashboard-card p-4"><div className="flex items-center justify-between mb-3"><h2 className="text-sm font-semibold">Recent analyses</h2><Link href="/analyses" className="text-[10px] text-teal">View all</Link></div><div className="space-y-4">{analyses.slice(0,4).map(analysis => <Link className="flex gap-2" href={`/analyses/${analysis.query_id}`} key={analysis.query_id}><span className="text-teal mt-0.5"><DashboardIcon name="chart" size={14} /></span><div className="min-w-0"><p className="text-xs leading-5 line-clamp-2">{analysis.question}</p><p className="text-[10px] text-ink-soft mt-1">{sourceDate(analysis.created_at).toLocaleDateString()}</p></div></Link>)}{ready.analyses && !analyses.length && <p className="text-xs text-ink-soft">Your first analysis will appear here.</p>}</div></section><Link href="/schedules" className="dashboard-card p-4 flex items-center gap-3"><span className="text-amber"><DashboardIcon name="clock" /></span><div><p className="text-xs font-medium">Scheduled analyses</p><p className="text-[10px] text-ink-soft mt-1">Repeat a useful question and track changes.</p></div></Link></aside></div>
  </div>;
}
