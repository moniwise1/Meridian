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

export function saveSession(s: Session) {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(TOKEN_KEY, JSON.stringify(s));
}

export function loadSession(): Session | null {
  if (typeof window === "undefined") return null;
  const raw = sessionStorage.getItem(TOKEN_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Session;
  } catch {
    return null;
  }
}

export function clearSession() {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(TOKEN_KEY);
}
