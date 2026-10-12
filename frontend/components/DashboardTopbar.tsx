"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSession, usePlatformSession } from "@/lib/useSession";
import NotificationBell from "@/components/NotificationBell";
import AskLauncher from "@/components/AskLauncher";
import DashboardIcon from "@/components/DashboardIcon";

export default function DashboardTopbar({ platform = false }: { platform?: boolean }) {
  const pathname = usePathname();
  const customer = useSession();
  const staff = usePlatformSession();
  const session = platform ? staff : customer;
  if (!session) return null;
  const initial = (session.email.split("@")[0] || "M").slice(0, 2).toUpperCase();
  return <header className="workspace-topbar flex items-center justify-between gap-3 px-4 sm:px-7 py-3.5 border-b border-line bg-panel">
    {!platform || staff?.role === "owner" ? <AskLauncher platform={platform} compact /> : <p className="text-sm font-medium text-teal">Platform operations</p>}
    <div className="flex items-center gap-3 sm:gap-5 shrink-0"><span className="hidden lg:flex items-center gap-2 rounded-md border border-line px-3 py-2 text-[11px] text-ink-soft"><DashboardIcon name="clock" size={14} />{new Date().toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}</span>{!platform && <NotificationBell />}<Link href={platform ? "/platform/profile" : "/account"} className="flex items-center gap-2.5"><span className="flex items-center justify-center w-8 h-8 rounded-full bg-teal-deep text-white text-[10px] font-semibold">{initial}</span><span className="hidden xl:block text-xs max-w-32 truncate text-ink">{session.email.split("@")[0]}</span><span className="sr-only">Open account profile from {pathname}</span></Link></div>
  </header>;
}
