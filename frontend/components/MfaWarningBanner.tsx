"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { loadSession } from "@/lib/auth";
import { getMfaStatus } from "@/lib/api";

// A slim, persistent warning across the top of the authenticated app
// (not a dismissible toast — it should keep reappearing every session
// until the user actually enables MFA, not just be closed once and
// forgotten). Self-guards on pathname/session exactly like Sidebar does,
// since it's mounted unconditionally in the root layout alongside it.
export default function MfaWarningBanner() {
  const pathname = usePathname();
  const [enabled, setEnabled] = useState<boolean | null>(null);

  const isPlatformRoute = pathname.startsWith("/platform");
  const isPublicRoute = pathname === "/status" || pathname === "/login";
  const session = loadSession();
  const skip = isPlatformRoute || isPublicRoute || !session;

  useEffect(() => {
    if (skip) return;
    getMfaStatus()
      .then((s) => setEnabled(s.enabled))
      .catch(() => {
        /* Not fatal — the banner just doesn't show if the check fails
           (e.g. a session that's about to be redirected to /login anyway
           by handleAuthFailure elsewhere on the page). */
      });
    // Re-check on route change — covers the case where the user just
    // enabled MFA on /security and navigated away, without needing a
    // full page reload for the banner to disappear.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, skip]);

  if (skip || enabled !== false || pathname === "/security") return null;

  return (
    <div className="bg-amber-soft text-amber text-[12.5px] px-4 py-2 flex items-center justify-center gap-2 border-b border-line">
      <span>Two-factor authentication isn&apos;t enabled on your account.</span>
      <Link href="/security" className="underline hover:no-underline font-medium">
        Enable it now →
      </Link>
    </div>
  );
}
