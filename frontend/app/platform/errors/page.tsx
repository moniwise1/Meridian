"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listRecentErrors, type PlatformErrorEntry } from "@/lib/platformApi";

const WINDOWS = [
  { label: "Last hour", hours: 1 },
  { label: "Last 24 hours", hours: 24 },
  { label: "Last 7 days", hours: 24 * 7 },
] as const;

export default function PlatformErrorsPage() {
  const [hours, setHours] = useState<number>(1);
  const [entries, setEntries] = useState<PlatformErrorEntry[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    // Resets happen inside the promise callbacks, not synchronously in the
    // effect body (react-hooks/set-state-in-effect) - `loading` therefore
    // only covers the very first fetch; switching windows afterward just
    // swaps the list in place once the new one resolves, no blank flash.
    listRecentErrors(hours)
      .then((data) => {
        setEntries(data);
        setError("");
      })
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [hours]);

  const q = search.trim().toLowerCase();
  const filtered = q
    ? entries.filter(
        (e) =>
          e.action.toLowerCase().includes(q) ||
          e.tenant_name.toLowerCase().includes(q) ||
          JSON.stringify(e.detail).toLowerCase().includes(q),
      )
    : entries;

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <Link href="/platform" className="text-[12.5px] text-teal hover:text-teal-deep transition-colors">
        ← Dashboard
      </Link>
      <h1 className="text-[22px] font-medium text-ink tracking-tight mt-2 mb-1.5">
        Recent errors
      </h1>
      <p className="text-[13.5px] text-ink-soft mb-6">
        The audit-log rows behind the Dashboard&apos;s error count — across every tenant, not just
        one. A rough internal signal (see the Dashboard&apos;s own note), not a substitute for real
        error tracking.
      </p>

      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div className="flex gap-1">
          {WINDOWS.map((w) => (
            <button
              key={w.hours}
              onClick={() => setHours(w.hours)}
              className={`text-[12.5px] px-3 py-1.5 rounded-[3px] transition-colors ${
                hours === w.hours
                  ? "bg-teal-deep text-white"
                  : "border border-line text-ink-soft hover:border-teal hover:text-teal"
              }`}
            >
              {w.label}
            </button>
          ))}
        </div>
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by tenant, action, or detail…"
          className="text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal w-64"
        />
      </div>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}
      {loading && <div className="text-[13px] text-ink-soft">Loading…</div>}

      {!loading && !error && (
        <div className="flex flex-col">
          {filtered.map((e) => (
            <div key={e.id} className="border-b border-line py-3 flex items-start gap-4">
              <div className="w-40 shrink-0 text-[11.5px] text-ink-soft font-[family-name:var(--font-mono)] pt-0.5">
                {new Date(e.timestamp).toLocaleString()}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-[13px] text-ink">{e.action.replace(/_/g, " ")}</span>
                  <span className="text-[10.5px] px-1.5 py-0.5 rounded-[2px] bg-amber-soft text-amber">
                    error
                  </span>
                  <span className="text-[11px] text-ink-soft">{e.tenant_name}</span>
                </div>
                {Object.keys(e.detail).length > 0 && (
                  <div className="text-[12px] text-ink-soft font-[family-name:var(--font-mono)] mt-1 break-words">
                    {JSON.stringify(e.detail)}
                  </div>
                )}
              </div>
            </div>
          ))}
          {filtered.length === 0 && (
            <div className="text-[13px] text-ink-soft">
              {entries.length === 0
                ? "No errors in this window — good sign."
                : "No errors match your search."}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
