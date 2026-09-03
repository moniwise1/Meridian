import type { Metadata } from "next";
import Sidebar from "@/components/Sidebar";
import AuthGate from "@/components/AuthGate";
import "./globals.css";

export const metadata: Metadata = {
  title: "Meridian — Enterprise Analytics Agent",
  description: "Ask business questions of your authorized data. Read-only, audited, evidence-backed.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">
        <AuthGate>
          <div className="flex min-h-screen">
            <Sidebar />
            <main className="flex-1 min-w-0">{children}</main>
          </div>
        </AuthGate>
      </body>
    </html>
  );
}
