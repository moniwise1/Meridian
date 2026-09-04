"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { clearSession } from "@/lib/auth";

// Idle-based sign-out, independent of the access token's own (much
// longer) expiry — activity alone keeps a session usable; only
// inactivity ever forces it to end. No fixed absolute session cap.
const IDLE_WARNING_MS = 10 * 60 * 1000; // 10 minutes with no activity → warn
const GRACE_MS = 60 * 1000; // 1 more minute to respond before signing out
const ACTIVITY_EVENTS = ["mousemove", "mousedown", "keydown", "scroll", "touchstart"] as const;

export default function InactivityWatcher() {
  const router = useRouter();
  const [warning, setWarning] = useState(false);
  const lastActivityRef = useRef(Date.now());
  const warningShownAtRef = useRef<number | null>(null);

  useEffect(() => {
    function onActivity() {
      lastActivityRef.current = Date.now();
      // Activity BEFORE the warning is showing resets the idle clock as
      // normal. Once the "Are you still here?" prompt is up, background
      // mouse/scroll jitter deliberately does NOT dismiss it — only the
      // explicit button below does; see its own comment for why.
      if (!warningShownAtRef.current) setWarning(false);
    }
    ACTIVITY_EVENTS.forEach((evt) => window.addEventListener(evt, onActivity, { passive: true }));

    const interval = setInterval(() => {
      const idleFor = Date.now() - lastActivityRef.current;
      if (warningShownAtRef.current) {
        if (Date.now() - warningShownAtRef.current >= GRACE_MS) {
          clearSession();
          router.push("/login?reason=inactivity");
        }
      } else if (idleFor >= IDLE_WARNING_MS) {
        warningShownAtRef.current = Date.now();
        setWarning(true);
      }
    }, 1000);

    return () => {
      ACTIVITY_EVENTS.forEach((evt) => window.removeEventListener(evt, onActivity));
      clearInterval(interval);
    };
  }, [router]);

  function stillHere() {
    lastActivityRef.current = Date.now();
    warningShownAtRef.current = null;
    setWarning(false);
  }

  if (!warning) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/30">
      <div className="bg-panel border border-line rounded-[4px] p-6 w-full max-w-xs shadow-lg">
        <div className="text-[15px] font-medium text-ink mb-1.5">Are you still here?</div>
        <p className="text-[12.5px] text-ink-soft leading-relaxed mb-5">
          You&apos;ve been inactive for a while. For your security, you&apos;ll be signed out in a
          minute unless you confirm you&apos;re still here.
        </p>
        <button
          onClick={stillHere}
          className="w-full text-[13px] py-1.5 rounded-[3px] bg-teal-deep text-white hover:bg-teal transition-colors"
        >
          Yes, I&apos;m still here
        </button>
      </div>
    </div>
  );
}
