"use client";

import { usePathname, useRouter } from "next/navigation";
import { clearSession } from "@/lib/auth";
import { useSession } from "@/lib/useSession";
import { useAccountType } from "@/lib/useAccountType";
import GlideNav from "@/components/glide/GlideNav";

const NAV = [
  { href: "/home", label: "Overview" },
  { href: "/overview", label: "Executive Overview", businessOnly: true },
  { href: "/financial", label: "Financial Analytics", businessOnly: true },
  { href: "/performance", label: "Sales & Performance", businessOnly: true },
  { href: "/", label: "Ask" },
  { href: "/risks", label: "Risks" },
  { href: "/analyses", label: "Analyses" },
  { href: "/schedules", label: "Scheduled analyses" },
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
    <aside className="workspace-sidebar w-full md:w-[220px] shrink-0 px-4 py-4 md:py-6 flex flex-col gap-4 md:gap-6">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2.5"><span className="brand-mark">M</span><div><div className="text-[16px] font-semibold tracking-tight">Meridian</div><div className="text-[10px] opacity-65 mt-0.5">Analytics</div></div></div>
        </div>
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
          Read-only source access. Your data stays under your control.
        </div>
      </div>
    </aside>
  );
}
