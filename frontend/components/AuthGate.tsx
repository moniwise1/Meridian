"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { loadSession, type Session } from "@/lib/auth";

export default function AuthGate({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [session, setSession] = useState<Session | null | undefined>(undefined);

  useEffect(() => {
    const s = loadSession();
    setSession(s);
    if (!s && pathname !== "/login") router.replace("/login");
  }, [pathname, router]);

  if (pathname === "/login") return <>{children}</>;
  if (session === undefined) return null; // avoid a flash before session check resolves
  if (!session) return null; // redirecting

  return <>{children}</>;
}
