"use client";

import Script from "next/script";
import { usePathname } from "next/navigation";
import { useEffect, useRef } from "react";

// Meta (Facebook) advertising pixel. Public pixel ids are visible in the
// page source of every site that runs one, so this is not a secret.
const PIXEL_ID = "1070709342371934";

// The pixel loads on these paths and NOWHERE else.
//
// This is a security boundary, not a preference. The pixel reports the
// full URL of every page it loads on to Meta, and this app puts one-time
// secrets in query strings: /reset-password?token=…,
// /accept-invite?token=…, /mfa-recovery?token=… . Loading the pixel
// app-wide would hand those tokens to a third party, which is the same
// hazard app/layout.tsx already guards Umami against with
// data-exclude-search. Unlike Umami, the pixel has no option to strip
// query strings, so the only safe control is where it loads at all.
//
// Keeping it off the signed-in product also means Meta never sees which
// customer is analysing what, and never receives a tenant's business
// data. Any new public marketing page has to be added here deliberately,
// after checking nothing secret can appear in its URL.
const TRACKED_PATHS = new Set(["/", "/interest"]);

declare global {
  interface Window {
    fbq?: (...args: unknown[]) => void;
  }
}

/**
 * Records a submitted enquiry as a Meta "Lead" conversion.
 *
 * Without this, an ad campaign can only be optimised against link
 * clicks, which is a measure of curiosity rather than of interest. It
 * sends the fact that a form was submitted and nothing from the form:
 * no name, email or phone number ever reaches Meta.
 *
 * Safe to call from anywhere. It does nothing when the pixel was never
 * loaded, which is the case on every page outside TRACKED_PATHS and for
 * anyone blocking it.
 */
export function trackLead(): void {
  if (typeof window === "undefined") return;
  window.fbq?.("track", "Lead");
}

export default function MetaPixel() {
  const pathname = usePathname();
  const tracked = TRACKED_PATHS.has(pathname);
  // The path the most recent PageView was counted for. This component is
  // always mounted and simply renders nothing off a tracked path, so the
  // ref survives navigation away and back.
  const counted = useRef<string | null>(null);

  useEffect(() => {
    if (!tracked) return;
    if (counted.current === null) {
      // The first tracked page of the visit: the inline snippet below
      // counts it as it initialises. Recording it here stops the effect
      // counting the same page a second time.
      counted.current = pathname;
      return;
    }
    if (counted.current === pathname) return;
    // A client-side navigation between marketing pages. Next.js does not
    // reload the document, so the snippet never runs again and the view
    // would otherwise go unrecorded.
    counted.current = pathname;
    window.fbq?.("track", "PageView");
  }, [pathname, tracked]);

  if (!tracked) return null;

  return (
    <>
      <Script id="meta-pixel" strategy="afterInteractive">
        {`!function(f,b,e,v,n,t,s){if(f.fbq)return;n=f.fbq=function(){n.callMethod?
n.callMethod.apply(n,arguments):n.queue.push(arguments)};if(!f._fbq)f._fbq=n;
n.push=n;n.loaded=!0;n.version='2.0';n.queue=[];t=b.createElement(e);t.async=!0;
t.src=v;s=b.getElementsByTagName(e)[0];s.parentNode.insertBefore(t,s)}(window,
document,'script','https://connect.facebook.net/en_US/fbevents.js');
fbq('init','${PIXEL_ID}');fbq('track','PageView');`}
      </Script>
      <noscript>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          height="1"
          width="1"
          style={{ display: "none" }}
          alt=""
          src={`https://www.facebook.com/tr?id=${PIXEL_ID}&ev=PageView&noscript=1`}
        />
      </noscript>
    </>
  );
}
