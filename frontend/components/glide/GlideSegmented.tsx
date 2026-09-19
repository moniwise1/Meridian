"use client";

import type { KeyboardEvent, ReactNode } from "react";
import { useGlide } from "@/components/glide/useGlide";

export type GlideOption<T extends string> = { value: T; label: ReactNode };

// A row of mutually exclusive choices with one highlight that glides to the
// chosen option. Two looks, same behaviour:
//   pill      - a rounded track with a dark thumb (Sign in / Create account)
//   underline - a tab row whose underline slides along (list filters)
//
// It's a radiogroup: exactly one option is selected, screen readers
// announce it that way, and arrow keys move the selection like native
// radio buttons. Only the selected option is in the tab order.
export default function GlideSegmented<T extends string>({
  options,
  value,
  onChange,
  ariaLabel,
  variant = "pill",
  fullWidth = false,
  className = "",
}: {
  options: GlideOption<T>[];
  value: T;
  onChange: (next: T) => void;
  ariaLabel: string;
  variant?: "pill" | "underline";
  fullWidth?: boolean;
  className?: string;
}) {
  const { containerRef, indicatorRef } = useGlide<HTMLDivElement>(value);
  const pill = variant === "pill";

  function onKeyDown(e: KeyboardEvent<HTMLDivElement>) {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const index = options.findIndex((o) => o.value === value);
    const next = options[(index + step + options.length) % options.length];
    onChange(next.value);
    containerRef.current?.querySelector<HTMLButtonElement>(`[data-glide-key="${CSS.escape(next.value)}"]`)?.focus();
  }

  return (
    <div
      ref={containerRef}
      role="radiogroup"
      aria-label={ariaLabel}
      onKeyDown={onKeyDown}
      className={
        pill
          ? `relative ${fullWidth ? "flex" : "inline-flex"} p-1 rounded-full border border-line bg-paper/80 shadow-[inset_0_1px_2px_rgba(18,63,61,0.06)] ${className}`
          : `relative flex items-center gap-1 border-b border-line ${className}`
      }
    >
      <span
        ref={indicatorRef}
        aria-hidden
        className={
          "pointer-events-none absolute left-0 top-0 opacity-0 transition-[transform,width,height,opacity] motion-reduce:transition-none " +
          (pill
            ? "rounded-full bg-teal-deep shadow-[inset_0_1px_0_rgba(255,255,255,0.25),0_4px_12px_rgba(18,63,61,0.28)] duration-[420ms] ease-glide"
            : "border-b-2 border-teal-deep duration-[380ms] ease-glide")
        }
      />
      {options.map((option) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value || "__all"}
            type="button"
            role="radio"
            aria-checked={selected}
            tabIndex={selected ? 0 : -1}
            data-glide-key={option.value}
            onClick={() => onChange(option.value)}
            className={
              "relative z-10 whitespace-nowrap transition-colors duration-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal " +
              (pill
                ? `${fullWidth ? "flex-1" : ""} px-4 py-1.5 text-[13px] rounded-full ${
                    // The label turns white a beat after the click, as the thumb
                    // arrives under it - not before, which would briefly leave
                    // white text on the pale track.
                    selected ? "text-white font-medium [transition-delay:90ms]" : "text-ink-soft hover:text-ink"
                  }`
                : `text-[13px] px-3 py-2 -mb-px border-b-2 border-transparent ${
                    selected ? "text-ink" : "text-ink-soft hover:text-ink"
                  }`)
            }
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
