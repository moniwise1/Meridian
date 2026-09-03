"use client";

import { useEffect, useState } from "react";
import { getBillingStatus, subscribe, cancelSubscription, type BillingStatus } from "@/lib/api";
import { loadSession } from "@/lib/auth";

const STATUS_LABEL: Record<string, string> = {
  none: "No subscription",
  pending: "Payment pending",
  active: "Active",
  cancelled: "Cancelled",
  refunded: "Cancelled — refunded",
};

const STATUS_COLOR: Record<string, string> = {
  none: "bg-line text-ink-soft",
  pending: "bg-amber-soft text-amber",
  active: "bg-teal-deep text-white",
  cancelled: "bg-line text-ink-soft",
  refunded: "bg-line text-ink-soft",
};

export default function BillingPage() {
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const isAdmin = loadSession()?.role === "admin";

  function refresh() {
    getBillingStatus()
      .then(setStatus)
      .catch((e) => setError(e.message));
  }

  useEffect(refresh, []);

  async function handleSubscribe() {
    setBusy(true);
    setError("");
    try {
      const callbackUrl = `${window.location.origin}/billing/callback`;
      const result = await subscribe(callbackUrl);
      window.location.href = result.authorization_url;
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  async function handleCancel() {
    setBusy(true);
    setError("");
    try {
      const result = await cancelSubscription();
      setStatus(result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const withinRefundWindow =
    status?.subscription_status === "active" &&
    status.refund_eligible_until !== null &&
    new Date(status.refund_eligible_until) > new Date();

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Billing</h1>
      <p className="text-[13.5px] text-ink-soft mb-8">
        Meridian is billed from the moment you subscribe — there&apos;s no delayed-billing free
        trial. If it&apos;s not for you, cancel within 7 days of subscribing for a full refund; after
        that, cancelling stops future billing but the current period isn&apos;t refunded.
      </p>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}

      {!status ? (
        <div className="text-[13px] text-ink-soft">Loading…</div>
      ) : (
        <div className="bg-panel border border-line rounded-[4px] p-5">
          <div className="flex items-center justify-between mb-4">
            <div className="text-[13.5px] text-ink">Subscription status</div>
            <div className="flex items-center gap-2">
              <span
                className={`text-[11px] px-2 py-0.5 rounded-[3px] ${
                  status.tier === "pro" ? "bg-teal-deep text-white" : "bg-line text-ink-soft"
                }`}
              >
                {status.tier === "pro" ? "Pro" : "Free"}
              </span>
              <span className={`text-[11px] px-2 py-0.5 rounded-[3px] ${STATUS_COLOR[status.subscription_status]}`}>
                {STATUS_LABEL[status.subscription_status]}
              </span>
            </div>
          </div>

          {status.tier === "free" && (
            <div className="text-[12.5px] text-ink-soft mb-2">
              The free plan is read-mostly: 1 account, and Ask / Risk scan / connecting new data
              sources require Pro.
            </div>
          )}

          {status.paid_at && (
            <div className="text-[12.5px] text-ink-soft mb-2">
              Subscribed: {new Date(status.paid_at).toLocaleDateString()}
            </div>
          )}

          {status.subscription_expires_at && status.subscription_status === "active" && (
            <div className="text-[12.5px] text-ink-soft mb-2">
              Renews: {new Date(status.subscription_expires_at).toLocaleDateString()}
            </div>
          )}

          {withinRefundWindow && status.refund_eligible_until && (
            <div className="text-[12.5px] text-amber mb-4">
              Eligible for a full refund if you cancel before{" "}
              {new Date(status.refund_eligible_until).toLocaleDateString()}.
            </div>
          )}

          {!isAdmin && status.subscription_status !== "active" && (
            <div className="text-[13px] text-ink-soft">
              Only an admin can manage billing for this organization.
            </div>
          )}

          {isAdmin && (status.subscription_status === "none" || status.subscription_status === "cancelled" || status.subscription_status === "refunded") && (
            <button
              onClick={handleSubscribe}
              disabled={busy}
              className="text-[13px] px-4 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
            >
              {busy ? "Redirecting to checkout…" : "Subscribe"}
            </button>
          )}

          {isAdmin && status.subscription_status === "pending" && (
            <div className="text-[13px] text-ink-soft">
              Waiting for payment confirmation. If you completed checkout and this doesn&apos;t
              update, refresh this page in a moment.
            </div>
          )}

          {isAdmin && status.subscription_status === "active" && (
            <button
              onClick={handleCancel}
              disabled={busy}
              className="text-[13px] px-4 py-1.5 rounded-[3px] border border-line text-ink hover:border-red hover:text-red transition-colors disabled:opacity-40"
            >
              {busy ? "Working…" : withinRefundWindow ? "Cancel & get a full refund" : "Cancel subscription"}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
