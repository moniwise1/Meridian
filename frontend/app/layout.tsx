import type { Metadata } from "next";
import Script from "next/script";
import WorkspaceChrome from "@/components/WorkspaceChrome";
import AuthGate from "@/components/AuthGate";
import MetaPixel from "@/components/MetaPixel";
import MfaWarningBanner from "@/components/MfaWarningBanner";
import SubscriptionExpiryBanner from "@/components/SubscriptionExpiryBanner";
import "./globals.css";

export const metadata: Metadata = {
  title: "Meridian Analytics | Data analysis and business intelligence",
  description: "Analyse files or securely connect your database. Ask questions about operations, customers, sales, research and finance, with answers grounded in your data.",
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
            competes with the actual page's own load.
            data-exclude-search strips query strings from every tracked
            URL - reset-password, accept-invite, and mfa-recovery all carry
            a real one-time secret token as a "?token=..." query param, and
            without this a routine page-view would otherwise send that
            token to Umami's servers along with the URL. */}
        <Script
          defer
          src="https://cloud.umami.is/script.js"
          data-website-id="e57bb3d3-e95f-4063-90d8-6f5cc4e23bd8"
          data-exclude-search="true"
          strategy="afterInteractive"
        />
        {/* Meta advertising pixel. Unlike Umami above, this one is NOT
            site-wide: it loads only on the public marketing pages listed
            in the component, because it reports full URLs to Meta and
            several of this app's routes carry one-time tokens in their
            query string. See components/MetaPixel.tsx. */}
        <MetaPixel />
        <AuthGate>
          <div className="flex flex-col min-h-screen">
            <MfaWarningBanner />
            <SubscriptionExpiryBanner />
            <WorkspaceChrome>{children}</WorkspaceChrome>
          </div>
        </AuthGate>
      </body>
    </html>
  );
}
