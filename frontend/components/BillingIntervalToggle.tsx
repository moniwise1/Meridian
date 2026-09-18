"use client";

import type { KeyboardEvent } from "react";
import type { Plan } from "@/lib/api";

export type BillingInterval = "monthly" | "annual";

export function formatNaira(amountKobo: number): string {
  return `₦${(amountKobo / 100).toLocaleString("en-NG", { maximumFractionDigits: 0 })}`;
}

// A two-option segmented control whose highlight glides between the
// options. It's a radiogroup rather than two buttons or a checkbox: there
// are exactly two mutually exclusive choices, and that's what screen
// readers should announce. Left/right arrow keys move between them, the
// same as a native radio group.
export default function BillingIntervalToggle({
  value,
  onChange,
  discountPercent,
  className = "",
}: {
  value: BillingInterval;
  onChange: (next: BillingInterval) => void;
  discountPercent: number;
  className?: string;
}) {
  const annual = value === "annual";

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    if (e.key === "ArrowRight" || e.key === "ArrowDown") {
      e.preventDefault();
      onChange("annual");
    } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
      e.preventDefault();
      onChange("monthly");
    }
  }

  const option =
    "relative z-10 w-36 py-2.5 text-[13.5px] font-medium rounded-full transition-colors duration-300 " +
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal";

  return (
    <div
      role="radiogroup"
      aria-label="Billing period"
      onKeyDown={onKeyDown}
      className={`relative inline-flex p-1 rounded-full border border-line bg-panel/70 backdrop-blur-xl shadow-[inset_0_1px_0_rgba(255,255,255,0.7),0_6px_20px_rgba(18,63,61,0.08)] ${className}`}
    >
      {/* The glide. Both options are the same fixed width, so the thumb is
          exactly half the track and moving it one full width lands it on
          the other option. motion-reduce drops the slide, not the state. */}
      <span
        aria-hidden
        className="absolute top-1 bottom-1 left-1 w-36 rounded-full bg-teal-deep shadow-[inset_0_1px_0_rgba(255,255,255,0.28),0_6px_16px_rgba(18,63,61,0.32)] transition-transform duration-500 ease-[cubic-bezier(0.34,1.3,0.5,1)] motion-reduce:transition-none"
        style={{ transform: annual ? "translateX(100%)" : "translateX(0)" }}
      />
      <button
        type="button"
        role="radio"
        aria-checked={!annual}
        tabIndex={annual ? -1 : 0}
        onClick={() => onChange("monthly")}
        className={`${option} ${annual ? "text-ink-soft hover:text-ink" : "text-white"}`}
      >
        Monthly
      </button>
      <button
        type="button"
        role="radio"
        aria-checked={annual}
        tabIndex={annual ? 0 : -1}
        onClick={() => onChange("annual")}
        className={`${option} ${annual ? "text-white" : "text-ink-soft hover:text-ink"}`}
      >
        Annual
        <span
          className={`ml-1.5 inline-block text-[10.5px] font-semibold px-1.5 py-0.5 rounded-full align-[1px] transition-colors duration-300 ${
            annual ? "bg-white/20 text-white" : "bg-amber-soft text-amber"
          }`}
        >
          −{discountPercent}%
        </span>
      </button>
    </div>
  );
}

// The price on a plan card. Annual is shown as its per-month equivalent -
// the number people compare across tiers and against the monthly price -
// with the real, up-front amount stated right underneath so nobody is
// surprised at checkout. Keyed on the interval so the figure re-mounts and
// settles in (animate-price-in, globals.css) instead of snapping.
export function PlanPrice({
  plan,
  interval,
  size = "lg",
}: {
  plan: Plan;
  interval: BillingInterval;
  size?: "lg" | "md";
}) {
  const annual = interval === "annual";
  const perMonth = annual ? Math.round(plan.annual_amount / 12) : plan.amount;
  const saving = plan.amount * 12 - plan.annual_amount;
  const big = size === "lg" ? "font-serif text-4xl" : "text-[22px] font-medium";

  return (
    <div className="mb-2">
      <div className="flex items-baseline gap-2 flex-wrap">
        <span key={`${plan.key}-${interval}`} className={`${big} text-ink tracking-tight tabular-nums motion-safe:animate-price-in`}>
          {formatNaira(perMonth)}
        </span>
        <span className="text-[13px] text-ink-soft">/mo</span>
        {annual && (
          <span
            key={`${plan.key}-was`}
            className="text-[13px] text-ink-soft line-through decoration-ink-soft/60 motion-safe:animate-price-in"
          >
            {formatNaira(plan.amount)}
          </span>
        )}
      </div>
      <div key={`${plan.key}-${interval}-note`} className="mt-1 text-[12.5px] text-ink-soft min-h-[1.25rem] motion-safe:animate-price-in">
        {annual ? (
          <>
            {formatNaira(plan.annual_amount)} billed yearly ·{" "}
            <span className="text-teal-deep font-medium">save {formatNaira(saving)}</span>
          </>
        ) : (
          "Billed monthly · cancel any time"
        )}
      </div>
    </div>
  );
}
