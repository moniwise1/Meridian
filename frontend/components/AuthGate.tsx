"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { loadSession, type Session } from "@/lib/auth";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [session, setSession] = useState<Session | null | undefined>(undefined);

  // /platform/* is a completely separate app surface with its own
  // session/auth (app/platform/layout.tsx, lib/platformAuth.ts) - the
  // tenant-scoped session this gate checks has nothing to do with staff
  // access, and gating it here would just bounce staff to the customer
  // login screen before platform's own auth ever runs.
  const isPlatformRoute = pathname.startsWith("/platform");

  useEffect(() => {
    if (isPlatformRoute) return;
    const s = loadSession();
    setSession(s);
    if (!s && pathname !== "/login") router.replace("/login");
  }, [pathname, router, isPlatformRoute]);

  if (pathname === "/login" || isPlatformRoute) return <>{children}</>;
  if (session === undefined) return null; // avoid a flash before session check resolves
  if (!session) return null; // redirecting

  return <>{children}</>;
}
