"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { staffLogin, bootstrapOwner } from "@/lib/platformApi";
import { savePlatformSession } from "@/lib/platformAuth";

export default function PlatformLoginPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"login" | "bootstrap">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const auth = mode === "login" ? await staffLogin(email, password) : await bootstrapOwner(email, password);
      savePlatformSession({ token: auth.access_token, staffId: auth.staff_id, role: auth.role, email });
      router.push("/platform");
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
          <div className="text-[12px] text-ink-soft mt-0.5">Internal admin</div>
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
              onClick={() => setMode("bootstrap")}
              className={`flex-1 py-1.5 rounded-[3px] transition-colors ${
                mode === "bootstrap" ? "bg-teal-deep text-white" : "text-ink-soft hover:text-ink"
              }`}
            >
              First-time setup
            </button>
          </div>

          <form onSubmit={handleSubmit} className="flex flex-col gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-[12px] text-ink-soft">Email</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@yourcompany.com"
                required
                className="text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[12px] text-ink-soft">Password</span>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                required
                minLength={mode === "bootstrap" ? 8 : undefined}
                className="text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
              />
            </label>

            {error && <div className="text-[12.5px] text-red">{error}</div>}

            <button
              type="submit"
              disabled={submitting}
              className="mt-1 text-[13px] py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
            >
              {submitting ? "Please wait…" : mode === "login" ? "Sign in" : "Create the first admin account"}
            </button>
          </form>
        </div>

        {mode === "bootstrap" && (
          <p className="text-[11.5px] text-ink-soft text-center mt-4 leading-relaxed">
            Only works once — this creates the very first internal admin ("owner") account. If one
            already exists, this will fail; ask an existing owner to add you from Staff instead.
          </p>
        )}
      </div>
    </div>
  );
}
