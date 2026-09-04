"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { loadSession, type Session } from "@/lib/auth";
import { getTenantSubdomain } from "@/lib/subdomain";
import LandingPage from "@/components/LandingPage";
import AskDashboard from "@/components/AskDashboard";
import OnboardingIntro from "@/components/OnboardingIntro";

// "/" is the one route that means two different things depending on who's
// looking: a logged-out visitor gets the public marketing landing page
// (see AuthGate.tsx — this is the only route it lets through without a
// session), and a signed-in user gets the real Ask dashboard, exactly as
// before. Deciding which to render happens HERE, not in AuthGate, so
// AuthGate's job stays purely "gate or don't."
//
// One more branch on top of that: a logged-out visitor on a TENANT
// subdomain (wamco.getmeridiananalytics.com) has already told the app
// which company they want — showing them the generic marketing page
// there would be a non-sequitur ("why is WAMCO showing me an ad for
// itself"). They get sent straight to that subdomain's own branded
// /login instead; the marketing page stays exclusive to the generic
// apex/www domain, where a stranger who doesn't know what this product
// is yet actually lands.
export default function RootPage() {
  const router = useRouter();
  const [session, setSession] = useState<Session | null | undefined>(undefined);

  useEffect(() => {
    setSession(loadSession());
  }, []);

  useEffect(() => {
    if (session === undefined || session) return; // only redirect once we know there's no session
    if (getTenantSubdomain()) router.replace("/login");
  }, [session, router]);

  if (session === undefined) return null; // avoid a flash of the wrong page before this resolves
  if (!session) return getTenantSubdomain() ? null : <LandingPage />;

  return (
    <>
      <AskDashboard />
      <OnboardingIntro />
    </>
  );
}
