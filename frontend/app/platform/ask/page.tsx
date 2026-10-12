"use client";

import { useEffect, useState } from "react";
import { askPlatform, type PlatformAnswer } from "@/lib/platformApi";
import { readAskDraft, clearAskDraft } from "@/lib/askDraft";
import { usePlatformSession } from "@/lib/useSession";

const questions = ["How many new accounts signed up?", "Compare analysis usage with the previous period", "How many subscriptions are active?", "How many support tickets are open?"];
export default function PlatformAskPage() {
  const session = usePlatformSession();
  const [question, setQuestion] = useState(() => readAskDraft(true));
  useEffect(() => {
    clearAskDraft(true);
    const receive = (event: Event) => {
      const detail = (event as CustomEvent<{ question: string; platform: boolean }>).detail;
      if (detail.platform) { setQuestion(detail.question); clearAskDraft(true); }
    };
    window.addEventListener("meridian:ask-draft", receive);
    return () => window.removeEventListener("meridian:ask-draft", receive);
  }, []);
  const [days, setDays] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [answer, setAnswer] = useState<PlatformAnswer | null>(null);
  async function ask(text: string) {
    if (busy || !text.trim()) return;
    setBusy(true); setError(""); setAnswer(null); setQuestion(text);
    try { setAnswer(await askPlatform(text, days)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  if (session?.role !== "owner") return <p className="p-8">Ask Meridian for platform operations is available to the owner.</p>;
  return <div className="max-w-4xl mx-auto px-4 sm:px-8 py-10">
    <p className="text-xs text-teal uppercase tracking-widest">Owner workspace</p><h1 className="text-3xl tracking-tight mt-2">Ask Meridian</h1><p className="text-sm text-ink-soft mt-3 mb-8">Explore account growth, product usage, subscriptions and support. Every answer comes from Meridian&apos;s platform records.</p>
    <div className="grid sm:grid-cols-2 gap-3 mb-6">{questions.map(q => <button disabled={busy} key={q} onClick={() => void ask(q)} className="text-left bg-panel border border-line rounded-xl p-4 hover:border-teal disabled:opacity-40 text-sm">{q}</button>)}</div>
    <form onSubmit={e => { e.preventDefault(); void ask(question); }} className="bg-panel border border-line rounded-xl p-5">
      <label className="text-xs text-ink-soft">Reporting window<select className="block border border-line bg-panel rounded-md p-2 mt-1 mb-4" value={days} disabled={busy} onChange={e => { setDays(Number(e.target.value)); setAnswer(null); }}>{[7, 30, 90, 365].map(n => <option key={n} value={n}>Last {n} days</option>)}</select></label>
      <label className="text-xs text-ink-soft">Your question<textarea required maxLength={1000} rows={3} disabled={busy} value={question} onChange={e => setQuestion(e.target.value)} className="block w-full border border-line bg-panel rounded-md p-3 mt-1 text-sm" placeholder="Ask about platform signups, usage, subscriptions or tickets" /></label><button disabled={busy || !question.trim()} className="bg-teal-deep text-white rounded-md px-5 py-2 mt-4 disabled:opacity-40">{busy ? "Checking records…" : "Ask Meridian"}</button>
    </form>
    {error && <p role="alert" className="text-red mt-5">{error}</p>}
    {answer && <section aria-live="polite" className="bg-panel border border-line rounded-xl p-6 mt-6"><h2 className="text-lg mb-3">{answer.supported ? "From your platform records" : "More context needed"}</h2><p className="leading-relaxed">{answer.answer}</p>{answer.metrics.map(m => <details key={m.label} className="text-sm mt-4"><summary className="cursor-pointer text-teal">{m.label}: {m.value} — inspect definition</summary><p className="text-ink-soft mt-2">{m.definition}</p><p className="text-xs text-ink-soft mt-1">Source: {m.source}</p></details>)}<p className="text-xs text-ink-soft mt-6">UTC window: {answer.period.start} – {answer.period.end}<br />Generated: {answer.generated_at}<br />{answer.scope}</p></section>}
  </div>;
}
