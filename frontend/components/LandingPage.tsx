"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listPlans, type Plan } from "@/lib/api";

function formatNaira(amountKobo: number): string {
  return `₦${(amountKobo / 100).toLocaleString("en-NG", { maximumFractionDigits: 0 })}`;
}

const FEATURES = [
  {
    title: "Ask in plain English",
    body: "No SQL, no dashboards to build. Type a real business question and Meridian finds the relevant authorized data, runs the analysis, and checks it for anomalies before it ever reaches you.",
  },
  {
    title: "Evidence, not guesses",
    body: "Every answer comes with the query that produced it, data-quality notes, and a plain-English explanation with a stated confidence level — never a number with nothing behind it.",
  },
  {
    title: "Document intelligence",
    body: "Upload a PDF, Word, PowerPoint, or Excel file and ask questions about it directly — including scanned pages, read automatically via OCR — no database required at all.",
  },
  {
    title: "Read-only, always",
    body: "Every connected database is verified read-only at the transaction level before it's ever saved — Meridian can query and explain, it cannot write, alter, or delete.",
  },
  {
    title: "Row- and column-level access",
    body: "Restrict what each teammate's questions can ever see, down to specific rows and columns, enforced on every single query — not a setting someone can forget to apply.",
  },
  {
    title: "A trail for everything",
    body: "Every query, connection change, and export is written to a hash-chained audit log with a one-click verification check — tamper-evident by construction, not just by policy.",
  },
] as const;

const STEPS = [
  { n: "1", title: "Connect or upload", body: "Link a read-only database, or upload a document — either can be the data source." },
  { n: "2", title: "Ask a question", body: "Plain English, the way you'd ask a colleague. Follow up naturally — Meridian keeps the thread." },
  { n: "3", title: "Get the evidence", body: "The answer, the query behind it, anomalies flagged, and a confidence-rated explanation." },
] as const;

// Small hand-drawn line icons (currentColor, stroke-based) rather than a
// photo or stock illustration - same reasoning as the chat mock below:
// built from the app's own design tokens so they never look like a
// mismatched stock asset bolted onto an otherwise custom-built page, and
// need no image file to ship or keep in sync.
function DatabaseIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <ellipse cx="12" cy="5.5" rx="7.5" ry="2.5" />
      <path d="M4.5 5.5v6c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5v-6" />
      <path d="M4.5 11.5v6c0 1.4 3.4 2.5 7.5 2.5s7.5-1.1 7.5-2.5v-6" />
    </svg>
  );
}

function ChatIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <path d="M4 5.5h16v10.5H9.5L5 20v-4H4z" />
      <path d="M8 9.5h8M8 12.5h5" />
    </svg>
  );
}

function EvidenceIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="w-5 h-5">
      <path d="M12 3.5l7 3v5c0 4.5-3 7.5-7 8.5-4-1-7-4-7-8.5v-5z" />
      <path d="M9 12l2 2 4-4.5" />
    </svg>
  );
}

const HERO_FLOW = [
  { icon: DatabaseIcon, label: "Connect a database or upload a document" },
  { icon: ChatIcon, label: "Ask a real business question, plain English" },
  { icon: EvidenceIcon, label: "Get an answer with the evidence behind it" },
] as const;

export default function LandingPage() {
  const [plans, setPlans] = useState<Plan[]>([]);

  useEffect(() => {
    listPlans().catch(() => []).then((p) => p && setPlans(p));
  }, []);

  return (
    <div className="min-h-screen bg-paper text-ink">
      {/* ---------- Nav ---------- */}
      <header className="sticky top-0 z-40 bg-paper/90 backdrop-blur border-b border-line">
        <div className="max-w-6xl mx-auto px-6 md:px-8 h-16 flex items-center justify-between">
          <div className="text-[15px] font-semibold tracking-tight text-ink">Meridian</div>
          <nav className="hidden md:flex items-center gap-6 text-[13px] text-ink-soft">
            <a href="#features" className="hover:text-ink transition-colors">Product</a>
            <a href="#security" className="hover:text-ink transition-colors">Security</a>
            <a href="#pricing" className="hover:text-ink transition-colors">Pricing</a>
          </nav>
          <div className="flex items-center gap-3">
            <Link href="/login" className="text-[13px] text-ink-soft hover:text-ink transition-colors">
              Sign in
            </Link>
            <Link
              href="/login?mode=register"
              className="text-[13px] px-3.5 py-1.5 rounded-[3px] bg-teal-deep text-white hover:bg-teal transition-colors"
            >
              Get started
            </Link>
          </div>
        </div>
      </header>

      {/* ---------- Hero ---------- */}
      <section className="relative overflow-hidden max-w-6xl mx-auto px-6 md:px-8 pt-20 pb-16 md:pt-28 md:pb-24">
        {/* Purely decorative - sits behind everything (negative z-index,
            no pointer events) and adds zero layout weight, so it can
            never push or misalign real content on any screen size. */}
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -z-10 -top-24 -right-40 w-[560px] h-[560px] rounded-full opacity-[0.07] blur-3xl bg-teal-deep"
        />
        <div className="max-w-2xl">
          <div className="text-[12px] font-[family-name:var(--font-mono)] text-teal-deep tracking-wide uppercase mb-4">
            Enterprise analytics agent
          </div>
          <h1 className="text-[34px] md:text-[44px] font-medium tracking-tight text-ink leading-[1.1] mb-5">
            Ask your data anything. Get an answer with the evidence behind it.
          </h1>
          <p className="text-[15.5px] text-ink-soft leading-relaxed mb-8 max-w-xl">
            Meridian connects to your databases and documents, answers real business questions in
            plain English, and shows its work — the query, the data quality, the anomalies, the
            confidence — every time. Read-only by design, so it can query and explain, and nothing
            else.
          </p>
          <div className="flex items-center gap-3">
            <Link
              href="/login?mode=register"
              className="text-[13.5px] px-5 py-2.5 rounded-[3px] bg-teal-deep text-white hover:bg-teal transition-colors"
            >
              Get started free
            </Link>
            <a
              href="#features"
              className="text-[13.5px] px-5 py-2.5 rounded-[3px] border border-line text-ink hover:border-teal hover:text-teal transition-colors"
            >
              See what it does
            </a>
          </div>

          {/* A quick visual read of the flow (connect → ask → evidence) -
              condensed teaser of the full "How it works" section below,
              here to give the hero some real visual interest beyond a
              wall of text before the reader ever scrolls. */}
          <div className="flex flex-wrap items-center gap-x-8 gap-y-4 mt-10">
            {HERO_FLOW.map(({ icon: Icon, label }) => (
              <div key={label} className="flex items-center gap-2.5 max-w-[220px]">
                <span className="shrink-0 w-8 h-8 rounded-full border border-line bg-panel flex items-center justify-center text-teal-deep">
                  <Icon />
                </span>
                <span className="text-[12px] text-ink-soft leading-snug">{label}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Illustrative mock of a real Ask exchange — built from the app's
            own design tokens, not a screenshot, so it never drifts out of
            sync visually and needs no image asset. */}
        <div className="mt-16 max-w-3xl bg-panel border border-line rounded-[6px] shadow-sm overflow-hidden">
          <div className="border-b border-line px-5 py-3 flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-line" />
            <span className="w-2.5 h-2.5 rounded-full bg-line" />
            <span className="w-2.5 h-2.5 rounded-full bg-line" />
          </div>
          <div className="p-6">
            <div className="text-[13px] text-ink-soft mb-1">You asked</div>
            <div className="text-[15px] text-ink mb-5">Why did South-East revenue fall last quarter?</div>
            <div className="text-[13px] text-ink-soft mb-2">Meridian found</div>
            <div className="border border-line rounded-[4px] p-4 bg-paper">
              <div className="text-[13.5px] text-ink leading-relaxed mb-3">
                South-East revenue fell 14.2% quarter-over-quarter, concentrated in two accounts that
                churned in week 6 — not a broad regional decline.
              </div>
              <div className="flex flex-wrap gap-2">
                <span className="text-[11px] px-2 py-0.5 rounded-[3px] bg-line text-ink-soft font-[family-name:var(--font-mono)]">
                  SQL query included
                </span>
                <span className="text-[11px] px-2 py-0.5 rounded-[3px] bg-line text-ink-soft font-[family-name:var(--font-mono)]">
                  2 anomalies flagged
                </span>
                <span className="text-[11px] px-2 py-0.5 rounded-[3px] bg-amber-soft text-amber font-[family-name:var(--font-mono)]">
                  Confidence: high
                </span>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ---------- Features ---------- */}
      <section id="features" className="max-w-6xl mx-auto px-6 md:px-8 py-16 md:py-20 border-t border-line">
        <div className="max-w-xl mb-12">
          <h2 className="text-[26px] font-medium tracking-tight text-ink mb-3">What Meridian does</h2>
          <p className="text-[14.5px] text-ink-soft leading-relaxed">
            Not another dashboard. An agent that does the analysis and shows its work, with the
            access controls a real enterprise data team actually needs.
          </p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
          {FEATURES.map((f) => (
            <div key={f.title} className="border border-line rounded-[4px] p-5 bg-panel">
              <div className="text-[14.5px] font-medium text-ink mb-2">{f.title}</div>
              <div className="text-[13px] text-ink-soft leading-relaxed">{f.body}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ---------- How it works ---------- */}
      <section className="max-w-6xl mx-auto px-6 md:px-8 py-16 md:py-20 border-t border-line">
        <h2 className="text-[26px] font-medium tracking-tight text-ink mb-12">How it works</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-8">
          {STEPS.map((s) => (
            <div key={s.n}>
              <div className="text-[13px] font-[family-name:var(--font-mono)] text-teal-deep mb-3">{s.n}</div>
              <div className="text-[15px] font-medium text-ink mb-2">{s.title}</div>
              <div className="text-[13px] text-ink-soft leading-relaxed">{s.body}</div>
            </div>
          ))}
        </div>
      </section>

      {/* ---------- Security ---------- */}
      <section id="security" className="max-w-6xl mx-auto px-6 md:px-8 py-16 md:py-20 border-t border-line">
        <div className="max-w-xl mb-10">
          <h2 className="text-[26px] font-medium tracking-tight text-ink mb-3">Built for a real security review</h2>
          <p className="text-[14.5px] text-ink-soft leading-relaxed">
            Not bolted on after the fact — read-only enforcement, encryption, and access control are
            checked on every request, not just configured once.
          </p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-10 gap-y-5">
          {[
            "Every connected database is proven read-only at the transaction level before it's ever saved — a write attempt is required to fail first.",
            "Stored credentials are encrypted at rest, with real envelope encryption via AWS KMS available for production.",
            "Role-based access plus per-user row- and column-level scope, enforced on every query — not just hidden in the UI.",
            "Two-factor authentication via any authenticator app, optional per user or required organization-wide.",
            "A hash-chained audit log covers every query, connection change, and export, with a one-click tamper check.",
            "Extracted document text and connected-database results are always handed to the AI as labelled, untrusted data — never blended into its instructions.",
          ].map((point) => (
            <div key={point} className="flex items-start gap-3">
              <span className="text-teal-deep shrink-0 mt-0.5">✓</span>
              <span className="text-[13.5px] text-ink-soft leading-relaxed">{point}</span>
            </div>
          ))}
        </div>
      </section>

      {/* ---------- Pricing ---------- */}
      <section id="pricing" className="max-w-6xl mx-auto px-6 md:px-8 py-16 md:py-20 border-t border-line">
        <div className="max-w-xl mb-12">
          <h2 className="text-[26px] font-medium tracking-tight text-ink mb-3">Simple, per-seat pricing</h2>
          <p className="text-[14.5px] text-ink-soft leading-relaxed">
            One plan per team, not per feature. Every plan includes the full product — plans differ
            only in how many teammates, data sources, questions, and downloads you get each month.
          </p>
        </div>

        {plans.length === 0 ? (
          <div className="text-[13px] text-ink-soft">Loading pricing…</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-6">
            {plans.map((plan) => (
              <div
                key={plan.key}
                className={`relative bg-panel border rounded-[4px] p-6 flex flex-col ${
                  plan.key === "pro" ? "border-teal-deep border-2" : "border-line"
                }`}
              >
                {plan.key === "pro" && (
                  <span className="absolute -top-2.5 left-6 text-[10.5px] px-2 py-0.5 rounded-[3px] bg-teal-deep text-white">
                    Most popular
                  </span>
                )}
                <div className="text-[15px] font-medium text-ink mb-1">{plan.label}</div>
                <div className="text-[26px] font-medium text-ink tracking-tight mb-1">
                  {formatNaira(plan.amount)}
                  <span className="text-[13px] text-ink-soft font-normal">/mo</span>
                </div>
                <div className="text-[12.5px] text-ink-soft mb-5">{plan.tagline}</div>
                <ul className="flex flex-col gap-2 mb-6 flex-1">
                  {plan.features.map((f, i) => (
                    <li key={i} className="text-[12.5px] text-ink flex items-start gap-2">
                      <span className="text-teal-deep shrink-0">✓</span>
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  href="/login?mode=register"
                  className={`text-center text-[13px] px-4 py-2 rounded-[3px] transition-colors ${
                    plan.key === "pro"
                      ? "bg-teal-deep text-white hover:bg-teal"
                      : "border border-line text-ink hover:border-teal hover:text-teal"
                  }`}
                >
                  Get started
                </Link>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ---------- Final CTA ---------- */}
      <section className="max-w-6xl mx-auto px-6 md:px-8 py-16 md:py-20 border-t border-line text-center">
        <h2 className="text-[26px] font-medium tracking-tight text-ink mb-4">
          Bring your data. Ask a real question.
        </h2>
        <p className="text-[14.5px] text-ink-soft leading-relaxed mb-8 max-w-xl mx-auto">
          Set up takes a few minutes — connect a read-only database or upload a document, and ask
          something you actually want to know.
        </p>
        <Link
          href="/login?mode=register"
          className="inline-block text-[13.5px] px-6 py-2.5 rounded-[3px] bg-teal-deep text-white hover:bg-teal transition-colors"
        >
          Get started free
        </Link>
      </section>

      {/* ---------- Footer ---------- */}
      <footer className="border-t border-line">
        <div className="max-w-6xl mx-auto px-6 md:px-8 py-14 grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-10">
          <div className="col-span-2 sm:col-span-1 pr-4">
            <div className="text-[15px] font-semibold tracking-tight text-ink mb-2">Meridian</div>
            <p className="text-[12.5px] text-ink-soft leading-relaxed max-w-[220px]">
              Enterprise analytics, read-only by design. Ask a real question, get an answer with the
              evidence behind it.
            </p>
          </div>

          <div>
            <div className="text-[11.5px] font-medium text-ink uppercase tracking-wide mb-3">Product</div>
            <nav className="flex flex-col gap-2.5 text-[13px] text-ink-soft">
              <a href="#features" className="hover:text-ink transition-colors">Product</a>
              <a href="#security" className="hover:text-ink transition-colors">Security</a>
              <a href="#pricing" className="hover:text-ink transition-colors">Pricing</a>
            </nav>
          </div>

          <div>
            <div className="text-[11.5px] font-medium text-ink uppercase tracking-wide mb-3">Account</div>
            <nav className="flex flex-col gap-2.5 text-[13px] text-ink-soft">
              <Link href="/login" className="hover:text-ink transition-colors">Sign in</Link>
              <Link href="/login?mode=register" className="hover:text-ink transition-colors">Create account</Link>
            </nav>
          </div>

          <div>
            <div className="text-[11.5px] font-medium text-ink uppercase tracking-wide mb-3">Resources</div>
            <nav className="flex flex-col gap-2.5 text-[13px] text-ink-soft">
              <Link href="/status" className="hover:text-ink transition-colors">System status</Link>
            </nav>
          </div>
        </div>

        <div className="border-t border-line">
          <div className="max-w-6xl mx-auto px-6 md:px-8 py-6 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
            <div className="text-[11.5px] text-ink-soft">
              © {new Date().getFullYear()} Meridian. All rights reserved.
            </div>
            <div className="text-[11.5px] text-ink-soft">Read-only by design — it can query and explain, nothing else.</div>
          </div>
        </div>
      </footer>
    </div>
  );
}
