import type { Metadata } from "next";
import Script from "next/script";
import Sidebar from "@/components/Sidebar";
import AuthGate from "@/components/AuthGate";
import MfaWarningBanner from "@/components/MfaWarningBanner";
import SubscriptionExpiryBanner from "@/components/SubscriptionExpiryBanner";
import "./globals.css";

export const metadata: Metadata = {
  title: "Meridian — Enterprise Analytics Agent",
  description: "Ask business questions of your authorized data. Read-only, audited, evidence-backed.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="antialiased">
        {/* Umami (self-service hosted, cloud.umami.is) - internal-only
            analytics: page views, approximate location from IP, and the
            explicit umami.track() events below (see lib/analytics.ts).
            No cookies, no cross-site tracking, nothing sent to any other
            third party - see the Privacy Policy's "Third parties we rely
            on" section. strategy="afterInteractive" so this never
            competes with the actual page's own load. */}
        <Script
          defer
          src="https://cloud.umami.is/script.js"
          data-website-id="e57bb3d3-e95f-4063-90d8-6f5cc4e23bd8"
          strategy="afterInteractive"
        />
        <AuthGate>
          <div className="flex flex-col min-h-screen">
            <MfaWarningBanner />
            <SubscriptionExpiryBanner />
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
