"use client";
import { usePathname } from "next/navigation";
import { useSession } from "@/lib/useSession";
import Sidebar from "@/components/Sidebar";
import DashboardTopbar from "@/components/DashboardTopbar";
const PUBLIC = ["/login", "/status", "/interest", "/auth/handoff", "/accept-invite", "/mfa-recovery", "/reset-password", "/privacy", "/terms"];
export default function WorkspaceChrome({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const session = useSession();
  const dashboard = !!session && !PUBLIC.includes(path) && !path.startsWith("/platform");
  return <div data-dashboard={dashboard ? "true" : undefined} className={"flex flex-col md:flex-row flex-1 min-h-0 " + (dashboard ? "workspace-shell" : "")}><Sidebar /><div className="flex-1 min-w-0">{dashboard && <DashboardTopbar />}<main className="min-w-0">{children}</main></div></div>;
}
