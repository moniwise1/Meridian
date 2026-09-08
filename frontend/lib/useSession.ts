"use client";

import { useSyncExternalStore } from "react";
import {
  subscribeSession,
  getSessionSnapshot,
  getServerSessionSnapshot,
  type Session,
} from "@/lib/auth";
import {
  subscribePlatformSession,
  getPlatformSessionSnapshot,
  getServerPlatformSessionSnapshot,
  type PlatformSession,
} from "@/lib/platformAuth";

// sessionStorage is a browser-only external store; useSyncExternalStore is
// React's supported way to read one without a setState-in-effect. It's
// SSR-safe: the getServerSnapshot arg is used on the server and the first
// client render, then the real snapshot once hydrated. Pair with
// useHydrated() below to tell "no session" apart from "not checked yet",
// which several route gates rely on to avoid a redirect flash.

export function useSession(): Session | null {
  return useSyncExternalStore(subscribeSession, getSessionSnapshot, getServerSessionSnapshot);
}

export function usePlatformSession(): PlatformSession | null {
  return useSyncExternalStore(
    subscribePlatformSession,
    getPlatformSessionSnapshot,
    getServerPlatformSessionSnapshot,
  );
}

const noopSubscribe = () => () => {};

// false on the server and the very first client render, true immediately
// after hydration - the standard SSR-safe "has the client taken over yet"
// check (client snapshot true, server snapshot false).
export function useHydrated(): boolean {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false,
  );
}
