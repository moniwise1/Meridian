"use client";

import { useEffect, useRef, useState } from "react";
import { analystRequest, type SavedConversation } from "@/lib/api";
import type { AnalystWorkspaceData } from "@/lib/analyst";

// Everything in here is scoped to one user AND one source on the backend
// (see backend/app/api/routes_analyst.py) - a teammate on the same tenant
// never sees these notes or conversations, so the copy says so plainly
// rather than leaving the user to guess.

export default function AnalystWorkspace({
  sourceKey,
  disabled,
  revision,
  onResume,
}: {
  sourceKey: string;
  disabled: boolean;
  // Bumped by the parent after every completed analysis, so a new
  // conversation shows up in the list without needing a manual refresh.
  revision: number;
  onResume: (conversation: SavedConversation) => void;
}) {
  const mounted = useRef(true);
  const [data, setData] = useState<AnalystWorkspaceData | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    // `active` rather than mounted.current: this guards against an older,
    // slower request for a PREVIOUS source landing after a newer one and
    // overwriting it, which unmount alone wouldn't catch.
    let active = true;
    analystRequest<AnalystWorkspaceData>(`/workspace?source_key=${encodeURIComponent(sourceKey)}`)
      .then((d) => {
        if (active) {
          setData(d);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError((e as Error).message);
      });
    return () => {
      active = false;
    };
  }, [sourceKey, revision, refresh]);

  async function act(action: () => Promise<unknown>) {
    if (busy || disabled) return;
    setBusy(true);
    setError("");
    try {
      await action();
      if (mounted.current) setRefresh((n) => n + 1);
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  const newFindings = data?.findings.filter((f) => f.status === "new") ?? [];
  const checksPending = data?.checks.some((c) => c.status !== "complete") ?? false;
  const checksExhausted = data?.checks.some((c) => c.attempts >= 3) ?? false;

  return (
    <section className="mb-7 border border-line rounded-[4px] p-4 text-[13px]">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <h2 className="font-medium text-ink text-[13.5px]">Your analyst workspace</h2>
        <button
          type="button"
          disabled={busy || disabled}
          onClick={() => setRefresh((n) => n + 1)}
          className="shrink-0 text-[12px] text-teal hover:text-teal-deep transition-colors disabled:opacity-40"
        >
          Refresh
        </button>
      </div>
      <p className="mt-1 text-[12.5px] text-ink-soft">
        Notes and conversations here are private to you and to this source.
      </p>

      {error && (
        <p role="alert" className="mt-3 text-[12.5px] text-red">
          {error}
        </p>
      )}

      {data && (
        <div className="mt-4 flex flex-col gap-4">
          {checksPending && (
            <p className="text-[12.5px] text-ink-soft">
              {checksExhausted
                ? "A check on this upload could not finish. The file is still available for questions."
                : "Checks on this upload are queued or running. Refresh to see the results."}
            </p>
          )}

          {newFindings.map((f) => (
            <article key={f.id} className="border border-amber/40 rounded-[3px] p-3">
              <div className="font-medium text-ink">{f.title}</div>
              <p className="mt-1 text-[12.5px] text-ink-soft leading-relaxed">{f.detail}</p>
              <p className="mt-2 text-[12px] text-ink-soft">
                {f.confidence.replaceAll("_", " ")} confidence · describes the uploaded snapshot only
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {(
                  [
                    ["acknowledged", "Reviewed"],
                    ["expected", "Expected"],
                    ["dismissed", "Dismiss"],
                  ] as const
                ).map(([status, label]) => (
                  <button
                    key={status}
                    type="button"
                    disabled={busy || disabled}
                    onClick={() => act(() => analystRequest(`/findings/${f.id}`, "PATCH", { status }))}
                    className="text-[12px] px-2.5 py-1 rounded-full border border-line text-ink-soft hover:text-ink hover:border-ink-soft transition-colors disabled:opacity-40"
                  >
                    {label}
                  </button>
                ))}
              </div>
            </article>
          ))}

          <details>
            <summary className="cursor-pointer text-[12.5px] text-ink-soft hover:text-ink transition-colors">
              Business definitions and corrections ({data.memories.length})
            </summary>
            <ul className="mt-2 flex flex-col gap-2">
              {data.memories.map((m) => (
                <li
                  key={m.id}
                  className="flex flex-wrap items-start justify-between gap-x-3 gap-y-1 bg-paper rounded-[3px] p-2 text-[12.5px]"
                >
                  <span className="min-w-0 break-words text-ink">{m.content}</span>
                  <button
                    type="button"
                    aria-label={`Remove note: ${m.content}`}
                    disabled={busy || disabled}
                    onClick={() => act(() => analystRequest(`/memory/${m.id}`, "DELETE"))}
                    className="shrink-0 text-teal hover:text-teal-deep transition-colors disabled:opacity-40"
                  >
                    Remove
                  </button>
                </li>
              ))}
            </ul>
            <form
              className="mt-3 flex flex-wrap gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                if (!note.trim()) return;
                void act(async () => {
                  await analystRequest("/memory", "POST", { source_key: sourceKey, content: note.trim() });
                  setNote("");
                });
              }}
            >
              <label className="sr-only" htmlFor="analyst-note">
                Definition or correction to remember
              </label>
              <input
                id="analyst-note"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={1000}
                placeholder="For us, revenue excludes refunds and tax."
                className="min-w-0 flex-1 border border-line rounded-[3px] bg-paper px-2.5 py-2 text-[12.5px] text-ink"
              />
              <button
                disabled={busy || disabled || !note.trim()}
                className="text-[12px] px-3 py-2 rounded-[3px] border border-teal/40 text-teal hover:text-teal-deep transition-colors disabled:opacity-40"
              >
                Save note
              </button>
            </form>
            <p className="mt-2 text-[12px] text-ink-soft">
              Only notes you save here are remembered. Nothing is inferred and stored on its own.
            </p>
          </details>

          <details>
            <summary className="cursor-pointer text-[12.5px] text-ink-soft hover:text-ink transition-colors">
              Saved conversations ({data.conversations.length})
            </summary>
            <div className="mt-2 flex flex-col gap-1">
              {data.conversations.map((c) => (
                <button
                  key={c.id}
                  type="button"
                  disabled={busy || disabled}
                  onClick={() =>
                    act(async () => {
                      const saved = await analystRequest<SavedConversation>(`/conversations/${c.id}`);
                      if (mounted.current) onResume(saved);
                    })
                  }
                  className="block w-full bg-paper rounded-[3px] p-2 text-left text-[12.5px] text-teal hover:text-teal-deep transition-colors disabled:opacity-40"
                >
                  {c.title}
                </button>
              ))}
              {data.conversations.length === 0 && (
                <p className="text-[12px] text-ink-soft">Your completed analyses will appear here.</p>
              )}
            </div>
          </details>
        </div>
      )}
    </section>
  );
}
