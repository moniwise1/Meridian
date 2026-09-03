"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { getHealthSnapshot, type HealthSnapshot } from "@/lib/platformApi";

function StatCard({ label, value, warn }: { label: string; value: number; warn?: boolean }) {
  return (
    <div className="bg-panel border border-line rounded-[4px] px-4 py-3.5">
      <div className={`text-[22px] font-medium tracking-tight tabular-nums ${warn && value > 0 ? "text-red" : "text-ink"}`}>
        {value}
      </div>
      <div className="text-[12px] text-ink-soft mt-0.5">{label}</div>
    </div>
  );
}

export default function PlatformDashboardPage() {
  const [snapshot, setSnapshot] = useState<HealthSnapshot | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getHealthSnapshot()
      .then(setSnapshot)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Dashboard</h1>
      <p className="text-[13.5px] text-ink-soft mb-8">
        A rough internal signal, not a substitute for real uptime monitoring — pair this with a
        third-party status/alerting tool for actual multi-region probing.
      </p>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}

      {snapshot && (
        <div className="grid grid-cols-3 gap-3 mb-10">
          <StatCard label="Active tenants" value={snapshot.active_tenants} />
          <StatCard label="Total tenants" value={snapshot.total_tenants} />
          <StatCard label="Errors, last hour" value={snapshot.recent_errors_last_hour} warn />
          <StatCard label="Open tickets" value={snapshot.open_tickets} warn />
          <StatCard label="Open incidents" value={snapshot.open_incidents} warn />
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <Link
          href="/platform/tenants"
          className="text-[13px] px-4 py-1.5 rounded-[3px] border border-line text-ink hover:border-teal hover:text-teal transition-colors"
        >
          Manage tenants
        </Link>
        <Link
          href="/platform/tickets"
          className="text-[13px] px-4 py-1.5 rounded-[3px] border border-line text-ink hover:border-teal hover:text-teal transition-colors"
        >
          View tickets
        </Link>
        <Link
          href="/platform/status"
          className="text-[13px] px-4 py-1.5 rounded-[3px] border border-line text-ink hover:border-teal hover:text-teal transition-colors"
        >
          Manage status page
        </Link>
      </div>
    </div>
  );
}
