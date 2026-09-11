"use client";

import { useEffect, useState } from "react";
import {
  listTenants,
  updateTenant,
  deleteTenant,
  resetUserPassword,
  deactivateAndRefund,
  type PlatformTenant,
} from "@/lib/platformApi";
import { loadPlatformSession } from "@/lib/platformAuth";

const STATUS_OPTIONS = ["none", "pending", "active", "cancelled", "refunded"];
const PLAN_OPTIONS = ["basic", "pro", "premium"];
const PLAN_LABEL: Record<string, string> = { basic: "Basic", pro: "Pro", premium: "Premium" };

export default function PlatformTenantsPage() {
  const [tenants, setTenants] = useState<PlatformTenant[]>([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [editingSubdomainId, setEditingSubdomainId] = useState<string | null>(null);
  const [subdomainInput, setSubdomainInput] = useState("");
  const [subdomainError, setSubdomainError] = useState("");
  // Per sub-account status line after "Reset password" is clicked - keyed by
  // user id so multiple rows can show independent outcomes at once.
  const [resetStatus, setResetStatus] = useState<Record<string, string>>({});
  // Owner-only fraud/abuse override state - separate from the delete
  // confirmation block below, since this one needs a reason, not a
  // type-the-name confirmation.
  const [refundingId, setRefundingId] = useState<string | null>(null);
  const [refundReason, setRefundReason] = useState("");
  const [refundError, setRefundError] = useState("");
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

  async function handlePlanChange(tenantId: string, plan: string) {
    try {
      await updateTenant(tenantId, { plan });
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleSubdomainSave(tenantId: string) {
    setSubdomainError("");
    try {
      await updateTenant(tenantId, { subdomain: subdomainInput.trim().toLowerCase() });
      setEditingSubdomainId(null);
      refresh();
    } catch (e) {
      setSubdomainError((e as Error).message);
    }
  }

  async function handleDelete(tenant: PlatformTenant) {
    // Compare trimmed: a tenant whose stored name has a stray leading or
    // trailing space (older signups didn't trim it — see the backend's
    // /auth/register) is otherwise impossible to confirm here, since the
    // padding is invisible in the input and the placeholder.
    if (confirmText.trim() !== tenant.name.trim()) return;
    try {
      await deleteTenant(tenant.id);
      setDeletingId(null);
      setConfirmText("");
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleResetPassword(tenantId: string, userId: string) {
    setResetStatus((prev) => ({ ...prev, [userId]: "Sending…" }));
    try {
      const { email } = await resetUserPassword(tenantId, userId);
      setResetStatus((prev) => ({ ...prev, [userId]: `Link sent to ${email}` }));
    } catch (e) {
      setResetStatus((prev) => ({ ...prev, [userId]: (e as Error).message }));
    }
  }

  async function handleDeactivateAndRefund(tenant: PlatformTenant) {
    setRefundError("");
    if (!refundReason.trim()) {
      setRefundError("A reason is required — it's written to the audit log.");
      return;
    }
    try {
      await deactivateAndRefund(tenant.id, refundReason.trim());
      setRefundingId(null);
      setRefundReason("");
      refresh();
    } catch (e) {
      setRefundError((e as Error).message);
    }
  }

  const q = search.trim().toLowerCase();
  const filteredTenants = q
    ? tenants.filter(
        (t) =>
          t.name.toLowerCase().includes(q) ||
          (t.subdomain ?? "").toLowerCase().includes(q) ||
          t.users.some((u) => u.email.toLowerCase().includes(q)),
      )
    : tenants;

  return (
    <div className="max-w-4xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Tenants</h1>
      <p className="text-[13.5px] text-ink-soft mb-8">
        Every organization on Meridian. Subscription status here overrides billing state directly —
        use it for comps/support overrides, not as a substitute for the real Paystack subscription.
      </p>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}

      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by name, subdomain, or user email…"
        className="w-full mb-4 text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
      />

      <div className="flex flex-col gap-3">
        {filteredTenants.map((t) => (
          <div key={t.id} className="bg-panel border border-line rounded-[4px] px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <div className="text-[13.5px] text-ink truncate">{t.name}</div>
                  <span
                    className={`text-[10.5px] px-1.5 py-0.5 rounded-[3px] shrink-0 ${
                      t.tier === "pro" ? "bg-teal-deep text-white" : "bg-line text-ink-soft"
                    }`}
                  >
                    {t.plan ? PLAN_LABEL[t.plan] : t.tier === "pro" ? "Pro" : "Free"}
                  </span>
                </div>
                <div className="text-[11.5px] text-ink-soft font-[family-name:var(--font-mono)] mt-0.5">
                  {t.user_count} user{t.user_count === 1 ? "" : "s"} · {t.connection_count} connection
                  {t.connection_count === 1 ? "" : "s"} · joined {new Date(t.created_at).toLocaleDateString()}
                </div>
                <div className="text-[11.5px] text-ink-soft font-[family-name:var(--font-mono)] mt-0.5 flex items-center gap-2">
                  <span>
                    {t.subdomain
                      ? `${t.subdomain}.${process.env.NEXT_PUBLIC_APEX_DOMAIN ?? "getmeridiananalytics.com"}`
                      : "no subdomain assigned"}
                  </span>
                  <button
                    onClick={() => {
                      setEditingSubdomainId(editingSubdomainId === t.id ? null : t.id);
                      setSubdomainInput(t.subdomain ?? "");
                      setSubdomainError("");
                    }}
                    className="text-teal hover:text-teal-deep transition-colors"
                  >
                    edit
                  </button>
                </div>
                {editingSubdomainId === t.id && (
                  <div className="flex items-center gap-2 mt-1.5">
                    <input
                      value={subdomainInput}
                      onChange={(e) => setSubdomainInput(e.target.value)}
                      placeholder="wamco"
                      className="text-[12px] font-[family-name:var(--font-mono)] border border-line rounded-[3px] px-2 py-1 bg-panel text-ink placeholder:text-ink-soft/50 w-40"
                    />
                    <button
                      onClick={() => handleSubdomainSave(t.id)}
                      className="text-[11.5px] px-2 py-1 rounded-[3px] bg-teal-deep text-white hover:bg-teal transition-colors"
                    >
                      Save
                    </button>
                    {subdomainError && <span className="text-[11.5px] text-red">{subdomainError}</span>}
                  </div>
                )}
                <div className="text-[11.5px] text-ink-soft font-[family-name:var(--font-mono)] mt-0.5">
                  {t.subscribed_at
                    ? `subscribed ${new Date(t.subscribed_at).toLocaleDateString()}`
                    : "never subscribed"}
                  {t.subscription_expires_at && (
                    <> · renews/expires {new Date(t.subscription_expires_at).toLocaleDateString()}</>
                  )}
                  {t.plan_amount_naira && <> · {t.plan_amount_naira}</>}
                </div>
                {(t.last_transaction_reference || t.paystack_customer_code) && (
                  <div className="text-[11px] text-ink-soft font-[family-name:var(--font-mono)] mt-0.5">
                    {t.last_transaction_reference && <>ref {t.last_transaction_reference}</>}
                    {t.last_transaction_reference && t.paystack_customer_code && <> · </>}
                    {t.paystack_customer_code && <>customer {t.paystack_customer_code}</>}
                  </div>
                )}
                <button
                  onClick={() => setExpandedId(expandedId === t.id ? null : t.id)}
                  className="text-[11.5px] text-teal hover:text-teal-deep transition-colors mt-1"
                >
                  {expandedId === t.id ? "Hide sub-accounts" : `Show sub-accounts (${t.user_count})`}
                </button>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                {t.tier === "pro" && (
                  <select
                    value={t.plan ?? ""}
                    onChange={(e) => handlePlanChange(t.id, e.target.value)}
                    title="Which plan to comp this tenant onto - only affects seat/connection limits, not the real Paystack subscription."
                    className="text-[12px] border border-line rounded-[3px] px-2 py-1 bg-panel text-ink"
                  >
                    {PLAN_OPTIONS.map((p) => (
                      <option key={p} value={p}>
                        {PLAN_LABEL[p]}
                      </option>
                    ))}
                  </select>
                )}
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
                {isOwner && t.subscription_status === "active" && (
                  <button
                    onClick={() => {
                      setRefundingId(refundingId === t.id ? null : t.id);
                      setRefundReason("");
                      setRefundError("");
                    }}
                    title="Fraud/abuse override: cancels the real Paystack subscription and refunds the last transaction in full."
                    className="text-[11.5px] text-red hover:opacity-70 transition-opacity"
                  >
                    Deactivate &amp; refund
                  </button>
                )}
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

            {expandedId === t.id && (
              <div className="mt-3 pt-3 border-t border-line">
                <div className="text-[11.5px] text-ink-soft mb-2">
                  Sub-accounts — every staff login under this tenant, oldest first.
                </div>
                <div className="flex flex-col gap-1.5">
                  {t.users.map((u) => (
                    <div
                      key={u.id}
                      className="flex items-center justify-between text-[12.5px] bg-paper border border-line rounded-[3px] px-3 py-1.5"
                    >
                      <span className="text-ink truncate">{u.email}</span>
                      <span className="flex items-center gap-3 shrink-0">
                        <span className="text-ink-soft capitalize">{u.role}</span>
                        <span className="text-ink-soft font-[family-name:var(--font-mono)]">
                          opened {new Date(u.created_at).toLocaleDateString()}
                        </span>
                        {resetStatus[u.id] ? (
                          <span className="text-ink-soft">{resetStatus[u.id]}</span>
                        ) : (
                          <button
                            onClick={() => handleResetPassword(t.id, u.id)}
                            title="Emails this user a one-time link to set a new password and sign in."
                            className="text-teal hover:text-teal-deep transition-colors"
                          >
                            Reset password
                          </button>
                        )}
                      </span>
                    </div>
                  ))}
                  {t.users.length === 0 && (
                    <div className="text-[12.5px] text-ink-soft">No sub-accounts.</div>
                  )}
                </div>
              </div>
            )}

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
                    disabled={confirmText.trim() !== t.name.trim()}
                    className="text-[12.5px] px-3 py-1.5 rounded-[3px] bg-red text-white disabled:opacity-40 hover:opacity-90 transition-opacity"
                  >
                    Permanently delete
                  </button>
                </div>
              </div>
            )}

            {refundingId === t.id && (
              <div className="mt-3 pt-3 border-t border-line">
                <div className="text-[12.5px] text-red mb-2">
                  This cancels {t.name}&apos;s real Paystack subscription and refunds their last
                  transaction in full, then marks the tenant cancelled. Use this only for confirmed
                  fraud or abuse — it&apos;s not a normal support action. Reason is required and is
                  written to the audit log.
                </div>
                <div className="flex items-center gap-2">
                  <input
                    value={refundReason}
                    onChange={(e) => setRefundReason(e.target.value)}
                    placeholder="Why — e.g. chargeback abuse, fake signup pattern"
                    className="flex-1 text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50"
                  />
                  <button
                    onClick={() => handleDeactivateAndRefund(t)}
                    disabled={!refundReason.trim()}
                    className="text-[12.5px] px-3 py-1.5 rounded-[3px] bg-red text-white disabled:opacity-40 hover:opacity-90 transition-opacity"
                  >
                    Deactivate &amp; refund
                  </button>
                </div>
                {refundError && <div className="text-[11.5px] text-red mt-1.5">{refundError}</div>}
              </div>
            )}
          </div>
        ))}
        {filteredTenants.length === 0 && !error && (
          <div className="text-[13px] text-ink-soft">
            {tenants.length === 0 ? "No tenants yet." : "No tenants match your search."}
          </div>
        )}
      </div>
    </div>
  );
}
