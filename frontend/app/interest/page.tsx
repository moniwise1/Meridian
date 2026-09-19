"use client";

import Link from "next/link";
import InterestForm from "@/components/InterestForm";

// The page an ad points at. Deliberately its own route rather than only a
// section of the landing page: an ad click should land on the thing it
// promised, with nothing above it to scroll past. The same form also sits
// in the "Inquire now" section of the landing page, for people who arrive
// the ordinary way and read first.

export default function RegisterInterestPage() {
  return (
    <div className="min-h-screen bg-paper">
      <div className="max-w-2xl mx-auto px-6 py-12 md:py-16">
        <Link href="/" className="font-serif text-2xl tracking-tight text-ink">Meridian</Link>
        <h1 className="font-serif text-3xl md:text-[2.5rem] leading-[1.15] tracking-[-0.03em] text-ink mt-8 mb-3">
          Inquire now
        </h1>
        <p className="text-[15px] text-ink-soft leading-relaxed mb-8">
          Ask questions about your business data in plain English and get an answer with the evidence
          behind it. Leave your details and we&apos;ll show you what Meridian can do with yours.
        </p>
        <InterestForm defaultSource="interest_page" />
        <p className="mt-6 text-center text-[13px] text-ink-soft">
          <Link href="/" className="text-teal hover:text-teal-deep transition-colors">
            Back to Meridian
          </Link>
        </p>
      </div>
    </div>
  );
}
