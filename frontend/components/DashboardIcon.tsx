export default function DashboardIcon({ name = "chart", size = 18 }: { name?: string; size?: number }) {
  const paths: Record<string, string> = {
    home: "M3 10 12 3l9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z",
    chat: "M21 11a8 8 0 0 1-8 8H6l-4 3V11a8 8 0 0 1 8-8h3a8 8 0 0 1 8 8ZM7 9h10M7 13h6",
    chart: "M4 3v17h17M8 15v-4M13 15V7M18 15V5",
    file: "M14 2H5v20h14V7Zm0 0v5h5M8 12h8M8 16h8",
    source: "M20 6c0 2-4 3-8 3S4 8 4 6s4-3 8-3 8 1 8 3ZM4 6v12c0 2 4 3 8 3s8-1 8-3V6M4 12c0 2 4 3 8 3s8-1 8-3",
    clock: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM12 7v5l3 2",
    shield: "m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6Zm-4 9 3 3 5-6",
    users: "M15 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM5 21v-3a7 7 0 0 1 14 0v3M18 4a3 3 0 0 1 0 6M22 19v-2a5 5 0 0 0-3-5",
    settings: "M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0ZM15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM12 3v3M12 18v3M3 12h3M18 12h3",
    folder: "M3 7V4h6l2 3h10v14H3Z",
    arrow: "M5 12h14m-5-5 5 5-5 5",
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={paths[name] ?? paths.chart} /></svg>;
}
export function navigationIcon(href: string) {
  if (href === "/" || href.endsWith("/ask")) return "chat";
  if (href.endsWith("/home") || href === "/platform") return "home";
  if (href.includes("connections")) return "source";
  if (href.includes("documents")) return "file";
  if (href.includes("library")) return "folder";
  if (href.includes("schedule") || href.includes("audit")) return "clock";
  if (href.includes("security") || href.includes("risks")) return "shield";
  if (href.includes("team") || href.includes("staff") || href.includes("tenants")) return "users";
  if (href.includes("account") || href.includes("profile")) return "settings";
  return "chart";
}
