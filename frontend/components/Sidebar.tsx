"use client";

import { usePathname, useRouter } from "next/navigation";
import { clearSession } from "@/lib/auth";
import { useSession } from "@/lib/useSession";
import { useAccountType } from "@/lib/useAccountType";
import NotificationBell from "@/components/NotificationBell";
import GlideNav from "@/components/glide/GlideNav";

const NAV = [
  { href: "/home", label: "Home" },
  { href: "/overview", label: "Executive Overview", businessOnly: true },
  { href: "/", label: "Ask" },
  { href: "/risks", label: "Risks" },
  { href: "/analyses", label: "Analyses" },
  { href: "/library", label: "Library" },
  { href: "/documents", label: "Documents" },
  { href: "/connections", label: "Data sources" },
  // Individuals have no team to manage - every individual plan is one
  // seat and the backend refuses an invite from one outright, so the page
  // would be a dead end rather than an upsell.
  { href: "/team", label: "Team", adminOnly: true, businessOnly: true },
  { href: "/billing", label: "Billing" },
  { href: "/account", label: "Account" },
  { href: "/security", label: "Security" },
  { href: "/support", label: "Support" },
  { href: "/audit", label: "Audit log" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const session = useSession();
  const accountType = useAccountType();

  // /platform/* has its own nav (app/platform/layout.tsx); /status is the
  // public status page (no session at all) - this sidebar is tenant-scoped
  // and has no business appearing on either. "/" is special: logged-in
  // it's the Ask dashboard (sidebar shows, as always); logged-out it's
  // the public marketing landing page (app/page.tsx), which has its own
  // nav/footer and must not show the internal app chrome at all.
  if (
    pathname === "/login" ||
    pathname === "/status" ||
    pathname === "/interest" ||
    pathname === "/auth/handoff" ||
    pathname === "/accept-invite" ||
    pathname === "/mfa-recovery" ||
    pathname === "/reset-password" ||
    pathname === "/privacy" ||
    pathname === "/terms" ||
    pathname.startsWith("/platform") ||
    (pathname === "/" && !session)
  ) {
    return null;
  }

  function handleLogout() {
    clearSession();
    router.push("/login");
  }

  // accountType is null until /auth/me answers (and stays null if it
  // never does), which deliberately reads as "show it": hiding a page
  // from a business on a network blip is worse than one extra nav item.
  const navItems = NAV.filter(
    (item) =>
      (!item.adminOnly || session?.role === "admin") &&
      (!item.businessOnly || accountType === "business"),
  );
  const activeHref =
    navItems.find((item) => (item.href === "/" ? pathname === "/" : pathname.startsWith(item.href)))?.href ?? null;

  return (
    <aside className="w-full md:w-56 shrink-0 border-b md:border-b-0 md:border-r border-line bg-panel px-5 py-4 md:py-6 flex flex-col gap-4 md:gap-8">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[15px] font-semibold tracking-tight text-ink">Meridian</div>
          <div className="text-[11px] text-ink-soft mt-0.5">Enterprise analytics</div>
        </div>
        {session && <NotificationBell />}
      </div>

      <details className="md:hidden">
        <summary className="cursor-pointer text-sm text-teal">Browse workspace</summary>
        <div className="mt-3"><GlideNav items={navItems} activeHref={activeHref} /></div>
        {session && <button onClick={handleLogout} className="text-sm text-teal mt-3">Sign out</button>}
      </details>
      <div className="hidden md:block"><GlideNav items={navItems} activeHref={activeHref} /></div>

      <div className="mt-auto hidden md:flex flex-col gap-3">
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
