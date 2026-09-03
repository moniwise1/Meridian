"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { verifyPayment } from "@/lib/api";

function CallbackContent() {
  const searchParams = useSearchParams();
  const [state, setState] = useState<"verifying" | "success" | "error">("verifying");
  const [error, setError] = useState("");

  useEffect(() => {
    // Paystack redirects back with ?reference=... (sometimes also
    // ?trxref=...) - never trust that the redirect itself means the
    // payment succeeded, always re-verify server-side (the frontend
    // equivalent of the backend's own "never trust the client's claim"
    // rule for this exact step).
    const reference = searchParams.get("reference") ?? searchParams.get("trxref");
    if (!reference) {
      setState("error");
      setError("No payment reference in the redirect — if you completed checkout, check Billing directly.");
      return;
    }
    verifyPayment(reference)
      .then(() => setState("success"))
      .catch((e) => {
        setState("error");
        setError(e.message);
      });
  }, [searchParams]);

  return (
    <div className="bg-panel border border-line rounded-[4px] p-5 text-center">
      {state === "verifying" && <div className="text-[13.5px] text-ink-soft">Confirming your payment…</div>}
      {state === "success" && (
        <>
          <div className="text-[15px] text-ink mb-2">You&apos;re subscribed.</div>
          <div className="text-[13px] text-ink-soft mb-4">Your subscription is now active.</div>
        </>
      )}
      {state === "error" && (
        <>
          <div className="text-[15px] text-ink mb-2">Could not confirm payment</div>
          <div className="text-[13px] text-red mb-4">{error}</div>
        </>
      )}
      <Link href="/billing" className="text-[13px] text-teal hover:text-teal-deep transition-colors">
        Go to Billing
      </Link>
    </div>
  );
}

export default function BillingCallbackPage() {
  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <Suspense fallback={<div className="text-[13.5px] text-ink-soft">Loading…</div>}>
        <CallbackContent />
      </Suspense>
    </div>
  );
}
