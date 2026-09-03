"use client";

import type { StepEvent } from "@/lib/api";

const STEP_LABELS: Record<string, string> = {
  understanding: "Understanding the question",
  finding_data: "Finding authorized data",
  running_analysis: "Running the analysis",
  checking_quality: "Checking data quality",
  investigating_drivers: "Checking for anomalies",
  forecasting: "Projecting the trend",
  preparing_insights: "Preparing the explanation",
  scanning: "Scanning tables for anomalies",
  policy: "Policy check",
  error: "Something went wrong",
};

export default function ProgressTrace({ steps }: { steps: StepEvent[] }) {
  if (steps.length === 0) return null;

  return (
    <ol className="relative pl-6">
      <div className="absolute left-[7px] top-1.5 bottom-1.5 w-px bg-line" />
      {steps.map((s, i) => {
        const label = STEP_LABELS[s.step] ?? s.step;
        const dotColor =
          s.status === "error" ? "bg-red" : s.status === "done" ? "bg-teal" : "bg-ink-soft";
        return (
          <li key={`${s.step}-${i}`} className="relative pb-3 last:pb-0">
            <span
              className={`absolute -left-[22px] top-1.5 h-[9px] w-[9px] rounded-full ${dotColor} ${
                s.status === "running" ? "animate-pulse" : ""
              }`}
            />
            <div className={`text-[13.5px] ${s.status === "error" ? "text-red" : "text-ink"}`}>
              {label}
            </div>
            {s.detail && (
              <div className="text-[12.5px] text-ink-soft mt-0.5 leading-snug">{s.detail}</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
