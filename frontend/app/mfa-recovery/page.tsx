"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { redeemMfaRecovery } from "@/lib/api";

// Reached from the link in an MFA-recovery email (see lib/api.ts's
// requestMfaRecovery, triggered from the mfa_code step of login/page.tsx)
// - a lost-authenticator user with no session and no code to enter.
// Deliberately does NOT redeem automatically on load, unlike
// /auth/handoff or /accept-invite: this action is security-REDUCING (it
// disables the account's two-factor protection), so an automated email
// link-scanner prefetching this URL must never be able to trigger it by
// itself. The visitor has to see what they're about to do and click
// "Yes, disable it" themselves.
function MfaRecoveryPageInner() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const [status, setStatus] = useState<"idle" | "working" | "done" | "error">(token ? "idle" : "error");
  const [error, setError] = useState(token ? "" : "This recovery link is missing its token.");

  async function handleConfirm() {
    setStatus("working");
    setError("");
    try {
      await redeemMfaRecovery(token);
      setStatus("done");
    } catch (e) {
      setError((e as Error).message);
      setStatus("error");
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-paper px-6">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="text-[16px] font-semibold tracking-tight text-ink">Meridian</div>
          <div className="text-[12px] text-ink-soft mt-0.5">Enterprise analytics</div>
        </div>

        <div className="bg-panel border border-line rounded-[4px] p-6">
          {status === "done" ? (
            <>
              <div className="text-[15px] font-medium text-ink mb-1.5">Two-factor authentication reset</div>
              <p className="text-[12.5px] text-ink-soft leading-relaxed mb-4">
                Your lost authenticator has been disabled. Sign back in — you&apos;ll be prompted to
                set up a new one before you can continue.
              </p>
              <a href="/login" className="text-[12.5px] text-teal hover:text-teal-deep transition-colors">
                Go to sign in →
              </a>
            </>
          ) : status === "error" ? (
            <>
              <div className="text-[15px] font-medium text-ink mb-1.5">Recovery link not available</div>
              <p className="text-[12.5px] text-ink-soft leading-relaxed mb-4">{error}</p>
              <a href="/login" className="text-[12.5px] text-teal hover:text-teal-deep transition-colors">
                Back to sign in
              </a>
            </>
          ) : (
            <>
              <div className="text-[15px] font-medium text-ink mb-1.5">Reset two-factor authentication?</div>
              <p className="text-[12.5px] text-ink-soft leading-relaxed mb-5">
                This disables the lost authenticator on your account. You&apos;ll be asked to set up
                a new one the next time you sign in. If you didn&apos;t request this, close this page
                — your account isn&apos;t affected until you confirm.
              </p>
              <button
                type="button"
                onClick={handleConfirm}
                disabled={status === "working"}
                className="w-full text-[13px] py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
              >
                {status === "working" ? "Resetting…" : "Yes, disable my lost authenticator"}
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function MfaRecoveryPage() {
  return (
    <Suspense fallback={null}>
      <MfaRecoveryPageInner />
    </Suspense>
  );
}
