"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { loadSession, clearSession, type Session } from "@/lib/auth";

const NAV = [
  { href: "/home", label: "Home" },
  { href: "/", label: "Ask" },
  { href: "/risks", label: "Risks" },
  { href: "/analyses", label: "Analyses" },
  { href: "/library", label: "Library" },
  { href: "/documents", label: "Documents" },
  { href: "/connections", label: "Data sources" },
  { href: "/team", label: "Team", adminOnly: true },
  { href: "/billing", label: "Billing" },
  { href: "/audit", label: "Audit log" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    setSession(loadSession());
  }, [pathname]);

  if (pathname === "/login") return null;

  function handleLogout() {
    clearSession();
    router.push("/login");
  }

  return (
    <aside className="w-56 shrink-0 border-r border-line bg-panel px-5 py-6 flex flex-col gap-8">
      <div>
        <div className="text-[15px] font-semibold tracking-tight text-ink">Meridian</div>
        <div className="text-[11px] text-ink-soft mt-0.5">Enterprise analytics</div>
      </div>

      <nav className="flex flex-col gap-1">
        {NAV.filter((item) => !item.adminOnly || session?.role === "admin").map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
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
        {session && (
          <div className="text-[12px] border-t border-line pt-3">
            <div className="text-ink truncate">{session.email}</div>
            <div className="text-ink-soft mt-0.5 flex items-center justify-between">
              <span className="capitalize">{session.role}</span>
              <button onClick={handleLogout} className="text-teal hover:text-teal-deep transition-colors">
                Sign out
              </button>
            </div>
          </div>
        )}
        <div className="text-[11px] text-ink-soft leading-relaxed border-t border-line pt-3">
          Read-only by design. The agent can query and explain — it cannot write, alter, or delete.
        </div>
      </div>
    </aside>
  );
}
