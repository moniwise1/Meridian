"use client";

import { useEffect, useState } from "react";
import {
  getMfaStatus, startMfaSetup, confirmMfaSetup, disableMfa, setMfaPolicy,
  type MfaStatus,
} from "@/lib/api";
import { loadSession } from "@/lib/auth";
import MfaEnroll from "@/components/MfaEnroll";

export default function SecurityPage() {
  const [status, setStatus] = useState<MfaStatus | null>(null);
  const [error, setError] = useState("");
  const [enrolling, setEnrolling] = useState(false);
  const [disabling, setDisabling] = useState(false);
  const [disableCode, setDisableCode] = useState("");
  const [disableError, setDisableError] = useState("");
  const [policyBusy, setPolicyBusy] = useState(false);
  const isAdmin = loadSession()?.role === "admin";

  function refresh() {
    getMfaStatus()
      .then(setStatus)
      .catch((e) => setError((e as Error).message));
  }

  useEffect(refresh, []);

  async function handleDisable(e: React.FormEvent) {
    e.preventDefault();
    setDisableError("");
    try {
      await disableMfa(disableCode);
      setDisabling(false);
      setDisableCode("");
      refresh();
    } catch (e) {
      setDisableError((e as Error).message);
    }
  }

  async function togglePolicy(next: boolean) {
    setPolicyBusy(true);
    setError("");
    try {
      await setMfaPolicy(next);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setPolicyBusy(false);
    }
  }

  if (enrolling) {
    return (
      <div className="max-w-3xl mx-auto px-8 py-12">
        <MfaEnroll
          onStart={startMfaSetup}
          onConfirm={async (code) => {
            await confirmMfaSetup(code);
            setEnrolling(false);
            refresh();
          }}
        />
        <button
          onClick={() => setEnrolling(false)}
          className="mt-4 text-[12px] text-ink-soft hover:text-ink transition-colors"
        >
          ← Cancel
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Security</h1>
      <p className="text-[13.5px] text-ink-soft mb-8">
        Two-factor authentication adds a 6-digit code from an authenticator app to your password at
        sign-in.
      </p>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}

      <div className="bg-panel border border-line rounded-[4px] p-4 mb-6">
        <div className="text-[13.5px] text-ink mb-1">Two-factor authentication</div>
        {!status && !error && <div className="text-[12.5px] text-ink-soft">Loading…</div>}
        {status && (
          <>
            <div className="text-[12.5px] text-ink-soft mb-3">
              {status.enabled ? "Enabled on your account." : "Not enabled on your account."}
              {status.tenant_requires_mfa && (
                <span className="block mt-1 text-amber">
                  Your organization requires two-factor authentication{status.enabled ? "" : " — set it up below"}.
                </span>
              )}
            </div>

            {!status.enabled && (
              <button
                onClick={() => setEnrolling(true)}
                className="text-[12.5px] px-3 py-1.5 rounded-[3px] bg-teal-deep text-white hover:bg-teal transition-colors"
              >
                Set up two-factor authentication
              </button>
            )}

            {status.enabled && status.tenant_requires_mfa && (
              <div className="text-[11.5px] text-ink-soft">
                Two-factor authentication can&apos;t be disabled while your organization requires it.
              </div>
            )}

            {status.enabled && !status.tenant_requires_mfa && !disabling && (
              <button
                onClick={() => setDisabling(true)}
                className="text-[12.5px] text-red hover:opacity-70 transition-opacity"
              >
                Disable two-factor authentication
              </button>
            )}

            {status.enabled && !status.tenant_requires_mfa && disabling && (
              <form onSubmit={handleDisable} className="flex flex-col gap-2 mt-2 max-w-[220px]">
                <label className="flex flex-col gap-1">
                  <span className="text-[12px] text-ink-soft">
                    Enter a current code to confirm
                  </span>
                  <input
                    type="text"
                    inputMode="numeric"
                    autoComplete="one-time-code"
                    value={disableCode}
                    onChange={(e) => setDisableCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                    placeholder="000000"
                    required
                    minLength={6}
                    maxLength={6}
                    className="text-[14px] tracking-[0.2em] text-center font-[family-name:var(--font-mono)] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/40"
                  />
                </label>
                {disableError && <div className="text-[12px] text-red">{disableError}</div>}
                <div className="flex items-center gap-2">
                  <button
                    type="submit"
                    disabled={disableCode.length !== 6}
                    className="text-[12.5px] px-3 py-1.5 rounded-[3px] bg-red text-white disabled:opacity-40 hover:opacity-90 transition-opacity"
                  >
                    Confirm disable
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setDisabling(false);
                      setDisableCode("");
                      setDisableError("");
                    }}
                    className="text-[12px] text-ink-soft hover:text-ink transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </>
        )}
        <p className="text-[11px] text-ink-soft leading-relaxed mt-4 border-t border-line pt-3">
          There is currently no self-service recovery for a lost authenticator device — ask an admin
          to remove and re-add your account if you lose access.
        </p>
      </div>

      {isAdmin && status && (
        <div className="bg-panel border border-line rounded-[4px] p-4">
          <div className="text-[13.5px] text-ink mb-1">Organization policy</div>
          <p className="text-[12.5px] text-ink-soft mb-3">
            Require two-factor authentication for every account on this tenant, present and future.
            Anyone not yet enrolled will be walked through setup the next time they sign in.
          </p>
          <label className="flex items-center gap-2 text-[12.5px] text-ink cursor-pointer w-fit">
            <input
              type="checkbox"
              checked={status.tenant_requires_mfa}
              disabled={policyBusy}
              onChange={(e) => togglePolicy(e.target.checked)}
              className="accent-teal-deep"
            />
            Require two-factor authentication for everyone
          </label>
        </div>
      )}
    </div>
  );
}
