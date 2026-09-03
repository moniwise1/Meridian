"use client";

import { useEffect, useState } from "react";
import { listIncidents, createIncident, addIncidentUpdate, type Incident } from "@/lib/platformApi";

const SEVERITY_COLOR: Record<string, string> = {
  minor: "bg-line text-ink-soft",
  major: "bg-amber-soft text-amber",
  critical: "bg-red text-white",
};

const STATUS_STEPS = ["investigating", "identified", "monitoring", "resolved"];

export default function PlatformStatusPage() {
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [error, setError] = useState("");
  const [showNew, setShowNew] = useState(false);
  const [title, setTitle] = useState("");
  const [severity, setSeverity] = useState("minor");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [updateDrafts, setUpdateDrafts] = useState<Record<string, string>>({});

  function refresh() {
    listIncidents()
      .then(setIncidents)
      .catch((e) => setError(e.message));
  }

  useEffect(refresh, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!title.trim() || !body.trim()) return;
    setBusy(true);
    try {
      await createIncident(title, severity, body);
      setTitle("");
      setBody("");
      setShowNew(false);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handlePostUpdate(incidentId: string, status: string) {
    const draft = updateDrafts[incidentId];
    if (!draft?.trim()) return;
    setBusy(true);
    try {
      await addIncidentUpdate(incidentId, status, draft);
      setUpdateDrafts({ ...updateDrafts, [incidentId]: "" });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <div className="flex items-start justify-between gap-4 mb-1.5">
        <h1 className="text-[22px] font-medium text-ink tracking-tight">Status</h1>
        <button
          onClick={() => setShowNew((v) => !v)}
          className="text-[12.5px] px-3 py-1.5 rounded-[3px] border border-line text-ink hover:border-teal hover:text-teal transition-colors"
        >
          {showNew ? "Cancel" : "New incident"}
        </button>
      </div>
      <p className="text-[13.5px] text-ink-soft mb-6">
        Manually-logged incidents — the content behind a public status page, same convention as most
        SaaS status pages (a human posts what&apos;s happening). This is not automated uptime
        probing; pair it with a real monitoring tool for that.
      </p>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}

      {showNew && (
        <form onSubmit={handleCreate} className="bg-panel border border-line rounded-[4px] p-5 mb-8">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Incident title"
            className="w-full text-[13px] border border-line rounded-[3px] px-3 py-2 mb-2 bg-panel text-ink placeholder:text-ink-soft/60"
          />
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
            className="text-[13px] border border-line rounded-[3px] px-2 py-1.5 mb-2 bg-panel text-ink"
          >
            <option value="minor">Minor</option>
            <option value="major">Major</option>
            <option value="critical">Critical</option>
          </select>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="What's happening…"
            rows={3}
            className="w-full text-[13px] border border-line rounded-[3px] px-3 py-2 bg-panel text-ink placeholder:text-ink-soft/60 resize-none"
          />
          <div className="flex justify-end mt-3">
            <button
              type="submit"
              disabled={busy || !title.trim() || !body.trim()}
              className="text-[13px] px-4 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
            >
              Post incident
            </button>
          </div>
        </form>
      )}

      <div className="flex flex-col gap-3">
        {incidents.map((incident) => (
          <div key={incident.id} className="bg-panel border border-line rounded-[4px] px-4 py-3">
            <div className="flex items-center justify-between gap-3 mb-2">
              <div className="text-[13.5px] text-ink">{incident.title}</div>
              <span className={`text-[11px] px-2 py-0.5 rounded-[3px] shrink-0 ${SEVERITY_COLOR[incident.severity]}`}>
                {incident.severity}
              </span>
            </div>
            <div className="flex flex-col gap-2 mb-3">
              {incident.updates.map((u) => (
                <div key={u.id} className="text-[12.5px]">
                  <span className="text-ink-soft">
                    [{new Date(u.created_at).toLocaleString()}] {u.status} —{" "}
                  </span>
                  <span className="text-ink">{u.body}</span>
                </div>
              ))}
            </div>
            {incident.status !== "resolved" && (
              <div className="flex items-center gap-2 pt-2 border-t border-line">
                <input
                  value={updateDrafts[incident.id] ?? ""}
                  onChange={(e) => setUpdateDrafts({ ...updateDrafts, [incident.id]: e.target.value })}
                  placeholder="Post an update…"
                  className="flex-1 text-[12.5px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/60"
                />
                {STATUS_STEPS.filter((s) => s !== incident.status).map((s) => (
                  <button
                    key={s}
                    onClick={() => handlePostUpdate(incident.id, s)}
                    disabled={busy || !updateDrafts[incident.id]?.trim()}
                    className="text-[11.5px] px-2.5 py-1.5 rounded-[3px] border border-line text-ink hover:border-teal hover:text-teal transition-colors disabled:opacity-40 whitespace-nowrap"
                  >
                    Mark {s}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
        {incidents.length === 0 && !error && (
          <div className="text-[13px] text-ink-soft">No incidents logged — all clear.</div>
        )}
      </div>
    </div>
  );
}
