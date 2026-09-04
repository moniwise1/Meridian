"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  login, register, verifyMfaLogin, setupMfaLogin, confirmMfaLogin,
  startMfaSetup, confirmMfaSetup, type AuthResponse,
} from "@/lib/api";
import { saveSession } from "@/lib/auth";
import MfaEnroll from "@/components/MfaEnroll";

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

  function finishLogin(auth: AuthResponse) {
    saveSession({
      token: auth.access_token,
      tenantId: auth.tenant_id,
      userId: auth.user_id,
      role: auth.role,
      email,
    });
    router.push("/");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      if (mode === "register") {
        const auth = await register(companyName, email, password);
        saveSession({
          token: auth.access_token, tenantId: auth.tenant_id, userId: auth.user_id,
          role: auth.role, email,
        });
        // Mandatory: the new admin sets up their own authenticator before
        // reaching the dashboard for the first time — no skip.
        setStep("mfa_setup_mandatory");
        return;
      }

      const result = await login(email, password);
      if (!result.mfa_required) {
        finishLogin(result as AuthResponse);
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
      finishLogin(auth);
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
              }}
              className="text-[12px] text-ink-soft hover:text-ink transition-colors"
            >
              ← Back
            </button>
          </form>
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
            finishLogin(auth);
          }}
        />
      </Shell>
    );
  }

  if (step === "mfa_setup_mandatory") {
    return (
      <Shell>
        <MfaEnroll
          title="Secure your new account"
          description="Set up two-factor authentication before continuing — scan this QR code with an authenticator app, then enter the code it shows."
          onStart={startMfaSetup}
          onConfirm={async (code) => {
            await confirmMfaSetup(code);
            router.push("/");
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
        <div className="flex gap-1 mb-5 text-[13px]">
          <button
            type="button"
            onClick={() => setMode("login")}
            className={`flex-1 py-1.5 rounded-[3px] transition-colors ${
              mode === "login" ? "bg-teal-deep text-white" : "text-ink-soft hover:text-ink"
            }`}
          >
            Sign in
          </button>
          <button
            type="button"
            onClick={() => setMode("register")}
            className={`flex-1 py-1.5 rounded-[3px] transition-colors ${
              mode === "register" ? "bg-teal-deep text-white" : "text-ink-soft hover:text-ink"
            }`}
          >
            Create account
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          {mode === "register" && (
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
            {submitting ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>
      </div>

      {mode === "register" && (
        <p className="text-[11.5px] text-ink-soft text-center mt-4 leading-relaxed">
          Creating an account makes you the admin for a new company workspace. You&apos;ll set up
          two-factor authentication right after.
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
