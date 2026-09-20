"use client";

import { useEffect } from "react";
import { useRouter, usePathname } from "next/navigation";
import { useSession, useHydrated } from "@/lib/useSession";
import InactivityWatcher from "@/components/InactivityWatcher";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const hydrated = useHydrated();
  const session = useSession();

  // /platform/* is a completely separate app surface with its own
  // session/auth (app/platform/layout.tsx, lib/platformAuth.ts) - the
  // tenant-scoped session this gate checks has nothing to do with staff
  // access, and gating it here would just bounce staff to the customer
  // login screen before platform's own auth ever runs.
  const isPlatformRoute = pathname.startsWith("/platform");
  // /status is the public status page - unauthenticated by design,
  // mirroring the backend's own GET /status (app/api/routes_status.py).
  // /auth/handoff is the cross-subdomain session handoff landing page
  // (see lib/api.ts's redeemHandoff) - visited with NO session at all by
  // design, since establishing one is the whole point of being there;
  // gating it here would bounce the visitor to /login before the handoff
  // token in the URL fragment ever gets a chance to be redeemed.
  // /accept-invite is the team-invite acceptance page (see lib/api.ts's
  // acceptTeamInvite) - same reasoning, visited by someone with no
  // account yet at all. /mfa-recovery is the lost-authenticator recovery
  // page (see lib/api.ts's redeemMfaRecovery) - visited by someone who,
  // by definition, can't complete login yet either. /reset-password is
  // the same shape again, reached from an admin-emailed link (see
  // lib/api.ts's redeemPasswordReset) - no session exists yet, setting
  // one is the whole point of being there. /privacy and /terms are the
  // legal pages - public by nature, linked from the marketing footer for
  // a visitor who has no account at all.
  // /interest is the "Inquire now" page an ad points at. It is the most
  // important public route there is after "/" and it was missing here:
  // every visitor arriving from an ad has no session by definition, so
  // this gate bounced them to a login screen for a product they had
  // never heard of, and the enquiry form was never shown. Verified
  // against production before the fix - the live ad URL redirected to
  // /login. Anything added under app/ that a stranger is meant to reach
  // has to be listed here too.
  const isPublicRoute =
    pathname === "/status" || pathname === "/auth/handoff" ||
    pathname === "/accept-invite" || pathname === "/mfa-recovery" ||
    pathname === "/reset-password" ||
    pathname === "/privacy" || pathname === "/terms" ||
    pathname === "/interest";
  const skipGate = isPlatformRoute || isPublicRoute;

  // "/" is the one route this gate does NOT force-redirect when logged
  // out — a stranger visiting it should see the public marketing landing
  // page, not get bounced straight to /login before ever seeing what the
  // product is. app/page.tsx itself decides what to render (LandingPage
  // vs. the real Ask dashboard) based on session presence; this gate's
  // only job here is to not redirect. A LOGGED-IN user at "/" is treated
  // exactly like every other protected route below (InactivityWatcher
  // included) — only the logged-OUT case at "/" is special.
  const isRoot = pathname === "/";

  useEffect(() => {
    if (skipGate || !hydrated) return;
    if (!session && pathname !== "/login" && !isRoot) router.replace("/login");
  }, [pathname, router, skipGate, isRoot, hydrated, session]);

  if (pathname === "/login" || skipGate) return <>{children}</>;
  if (!hydrated) return null; // avoid a flash before the client reads the session
  if (!session) return isRoot ? <>{children}</> : null; // "/" renders (the landing page); everything else waits on its redirect

  return (
    <>
      {children}
      <InactivityWatcher />
    </>
  );
}
