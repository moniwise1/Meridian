"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  login, register, verifyMfaLogin, setupMfaLogin, confirmMfaLogin, requestMfaRecovery,
  startMfaSetup, confirmMfaSetup, getTenantBySubdomain, createHandoff, type AuthResponse, type TenantBySubdomain,
} from "@/lib/api";
import { saveSession, loadSession } from "@/lib/auth";
import { getTenantSubdomain } from "@/lib/subdomain";
import MfaEnroll from "@/components/MfaEnroll";

const APEX_DOMAIN = process.env.NEXT_PUBLIC_APEX_DOMAIN ?? "getmeridiananalytics.com";

// "none" = the generic domain (no tenant subdomain in the URL at all) -
// login stays fully unrestricted, register stays available, exactly as
// before this feature existed. "not_found" = ON a tenant-shaped subdomain
// but no tenant actually owns it (typo, or one that was never assigned).
// Resolved via a real lookup (getTenantBySubdomain) rather than trusting
// the URL alone, since the subdomain string itself proves nothing.
type TenantContext = TenantBySubdomain | "none" | "not_found" | undefined;

// A plain step (credentials in, session out) covers every tenant that has
// never touched MFA — unchanged from before. Once MFA is involved, login
// becomes a small state machine:
//   credentials -> mfa_code            (already enrolled: enter a code)
//   credentials -> mfa_setup_login     (org requires it, never enrolled: scan+confirm)
// Registration is separate: it always grants a real session immediately
// (unchanged backend behavior), then this page forces the new admin
// through mfa_setup_mandatory before routing to "/" — no skip button,
// see MfaEnroll's own docstring for why every place it's used is mandatory.
type Step = "credentials" | "mfa_code" | "mfa_setup_login" | "mfa_setup_mandatory";

function LoginPageInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const inactivityReason = searchParams.get("reason") === "inactivity";
  // The public landing page's "Get started" CTA deep-links here with
  // ?mode=register so a visitor lands directly on the account-creation
  // form instead of sign-in — everything past this point (register(),
  // the mandatory MFA setup step, etc.) is completely unchanged.
  const [mode, setMode] = useState<"login" | "register">(
    searchParams.get("mode") === "register" ? "register" : "login",
  );
  const [step, setStep] = useState<Step>("credentials");
  const [companyName, setCompanyName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [preAuthToken, setPreAuthToken] = useState("");
  const [mfaCode, setMfaCode] = useState("");
  const [assignedSubdomain, setAssignedSubdomain] = useState("");
  const [recoverySending, setRecoverySending] = useState(false);
  const [recoverySentTo, setRecoverySentTo] = useState("");
  const [recoveryError, setRecoveryError] = useState("");

  // undefined until resolved client-side (window isn't available during
  // SSR) - rendered as a blank Shell until then, same "avoid a flash of
  // the wrong screen" pattern AuthGate already uses elsewhere.
  const [tenantContext, setTenantContext] = useState<TenantContext>(undefined);
  useEffect(() => {
    const sub = getTenantSubdomain();
    if (!sub) {
      setTenantContext("none");
      return;
    }
    getTenantBySubdomain(sub)
      .then(setTenantContext)
      .catch(() => setTenantContext("not_found"));
  }, []);
  const tenant = tenantContext && tenantContext !== "none" && tenantContext !== "not_found" ? tenantContext : null;

  // Every tenant subdomain is its own independent store in the mall - this
  // is what makes the address bar actually SHOW that after a login on the
  // generic domain (the mall entrance), rather than leaving the visitor on
  // www forever. saveSession() above already grants a real, working
  // session on the generic domain, so if the handoff can't be minted for
  // any reason (network blip, the account has no subdomain yet, etc.) the
  // user still lands on a working dashboard - just not the branded one -
  // instead of getting stuck. See routes_auth.py's /auth/handoff/* pair
  // and app/auth/handoff/page.tsx for the redemption side of this.
  async function redirectToOwnSubdomain(subdomain: string | null | undefined, accessToken: string) {
    // Already ON that tenant's own subdomain (logged in directly at
    // wamco.getmeridiananalytics.com rather than via the generic domain) -
    // the session just saved is already on the right origin, no handoff
    // needed at all.
    if (!subdomain || tenant?.subdomain === subdomain) {
      router.push("/");
      return;
    }
    try {
      const handoffToken = await createHandoff(accessToken);
      window.location.href = `https://${subdomain}.${APEX_DOMAIN}/auth/handoff#token=${handoffToken}`;
    } catch {
      router.push("/");
    }
  }

  async function finishLogin(auth: AuthResponse) {
    saveSession({
      token: auth.access_token,
      tenantId: auth.tenant_id,
      userId: auth.user_id,
      role: auth.role,
      email,
    });
    await redirectToOwnSubdomain(auth.subdomain, auth.access_token);
  }

  // Registration always creates a brand-new tenant with its OWN
  // auto-generated subdomain (see routes_auth.py's register()) - doing
  // that from inside an EXISTING company's subdomain would be
  // nonsensical (which company are you even registering?), so it's only
  // ever offered on the generic domain; effectiveMode forces "login"
  // whenever a real tenant subdomain is resolved, regardless of the
  // ?mode= query param or anything the user clicked before this resolved.
  const effectiveMode = tenant ? "login" : mode;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      if (effectiveMode === "register") {
        const auth = await register(companyName, email, password);
        saveSession({
          token: auth.access_token, tenantId: auth.tenant_id, userId: auth.user_id,
          role: auth.role, email,
        });
        if (auth.subdomain) setAssignedSubdomain(auth.subdomain);
        // Mandatory: the new admin sets up their own authenticator before
        // reaching the dashboard for the first time — no skip.
        setStep("mfa_setup_mandatory");
        return;
      }

      const result = await login(email, password, tenant?.subdomain);
      if (!result.mfa_required) {
        await finishLogin(result as AuthResponse);
        return;
      }
      setPreAuthToken(result.pre_auth_token!);
      setStep(result.mfa_setup_required ? "mfa_setup_login" : "mfa_code");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  async function handleMfaCode(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const auth = await verifyMfaLogin(preAuthToken, mfaCode);
      await finishLogin(auth);
    } catch (e) {
      setError((e as Error).message);
      setMfaCode("");
    } finally {
      setSubmitting(false);
    }
  }

  if (step === "mfa_code") {
    return (
      <Shell>
        <div className="bg-panel border border-line rounded-[4px] p-6">
          <div className="text-[15px] font-medium text-ink mb-1.5">Enter your authenticator code</div>
          <p className="text-[12.5px] text-ink-soft leading-relaxed mb-5">
            Your organization requires a code from your authenticator app to finish signing in.
          </p>
          <form onSubmit={handleMfaCode} className="flex flex-col gap-3">
            <input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              value={mfaCode}
              onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
              placeholder="000000"
              required
              minLength={6}
              maxLength={6}
              className="text-[16px] tracking-[0.3em] text-center font-[family-name:var(--font-mono)] border border-line rounded-[3px] px-2.5 py-2 bg-panel text-ink placeholder:text-ink-soft/40 focus:outline-none focus:ring-1 focus:ring-teal"
            />
            {error && <div className="text-[12.5px] text-red">{error}</div>}
            <button
              type="submit"
              disabled={submitting || mfaCode.length !== 6}
              className="text-[13px] py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
            >
              {submitting ? "Verifying…" : "Verify and sign in"}
            </button>
            <button
              type="button"
              onClick={() => {
                setStep("credentials");
                setError("");
                setMfaCode("");
                setRecoverySentTo("");
                setRecoveryError("");
              }}
              className="text-[12px] text-ink-soft hover:text-ink transition-colors"
            >
              ← Back
            </button>
          </form>

          <div className="mt-4 pt-4 border-t border-line">
            {recoverySentTo ? (
              <p className="text-[12px] text-ink-soft leading-relaxed">
                We sent a recovery link to <span className="text-ink">{recoverySentTo}</span> — it
                expires in 15 minutes. Following it disables your lost authenticator so you can set
                up a new one.
              </p>
            ) : (
              <button
                type="button"
                disabled={recoverySending}
                onClick={async () => {
                  setRecoveryError("");
                  setRecoverySending(true);
                  try {
                    const { masked_email } = await requestMfaRecovery(preAuthToken);
                    setRecoverySentTo(masked_email);
                  } catch (e) {
                    setRecoveryError((e as Error).message);
                  } finally {
                    setRecoverySending(false);
                  }
                }}
                className="text-[12px] text-ink-soft hover:text-ink transition-colors disabled:opacity-40"
              >
                {recoverySending ? "Sending…" : "Lost your authenticator? Send a recovery link"}
              </button>
            )}
            {recoveryError && <div className="mt-1.5 text-[12px] text-red">{recoveryError}</div>}
          </div>
        </div>
      </Shell>
    );
  }

  if (step === "mfa_setup_login") {
    return (
      <Shell>
        <MfaEnroll
          title="Set up two-factor authentication"
          description="Your organization now requires two-factor authentication. Scan this QR code with an authenticator app, then enter the code it shows to finish signing in."
          onStart={(signal) => setupMfaLogin(preAuthToken, signal)}
          onConfirm={async (code) => {
            const auth = await confirmMfaLogin(preAuthToken, code);
            await finishLogin(auth);
          }}
        />
      </Shell>
    );
  }

  // Resolving which tenant (if any) this subdomain belongs to - blank
  // rather than flashing the wrong screen first, same pattern AuthGate
  // uses elsewhere for the same reason.
  if (tenantContext === undefined) return null;

  if (tenantContext === "not_found") {
    return (
      <Shell>
        <div className="bg-panel border border-line rounded-[4px] p-6 text-center">
          <div className="text-[15px] font-medium text-ink mb-1.5">Workspace not found</div>
          <p className="text-[12.5px] text-ink-soft leading-relaxed mb-4">
            There&apos;s no organization at this address. Double-check the link, or head to the main
            site to sign in or create a new workspace.
          </p>
          <a
            href={`https://${process.env.NEXT_PUBLIC_APEX_DOMAIN ?? "getmeridiananalytics.com"}/login`}
            className="text-[12.5px] text-teal hover:text-teal-deep transition-colors"
          >
            Go to the main site →
          </a>
        </div>
      </Shell>
    );
  }

  if (step === "mfa_setup_mandatory") {
    return (
      <Shell>
        {assignedSubdomain && (
          <div className="mb-4 text-[12.5px] text-ink-soft bg-panel border border-line rounded-[3px] px-3 py-2 text-center">
            Your team&apos;s workspace is live at{" "}
            <span className="text-ink font-[family-name:var(--font-mono)]">
              {assignedSubdomain}.{process.env.NEXT_PUBLIC_APEX_DOMAIN ?? "getmeridiananalytics.com"}
            </span>{" "}
            — worth bookmarking.
          </div>
        )}
        <MfaEnroll
          title="Secure your new account"
          description="Set up two-factor authentication before continuing — scan this QR code with an authenticator app, then enter the code it shows."
          onStart={startMfaSetup}
          onConfirm={async (code) => {
            await confirmMfaSetup(code);
            // register()'s own saveSession() call in handleSubmit already
            // put a working access_token in sessionStorage - confirming
            // MFA setup doesn't rotate it, so it's still good for minting
            // the handoff token here.
            const token = loadSession()?.token;
            if (token) {
              await redirectToOwnSubdomain(assignedSubdomain, token);
            } else {
              router.push("/");
            }
          }}
        />
      </Shell>
    );
  }

  return (
    <Shell>
      {inactivityReason && (
        <div className="mb-4 text-[12.5px] text-ink-soft bg-panel border border-line rounded-[3px] px-3 py-2">
          You were signed out after a period of inactivity. Please sign in again.
        </div>
      )}
      <div className="bg-panel border border-line rounded-[4px] p-6">
        {tenant ? (
          <div className="text-[15px] font-medium text-ink text-center mb-5">Sign in to {tenant.name}</div>
        ) : (
          <div className="flex gap-1 mb-5 text-[13px]">
            <button
              type="button"
              onClick={() => setMode("login")}
              className={`flex-1 py-1.5 rounded-[3px] transition-colors ${
                effectiveMode === "login" ? "bg-teal-deep text-white" : "text-ink-soft hover:text-ink"
              }`}
            >
              Sign in
            </button>
            <button
              type="button"
              onClick={() => setMode("register")}
              className={`flex-1 py-1.5 rounded-[3px] transition-colors ${
                effectiveMode === "register" ? "bg-teal-deep text-white" : "text-ink-soft hover:text-ink"
              }`}
            >
              Create account
            </button>
          </div>
        )}

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          {effectiveMode === "register" && (
            <Field label="Company name" value={companyName} onChange={setCompanyName} placeholder="Acme Inc." />
          )}
          <Field label="Email" value={email} onChange={setEmail} placeholder="you@company.com" type="email" />
          <Field label="Password" value={password} onChange={setPassword} placeholder="••••••••" type="password" />

          {error && <div className="text-[12.5px] text-red">{error}</div>}

          <button
            type="submit"
            disabled={submitting}
            className="mt-1 text-[13px] py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
          >
            {submitting ? "Please wait…" : effectiveMode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>
      </div>

      {effectiveMode === "register" && (
        <p className="text-[11.5px] text-ink-soft text-center mt-4 leading-relaxed">
          Creating an account makes you the admin for a new company workspace. You&apos;ll set up
          two-factor authentication right after.
        </p>
      )}

      {tenant && (
        <p className="text-[11.5px] text-ink-soft text-center mt-4 leading-relaxed">
          Not part of {tenant.name}?{" "}
          <a
            href={`https://${process.env.NEXT_PUBLIC_APEX_DOMAIN ?? "getmeridiananalytics.com"}/login?mode=register`}
            className="text-teal hover:text-teal-deep transition-colors"
          >
            Create your own workspace
          </a>
          .
        </p>
      )}
    </Shell>
  );
}

export default function LoginPage() {
  // useSearchParams() (for the post-inactivity-logout message) needs a
  // Suspense boundary around anything that calls it, per Next.js's static-
  // rendering rules for the App Router.
  return (
    <Suspense fallback={null}>
      <LoginPageInner />
    </Suspense>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-paper px-6">
      <div className="w-full max-w-sm">
        <div className="text-center mb-8">
          <div className="text-[16px] font-semibold tracking-tight text-ink">Meridian</div>
          <div className="text-[12px] text-ink-soft mt-0.5">Enterprise analytics</div>
        </div>
        {children}
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[12px] text-ink-soft">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required
        minLength={type === "password" ? 8 : undefined}
        className="text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
      />
    </label>
  );
}
