"use client";

import { Suspense, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { registerInterest } from "@/lib/api";
import { track } from "@/lib/analytics";

// The page a Facebook ad points at. Deliberately its own route rather than
// a section of the landing page: an ad click should land on the thing it
// promised, with nothing above it to scroll past, and the ad's own
// ?source= / ?campaign= travel with the enquiry so spend can be judged
// per campaign later.

function InterestForm() {
  const params = useSearchParams();
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
    try {
      await registerInterest({
        full_name: fullName,
        business_name: businessName || null,
        email,
        phone,
        message: message || null,
        consent,
        source: params.get("source"),
        campaign: params.get("campaign"),
        company_website: honeypot,
      });
      track("interest_registered", { source: params.get("source") ?? "direct" });
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
        <h1 className="font-serif text-3xl text-ink mb-3">Thank you — we&apos;ll be in touch.</h1>
        <p className="text-[14px] text-ink-soft leading-relaxed mb-6">
          We&apos;ve got your details and someone from Meridian will call or email you shortly.
        </p>
        <Link href="/" className="text-[13.5px] text-teal hover:text-teal-deep transition-colors">
          Back to Meridian
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="bg-panel border border-line rounded-[6px] p-6 md:p-8 flex flex-col gap-4">
      <Field label="Your name" value={fullName} onChange={setFullName} required placeholder="Ada Obi" autoComplete="name" />
      <Field label="Business name" value={businessName} onChange={setBusinessName} optional placeholder="Obi Logistics" autoComplete="organization" />
      <Field label="Phone number" value={phone} onChange={setPhone} required placeholder="0803 123 4567" type="tel" autoComplete="tel" />
      <Field label="Email" value={email} onChange={setEmail} required placeholder="you@company.com" type="email" autoComplete="email" />

      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] text-ink">
          What would you like to know? <span className="text-ink-soft">(optional)</span>
        </span>
        <textarea
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          rows={3}
          maxLength={2000}
          placeholder="Tell us a little about your data and what you'd like answered."
          className="text-[13.5px] border border-line rounded-[4px] px-3 py-2 bg-paper text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
        />
      </label>

      {/* Honeypot: never shown to a person, and not reachable by keyboard.
          Anything that fills it in is a bot (see routes_leads.py). */}
      <div aria-hidden className="absolute left-[-9999px] top-0 h-0 w-0 overflow-hidden">
        <label>
          Company website
          <input
            type="text"
            tabIndex={-1}
            autoComplete="off"
            value={honeypot}
            onChange={(e) => setHoneypot(e.target.value)}
          />
        </label>
      </div>

      <label className="flex items-start gap-2.5 text-[12.5px] text-ink-soft leading-relaxed cursor-pointer">
        <input
          type="checkbox"
          checked={consent}
          onChange={(e) => setConsent(e.target.checked)}
          className="mt-0.5 accent-teal-deep"
        />
        <span>
          Meridian may contact me about this enquiry. See our{" "}
          <Link href="/privacy" className="text-teal hover:text-teal-deep transition-colors">
            Privacy Policy
          </Link>
          .
        </span>
      </label>

      {error && <div role="alert" className="text-[13px] text-red">{error}</div>}

      <button
        type="submit"
        disabled={busy}
        className="mt-1 text-[14px] py-3 rounded-full bg-teal-deep text-white font-medium hover:bg-teal transition-colors disabled:opacity-40"
      >
        {busy ? "Sending…" : "Register my interest"}
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

export default function RegisterInterestPage() {
  return (
    <div className="min-h-screen bg-paper">
      <div className="max-w-xl mx-auto px-6 py-12 md:py-16">
        <Link href="/" className="font-serif text-2xl tracking-tight text-ink">Meridian</Link>
        <h1 className="font-serif text-3xl md:text-[2.5rem] leading-[1.15] tracking-[-0.03em] text-ink mt-8 mb-3">
          Register your interest
        </h1>
        <p className="text-[15px] text-ink-soft leading-relaxed mb-8">
          Ask questions about your business data in plain English and get an answer with the evidence
          behind it. Leave your details and we&apos;ll show you what Meridian can do with yours.
        </p>
        <Suspense fallback={<div className="text-[13px] text-ink-soft">Loading…</div>}>
          <InterestForm />
        </Suspense>
      </div>
    </div>
  );
}
