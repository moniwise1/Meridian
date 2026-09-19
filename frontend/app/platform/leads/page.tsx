"use client";

import { useCallback, useEffect, useState } from "react";
import { listLeads, setLeadStatus, addLeadComment, type Lead } from "@/lib/platformApi";
import GlideSegmented from "@/components/glide/GlideSegmented";

const STATUSES = [
  { value: "open", label: "Open" },
  { value: "won", label: "Won" },
  { value: "not_interested", label: "Not interested" },
  { value: "closed", label: "Closed" },
] as const;

const STATUS_STYLE: Record<string, string> = {
  open: "bg-amber-soft text-amber",
  won: "bg-teal-deep text-white",
  not_interested: "bg-line text-ink-soft",
  closed: "bg-line text-ink-soft",
};

function CopyButton({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        } catch {
          // Clipboard access can be refused (an insecure origin, or the
          // browser's own permission). Say so rather than looking broken.
          setCopied(false);
          window.prompt(`Copy this ${label}:`, value);
        }
      }}
      className="text-[11.5px] px-2 py-0.5 rounded-[3px] border border-line text-ink-soft hover:text-teal hover:border-teal transition-colors"
    >
      {copied ? "Copied" : `Copy ${label}`}
    </button>
  );
}

function LeadCard({ lead, onChanged }: { lead: Lead; onChanged: (next: Lead) => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  async function run(action: () => Promise<Lead>) {
    setBusy(true);
    setError("");
    try {
      onChanged(await action());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="bg-panel border border-line rounded-[4px] p-4">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="min-w-0">
          <div className="text-[14px] text-ink font-medium">{lead.full_name}</div>
          <div className="text-[12.5px] text-ink-soft">
            {lead.business_name || <span className="italic">No business name given</span>}
          </div>
        </div>
        <span className={`text-[11px] px-2 py-0.5 rounded-[3px] shrink-0 ${STATUS_STYLE[lead.status]}`}>
          {STATUSES.find((s) => s.value === lead.status)?.label ?? lead.status}
        </span>
      </div>

      <div className="mt-3 flex flex-col gap-1.5 text-[12.5px]">
        <div className="flex items-center gap-2 flex-wrap">
          <a href={`tel:${lead.phone}`} className="text-teal hover:text-teal-deep transition-colors font-[family-name:var(--font-mono)]">
            {lead.phone}
          </a>
          <CopyButton value={lead.phone} label="number" />
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <a href={`mailto:${lead.email}`} className="text-teal hover:text-teal-deep transition-colors break-all">
            {lead.email}
          </a>
          <CopyButton value={lead.email} label="email" />
        </div>
      </div>

      {lead.message && (
        <p className="mt-3 text-[12.5px] text-ink leading-relaxed bg-paper rounded-[3px] p-2.5">{lead.message}</p>
      )}

      <div className="mt-3 flex items-center gap-2 flex-wrap text-[11.5px] text-ink-soft">
        <span>Came in {new Date(lead.created_at).toLocaleDateString()}</span>
        {lead.source && <span>· via {lead.source}</span>}
        {lead.campaign && <span>· {lead.campaign}</span>}
        {!lead.consented && <span className="text-amber">· did not tick the contact box</span>}
        {!lead.in_sheet && (
          <span className="text-amber" title={lead.sheet_error ?? "Waiting to be written to the sheet"}>
            · not in your sheet yet
          </span>
        )}
      </div>

      <div className="mt-4">
        <GlideSegmented
          ariaLabel={`Status for ${lead.full_name}`}
          options={STATUSES.map((s) => ({ value: s.value, label: s.label }))}
          value={lead.status}
          onChange={(next) => {
            if (next !== lead.status) void run(() => setLeadStatus(lead.id, next));
          }}
        />
      </div>

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="mt-3 text-[12px] text-teal hover:text-teal-deep transition-colors"
      >
        {open ? "Hide notes" : `Notes & history (${lead.comments.length})`}
      </button>

      {open && (
        <div className="mt-2 flex flex-col gap-2">
          {lead.comments.length === 0 && <p className="text-[12px] text-ink-soft">Nothing recorded yet.</p>}
          {lead.comments.map((c) => (
            <div key={c.id} className="text-[12.5px] bg-paper rounded-[3px] p-2.5">
              <div className={c.kind === "status" ? "text-ink-soft italic" : "text-ink"}>{c.body}</div>
              <div className="text-[11px] text-ink-soft mt-1">
                {c.staff_email ?? "From the enquiry"} · {new Date(c.created_at).toLocaleString()}
              </div>
            </div>
          ))}
          <form
            className="flex gap-2 mt-1"
            onSubmit={(e) => {
              e.preventDefault();
              const text = note.trim();
              if (!text) return;
              void run(async () => {
                const next = await addLeadComment(lead.id, text);
                setNote("");
                return next;
              });
            }}
          >
            <input
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={2000}
              placeholder="What happened on the call?"
              className="flex-1 min-w-0 text-[12.5px] border border-line rounded-[3px] px-2.5 py-1.5 bg-paper text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
            />
            <button
              disabled={busy || !note.trim()}
              className="text-[12px] px-3 py-1.5 rounded-[3px] bg-teal-deep text-white hover:bg-teal transition-colors disabled:opacity-40"
            >
              Add note
            </button>
          </form>
        </div>
      )}

      {error && <div role="alert" className="mt-2 text-[12px] text-red">{error}</div>}
    </div>
  );
}

export default function PlatformLeadsPage() {
  const [leads, setLeads] = useState<Lead[]>([]);
  const [filter, setFilter] = useState("");
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(() => {
    setLoading(true);
    listLeads(filter || undefined, search || undefined)
      .then((rows) => {
        setLeads(rows);
        setError("");
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [filter, search]);

  useEffect(() => {
    // Debounced so typing in the search box doesn't fire a request per key.
    const id = setTimeout(refresh, search ? 300 : 0);
    return () => clearTimeout(id);
  }, [refresh, search]);

  return (
    <div className="max-w-4xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Leads</h1>
      <p className="text-[13.5px] text-ink-soft mb-6">
        Everyone who registered their interest through the website or an ad.
      </p>

      <GlideSegmented
        variant="underline"
        ariaLabel="Filter leads by status"
        options={[{ value: "", label: "All" }, ...STATUSES.map((s) => ({ value: s.value, label: s.label }))]}
        value={filter}
        onChange={setFilter}
        className="mb-6"
      />

      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by name, business, email or phone…"
        className="w-full mb-6 text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
      />

      {error && <div role="alert" className="mb-4 text-[13px] text-red">{error}</div>}

      {loading && leads.length === 0 ? (
        <div className="text-[13px] text-ink-soft">Loading…</div>
      ) : leads.length === 0 ? (
        <div className="text-[13px] text-ink-soft">
          {search || filter ? "No leads match that." : "No leads yet. They'll appear here as they come in."}
        </div>
      ) : (
        <div className="flex flex-col gap-3">
          {leads.map((lead) => (
            <LeadCard
              key={lead.id}
              lead={lead}
              onChanged={(next) => setLeads((prev) => prev.map((l) => (l.id === next.id ? next : l)))}
            />
          ))}
        </div>
      )}
    </div>
  );
}
