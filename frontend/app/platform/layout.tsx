"use client";

import { useEffect } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { clearPlatformSession } from "@/lib/platformAuth";
import { usePlatformSession, useHydrated } from "@/lib/useSession";
import DashboardTopbar from "@/components/DashboardTopbar";
import GlideNav from "@/components/glide/GlideNav";

// `restricted: true` marks the areas a limited role (currently "sales")
// may open. It mirrors RESTRICTED_ROLE_ALLOWED_PREFIXES in
// app/security/platform_auth.py, which is what actually enforces this -
// hiding a tab is a courtesy, not a control.
const NAV = [
  { href: "/platform", label: "Dashboard" },
  { href: "/platform/analytics", label: "Analytics" },
  { href: "/platform/ask", label: "Ask Meridian", ownerOnly: true },
  { href: "/platform/tenants", label: "Tenants" },
  { href: "/platform/leads", label: "Leads", restricted: true },
  { href: "/platform/tickets", label: "Tickets", restricted: true },
  { href: "/platform/status", label: "Status" },
  { href: "/platform/staff", label: "Staff", ownerOnly: true },
  { href: "/platform/audit", label: "Activity" },
  { href: "/platform/profile", label: "My profile", restricted: true },
];

const FULL_ACCESS_ROLES = ["owner", "support"];

// Mirrors RESTRICTED_ROLE_ALLOWED_PREFIXES in
// app/security/platform_auth.py, in page terms rather than API terms
// (/platform/profile is the page; /platform/me is the endpoint behind it).
// The server is what enforces this; showing "Not authorized" here just
// means a restricted account gets a plain answer instead of a page that
// loads and then fails to fetch anything.
const RESTRICTED_ALLOWED_PAGES = ["/platform/leads", "/platform/tickets", "/platform/profile"];

function allowedForRole(pathname: string, role: string): boolean {
  if (FULL_ACCESS_ROLES.includes(role)) return true;
  return RESTRICTED_ALLOWED_PAGES.some((prefix) => pathname.startsWith(prefix));
}

export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const hydrated = useHydrated();
  const session = usePlatformSession();

  // /platform/accept-invite is the staff-invite acceptance page (see
  // lib/platformApi.ts's acceptStaffInvite) - visited by someone with no
  // platform session at all, same reasoning as /platform/login itself.
  const isPublicRoute = pathname === "/platform/login" || pathname === "/platform/accept-invite";

  useEffect(() => {
    if (isPublicRoute || !hydrated) return;
    if (!session) router.replace("/platform/login");
  }, [pathname, router, isPublicRoute, hydrated, session]);

  if (isPublicRoute) return <>{children}</>;
  if (!hydrated || !session) return null; // avoid a flash / mid-redirect

  function handleLogout() {
    clearPlatformSession();
    router.push("/platform/login");
  }

  const fullAccess = FULL_ACCESS_ROLES.includes(session.role);
  const navItems = NAV.filter(
    (item) => (fullAccess || item.restricted) && (!item.ownerOnly || session.role === "owner"),
  );
  const activeHref =
    navItems.find((item) =>
      item.href === "/platform" ? pathname === "/platform" : pathname.startsWith(item.href),
    )?.href ?? null;

  return (
    <div data-dashboard="true" className="workspace-shell flex flex-col md:flex-row min-h-screen">
      <aside className="workspace-sidebar w-full md:w-[220px] shrink-0 px-4 py-4 md:py-6 flex flex-col gap-4 md:gap-6">
        <div>
          <div className="flex items-center gap-2.5"><span className="brand-mark">M</span><div><div className="text-[16px] font-semibold tracking-tight">Meridian</div><div className="text-[10px] opacity-65 mt-0.5">Owner workspace</div></div></div>
        </div>

        <details className="md:hidden">
          <summary className="cursor-pointer text-sm text-teal">Browse owner workspace</summary>
          <div className="mt-3"><GlideNav items={navItems} activeHref={activeHref} /></div>
          <button onClick={handleLogout} className="text-sm text-teal mt-3">Sign out</button>
        </details>
        <div className="hidden md:block"><GlideNav items={navItems} activeHref={activeHref} /></div>

        <div className="mt-auto hidden md:flex flex-col gap-3">
          <div className="text-[12px] border-t border-line pt-3">
            <div className="text-ink truncate">{session.email}</div>
            <div className="text-ink-soft mt-0.5 flex items-center justify-between">
              <span className="capitalize">{session.role.replace("_", " ")}</span>
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
      <main className="flex-1 min-w-0"><DashboardTopbar platform />
        {allowedForRole(pathname, session.role) ? (
          children
        ) : (
          <div className="max-w-xl mx-auto px-8 py-16">
            <h1 className="text-[22px] font-medium text-ink tracking-tight mb-2">Not authorized</h1>
            <p className="text-[13.5px] text-ink-soft leading-relaxed">
              Your account doesn&apos;t have access to this part of the console. You can open{" "}
              <Link href="/platform/leads" className="text-teal hover:text-teal-deep transition-colors">Leads</Link>,{" "}
              <Link href="/platform/tickets" className="text-teal hover:text-teal-deep transition-colors">Tickets</Link>{" "}
              and{" "}
              <Link href="/platform/profile" className="text-teal hover:text-teal-deep transition-colors">My profile</Link>.
              If you need more, ask an owner.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
