// Thin wrapper around Umami's global tracking function (loaded via the
// <Script> tag in app/layout.tsx). Never throws and never blocks: the
// script loads async, so `window.umami` may not exist yet (a slow
// connection, an ad-blocker, or the very first paint before it's parsed) -
// a missed event here should never be able to break the actual feature the
// user is trying to use.
declare global {
  interface Window {
    umami?: { track: (event: string, data?: Record<string, unknown>) => void };
  }
}

export function track(event: string, data?: Record<string, unknown>) {
  try {
    window.umami?.track(event, data);
  } catch {
    // Analytics is never allowed to be the reason a real user action fails.
  }
}
