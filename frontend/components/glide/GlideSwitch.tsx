"use client";

import { useId } from "react";

// An on/off switch whose knob glides across and whose track fills with
// colour as it goes - for settings that are simply on or off, where a
// checkbox looks like a form field rather than a setting.
//
// role="switch" + aria-checked, so screen readers announce "on"/"off";
// Space and Enter work because it's a real <button>, and clicking the
// label text toggles it too (a <label> activates the button it points at).
export default function GlideSwitch({
  checked,
  onChange,
  label,
  disabled = false,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  label: string;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex items-center gap-3 w-fit">
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-[background-color,border-color,box-shadow] duration-300 ease-glide focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-teal disabled:opacity-50 disabled:cursor-not-allowed ${
          checked
            ? "bg-teal-deep border-teal-deep shadow-[inset_0_1px_0_rgba(255,255,255,0.2)]"
            : "bg-line border-line shadow-[inset_0_1px_2px_rgba(18,63,61,0.12)]"
        }`}
      >
        <span
          aria-hidden
          className="inline-block h-5 w-5 rounded-full bg-white shadow-[0_1px_3px_rgba(18,63,61,0.35)] transition-transform duration-[380ms] ease-glide motion-reduce:transition-none"
          style={{ transform: checked ? "translateX(21px)" : "translateX(1px)" }}
        />
      </button>
      <label htmlFor={id} className={`text-[12.5px] text-ink ${disabled ? "opacity-60" : "cursor-pointer"}`}>
        {label}
      </label>
    </div>
  );
}
