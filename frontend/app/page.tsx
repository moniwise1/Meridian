"use client";

import { useEffect, useState } from "react";
import { loadSession, type Session } from "@/lib/auth";
import LandingPage from "@/components/LandingPage";
import AskDashboard from "@/components/AskDashboard";
import OnboardingIntro from "@/components/OnboardingIntro";

// "/" is the one route that means two different things depending on who's
// looking: a logged-out visitor gets the public marketing landing page
// (see AuthGate.tsx — this is the only route it lets through without a
// session), and a signed-in user gets the real Ask dashboard, exactly as
// before. Deciding which to render happens HERE, not in AuthGate, so
// AuthGate's job stays purely "gate or don't."
export default function RootPage() {
  const [session, setSession] = useState<Session | null | undefined>(undefined);

  useEffect(() => {
    setSession(loadSession());
  }, []);

  if (session === undefined) return null; // avoid a flash of the wrong page before this resolves
  if (!session) return <LandingPage />;

  return (
    <>
      <AskDashboard />
      <OnboardingIntro />
    </>
  );
}
