"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { useSession } from "@/lib/useSession";
import { getBillingStatus } from "@/lib/api";

// Same slim persistent-bar pattern as MfaWarningBanner - a heads-up that
// reappears every session until the renewal actually happens (or the
// subscription is no longer within the window), not a dismissible toast.
// This is the "you can see it yourself" complement to the automatic
// email/in-app-notification reminder (app/user_notifications.py's
// maybe_send_expiry_reminder) - same underlying data, just always visible
// rather than something that has to land in an inbox or the bell.
const WARNING_WINDOW_DAYS = 7;

export default function SubscriptionExpiryBanner() {
  const pathname = usePathname();
  const session = useSession();
  const [daysLeft, setDaysLeft] = useState<number | null>(null);

  const isPlatformRoute = pathname.startsWith("/platform");
  const isPublicRoute = pathname === "/status" || pathname === "/login";
  const skip = isPlatformRoute || isPublicRoute || !session;

  useEffect(() => {
    if (skip) return;
    getBillingStatus()
      .then((s) => {
        if (s.subscription_status !== "active" || !s.subscription_expires_at) {
          setDaysLeft(null);
          return;
        }
        const msLeft = new Date(s.subscription_expires_at).getTime() - Date.now();
        setDaysLeft(Math.ceil(msLeft / (24 * 60 * 60 * 1000)));
      })
      .catch(() => {
        /* Not fatal — same reasoning as MfaWarningBanner: the banner just
           doesn't show if the check fails. */
      });
  }, [pathname, skip]);

  if (skip || daysLeft === null || daysLeft < 0 || daysLeft > WARNING_WINDOW_DAYS || pathname === "/billing") {
    return null;
  }

  return (
    <div className="bg-amber-soft text-amber text-[12.5px] px-4 py-2 flex items-center justify-center gap-2 border-b border-line">
      <span>
        Your subscription {daysLeft === 0 ? "renews today" : `renews in ${daysLeft} day${daysLeft === 1 ? "" : "s"}`}.
      </span>
      <Link href="/billing" className="underline hover:no-underline font-medium">
        View billing →
      </Link>
    </div>
  );
}
