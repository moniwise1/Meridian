"use client";

// Deliberately a separate storage key from lib/auth.ts's tenant session
// ("meridian_token") - a browser could plausibly have both a customer
// session and a staff session open at once (e.g. a support agent testing
// their own trial org), and mixing the two keys would risk one silently
// clobbering or being read as the other.
const TOKEN_KEY = "meridian_platform_token";

export type PlatformSession = {
  token: string;
  staffId: string;
  role: string;
  email: string;
};

export function savePlatformSession(s: PlatformSession) {
  if (typeof window === "undefined") return;
  sessionStorage.setItem(TOKEN_KEY, JSON.stringify(s));
}

export function loadPlatformSession(): PlatformSession | null {
  if (typeof window === "undefined") return null;
  const raw = sessionStorage.getItem(TOKEN_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as PlatformSession;
  } catch {
    return null;
  }
}

export function clearPlatformSession() {
  if (typeof window === "undefined") return;
  sessionStorage.removeItem(TOKEN_KEY);
}
