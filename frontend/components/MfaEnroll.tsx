"use client";

import { useEffect, useState } from "react";
import type { MfaEnrollment } from "@/lib/api";

// Shared QR-scan-then-confirm UI, used in three places that each supply
// their own onStart/onConfirm: the mandatory step right after
// registration (self-service /auth/mfa/setup + /confirm, since register()
// already grants a real session), the login-time enrollment path (a
// tenant that turned on the org policy after this user last logged in —
// /auth/mfa/setup-login + /confirm-login, no real session yet), and the
// opt-in flow on the Security page (self-service, same endpoints as the
// post-registration case). No skip button anywhere this is used — every
// caller reaches this screen because completing it is mandatory in that
// context.
export default function MfaEnroll({
  onStart,
  onConfirm,
  title = "Set up two-factor authentication",
  description = "Scan this QR code with an authenticator app (Google Authenticator, Authy, 1Password, etc.), then enter the 6-digit code it shows.",
}: {
  onStart: () => Promise<MfaEnrollment>;
  onConfirm: (code: string) => Promise<void>;
  title?: string;
  description?: string;
}) {
  const [enrollment, setEnrollment] = useState<MfaEnrollment | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [loadingQr, setLoadingQr] = useState(true);
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    // onStart isn't a read — every call generates a NEW secret server-side
    // and invalidates whatever was pending before (see /auth/mfa/setup's
    // docstring: "calling this again before confirming just replaces the
    // pending secret"). React's Strict Mode deliberately double-invokes
    // effects in dev to surface exactly this kind of bug: without the
    // `ignore` guard below, the FIRST call's now-stale secret could still
    // win the setEnrollment race and end up displayed on screen — a QR
    // code the server has already discarded, which would make every code
    // typed against it fail with a confusing "Incorrect code" (caught live
    // against a real dev server before shipping, not merely reasoned
    // about). The guard doesn't stop onStart from firing twice; it just
    // makes sure only the call whose effect instance is still mounted is
    // allowed to update what's shown, so the screen always matches
    // whatever secret is actually live server-side.
    let ignore = false;
    onStart()
      .then((result) => {
        if (!ignore) setEnrollment(result);
      })
      .catch((e) => {
        if (!ignore) setError((e as Error).message);
      })
      .finally(() => {
        if (!ignore) setLoadingQr(false);
      });
    return () => {
      ignore = true;
    };
    // Intentionally run once per mount — onStart is expected to be a
    // stable-enough reference from the caller for this component's
    // purposes (a fresh inline function per parent render would only
    // re-run this if the parent itself re-rendered, which none of this
    // component's current callers do while it's showing).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleConfirm(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setConfirming(true);
    try {
      await onConfirm(code);
    } catch (err) {
      setError((err as Error).message);
      setCode("");
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="w-full max-w-sm">
      <div className="bg-panel border border-line rounded-[4px] p-6">
        <div className="text-[15px] font-medium text-ink mb-1.5">{title}</div>
        <p className="text-[12.5px] text-ink-soft leading-relaxed mb-5">{description}</p>

        {loadingQr && <div className="text-[13px] text-ink-soft">Loading…</div>}

        {enrollment && (
          <>
            <div className="flex justify-center mb-4">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={enrollment.qr_code}
                alt="Authenticator QR code"
                className="w-40 h-40 border border-line rounded-[4px] bg-white p-1"
              />
            </div>
            <div className="mb-5">
              <div className="text-[11px] text-ink-soft mb-1">Can&apos;t scan? Enter this key manually:</div>
              <div className="text-[12px] font-[family-name:var(--font-mono)] text-ink bg-paper border border-line rounded-[3px] px-2.5 py-1.5 break-all select-all">
                {enrollment.secret}
              </div>
            </div>

            <form onSubmit={handleConfirm} className="flex flex-col gap-3">
              <label className="flex flex-col gap-1">
                <span className="text-[12px] text-ink-soft">6-digit code</span>
                <input
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  placeholder="000000"
                  required
                  minLength={6}
                  maxLength={6}
                  className="text-[16px] tracking-[0.3em] text-center font-[family-name:var(--font-mono)] border border-line rounded-[3px] px-2.5 py-2 bg-panel text-ink placeholder:text-ink-soft/40 focus:outline-none focus:ring-1 focus:ring-teal"
                />
              </label>
              {error && <div className="text-[12.5px] text-red">{error}</div>}
              <button
                type="submit"
                disabled={confirming || code.length !== 6}
                className="text-[13px] py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
              >
                {confirming ? "Verifying…" : "Confirm"}
              </button>
            </form>
          </>
        )}

        {!loadingQr && !enrollment && error && <div className="text-[12.5px] text-red">{error}</div>}
      </div>
    </div>
  );
}
