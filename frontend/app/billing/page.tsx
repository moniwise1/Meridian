"use client";

import { useEffect, useState } from "react";
import { getBillingStatus, listPlans, subscribe, cancelSubscription, type BillingStatus, type Plan } from "@/lib/api";
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

function formatNaira(amountKobo: number): string {
  return `₦${(amountKobo / 100).toLocaleString("en-NG", { maximumFractionDigits: 0 })}`;
}

export default function BillingPage() {
  const [status, setStatus] = useState<BillingStatus | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null); // plan key currently subscribing, or "cancel"
  const isAdmin = loadSession()?.role === "admin";

  function refresh() {
    getBillingStatus()
      .then(setStatus)
      .catch((e) => setError(e.message));
    listPlans()
      .then(setPlans)
      .catch(() => {
        /* Status panel still works without plan cards - just no pricing shown */
      });
  }

  useEffect(refresh, []);

  async function handleSubscribe(planKey: string) {
    setBusy(planKey);
    setError("");
    try {
      const callbackUrl = `${window.location.origin}/billing/callback`;
      const result = await subscribe(planKey, callbackUrl);
      window.location.href = result.authorization_url;
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  async function handleCancel() {
    setBusy("cancel");
    setError("");
    try {
      const result = await cancelSubscription();
      setStatus(result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(null);
    }
  }

  const withinRefundWindow =
    status?.subscription_status === "active" &&
    status.refund_eligible_until !== null &&
    new Date(status.refund_eligible_until) > new Date();

  const currentPlan = status?.plan ? plans.find((p) => p.key === status.plan) : null;
  const needsAPlan =
    status !== null && (status.subscription_status === "none" || status.subscription_status === "cancelled" || status.subscription_status === "refunded");

  return (
    <div className="max-w-5xl mx-auto px-8 py-12">
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
        <>
          {!needsAPlan && (
            <div className="bg-panel border border-line rounded-[4px] p-5 max-w-3xl mb-8">
              <div className="flex items-center justify-between mb-4">
                <div className="text-[13.5px] text-ink">Subscription status</div>
                <div className="flex items-center gap-2">
                  <span
                    className={`text-[11px] px-2 py-0.5 rounded-[3px] ${
                      status.tier === "pro" ? "bg-teal-deep text-white" : "bg-line text-ink-soft"
                    }`}
                  >
                    {currentPlan ? currentPlan.label : status.tier === "pro" ? "Pro" : "Free"}
                  </span>
                  <span className={`text-[11px] px-2 py-0.5 rounded-[3px] ${STATUS_COLOR[status.subscription_status]}`}>
                    {STATUS_LABEL[status.subscription_status]}
                  </span>
                </div>
              </div>

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

              {!isAdmin && (
                <div className="text-[13px] text-ink-soft">
                  Only an admin can manage billing for this organization.
                </div>
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
                  disabled={busy !== null}
                  className="text-[13px] px-4 py-1.5 rounded-[3px] border border-line text-ink hover:border-red hover:text-red transition-colors disabled:opacity-40"
                >
                  {busy === "cancel" ? "Working…" : withinRefundWindow ? "Cancel & get a full refund" : "Cancel subscription"}
                </button>
              )}
            </div>
          )}

          {needsAPlan && (
            <>
              {!isAdmin ? (
                <div className="text-[13px] text-ink-soft mb-8">
                  Only an admin can manage billing for this organization.
                </div>
              ) : (
                <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-8">
                  {plans.map((plan) => (
                    <div
                      key={plan.key}
                      className={`relative bg-panel border rounded-[4px] p-5 flex flex-col ${
                        plan.key === "pro" ? "border-teal-deep border-2" : "border-line"
                      }`}
                    >
                      {plan.key === "pro" && (
                        <span className="absolute -top-2.5 left-5 text-[10.5px] px-2 py-0.5 rounded-[3px] bg-teal-deep text-white">
                          Most popular
                        </span>
                      )}
                      <div className="text-[15px] font-medium text-ink mb-1">{plan.label}</div>
                      <div className="text-[22px] font-medium text-ink tracking-tight mb-1">
                        {formatNaira(plan.amount)}
                        <span className="text-[13px] text-ink-soft font-normal">/mo</span>
                      </div>
                      <div className="text-[12.5px] text-ink-soft mb-4">{plan.tagline}</div>

                      <ul className="flex flex-col gap-2 mb-5 flex-1">
                        {plan.features.map((f, i) => (
                          <li key={i} className="text-[12.5px] text-ink flex items-start gap-2">
                            <span className="text-teal-deep shrink-0">✓</span>
                            <span>{f}</span>
                          </li>
                        ))}
                      </ul>

                      <button
                        onClick={() => handleSubscribe(plan.key)}
                        disabled={busy !== null || !plan.configured}
                        title={!plan.configured ? "This plan isn't available for checkout yet." : undefined}
                        className={`text-[13px] px-4 py-1.5 rounded-[3px] transition-colors disabled:opacity-40 ${
                          plan.key === "pro"
                            ? "bg-teal-deep text-white hover:bg-teal"
                            : "border border-line text-ink hover:border-teal hover:text-teal"
                        }`}
                      >
                        {busy === plan.key ? "Redirecting to checkout…" : !plan.configured ? "Not yet available" : `Subscribe to ${plan.label}`}
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}
