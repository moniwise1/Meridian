"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { loadSession } from "@/lib/auth";

const STEPS = [
  {
    title: "Welcome to Meridian",
    body: "Ask business questions about your data in plain English — Meridian finds the relevant authorized data, analyses it, checks for anomalies, and explains the answer with evidence, not just a number.",
  },
  {
    title: "1. Connect a data source, or upload a document",
    body: "Connect a read-only database (Postgres, MySQL, SQL Server, Snowflake), or upload a PDF, Word, PowerPoint, or Excel file — a document can be the thing you ask about directly, no database required.",
    link: { href: "/connections", label: "Go to Data sources" },
  },
  {
    title: "2. Ask your first question",
    body: "Type a real question — e.g. \"Why did South-East revenue fall last quarter?\" — and watch the step-by-step trace as Meridian works through it.",
    link: { href: "/", label: "Go to Ask" },
  },
  {
    title: "3. Secure your account",
    body: "Turn on two-factor authentication so a password alone is never enough to sign in as you. Takes under a minute with any authenticator app.",
    link: { href: "/security", label: "Go to Security" },
  },
] as const;

function storageKey(userId: string) {
  return `meridian_onboarding_seen_${userId}`;
}

export default function OnboardingIntro() {
  const [visible, setVisible] = useState(false);
  const [step, setStep] = useState(0);

  useEffect(() => {
    const session = loadSession();
    if (!session) return;
    // Per-user, client-side only — a lightweight "have they seen this"
    // flag, not anything security- or billing-relevant, so localStorage is
    // the right tool here rather than a backend field (see CLAUDE.md's
    // browser-storage guidance: fine for per-viewer UX convenience, never
    // for state that must be shared or reliably persisted).
    try {
      if (!localStorage.getItem(storageKey(session.userId))) setVisible(true);
    } catch {
      // localStorage unavailable (private window, blocked site data) -
      // just skip the intro rather than risk it reappearing every visit.
    }
  }, []);

  function dismiss() {
    setVisible(false);
    const session = loadSession();
    if (!session) return;
    try {
      localStorage.setItem(storageKey(session.userId), "1");
    } catch {
      // Nothing to do if storage is unavailable — worst case the intro
      // reappears next visit, never a functional break.
    }
  }

  if (!visible) return null;

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30 px-6">
      <div className="bg-panel border border-line rounded-[4px] p-6 w-full max-w-sm shadow-lg">
        <div className="flex items-center gap-1.5 mb-4">
          {STEPS.map((_, i) => (
            <div
              key={i}
              className={`h-1 flex-1 rounded-full transition-colors ${i <= step ? "bg-teal-deep" : "bg-line"}`}
            />
          ))}
        </div>

        <div className="text-[15px] font-medium text-ink mb-2">{current.title}</div>
        <p className="text-[13px] text-ink-soft leading-relaxed mb-5">{current.body}</p>

        <div className="flex items-center justify-between">
          <button onClick={dismiss} className="text-[12px] text-ink-soft hover:text-ink transition-colors">
            Skip
          </button>
          <div className="flex items-center gap-2">
            {"link" in current && current.link && (
              <Link
                href={current.link.href}
                onClick={dismiss}
                className="text-[12.5px] text-teal hover:text-teal-deep transition-colors"
              >
                {current.link.label}
              </Link>
            )}
            <button
              onClick={() => (isLast ? dismiss() : setStep((s) => s + 1))}
              className="text-[12.5px] px-3 py-1.5 rounded-[3px] bg-teal-deep text-white hover:bg-teal transition-colors"
            >
              {isLast ? "Got it" : "Next"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
