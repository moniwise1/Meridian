"use client";

import { useEffect, useState } from "react";
import { listTenants, updateTenant, deleteTenant, type PlatformTenant } from "@/lib/platformApi";
import { loadPlatformSession } from "@/lib/platformAuth";

const STATUS_OPTIONS = ["none", "pending", "active", "cancelled", "refunded"];

export default function PlatformTenantsPage() {
  const [tenants, setTenants] = useState<PlatformTenant[]>([]);
  const [error, setError] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const isOwner = loadPlatformSession()?.role === "owner";

  function refresh() {
    listTenants()
      .then(setTenants)
      .catch((e) => setError(e.message));
  }

  useEffect(refresh, []);

  async function handleStatusChange(tenantId: string, status: string) {
    try {
      await updateTenant(tenantId, { subscription_status: status });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleDelete(tenant: PlatformTenant) {
    if (confirmText !== tenant.name) return;
    try {
      await deleteTenant(tenant.id);
      setDeletingId(null);
      setConfirmText("");
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  return (
    <div className="max-w-4xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Tenants</h1>
      <p className="text-[13.5px] text-ink-soft mb-8">
        Every organization on Meridian. Subscription status here overrides billing state directly —
        use it for comps/support overrides, not as a substitute for the real Paystack subscription.
      </p>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}

      <div className="flex flex-col gap-3">
        {tenants.map((t) => (
          <div key={t.id} className="bg-panel border border-line rounded-[4px] px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[13.5px] text-ink truncate">{t.name}</div>
                <div className="text-[11.5px] text-ink-soft font-[family-name:var(--font-mono)] mt-0.5">
                  {t.user_count} user{t.user_count === 1 ? "" : "s"} · {t.connection_count} connection
                  {t.connection_count === 1 ? "" : "s"} · joined {new Date(t.created_at).toLocaleDateString()}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <select
                  value={t.subscription_status}
                  onChange={(e) => handleStatusChange(t.id, e.target.value)}
                  className="text-[12px] border border-line rounded-[3px] px-2 py-1 bg-panel text-ink"
                >
                  {STATUS_OPTIONS.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
                {isOwner && (
                  <button
                    onClick={() => {
                      setDeletingId(deletingId === t.id ? null : t.id);
                      setConfirmText("");
                    }}
                    className="text-[11.5px] text-red hover:opacity-70 transition-opacity"
                  >
                    Delete
                  </button>
                )}
              </div>
            </div>

            {deletingId === t.id && (
              <div className="mt-3 pt-3 border-t border-line">
                <div className="text-[12.5px] text-red mb-2">
                  This permanently deletes {t.name} and everything scoped to it — users, connections,
                  analyses, documents, tickets, audit history. There is no undo. Type the
                  organization&apos;s name to confirm.
                </div>
                <div className="flex items-center gap-2">
                  <input
                    value={confirmText}
                    onChange={(e) => setConfirmText(e.target.value)}
                    placeholder={t.name}
                    className="flex-1 text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50"
                  />
                  <button
                    onClick={() => handleDelete(t)}
                    disabled={confirmText !== t.name}
                    className="text-[12.5px] px-3 py-1.5 rounded-[3px] bg-red text-white disabled:opacity-40 hover:opacity-90 transition-opacity"
                  >
                    Permanently delete
                  </button>
                </div>
              </div>
            )}
          </div>
        ))}
        {tenants.length === 0 && !error && <div className="text-[13px] text-ink-soft">No tenants yet.</div>}
      </div>
    </div>
  );
}
