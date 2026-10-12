"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import DashboardIcon from "@/components/DashboardIcon";
import { saveAskDraft } from "@/lib/askDraft";
export default function AskLauncher({ platform = false, compact = false }: { platform?: boolean; compact?: boolean }) {
  const router = useRouter();
  const [error, setError] = useState("");
  return <div className={compact ? "min-w-0 flex-1 w-full max-w-md" : "mb-4"}><form className={compact ? "flex items-center gap-2 border border-line rounded-lg bg-paper/60 px-3 py-2" : "flex gap-2"} onSubmit={event => {
    event.preventDefault();
    const question = String(new FormData(event.currentTarget).get("question") ?? "");
    try { saveAskDraft(question, platform); setError(""); router.push(platform ? "/platform/ask" : "/"); }
    catch { setError("Open Ask and enter your question there; browser storage is unavailable."); }
  }}>{compact && <span className="text-teal"><DashboardIcon name="chat" size={16} /></span>}<input required name="question" maxLength={platform ? 1000 : 8000} aria-label={platform ? "Ask about platform records" : "Ask about your data"} placeholder={compact ? platform ? "Ask about accounts, usage or support…" : "Ask about your files or connected data…" : "Ask a question…"} className={compact ? "bg-transparent outline-none min-w-0 flex-1 text-xs text-ink placeholder:text-ink-soft" : "border border-line rounded-md bg-panel p-2 text-xs w-full min-w-0"} /><button aria-label="Open Ask Meridian" className={compact ? "text-teal" : "bg-teal-deep text-white rounded-md p-2"}><DashboardIcon name="arrow" size={15} /></button></form>{error && <p role="alert" className="text-[10px] text-red mt-2">{error}</p>}</div>;
}
