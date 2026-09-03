"use client";

import { useEffect, useState } from "react";
import { listMyTickets, createTicket, replyToTicket, type SupportTicket } from "@/lib/api";

const STATUS_COLOR: Record<string, string> = {
  open: "bg-amber-soft text-amber",
  in_progress: "bg-amber-soft text-amber",
  resolved: "bg-teal-deep text-white",
  closed: "bg-line text-ink-soft",
};

export default function SupportPage() {
  const [tickets, setTickets] = useState<SupportTicket[]>([]);
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);

  function refresh() {
    listMyTickets()
      .then(setTickets)
      .catch((e) => setError(e.message));
  }

  useEffect(refresh, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!subject.trim() || !message.trim()) return;
    setBusy(true);
    setError("");
    try {
      const ticket = await createTicket(subject, message);
      setSubject("");
      setMessage("");
      refresh();
      setOpenId(ticket.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleReply(ticketId: string) {
    if (!reply.trim()) return;
    setBusy(true);
    setError("");
    try {
      await replyToTicket(ticketId, reply);
      setReply("");
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Support</h1>
      <p className="text-[13.5px] text-ink-soft mb-8">
        Questions, issues, or requests — our team replies here.
      </p>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}

      <form onSubmit={handleCreate} className="bg-panel border border-line rounded-[4px] p-5 mb-8">
        <div className="text-[13px] text-ink-soft mb-3">New ticket</div>
        <input
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          placeholder="Subject"
          className="w-full text-[13px] border border-line rounded-[3px] px-3 py-2 mb-2 bg-panel text-ink placeholder:text-ink-soft/60"
        />
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Describe the issue or question…"
          rows={3}
          className="w-full text-[13px] border border-line rounded-[3px] px-3 py-2 bg-panel text-ink placeholder:text-ink-soft/60 resize-none"
        />
        <div className="flex justify-end mt-3">
          <button
            type="submit"
            disabled={busy || !subject.trim() || !message.trim()}
            className="text-[13px] px-4 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
          >
            {busy ? "Sending…" : "Submit"}
          </button>
        </div>
      </form>

      <div className="flex flex-col gap-3">
        {tickets.map((t) => (
          <div key={t.id} className="bg-panel border border-line rounded-[4px] px-4 py-3">
            <button
              onClick={() => setOpenId(openId === t.id ? null : t.id)}
              className="w-full flex items-center justify-between gap-3 text-left"
            >
              <div className="min-w-0">
                <div className="text-[13.5px] text-ink truncate">{t.subject}</div>
                <div className="text-[11.5px] text-ink-soft mt-0.5">
                  {new Date(t.updated_at).toLocaleString()} · {t.messages.length} message
                  {t.messages.length === 1 ? "" : "s"}
                </div>
              </div>
              <span className={`text-[11px] px-2 py-0.5 rounded-[3px] shrink-0 ${STATUS_COLOR[t.status]}`}>
                {t.status.replace("_", " ")}
              </span>
            </button>

            {openId === t.id && (
              <div className="mt-3 pt-3 border-t border-line flex flex-col gap-3">
                {t.messages.map((m) => (
                  <div key={m.id} className={m.author_type === "staff" ? "pl-3 border-l-2 border-teal" : ""}>
                    <div className="text-[11.5px] text-ink-soft mb-0.5">
                      {m.author_type === "staff" ? `${m.author_label} (support)` : m.author_label} ·{" "}
                      {new Date(m.created_at).toLocaleString()}
                    </div>
                    <div className="text-[13px] text-ink whitespace-pre-wrap">{m.body}</div>
                  </div>
                ))}
                <div className="flex items-center gap-2 mt-1">
                  <input
                    value={reply}
                    onChange={(e) => setReply(e.target.value)}
                    placeholder="Reply…"
                    className="flex-1 text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/60"
                  />
                  <button
                    onClick={() => handleReply(t.id)}
                    disabled={busy || !reply.trim()}
                    className="text-[12.5px] px-3 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
                  >
                    Send
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
        {tickets.length === 0 && !error && <div className="text-[13px] text-ink-soft">No tickets yet.</div>}
      </div>
    </div>
  );
}
