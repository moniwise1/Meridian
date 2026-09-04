"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { redeemHandoff } from "@/lib/api";
import { saveSession } from "@/lib/auth";

// Lands here immediately after a successful login/registration on the
// generic domain, when that account belongs to a tenant with its own
// subdomain — see lib/api.ts's createHandoff/redeemHandoff and
// backend/app/api/routes_auth.py's /auth/handoff/* pair for why this
// can't just be a redirect carrying the real session directly. The token
// lives in the URL FRAGMENT (never sent to any server) specifically so
// it's exchanged for a real session here and then immediately scrubbed
// from the address bar — never lingers in server logs, and only
// visible in this browser's own history for as long as the user keeps it.
export default function HandoffPage() {
  const router = useRouter();
  const [error, setError] = useState("");

  useEffect(() => {
    const hash = window.location.hash; // "#token=..."
    const token = new URLSearchParams(hash.replace(/^#/, "")).get("token");
    if (!token) {
      setError("Missing handoff token.");
      return;
    }
    redeemHandoff(token)
      .then((auth) => {
        saveSession({
          token: auth.access_token, tenantId: auth.tenant_id, userId: auth.user_id,
          role: auth.role, email: auth.email ?? "",
        });
        // Clears the token from the address bar/history before landing on
        // the dashboard — router.replace (not push) so this page never
        // sits in back-navigation history either.
        router.replace("/");
      })
      .catch((e) => setError((e as Error).message));
  }, [router]);

  if (error) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-paper px-6">
        <div className="w-full max-w-sm text-center">
          <div className="text-[16px] font-semibold tracking-tight text-ink mb-1">Meridian</div>
          <div className="bg-panel border border-line rounded-[4px] p-6 mt-6">
            <div className="text-[13.5px] text-red mb-3">{error}</div>
            <a href="/login" className="text-[12.5px] text-teal hover:text-teal-deep transition-colors">
              Back to sign in
            </a>
          </div>
        </div>
      </div>
    );
  }

  return null;
}
