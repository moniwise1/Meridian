"use client";

import { useState } from "react";
import Link from "next/link";
import { registerInterest } from "@/lib/api";
import { track } from "@/lib/analytics";
import { trackLead } from "@/components/MetaPixel";

// The enquiry form itself, used in two places: the "Inquire now" section of
// the landing page, and the standalone /interest page an ad points at.
// One component so the two can never drift apart - the same fields, the
// same validation, the same thank-you.
//
// Where the enquiry came from is read from the page's own query string
// (?source=facebook&campaign=…) at submit time rather than through
// useSearchParams, so this can be dropped into any page - including a
// statically rendered one - without a Suspense boundary around it.

export default function InterestForm({
  defaultSource,
  compact = false,
}: {
  defaultSource: string;
  compact?: boolean;
}) {
  const [fullName, setFullName] = useState("");
  const [businessName, setBusinessName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [message, setMessage] = useState("");
  const [consent, setConsent] = useState(false);
  const [honeypot, setHoneypot] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError("");
    const params = new URLSearchParams(typeof window === "undefined" ? "" : window.location.search);
    const source = params.get("source") ?? defaultSource;
    try {
      await registerInterest({
        full_name: fullName,
        business_name: businessName || null,
        email,
        phone,
        message: message || null,
        consent,
        source,
        campaign: params.get("campaign"),
        company_website: honeypot,
      });
      track("interest_registered", { source });
      // Reports the conversion to Meta so a campaign can be optimised
      // against enquiries rather than clicks. Only the fact of a
      // submission is sent - no name, email, phone or message. Does
      // nothing if the pixel was never loaded on this page.
      trackLead();
      setDone(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <div className="bg-panel border border-line rounded-[6px] p-8 text-center">
        <div className="font-serif text-2xl text-ink mb-2">Thank you — we&apos;ll be in touch.</div>
        <p className="text-[13.5px] text-ink-soft leading-relaxed">
          We&apos;ve got your details. Someone from Meridian will call or email you shortly.
        </p>
      </div>
    );
  }

  return (
    <form
      onSubmit={submit}
      className={`bg-panel border border-line rounded-[6px] flex flex-col gap-4 ${compact ? "p-5 md:p-6" : "p-6 md:p-8"}`}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Your name" value={fullName} onChange={setFullName} required placeholder="Ada Obi" autoComplete="name" />
        <Field label="Business name" value={businessName} onChange={setBusinessName} optional placeholder="Obi Logistics" autoComplete="organization" />
        <Field label="Phone number" value={phone} onChange={setPhone} required placeholder="0803 123 4567" type="tel" autoComplete="tel" />
        <Field label="Email" value={email} onChange={setEmail} required placeholder="you@company.com" type="email" autoComplete="email" />
      </div>

      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] text-ink">
          What would you like to know? <span className="text-ink-soft">(optional)</span>
        </span>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={compact ? 2 : 3}
          maxLength={2000}
          placeholder="Tell us a little about your data and what you'd like answered."
          className="text-[13.5px] border border-line rounded-[4px] px-3 py-2 bg-paper text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
        />
      </label>

      {/* Honeypot: off-screen, hidden from assistive tech and unreachable by
          keyboard. Anything that fills it is a bot (see routes_leads.py). */}
      <div aria-hidden className="absolute left-[-9999px] top-0 h-0 w-0 overflow-hidden">
        <label>
          Company website
          <input type="text" tabIndex={-1} autoComplete="off" value={honeypot}
                 onChange={(e) => setHoneypot(e.target.value)} />
        </label>
      </div>

      <label className="flex items-start gap-2.5 text-[12.5px] text-ink-soft leading-relaxed cursor-pointer">
        <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)}
               className="mt-0.5 accent-teal-deep" />
        <span>
          Meridian may contact me about this enquiry. See our{" "}
          <Link href="/privacy" className="text-teal hover:text-teal-deep transition-colors">Privacy Policy</Link>.
        </span>
      </label>

      {error && <div role="alert" className="text-[13px] text-red">{error}</div>}

      <button
        type="submit"
        disabled={busy}
        className="mt-1 text-[14px] py-3 rounded-full bg-teal-deep text-white font-medium hover:bg-teal transition-colors disabled:opacity-40"
      >
        {busy ? "Sending…" : "Inquire now"}
      </button>
      <p className="text-[12px] text-ink-soft text-center">
        No payment now. We&apos;ll answer your questions first.
      </p>
    </form>
  );
}

function Field({
  label, value, onChange, placeholder, type = "text", required = false, optional = false, autoComplete,
}: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string;
  type?: string; required?: boolean; optional?: boolean; autoComplete?: string;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-[13px] text-ink">
        {label} {optional && <span className="text-ink-soft">(optional)</span>}
      </span>
      <input
        type={type}
        value={value}
        required={required}
        autoComplete={autoComplete}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="text-[13.5px] border border-line rounded-[4px] px-3 py-2 bg-paper text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
      />
    </label>
  );
}
