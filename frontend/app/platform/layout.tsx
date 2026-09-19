"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { clearPlatformSession } from "@/lib/platformAuth";
import { usePlatformSession, useHydrated } from "@/lib/useSession";
import GlideNav from "@/components/glide/GlideNav";

// `restricted: true` marks the areas a limited role (currently "sales")
// may open. It mirrors RESTRICTED_ROLE_ALLOWED_PREFIXES in
// app/security/platform_auth.py, which is what actually enforces this -
// hiding a tab is a courtesy, not a control.
const NAV = [
  { href: "/platform", label: "Dashboard" },
  { href: "/platform/analytics", label: "Analytics" },
  { href: "/platform/tenants", label: "Tenants" },
  { href: "/platform/leads", label: "Leads", restricted: true },
  { href: "/platform/tickets", label: "Tickets", restricted: true },
  { href: "/platform/status", label: "Status" },
  { href: "/platform/staff", label: "Staff", ownerOnly: true },
  { href: "/platform/audit", label: "Activity" },
  { href: "/platform/profile", label: "My profile", restricted: true },
];

const FULL_ACCESS_ROLES = ["owner", "support"];

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
    <div className="flex min-h-screen">
      <aside className="w-56 shrink-0 border-r border-line bg-panel px-5 py-6 flex flex-col gap-8">
        <div>
          <div className="text-[15px] font-semibold tracking-tight text-ink">Meridian</div>
          <div className="text-[11px] text-ink-soft mt-0.5">Internal admin</div>
        </div>

        <GlideNav items={navItems} activeHref={activeHref} />

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
