"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  listNotifications,
  markNotificationsRead,
  type AppNotification,
} from "@/lib/api";

const POLL_MS = 60_000;

// A small accent per notification kind — keeps the panel scannable
// without a whole icon set.
const KIND_ACCENT: Record<string, string> = {
  subscription_activated: "bg-teal",
  subscription_expiring: "bg-amber",
  subscription_cancelled: "bg-ink-soft",
  subscription_renewal_failed: "bg-red",
  teammate_joined: "bg-slate",
};

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  const secs = Math.round((Date.now() - then) / 1000);
  if (secs < 60) return "just now";
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.round(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

export default function NotificationBell() {
  const router = useRouter();
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const panelRef = useRef<HTMLDivElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      const data = await listNotifications();
      setItems(data.notifications);
      setUnread(data.unread_count);
      setLoaded(true);
    } catch {
      // Bell is ambient — a failed poll should never surface an error in
      // the chrome. Leave whatever was last shown; the next poll retries.
    }
  }, []);

  useEffect(() => {
    // Polling an external system (the notifications API) for updates — the
    // case react-hooks/set-state-in-effect explicitly allows; the setState
    // lands in refresh()'s async continuation, not synchronously here.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
    const id = window.setInterval(refresh, POLL_MS);
    const onFocus = () => refresh();
    window.addEventListener("focus", onFocus);
    return () => {
      window.clearInterval(id);
      window.removeEventListener("focus", onFocus);
    };
  }, [refresh]);

  // Close on Escape or a click outside the panel.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  async function handleMarkAll() {
    setUnread(0);
    setItems((prev) => prev.map((n) => ({ ...n, read: true })));
    try {
      const data = await markNotificationsRead();
      setItems(data.notifications);
      setUnread(data.unread_count);
    } catch {
      refresh();
    }
  }

  async function handleClick(n: AppNotification) {
    if (!n.read) {
      setItems((prev) => prev.map((x) => (x.id === n.id ? { ...x, read: true } : x)));
      setUnread((u) => Math.max(0, u - 1));
      markNotificationsRead([n.id]).catch(() => refresh());
    }
    setOpen(false);
    if (n.link) router.push(n.link);
  }

  return (
    <div className="relative">
      <button
        type="button"
        aria-label={unread > 0 ? `Notifications, ${unread} unread` : "Notifications"}
        onClick={() => setOpen((v) => !v)}
        className="relative flex h-7 w-7 items-center justify-center rounded-[4px] text-ink-soft hover:text-ink hover:bg-paper transition-colors"
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
          <path d="M13.73 21a2 2 0 0 1-3.46 0" />
        </svg>
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-red px-1 text-[10px] font-semibold leading-none text-white">
            {unread > 9 ? "9+" : unread}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div
            ref={panelRef}
            className="fixed left-3 top-14 z-50 w-[340px] max-h-[70vh] overflow-y-auto rounded-[6px] border border-line bg-panel shadow-lg"
          >
            <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
              <span className="text-[12.5px] font-medium text-ink">Notifications</span>
              {unread > 0 && (
                <button
                  type="button"
                  onClick={handleMarkAll}
                  className="text-[11.5px] text-teal hover:text-teal-deep transition-colors"
                >
                  Mark all read
                </button>
              )}
            </div>

            {loaded && items.length === 0 && (
              <div className="px-3.5 py-6 text-center text-[12.5px] text-ink-soft">
                Nothing yet. Updates to your subscription and team show up here.
              </div>
            )}

            <ul>
              {items.map((n) => {
                const clickable = Boolean(n.link);
                return (
                  <li key={n.id}>
                    <div
                      role={clickable ? "button" : undefined}
                      tabIndex={clickable ? 0 : undefined}
                      onClick={clickable ? () => handleClick(n) : undefined}
                      onKeyDown={
                        clickable
                          ? (e) => (e.key === "Enter" || e.key === " ") && handleClick(n)
                          : undefined
                      }
                      className={`flex gap-2.5 border-b border-line px-3.5 py-2.5 ${
                        clickable ? "cursor-pointer hover:bg-paper" : ""
                      } ${n.read ? "" : "bg-paper/60"}`}
                    >
                      <span
                        className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                          n.read ? "bg-transparent" : KIND_ACCENT[n.kind] ?? "bg-teal"
                        }`}
                      />
                      <div className="min-w-0 flex-1">
                        <div className={`text-[12.5px] ${n.read ? "text-ink-soft" : "text-ink font-medium"}`}>
                          {n.title}
                        </div>
                        {n.body && (
                          <div className="mt-0.5 text-[11.5px] leading-snug text-ink-soft">{n.body}</div>
                        )}
                        <div className="mt-1 text-[10.5px] text-ink-soft">{relativeTime(n.created_at)}</div>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        </>
      )}
    </div>
  );
}
