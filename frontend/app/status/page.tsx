"use client";

import { useEffect, useState } from "react";
import { getPublicStatus, type PublicStatus } from "@/lib/api";

const SEVERITY_COLOR: Record<string, string> = {
  minor: "bg-line text-ink-soft",
  major: "bg-amber-soft text-amber",
  critical: "bg-red text-white",
};

export default function PublicStatusPage() {
  const [status, setStatus] = useState<PublicStatus | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getPublicStatus()
      .then(setStatus)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div className="min-h-screen bg-paper">
      <div className="max-w-2xl mx-auto px-8 py-16">
        <div className="text-[16px] font-semibold tracking-tight text-ink mb-1">Meridian</div>
        <div className="text-[12px] text-ink-soft mb-10">System status</div>

        {error && <div className="mb-6 text-[13px] text-red">{error}</div>}

        {status && (
          <div
            className={`rounded-[4px] px-5 py-4 mb-10 border ${
              status.operational ? "border-line bg-panel" : "border-amber bg-amber-soft"
            }`}
          >
            <div className={`text-[15px] font-medium ${status.operational ? "text-ink" : "text-amber"}`}>
              {status.operational ? "All systems operational" : "We're aware of an issue"}
            </div>
          </div>
        )}

        <div className="text-[13px] text-ink-soft mb-4">Incident history (last 90 days)</div>
        <div className="flex flex-col gap-3">
          {status?.incidents.map((incident) => (
            <div key={incident.id} className="bg-panel border border-line rounded-[4px] px-4 py-3">
              <div className="flex items-center justify-between gap-3 mb-2">
                <div className="text-[13.5px] text-ink">{incident.title}</div>
                <span
                  className={`text-[11px] px-2 py-0.5 rounded-[3px] shrink-0 ${SEVERITY_COLOR[incident.severity]}`}
                >
                  {incident.severity}
                </span>
              </div>
              <div className="flex flex-col gap-1.5">
                {incident.updates.map((u, i) => (
                  <div key={i} className="text-[12.5px]">
                    <span className="text-ink-soft">
                      [{new Date(u.created_at).toLocaleString()}] {u.status} —{" "}
                    </span>
                    <span className="text-ink">{u.body}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
          {status && status.incidents.length === 0 && (
            <div className="text-[13px] text-ink-soft">No incidents in the last 90 days.</div>
          )}
        </div>
      </div>
    </div>
  );
}
