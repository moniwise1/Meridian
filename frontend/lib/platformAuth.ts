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

// Same snapshot-cache reasoning as lib/auth.ts - see the comment there.
let cachedRaw: string | null = null;
let cachedSession: PlatformSession | null = null;

function snapshot(): PlatformSession | null {
  const raw = typeof window === "undefined" ? null : window.sessionStorage.getItem(TOKEN_KEY);
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      cachedSession = raw ? (JSON.parse(raw) as PlatformSession) : null;
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

export function subscribePlatformSession(onStoreChange: () => void): () => void {
  listeners.add(onStoreChange);
  const onStorage = (e: StorageEvent) => {
    if (e.key === TOKEN_KEY || e.key === null) onStoreChange();
  };
  if (typeof window !== "undefined") window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(onStoreChange);
    if (typeof window !== "undefined") window.removeEventListener("storage", onStorage);
  };
}

export function getPlatformSessionSnapshot(): PlatformSession | null {
  return snapshot();
}

export function getServerPlatformSessionSnapshot(): PlatformSession | null {
  return null;
}

export function loadPlatformSession(): PlatformSession | null {
  return snapshot();
}

export function savePlatformSession(s: PlatformSession) {
  if (typeof window === "undefined") return;
  const raw = JSON.stringify(s);
  window.sessionStorage.setItem(TOKEN_KEY, raw);
  cachedRaw = raw;
  cachedSession = s;
  notify();
}

export function clearPlatformSession() {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(TOKEN_KEY);
  cachedRaw = null;
  cachedSession = null;
  notify();
}
