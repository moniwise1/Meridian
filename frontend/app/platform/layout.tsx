"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { loadPlatformSession, clearPlatformSession, type PlatformSession } from "@/lib/platformAuth";

const NAV = [
  { href: "/platform", label: "Dashboard" },
  { href: "/platform/tenants", label: "Tenants" },
  { href: "/platform/tickets", label: "Tickets" },
  { href: "/platform/status", label: "Status" },
  { href: "/platform/staff", label: "Staff", ownerOnly: true },
  { href: "/platform/audit", label: "Activity" },
];

export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<PlatformSession | null | undefined>(undefined);

  useEffect(() => {
    const s = loadPlatformSession();
    setSession(s);
    if (!s && pathname !== "/platform/login") router.replace("/platform/login");
  }, [pathname, router]);

  if (pathname === "/platform/login") return <>{children}</>;
  if (session === undefined || !session) return null; // avoid a flash / mid-redirect

  function handleLogout() {
    clearPlatformSession();
    router.push("/platform/login");
  }

  return (
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 border-r border-line bg-panel px-5 py-6 flex flex-col gap-8">
        <div>
          <div className="text-[15px] font-semibold tracking-tight text-ink">Meridian</div>
          <div className="text-[11px] text-ink-soft mt-0.5">Internal admin</div>
        </div>

        <nav className="flex flex-col gap-1">
          {NAV.filter((item) => !item.ownerOnly || session.role === "owner").map((item) => {
            const active = item.href === "/platform" ? pathname === "/platform" : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`text-[13.5px] px-2.5 py-1.5 rounded-[3px] transition-colors ${
                  active ? "bg-teal-deep text-white" : "text-ink-soft hover:text-ink hover:bg-paper"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="mt-auto flex flex-col gap-3">
          <div className="text-[12px] border-t border-line pt-3">
            <div className="text-ink truncate">{session.email}</div>
            <div className="text-ink-soft mt-0.5 flex items-center justify-between">
              <span className="capitalize">{session.role}</span>
              <button onClick={handleLogout} className="text-teal hover:text-teal-deep transition-colors">
                Sign out
              </button>
            </div>
          </div>
          <div className="text-[11px] text-ink-soft leading-relaxed border-t border-line pt-3">
            Internal only — separate login from customer accounts.
          </div>
        </div>
      </aside>
      <main className="flex-1 min-w-0">{children}</main>
    </div>
  );
}
