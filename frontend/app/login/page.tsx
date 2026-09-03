"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login, register } from "@/lib/api";
import { saveSession } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [companyName, setCompanyName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const auth = mode === "login" ? await login(email, password) : await register(companyName, email, password);
      saveSession({
        token: auth.access_token,
        tenantId: auth.tenant_id,
        userId: auth.user_id,
        role: auth.role,
        email,
      });
      router.push("/");
    } catch (e) {
      setError((e as Error).message);
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
            Creating an account makes you the admin for a new company workspace.
          </p>
        )}
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
