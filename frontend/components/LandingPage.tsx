"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listPlans, type Plan } from "@/lib/api";
import { track } from "@/lib/analytics";

function formatNaira(amountKobo: number): string {
  return `₦${(amountKobo / 100).toLocaleString("en-NG", { maximumFractionDigits: 0 })}`;
}

const FEATURES = [
  {
    title: "Your next decision starts with a question",
    body: "Why did revenue fall? Which accounts need attention? Ask in plain English and get an analysis of your data, without writing SQL or building another dashboard.",
  },
  {
    title: "Walk into the meeting with the evidence",
    body: "When someone asks how you reached a conclusion, have the answer ready. Meridian includes the source query, data-quality notes, and a confidence level so you can review the evidence before you act.",
  },
  {
    title: "Start with the data you already have",
    body: "Connect a live database or upload a report, spreadsheet, or presentation. Meridian also reads scanned documents, so you can start exploring without first moving everything into a new data warehouse.",
  },
  {
    title: "Explore your data without changing it",
    body: "Your production records stay untouched. Meridian verifies that each database connection is read-only before saving it, so your team can investigate questions without writing to the source.",
  },
  {
    title: "Give your team answers within their access",
    body: "Let more people find what they need while keeping sensitive information restricted. Row- and column-level permissions control what each person can see on every query.",
  },
  {
    title: "Be ready when someone asks what happened",
    body: "Keep a traceable record of queries, connection changes, and exports. A tamper-evident audit trail and one-click verification help you respond to internal reviews and audit questions with evidence.",
  },
] as const;

const STEPS = [
  {
    n: "1",
    title: "Bring your data",
    body: "Connect a read-only database or upload a document you want to understand.",
  },
  {
    n: "2",
    title: "Ask what matters",
    body: "Ask a business question in your own words. Add follow-up questions as you explore.",
  },
  {
    n: "3",
    title: "Review the answer and the proof",
    body: "See the findings, supporting query, confidence level, and any data-quality concerns before deciding what to do next.",
  },
] as const;

// Small hand-drawn line icons (currentColor, stroke-based) rather than a
// photo or stock illustration - built from the app's own design tokens so
// they never look like a mismatched stock asset bolted onto an otherwise
// custom-built page, and need no image file to ship or keep in sync.
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

function LockIcon({ small = false }: { small?: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"
      strokeLinejoin="round" className={small ? "w-3.5 h-3.5 shrink-0" : "w-4 h-4 shrink-0"}
    >
      <rect x="5.5" y="10.5" width="13" height="9.5" rx="1.5" />
      <path d="M8 10.5V7.5a4 4 0 0 1 8 0v3" />
    </svg>
  );
}

// Same hand-drawn line-icon treatment as the rest of this file's icons
// (currentColor, stroke-based, no image asset) - simple line-art evoking
// each platform's own mark rather than a pixel-accurate brand asset.
function LinkedInIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="w-[18px] h-[18px]">
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <line x1="7.5" y1="10.5" x2="7.5" y2="16.5" />
      <circle cx="7.5" cy="7" r="0.9" fill="currentColor" stroke="none" />
      <path d="M11.5 16.5v-4a2.2 2.2 0 0 1 4.4 0v4" />
      <line x1="11.5" y1="10.5" x2="11.5" y2="16.5" />
    </svg>
  );
}

function XIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="w-[18px] h-[18px]">
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <line x1="8" y1="8" x2="16" y2="16" />
      <line x1="16" y1="8" x2="8" y2="16" />
    </svg>
  );
}

function InstagramIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="w-[18px] h-[18px]">
      <rect x="3" y="3" width="18" height="18" rx="5" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="17" cy="7" r="0.8" fill="currentColor" stroke="none" />
    </svg>
  );
}

function FacebookIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="w-[18px] h-[18px]">
      <rect x="3" y="3" width="18" height="18" rx="3" />
      <path d="M14 8.5h-1a1.5 1.5 0 0 0-1.5 1.5v1.5H14l-.3 2h-2.2v4.5" />
    </svg>
  );
}

// Fill in each real profile URL as soon as the account exists - an empty
// href renders the icon without a link (nothing to send anyone to yet)
// rather than shipping a dead "#" link.
const SOCIAL_LINKS = [
  { name: "LinkedIn", href: "", Icon: LinkedInIcon },
  { name: "X (Twitter)", href: "", Icon: XIcon },
  { name: "Instagram", href: "", Icon: InstagramIcon },
  { name: "Facebook", href: "", Icon: FacebookIcon },
] as const;

const HERO_FLOW = [
  { icon: DatabaseIcon, label: "Use your existing data" },
  { icon: ChatIcon, label: "Ask in plain English" },
  { icon: EvidenceIcon, label: "Check the evidence behind each answer" },
] as const;

// The same glass-button treatment used throughout this page - translucent,
// blurred, with a soft inset highlight to read as real frosted glass
// rather than a flat semi-transparent fill. Centralized here so every
// button on the page stays visually identical instead of six near-copies
// of the same long class string quietly drifting apart over edits.
const GLASS_BUTTON =
  "rounded-full border backdrop-blur-xl bg-linear-to-b from-white/20 to-white/0 " +
  "shadow-[inset_0_1px_0_rgba(255,255,255,0.55),inset_0_-1px_0_rgba(255,255,255,0.12),0_5px_16px_rgba(18,63,61,0.12)] " +
  "transition-[background-color,box-shadow,transform] duration-200 motion-safe:hover:-translate-y-0.5 active:translate-y-0";
const GLASS_BUTTON_PRIMARY = `${GLASS_BUTTON} bg-teal-deep/85 border-white/35 text-white hover:bg-teal-deep/95`;
const GLASS_BUTTON_SECONDARY = `${GLASS_BUTTON} bg-white/40 border-white/80 text-ink hover:bg-white/70`;

// Illustrative product panels only; no live data or interactive controls.
const FEATURE_VISUALS = [
  <figure key="answer" className="p-6 md:p-8">
    <figcaption className="mb-7 flex items-center justify-between border-b border-line pb-4 text-xs font-mono text-ink-soft"><span>REVENUE ANALYSIS</span><span>EXAMPLE</span></figcaption>
    <div className="mb-2 text-sm text-ink-soft">South-East · quarter-over-quarter</div>
    <div className="font-serif text-6xl tracking-tight">−14.2<span className="text-3xl">%</span></div>
    <svg role="img" aria-label="Illustrative revenue trend declining in week six" viewBox="0 0 440 150" className="my-6 w-full text-teal" fill="none">
      <path d="M0 30H440M0 75H440M0 120H440" stroke="var(--line)" />
      <path d="M0 42L40 38L80 48L120 32L160 40L200 37L240 98L280 108L320 103L360 114L400 109L440 115" stroke="currentColor" strokeWidth="3" />
      <path d="M240 10V140" stroke="currentColor" strokeDasharray="4 5" />
    </svg>
    <div className="flex justify-between text-xs font-mono text-ink-soft"><span>WEEK 1</span><span>WEEK 6 · 2 ACCOUNTS CHURNED</span></div>
  </figure>,
  <figure key="query" className="p-6 md:p-8">
    <figcaption className="mb-6 flex justify-between border-b border-line pb-4 text-xs font-mono text-ink-soft"><span>QUERY EVIDENCE</span><span>EXAMPLE</span></figcaption>
    <pre className="overflow-x-auto text-sm leading-8 text-teal-deep"><code>{`SELECT region, SUM(revenue)
FROM quarterly_revenue
WHERE region = 'South-East'
GROUP BY region;`}</code></pre>
    <dl className="mt-7 divide-y divide-line border-t border-line text-sm">
      <div className="flex justify-between py-4"><dt className="text-ink-soft">Confidence</dt><dd>High</dd></div>
      <div className="flex justify-between py-4"><dt className="text-ink-soft">Data-quality notes</dt><dd>2 anomalies flagged</dd></div>
      <div className="flex justify-between pt-4"><dt className="text-ink-soft">Source query</dt><dd className="text-teal">Included</dd></div>
    </dl>
  </figure>,
  <figure key="sources" className="p-6 md:p-8">
    <figcaption className="mb-3 flex justify-between border-b border-line pb-4 text-xs font-mono text-ink-soft"><span>DATA SOURCES</span><span>EXAMPLE</span></figcaption>
    <div className="divide-y divide-line">
      <div className="flex items-center gap-4 py-5"><span className="font-mono text-xs text-ink-soft">01</span><div className="flex-1"><div className="text-base">Production database</div><div className="mt-1 text-sm text-ink-soft">Read-only connection</div></div><DatabaseIcon /></div>
      <div className="flex items-center gap-4 py-5"><span className="font-mono text-xs text-ink-soft">02</span><div className="flex-1"><div className="text-base">Quarterly report.pdf</div><div className="mt-1 text-sm text-ink-soft">Document · OCR supported</div></div><span className="font-mono text-xs text-teal">PDF</span></div>
      <div className="flex items-center gap-4 py-5"><span className="font-mono text-xs text-ink-soft">03</span><div className="flex-1"><div className="text-base">Regional revenue.xlsx</div><div className="mt-1 text-sm text-ink-soft">Spreadsheet</div></div><span className="font-mono text-xs text-teal">XLS</span></div>
    </div>
  </figure>,
  <figure key="readonly" className="p-6 md:p-8">
    <figcaption className="mb-7 flex justify-between border-b border-line pb-4 text-xs font-mono text-ink-soft"><span>CONNECTION VERIFICATION</span><span>EXAMPLE</span></figcaption>
    <div className="mb-8 flex items-center gap-3 text-2xl font-serif"><LockIcon />Read-only by design.</div>
    <div className="space-y-5 font-mono text-sm"><div className="flex justify-between"><span className="text-ink-soft">SELECT</span><span className="text-teal">ALLOWED</span></div><div className="flex justify-between"><span className="text-ink-soft">INSERT / UPDATE</span><span>BLOCKED</span></div><div className="flex justify-between"><span className="text-ink-soft">DELETE / ALTER</span><span>BLOCKED</span></div></div>
    <p className="mt-8 border-t border-line pt-5 text-sm leading-relaxed text-ink-soft">Verified at the transaction level before a connection is saved.</p>
  </figure>,
  <figure key="access" className="p-6 md:p-8">
    <figcaption className="mb-6 flex justify-between border-b border-line pb-4 text-xs font-mono text-ink-soft"><span>QUERY SCOPE</span><span>EXAMPLE</span></figcaption>
    <table className="w-full text-left text-sm"><thead className="text-ink-soft"><tr><th className="pb-4 font-normal">Data</th><th className="pb-4 font-normal">Team member access</th></tr></thead><tbody className="divide-y divide-line"><tr><td className="py-5">Assigned region</td><td className="text-teal">Visible</td></tr><tr><td className="py-5">Other regions</td><td>Restricted</td></tr><tr><td className="py-5">Sensitive columns</td><td>Restricted</td></tr></tbody></table>
    <p className="mt-3 border-t border-line pt-5 text-sm text-ink-soft">Permissions enforced on every query.</p>
  </figure>,
  <figure key="audit" className="p-6 md:p-8">
    <figcaption className="mb-6 flex justify-between border-b border-line pb-4 text-xs font-mono text-ink-soft"><span>AUDIT TRAIL</span><span>EXAMPLE</span></figcaption>
    <div className="space-y-0 text-sm"><div className="grid grid-cols-[70px_1fr] gap-4 border-b border-line py-5"><span className="font-mono text-ink-soft">09:41</span><span>Read-only connection verified</span></div><div className="grid grid-cols-[70px_1fr] gap-4 border-b border-line py-5"><span className="font-mono text-ink-soft">09:42</span><span>Revenue analysis completed</span></div><div className="grid grid-cols-[70px_1fr] gap-4 py-5"><span className="font-mono text-ink-soft">09:43</span><span>Result exported</span></div></div>
    <div className="mt-5 bg-paper px-4 py-3 font-mono text-xs text-teal">HASH-CHAINED · TAMPER-EVIDENT</div>
  </figure>,
];

export default function LandingPage() {
  const [plans, setPlans] = useState<Plan[]>([]);

  useEffect(() => {
    listPlans().catch(() => []).then((p) => p && setPlans(p));
  }, []);

  return (
    <div className="min-h-screen font-sans bg-paper text-ink [&_a]:focus-visible:outline-2 [&_a]:focus-visible:outline-offset-4 [&_a]:focus-visible:outline-teal">

      <header className="sticky top-0 z-40 bg-paper border-b border-line">
        <div className="max-w-[1200px] mx-auto px-5 md:px-8 h-[72px] flex items-center justify-between">
          <div className="flex items-center gap-2.5 font-serif text-xl sm:text-2xl tracking-tight text-ink"><span aria-hidden="true" className="flex h-8 w-8 sm:h-10 sm:w-10 items-center justify-center bg-ink text-2xl font-bold text-paper">M</span>Meridian</div>
          <nav className="hidden md:flex items-center gap-9 text-sm text-ink-soft">
            <a href="#features" className="hover:text-ink transition-colors">Product</a>
            <a href="#security" className="hover:text-ink transition-colors">Security</a>
            <a href="#pricing" className="hover:text-ink transition-colors">Pricing</a>
          </nav>
          <div className="flex items-center gap-3">
            <Link href="/login" className="text-sm text-ink-soft hover:text-ink transition-colors">
              Sign in
            </Link>
            <Link
              href="/login?mode=register"
              onClick={() => track("cta_get_started", { location: "nav" })}
              className={`text-sm px-4 sm:px-5 py-2.5 ${GLASS_BUTTON_PRIMARY}`}
            >
              Get started
            </Link>
          </div>
        </div>
      </header>

      <section className="max-w-[1200px] mx-auto px-6 md:px-8 pt-14 pb-14 md:pt-20 md:pb-20">

        <div className="flex flex-col gap-12 md:gap-16">
          <div className="mx-auto w-full max-w-[1100px] text-center">
            <div className="text-xs font-[family-name:var(--font-mono)] text-teal-deep tracking-[0.18em] uppercase mb-7">
              AI analytics for business teams
            </div>
            <h1 className="mx-auto max-w-[1000px] font-serif text-[clamp(2.25rem,4.8vw,4.25rem)] font-normal tracking-[-0.035em] text-ink leading-[1.1] mb-6 text-balance">
              <span className="block">Less time chasing reports.</span>{" "}
              <span className="block text-teal">More confidence in every decision.</span>
            </h1>
            <p className="text-base text-ink-soft leading-7 mb-7 max-w-[650px] mx-auto">
              Find out what changed, why it matters, and where to look next. Ask Meridian a question
              about your database or documents and get a clear answer with the evidence to check it.
              No SQL required. Your source data stays untouched.
            </p>
            <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-center gap-3 max-w-sm sm:max-w-none mx-auto">
              <Link
                href="/login?mode=register"
                onClick={() => track("cta_get_started", { location: "hero" })}
                className={`text-center text-sm font-medium px-6 py-3.5 ${GLASS_BUTTON_PRIMARY}`}
              >
                Start exploring free
              </Link>
              <a
                href="#features"
                className={`text-center text-sm font-medium px-6 py-3.5 ${GLASS_BUTTON_SECONDARY}`}
              >
                See Meridian in action
              </a>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-5 sm:gap-8 mt-8 mx-auto max-w-[740px] border-t border-line pt-6 text-left">
              {HERO_FLOW.map(({ icon: Icon, label }) => (
                <div key={label} className="flex items-center gap-2.5">
                  <span className="shrink-0 w-8 h-8 flex items-center justify-center text-teal-deep">
                    <Icon />
                  </span>
                  <span className="text-sm text-ink-soft leading-snug">{label}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="w-full border border-line bg-panel">
            <div className="flex items-center gap-2.5 border-b border-line bg-paper px-6 py-4 text-xs font-mono uppercase tracking-widest text-ink-soft">
              <span className="w-1.5 h-1.5 rounded-full bg-teal-deep" />
              Example analysis
            </div>
            <div className="bg-panel overflow-hidden">
              <div className="p-6 md:p-10">
                <div className="text-[13px] text-ink-soft mb-1">You asked</div>
                <div className="text-xl md:text-3xl font-serif leading-snug tracking-tight text-ink mb-7">Why did South-East revenue fall last quarter?</div>
                <div className="text-[13px] text-ink-soft mb-2">Meridian found</div>
                <div className="grid items-center gap-8 lg:grid-cols-[1.1fr_1fr] lg:gap-x-16 border-t border-line pt-6">
                  <div className="text-lg md:text-xl text-ink leading-relaxed max-w-xl">
                    South-East revenue fell 14.2% quarter-over-quarter, concentrated in two accounts
                    that churned in week 6. The decline was not spread across the region.
                  </div>

                  <div className="flex items-end gap-5 h-44 mb-1">
                    {[
                      { label: "NW", pct: 68 },
                      { label: "NE", pct: 54 },
                      { label: "SE", pct: 27 },
                      { label: "SW", pct: 61 },
                      { label: "C", pct: 47 },
                    ].map((bar) => (
                      <div key={bar.label} className="flex-1 flex flex-col items-center gap-1.5">
                        <div className="w-full flex items-end h-40 border-b border-line">
                          <div
                            className={`w-full rounded-t-[2px] ${bar.label === "SE" ? "bg-teal" : "bg-line"}`}
                            style={{ height: `${bar.pct}%` }}
                          />
                        </div>
                        <span className="text-xs text-ink-soft">{bar.label}</span>
                      </div>
                    ))}
                  </div>
                  <div className="flex flex-wrap gap-3 lg:col-span-2 border-t border-line pt-5">
                    <span className="text-xs px-3 py-1.5 bg-paper text-ink-soft font-[family-name:var(--font-mono)]">
                      SQL query included
                    </span>
                    <span className="text-xs px-3 py-1.5 bg-paper text-ink-soft font-[family-name:var(--font-mono)]">
                      2 anomalies flagged
                    </span>
                    <span className="text-xs px-3 py-1.5 bg-teal-deep text-white font-[family-name:var(--font-mono)]">
                      Confidence: high
                    </span>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="features" className="max-w-[1200px] mx-auto px-6 md:px-8 scroll-mt-24 py-14 md:py-20 border-t border-line">
        <div className="grid gap-5 lg:grid-cols-[0.8fr_1.2fr] lg:gap-20 mb-8 md:mb-12">
          <h2 className="font-serif text-3xl md:text-[2.75rem] leading-[1.15] font-normal tracking-[-0.035em] text-ink mb-3">Spend less time finding answers. More time using them.</h2>
          <p className="text-base text-ink-soft leading-relaxed">
            A missed target. A sudden revenue dip. A board meeting coming up.
            You need to understand what is happening, not spend the day piecing together reports.
            Meridian helps you move from a business question to an answer you can examine,
            explain, and use.
          </p>
        </div>
        <div className="divide-y divide-line">
          {FEATURES.map((f, index) => {
            // Alternates text/visual sides every other row for an editorial
            // feel instead of a repetitive fixed grid - computed in JS
            // rather than a CSS "nth-child of group" selector, since
            // Tailwind has no built-in variant for that.
            const reversed = index % 2 === 1;
            return (
              <article key={f.title} className="grid items-center gap-8 py-10 md:py-14 lg:grid-cols-2 lg:gap-16">
                <div className={reversed ? "lg:order-2" : undefined}>
                  <h3 className="mb-4 max-w-lg font-serif text-[1.75rem] leading-[1.2] tracking-[-0.025em] md:text-[2.15rem]">{f.title}</h3>
                  <p className="max-w-[52ch] text-base leading-7 text-ink-soft">{f.body}</p>
                </div>
                <div className={`min-w-0 border border-line bg-panel ${reversed ? "lg:order-1" : ""}`}>
                  {FEATURE_VISUALS[index]}
                </div>
              </article>
            );
          })}
        </div>
      </section>

      <section className="max-w-[1200px] mx-auto px-6 md:px-8 scroll-mt-24 py-14 md:py-20 border-t border-line">
        <h2 className="font-serif text-3xl md:text-[2.75rem] leading-[1.15] font-normal tracking-[-0.035em] text-ink mb-12">From your first question to the evidence</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-8 md:gap-10">
          {STEPS.map((s) => (
            <div key={s.n} className="border-t border-line pt-6">
              <div className="font-mono text-sm text-teal-deep mb-5">{s.n}</div>
              <div className="text-xl font-medium text-ink mb-3">{s.title}</div>
              <div className="text-base text-ink-soft leading-relaxed">{s.body}</div>
            </div>
          ))}
        </div>
      </section>

      <section id="security" className="max-w-[1200px] mx-auto px-6 md:px-8 scroll-mt-24 py-14 md:py-20 border-t border-line">
        <div className="max-w-xl mb-10">
          <h2 className="font-serif text-3xl md:text-[2.75rem] leading-[1.15] font-normal tracking-[-0.035em] text-ink mb-3">Move forward with control over your data</h2>
          <p className="text-base text-ink-soft leading-relaxed">
            Giving your team an analytics tool should not mean giving up control.
            Meridian combines verified read-only connections, scoped access, and an audit trail
            to support your security review.
          </p>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-12 gap-y-0">
          {[
            "Protect source records with connections that must pass a read-only check before they are saved.",
            "Keep stored credentials encrypted, with AWS KMS envelope encryption available for production.",
            "Control access by role, row, and column, with permissions enforced on every query.",
            "Add two-factor authentication for individual users or require it across your organization.",
            "Review queries, connection changes, and exports in a tamper-evident audit log.",
            "Treat uploaded content and database results as data to analyze, rather than instructions for the AI to follow.",
          ].map((point) => (
            <div key={point} className="flex items-start gap-3 border-t border-line py-5">
              <span className="text-teal-deep shrink-0 mt-0.5">✓</span>
              <span className="text-base text-ink-soft leading-relaxed">{point}</span>
            </div>
          ))}
        </div>
      </section>

      <section id="pricing" className="max-w-[1200px] mx-auto px-6 md:px-8 scroll-mt-24 py-14 md:py-20 border-t border-line">
        <div className="max-w-xl mb-12">
          <h2 className="font-serif text-3xl md:text-[2.75rem] leading-[1.15] font-normal tracking-[-0.035em] text-ink mb-3">Choose the plan that fits your team</h2>
          <p className="text-base text-ink-soft leading-relaxed">
            Get the full product on every plan. Choose the capacity your team needs for people,
            data sources, questions, and downloads, with clear monthly limits.
          </p>
        </div>

        {plans.length === 0 ? (
          <div className="text-[13px] text-ink-soft">Loading pricing…</div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
            {plans.map((plan) => (
              <div
                key={plan.key}
                className={`relative bg-panel border p-7 md:p-8 flex flex-col ${
                  plan.key === "pro" ? "border-teal-deep border-2 bg-paper" : "border-line"
                }`}
              >
                {plan.key === "pro" && (
                  <span className="absolute -top-3 left-7 text-xs px-3 py-1 bg-teal-deep text-white">
                    Most popular
                  </span>
                )}
                <div className="text-xl font-medium text-ink mb-4">{plan.label}</div>
                <div className="font-serif text-4xl text-ink tracking-tight mb-2">
                  {formatNaira(plan.amount)}
                  <span className="text-[13px] text-ink-soft font-normal">/mo</span>
                </div>
                <div className="text-sm text-ink-soft mb-5">{plan.tagline}</div>
                <ul className="flex flex-col gap-2 mb-6 flex-1">
                  {plan.features.map((f, i) => (
                    <li key={i} className="text-sm text-ink flex items-start gap-2">
                      <span className="text-teal-deep shrink-0">✓</span>
                      <span>{f}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  href="/login?mode=register"
                  onClick={() => track("cta_get_started", { location: "pricing", plan: plan.key })}
                  className={`text-center text-sm px-5 py-3 ${plan.key === "pro" ? GLASS_BUTTON_PRIMARY : GLASS_BUTTON_SECONDARY}`}
                >
                  Get started
                </Link>
              </div>
            ))}
          </div>
        )}
      </section>

      <section className="max-w-[1200px] mx-auto px-6 md:px-8 scroll-mt-24 py-14 md:py-20 border-t border-line bg-panel text-center">
        <h2 className="font-serif text-3xl md:text-[2.75rem] leading-[1.15] font-normal tracking-[-0.035em] text-ink mb-4">
          What question is holding up your next decision?
        </h2>
        <p className="text-base text-ink-soft leading-relaxed mb-8 max-w-xl mx-auto">
          Bring a report or connect a database. Ask the question you need answered,
          then see what your data can tell you.
        </p>
        <Link
          href="/login?mode=register"
          onClick={() => track("cta_get_started", { location: "final_cta" })}
          className={`inline-block text-base px-8 py-3.5 ${GLASS_BUTTON_PRIMARY}`}
        >
          Start exploring free
        </Link>
      </section>

      <footer className="border-t border-line">
        <div className="max-w-[1200px] mx-auto px-6 md:px-8 py-14 grid grid-cols-2 lg:grid-cols-5 gap-x-8 gap-y-10">
          <div className="col-span-2 lg:col-span-2 pr-4">
            <div className="font-serif text-3xl tracking-tight text-ink mb-4">Meridian</div>
            <p className="text-sm text-ink-soft leading-relaxed max-w-[260px] mb-3">
              Business answers backed by your data. Ask in plain English,
              review the evidence, and make your next decision with more confidence.
            </p>
            <p className="text-xs text-ink-soft/70 leading-relaxed max-w-[260px] mb-4">
              A product of Meridian Techverse Limited (RC 9849528), Nigeria.
            </p>
            <div className="flex items-center gap-2 text-xs text-ink-soft border border-line rounded-[4px] px-3 py-2 max-w-[260px]">
              <LockIcon />
              <span>
                Payments secured by <strong className="text-ink font-medium">Paystack</strong>.
                PCI DSS Level 1 certified
              </span>
            </div>
          </div>

          <div>
            <div className="text-xs font-medium text-ink uppercase tracking-wide mb-3">Product</div>
            <nav className="flex flex-col gap-3 text-sm text-ink-soft">
              <a href="#features" className="hover:text-ink transition-colors">Product</a>
              <a href="#security" className="hover:text-ink transition-colors">Security</a>
              <a href="#pricing" className="hover:text-ink transition-colors">Pricing</a>
            </nav>
          </div>

          <div>
            <div className="text-xs font-medium text-ink uppercase tracking-wide mb-3">Account</div>
            <nav className="flex flex-col gap-3 text-sm text-ink-soft">
              <Link href="/login" className="hover:text-ink transition-colors">Sign in</Link>
              <Link href="/login?mode=register" className="hover:text-ink transition-colors">Create account</Link>
            </nav>
          </div>

          <div>
            <div className="text-xs font-medium text-ink uppercase tracking-wide mb-3">Legal &amp; support</div>
            <nav className="flex flex-col gap-3 text-sm text-ink-soft">
              <Link href="/status" className="hover:text-ink transition-colors">System status</Link>
              <Link href="/privacy" className="hover:text-ink transition-colors">Privacy Policy</Link>
              <Link href="/terms" className="hover:text-ink transition-colors">Terms of Service</Link>
              <a href="mailto:hello@getmeridiananalytics.com" className="hover:text-ink transition-colors">Contact us</a>
            </nav>
          </div>
        </div>

        <div className="border-t border-line">
          <div className="max-w-[1200px] mx-auto px-6 md:px-8 py-6 flex flex-col lg:flex-row items-start lg:items-center justify-between gap-4">
            <div className="text-xs text-ink-soft">
              © {new Date().getFullYear()} Meridian Techverse Limited. All rights reserved.
            </div>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-ink-soft">
              <span>Read-only by design</span>
              <span className="text-line hidden sm:inline">•</span>
              <span className="flex items-center gap-1.5">
                <LockIcon small />
                Secured checkout via Paystack
              </span>
            </div>
            <div className="flex items-center gap-3.5 text-ink-soft">
              {SOCIAL_LINKS.map(({ name, href, Icon }) =>
                href ? (
                  <a
                    key={name} href={href} target="_blank" rel="noopener noreferrer" aria-label={name}
                    className="hover:text-ink transition-colors"
                  >
                    <Icon />
                  </a>
                ) : (
                  <span key={name} aria-hidden="true" className="opacity-30">
                    <Icon />
                  </span>
                )
              )}
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
