"use client";

import { useState } from "react";

// Shown when the backend pauses an analysis to ask something that would
// genuinely change the answer (see app/agents/planner.py's
// ClarificationEvent) - a real intermediate state, not a step or a result:
// nothing was computed or persisted yet, so this is the only thing on
// screen until the user answers or skips.
export default function ClarificationPrompt({
  question, busy, onAnswer, onSkip,
}: {
  question: string;
  busy: boolean;
  onAnswer: (answer: string) => void;
  onSkip: () => void;
}) {
  const [answer, setAnswer] = useState("");

  return (
    <div className="bg-panel border border-teal-deep/30 rounded-[4px] p-4">
      <div className="text-[12px] text-teal-deep font-medium mb-2">One quick thing before I run this</div>
      <div className="text-[14px] text-ink mb-3">{question}</div>
      <div className="flex items-center gap-2">
        <input
          value={answer}
          onChange={(e) => setAnswer(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && answer.trim() && !busy) onAnswer(answer.trim());
          }}
          placeholder="Your answer…"
          disabled={busy}
          className="flex-1 text-[13.5px] border border-line rounded-[3px] px-3 py-2 bg-panel text-ink placeholder:text-ink-soft/70 focus:outline-none focus:ring-1 focus:ring-teal disabled:opacity-60"
        />
        <button
          onClick={() => answer.trim() && onAnswer(answer.trim())}
          disabled={busy || !answer.trim()}
          className="text-[13px] px-4 py-2 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-teal transition-colors"
        >
          Answer
        </button>
      </div>
      <button
        onClick={onSkip}
        disabled={busy}
        className="mt-2 text-[12px] text-ink-soft hover:text-ink transition-colors disabled:opacity-60"
      >
        Skip — just make your best guess
      </button>
    </div>
  );
}
