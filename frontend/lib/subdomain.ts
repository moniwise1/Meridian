// Per-tenant subdomains (wamco.getmeridiananalytics.com) - a real login
// boundary, not decoration, see backend/app/api/routes_auth.py's login().
// This file's only job is figuring out, purely from the browser's own
// current hostname, whether the visitor is on a tenant's subdomain or on
// the generic app (bare apex, "www", localhost, or the platform's own
// auto-generated *.up.railway.app fallback domain) - none of which carry
// a tenant subdomain.
//
// The apex domain is configurable (NEXT_PUBLIC_APEX_DOMAIN) rather than
// hardcoded, so this doesn't silently break if the domain ever changes.
const APEX_DOMAIN = process.env.NEXT_PUBLIC_APEX_DOMAIN ?? "getmeridiananalytics.com";

const NON_TENANT_LABELS = new Set(["www"]);

export function getTenantSubdomain(): string | null {
  if (typeof window === "undefined") return null;
  const host = window.location.hostname;

  if (host === "localhost" || host === "127.0.0.1") return null;
  if (host.endsWith(".up.railway.app")) return null; // the platform's own fallback domain
  if (host === APEX_DOMAIN) return null; // bare apex

  if (host.endsWith(`.${APEX_DOMAIN}`)) {
    const label = host.slice(0, -(`.${APEX_DOMAIN}`.length));
    // Only a single-label subdomain counts ("wamco", not
    // "wamco.staging") - matches Railway's own "wildcards can't be
    // nested" limitation on the DNS side, so this never claims to
    // support something the infrastructure doesn't.
    if (label && !label.includes(".") && !NON_TENANT_LABELS.has(label)) {
      return label;
    }
  }
  return null;
}
