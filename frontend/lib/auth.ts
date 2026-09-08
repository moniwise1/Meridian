"use client";

// Token lives in memory + sessionStorage (not localStorage) so it doesn't
// silently persist across a shared/public machine forever. This is a
// pragmatic MVP choice - a production build would use an httpOnly cookie
// set by the backend instead, so the token is never reachable from JS at all.
const TOKEN_KEY = "meridian_token";

export type Session = {
  token: string;
  tenantId: string;
  userId: string;
  role: string;
  email: string;
};

// --- snapshot cache -----------------------------------------------------
// useSyncExternalStore (see lib/useSession.ts) requires getSnapshot to
// return a STABLE reference while the value is unchanged, or React throws
// "The result of getSnapshot should be cached". A bare
// sessionStorage.getItem + JSON.parse hands back a new object every call,
// so parse once and keep it, keyed on the exact raw string it came from.
// saveSession/clearSession keep `cachedRaw` in lockstep with what storage
// now holds, so the cache and storage never disagree.
let cachedRaw: string | null = null;
let cachedSession: Session | null = null;

function snapshot(): Session | null {
  const raw = typeof window === "undefined" ? null : window.sessionStorage.getItem(TOKEN_KEY);
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      cachedSession = raw ? (JSON.parse(raw) as Session) : null;
    } catch {
      cachedSession = null;
    }
  }
  return cachedSession;
}

const listeners = new Set<() => void>();

function notify() {
  for (const listener of listeners) listener();
}

// --- public API -------------------------------------------------------

export function subscribeSession(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange);
  // Another tab writing the session fires a 'storage' event here (it never
  // fires in the tab that made the change - notify() below covers that).
  const onStorage = (e: StorageEvent) => {
    if (e.key === TOKEN_KEY || e.key === null) onStoreChange();
  };
  if (typeof window !== "undefined") window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(onStoreChange);
    if (typeof window !== "undefined") window.removeEventListener("storage", onStorage);
  };
}

export function getSessionSnapshot(): Session | null {
  return snapshot();
}

// Server / first-client-render value. A distinct constant (not snapshot())
// so useSyncExternalStore can tell "hydrated" from "not yet" - see
// useHydrated() in lib/useSession.ts.
export function getServerSessionSnapshot(): Session | null {
  return null;
}

export function loadSession(): Session | null {
  return snapshot();
}

export function saveSession(s: Session) {
  if (typeof window === "undefined") return;
  const raw = JSON.stringify(s);
  window.sessionStorage.setItem(TOKEN_KEY, raw);
  cachedRaw = raw;
  cachedSession = s;
  notify();
}

export function clearSession() {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(TOKEN_KEY);
  cachedRaw = null;
  cachedSession = null;
  notify();
}
