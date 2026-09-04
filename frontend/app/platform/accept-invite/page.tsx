"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { lookupStaffInvite, acceptStaffInvite, type StaffInviteLookup } from "@/lib/platformApi";
import { savePlatformSession } from "@/lib/platformAuth";

// Reached from the link in a platform-staff invite email (see
// lib/platformApi.ts's inviteStaff / backend's routes_platform.py
// _staff_accept_url). Public - deliberately outside the normal
// /platform/* session gate (see app/platform/layout.tsx), since proving
// there's no session yet is the whole point of being here.
function PlatformAcceptInvitePageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token") ?? "";

  const [invite, setInvite] = useState<StaffInviteLookup | null>(null);
  const [lookupError, setLookupError] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");

  useEffect(() => {
    if (!token) {
      setLookupError("This invite link is missing its token.");
      return;
    }
    lookupStaffInvite(token)
      .then(setInvite)
      .catch((e) => setLookupError((e as Error).message));
  }, [token]);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitError("");
    if (password !== confirmPassword) {
      setSubmitError("Passwords don't match.");
      return;
    }
    setSubmitting(true);
    try {
      const auth = await acceptStaffInvite(token, password);
      savePlatformSession({
        token: auth.access_token, staffId: auth.staff_id, role: auth.role,
        email: invite?.email ?? "",
      });
      router.push("/platform");
    } catch (e) {
      setSubmitError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-paper px-6">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="text-[16px] font-semibold tracking-tight text-ink">Meridian</div>
          <div className="text-[12px] text-ink-soft mt-0.5">Internal admin</div>
        </div>

        <div className="bg-panel border border-line rounded-[4px] p-6">
          {lookupError ? (
            <>
              <div className="text-[15px] font-medium text-ink mb-1.5">Invite not available</div>
              <p className="text-[12.5px] text-ink-soft leading-relaxed mb-4">{lookupError}</p>
              <a href="/platform/login" className="text-[12.5px] text-teal hover:text-teal-deep transition-colors">
                Go to sign in →
              </a>
            </>
          ) : !invite ? null : (
            <>
              <div className="text-[15px] font-medium text-ink mb-1.5">Join Meridian&apos;s internal team</div>
              <p className="text-[12.5px] text-ink-soft leading-relaxed mb-5">
                {invite.invited_by_email} invited <strong className="text-ink font-medium">{invite.email}</strong>{" "}
                to join as{" "}<span className="capitalize">{invite.role}</span>. Set a password to accept.
              </p>
              <form onSubmit={handleSubmit} className="flex flex-col gap-3">
                <label className="flex flex-col gap-1">
                  <span className="text-[12px] text-ink-soft">Password</span>
                  <input
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    required
                    minLength={8}
                    className="text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
                  />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-[12px] text-ink-soft">Confirm password</span>
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
                {submitError && <div className="text-[12.5px] text-red">{submitError}</div>}
                <button
                  type="submit"
                  disabled={submitting}
                  className="mt-1 text-[13px] py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
                >
                  {submitting ? "Joining…" : "Accept and join"}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export default function PlatformAcceptInvitePage() {
  return (
    <Suspense fallback={null}>
      <PlatformAcceptInvitePageInner />
    </Suspense>
  );
}
