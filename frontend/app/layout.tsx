import type { Metadata } from "next";
import Sidebar from "@/components/Sidebar";
import AuthGate from "@/components/AuthGate";
import MfaWarningBanner from "@/components/MfaWarningBanner";
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
          <div className="flex flex-col min-h-screen">
            <MfaWarningBanner />
            <div className="flex flex-1 min-h-0">
              <Sidebar />
              <main className="flex-1 min-w-0">{children}</main>
            </div>
          </div>
        </AuthGate>
      </body>
    </html>
  );
}
