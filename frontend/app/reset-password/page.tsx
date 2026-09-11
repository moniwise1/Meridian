"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { redeemPasswordReset } from "@/lib/api";
import { saveSession } from "@/lib/auth";

// Reached from the link in a staff-triggered password-reset email (see
// lib/platformApi.ts's resetUserPassword, backend/app/api/
// routes_platform.py's reset_user_password) - a locked-out user with no
// session and no old password to prove. Redeeming sets the new password
// AND signs the user straight in (a real session comes back), so this is
// the one form, not a separate "now log in again" step afterward.
function ResetPasswordPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(token ? "" : "This reset link is missing its token.");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (password !== confirmPassword) {
      setError("Passwords don't match.");
      return;
    }
    setSubmitting(true);
    try {
      const auth = await redeemPasswordReset(token, password);
      saveSession({
        token: auth.access_token, tenantId: auth.tenant_id, userId: auth.user_id,
        role: auth.role, email: auth.email ?? "",
      });
      router.replace("/");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSubmitting(false);
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
          <div className="text-[15px] font-medium text-ink mb-1.5">Set a new password</div>
          <p className="text-[12.5px] text-ink-soft leading-relaxed mb-5">
            Choose a new password to finish resetting your account. You&apos;ll be signed in
            immediately afterward.
          </p>

          {token ? (
            <form onSubmit={handleSubmit} className="flex flex-col gap-3">
              <label className="flex flex-col gap-1">
                <span className="text-[12px] text-ink-soft">New password</span>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="At least 8 characters"
                  required
                  minLength={8}
                  className="text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-[12px] text-ink-soft">Confirm new password</span>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="••••••••"
                  required
                  minLength={8}
                  className="text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
                />
              </label>
              {error && <div className="text-[12.5px] text-red">{error}</div>}
              <button
                type="submit"
                disabled={submitting}
                className="mt-1 text-[13px] py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
              >
                {submitting ? "Setting password…" : "Set password and sign in"}
              </button>
            </form>
          ) : (
            <>
              <div className="text-[12.5px] text-red mb-4">{error}</div>
              <a href="/login" className="text-[12.5px] text-teal hover:text-teal-deep transition-colors">
                Back to sign in
              </a>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordPageInner />
    </Suspense>
  );
}
