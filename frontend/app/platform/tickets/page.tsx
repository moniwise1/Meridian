"use client";

import { useEffect, useState } from "react";
import { listAllTickets, updateTicket, staffReplyToTicket, type PlatformTicket } from "@/lib/platformApi";

const STATUS_COLOR: Record<string, string> = {
  open: "bg-amber-soft text-amber",
  in_progress: "bg-amber-soft text-amber",
  resolved: "bg-teal-deep text-white",
  closed: "bg-line text-ink-soft",
};

const STATUS_OPTIONS = ["open", "in_progress", "resolved", "closed"];
const PRIORITY_OPTIONS = ["low", "normal", "high", "urgent"];

export default function PlatformTicketsPage() {
  const [tickets, setTickets] = useState<PlatformTicket[]>([]);
  const [filter, setFilter] = useState<string>("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);

  function refresh() {
    listAllTickets(filter || undefined)
      .then(setTickets)
      .catch((e) => setError(e.message));
  }

  useEffect(refresh, [filter]);

  async function handleStatusChange(ticketId: string, status: string) {
    try {
      await updateTicket(ticketId, { status });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handlePriorityChange(ticketId: string, priority: string) {
    try {
      await updateTicket(ticketId, { priority });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleReply(ticketId: string) {
    if (!reply.trim()) return;
    setBusy(true);
    try {
      await staffReplyToTicket(ticketId, reply);
      setReply("");
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const q = search.trim().toLowerCase();
  const filteredTickets = q
    ? tickets.filter((t) => t.subject.toLowerCase().includes(q) || t.tenant_name.toLowerCase().includes(q))
    : tickets;

  return (
    <div className="max-w-4xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Tickets</h1>
      <p className="text-[13.5px] text-ink-soft mb-6">Across every organization on Meridian.</p>

      <div className="flex items-center gap-1 mb-6 border-b border-line">
        {["", ...STATUS_OPTIONS].map((s) => (
          <button
            key={s || "all"}
            onClick={() => setFilter(s)}
            className={`text-[13px] px-3 py-2 -mb-px border-b-2 transition-colors ${
              filter === s ? "border-teal-deep text-ink" : "border-transparent text-ink-soft hover:text-ink"
            }`}
          >
            {s ? s.replace("_", " ") : "All"}
          </button>
        ))}
      </div>

      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by subject or organization…"
        className="w-full mb-6 text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
      />

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}

      <div className="flex flex-col gap-3">
        {filteredTickets.map((t) => (
          <div key={t.id} className="bg-panel border border-line rounded-[4px] px-4 py-3">
            <button
              onClick={() => setOpenId(openId === t.id ? null : t.id)}
              className="w-full flex items-center justify-between gap-3 text-left"
            >
              <div className="min-w-0">
                <div className="text-[13.5px] text-ink truncate">{t.subject}</div>
                <div className="text-[11.5px] text-ink-soft font-[family-name:var(--font-mono)] mt-0.5">
                  {t.tenant_name} · {new Date(t.updated_at).toLocaleString()}
                </div>
              </div>
              <span className={`text-[11px] px-2 py-0.5 rounded-[3px] shrink-0 ${STATUS_COLOR[t.status]}`}>
                {t.status.replace("_", " ")}
              </span>
            </button>

            {openId === t.id && (
              <div className="mt-3 pt-3 border-t border-line flex flex-col gap-3">
                <div className="flex items-center gap-2">
                  <select
                    value={t.status}
                    onChange={(e) => handleStatusChange(t.id, e.target.value)}
                    className="text-[12px] border border-line rounded-[3px] px-2 py-1 bg-panel text-ink"
                  >
                    {STATUS_OPTIONS.map((s) => (
                      <option key={s} value={s}>
                        {s.replace("_", " ")}
                      </option>
                    ))}
                  </select>
                  <select
                    value={t.priority}
                    onChange={(e) => handlePriorityChange(t.id, e.target.value)}
                    className="text-[12px] border border-line rounded-[3px] px-2 py-1 bg-panel text-ink"
                  >
                    {PRIORITY_OPTIONS.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </select>
                </div>

                {t.messages.map((m) => (
                  <div key={m.id} className={m.author_type === "staff" ? "pl-3 border-l-2 border-teal" : ""}>
                    <div className="text-[11.5px] text-ink-soft mb-0.5">
                      {m.author_type === "staff" ? `${m.author_label} (staff)` : m.author_label} ·{" "}
                      {new Date(m.created_at).toLocaleString()}
                    </div>
                    <div className="text-[13px] text-ink whitespace-pre-wrap">{m.body}</div>
                  </div>
                ))}

                <div className="flex items-center gap-2">
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
        {filteredTickets.length === 0 && !error && (
          <div className="text-[13px] text-ink-soft">
            {tickets.length === 0 ? "No tickets." : "No tickets match your search."}
          </div>
        )}
      </div>
    </div>
  );
}
