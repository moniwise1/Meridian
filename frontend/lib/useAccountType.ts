"use client";

import { useEffect, useState } from "react";
import { getMe, type AccountType } from "@/lib/api";
import { useSession } from "@/lib/useSession";

// Whether the signed-in tenant is a business or an individual. Several
// parts of the UI only make sense for one of them - the Team page and the
// workspace address for a business, the one-person plans for an individual
// - and the session in sessionStorage doesn't carry it (it holds only what
// login itself returns: token, tenant, user, role, email).
//
// Cached per tenant for the lifetime of the page load. An account's type
// is fixed when it signs up and only platform staff could ever change it,
// so re-asking on every client-side navigation would mean a request per
// page view for a value that cannot move underneath us. Keyed on tenant id
// rather than cleared on sign-out, so signing in as a different account in
// the same tab can never inherit the previous one's answer.
let cachedTenantId: string | null = null;
let cached: AccountType | null = null;

export function useAccountType(): AccountType | null {
  const session = useSession();
  const tenantId = session?.tenantId ?? null;
  // Only a re-render trigger. The value itself is derived from the module
  // cache during render below, so there is no second copy in state to
  // keep in step - and nothing to set synchronously inside the effect.
  const [, setFetchCount] = useState(0);

  useEffect(() => {
    if (!tenantId || (tenantId === cachedTenantId && cached)) return;
    let live = true;
    getMe()
      .then((me) => {
        cachedTenantId = tenantId;
        cached = me.account_type;
        if (live) setFetchCount((n) => n + 1);
      })
      .catch(() => {
        // Left unknown rather than guessed. Every caller treats null as
        // "don't hide anything yet": a network blip should show one extra
        // nav item at worst, never silently take a page away from a
        // business that is entitled to it. The backend is the real guard
        // either way (routes_auth.invite_teammate refuses outright).
      });
    return () => {
      live = false;
    };
  }, [tenantId]);

  return tenantId && tenantId === cachedTenantId ? cached : null;
}
