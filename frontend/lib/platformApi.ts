import { loadPlatformSession, clearPlatformSession } from "@/lib/platformAuth";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

class PlatformAuthError extends Error {}

function authHeaders(): Record<string, string> {
  const session = loadPlatformSession();
  if (!session) throw new PlatformAuthError("Not signed in.");
  return { Authorization: `Bearer ${session.token}` };
}

async function handleAuthFailure(res: Response) {
  if (res.status === 401) {
    clearPlatformSession();
    if (typeof window !== "undefined") window.location.href = "/platform/login";
    throw new PlatformAuthError("Session expired. Please sign in again.");
  }
}

// ---------- Staff auth ----------

export type StaffAuthResponse = {
  access_token: string;
  token_type: string;
  staff_id: string;
  role: string;
};

export async function staffLogin(email: string, password: string): Promise<StaffAuthResponse> {
  const res = await fetch(`${API_BASE}/platform/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Incorrect email or password.");
  return body;
}

export type StaffBootstrapResponse = StaffAuthResponse;

export async function bootstrapOwner(email: string, password: string): Promise<StaffBootstrapResponse> {
  const res = await fetch(`${API_BASE}/platform/bootstrap`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not create the first admin account.");
  return body;
}

export type Staff = { id: string; email: string; role: string; created_at: string };

export async function listStaff(): Promise<Staff[]> {
  const res = await fetch(`${API_BASE}/platform/staff`, { headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not load staff.");
  return res.json();
}

// ---------- Staff invites ----------
// Real invite-by-email (backend/app/invites.py), same shape as the
// tenant-side team invites in lib/api.ts - an owner names an email +
// role, the recipient accepts within 24 hours by proving control of
// their inbox and picking their own password.

export type StaffInvite = {
  id: string;
  email: string;
  role: string;
  status: "pending" | "accepted" | "revoked" | "expired";
  invited_by_email: string;
  created_at: string;
  expires_at: string;
};

export async function inviteStaff(email: string, role: string): Promise<StaffInvite> {
  const res = await fetch(`${API_BASE}/platform/staff/invite`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ email, role }),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not invite this staff member.");
  return body;
}

export async function listStaffInvites(): Promise<StaffInvite[]> {
  const res = await fetch(`${API_BASE}/platform/staff/invites`, { headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not load pending invites.");
  return res.json();
}

export async function revokeStaffInvite(inviteId: string): Promise<StaffInvite> {
  const res = await fetch(`${API_BASE}/platform/staff/invite/${inviteId}/revoke`, {
    method: "POST",
    headers: authHeaders(),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not revoke this invite.");
  return body;
}

export type StaffInviteLookup = { role: string; invited_by_email: string; email: string };

export async function lookupStaffInvite(token: string): Promise<StaffInviteLookup> {
  const res = await fetch(`${API_BASE}/platform/staff/invite/lookup?token=${encodeURIComponent(token)}`);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "This invite is invalid or has expired.");
  return body;
}

export async function acceptStaffInvite(token: string, password: string): Promise<StaffAuthResponse> {
  const res = await fetch(`${API_BASE}/platform/staff/invite/accept`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, password }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not accept this invite.");
  return body;
}

export async function updateStaffRole(staffId: string, role: string): Promise<Staff> {
  const res = await fetch(`${API_BASE}/platform/staff/${staffId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ role }),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not update this staff member's role.");
  return body;
}

export async function deleteStaff(staffId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/platform/staff/${staffId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  await handleAuthFailure(res);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "Could not remove this staff member.");
  }
}

// ---------- Tenants ----------

export type PlatformTenantUser = {
  id: string;
  email: string;
  role: string;
  created_at: string;
};

export type PlatformTenant = {
  id: string;
  name: string;
  subdomain: string | null;
  subscription_status: string;
  tier: "free" | "pro";
  plan: "basic" | "pro" | "premium" | null;
  created_at: string;
  subscribed_at: string | null;
  subscription_expires_at: string | null;
  user_count: number;
  connection_count: number;
  users: PlatformTenantUser[];
};

export async function listTenants(): Promise<PlatformTenant[]> {
  const res = await fetch(`${API_BASE}/platform/tenants`, { headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not load tenants.");
  return res.json();
}

export async function updateTenant(
  tenantId: string,
  updates: { name?: string; subdomain?: string; subscription_status?: string; plan?: string },
): Promise<PlatformTenant> {
  const res = await fetch(`${API_BASE}/platform/tenants/${tenantId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(updates),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not update this tenant.");
  return body;
}

export async function deleteTenant(tenantId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/platform/tenants/${tenantId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  await handleAuthFailure(res);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "Could not delete this tenant.");
  }
}

// ---------- Tickets ----------

export type PlatformTicketMessage = {
  id: string;
  author_type: "customer" | "staff";
  author_label: string;
  body: string;
  created_at: string;
};

export type PlatformTicket = {
  id: string;
  tenant_id: string;
  tenant_name: string;
  subject: string;
  status: string;
  priority: string;
  assigned_to_staff_id: string | null;
  created_at: string;
  updated_at: string;
  messages: PlatformTicketMessage[];
};

export async function listAllTickets(status?: string): Promise<PlatformTicket[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  const res = await fetch(`${API_BASE}/platform/tickets${qs}`, { headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not load tickets.");
  return res.json();
}

export async function updateTicket(
  ticketId: string,
  updates: { status?: string; priority?: string; assigned_to_staff_id?: string },
): Promise<PlatformTicket> {
  const res = await fetch(`${API_BASE}/platform/tickets/${ticketId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(updates),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not update this ticket.");
  return body;
}

export async function staffReplyToTicket(ticketId: string, body: string): Promise<PlatformTicket> {
  const res = await fetch(`${API_BASE}/platform/tickets/${ticketId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ body }),
  });
  await handleAuthFailure(res);
  const respBody = await res.json();
  if (!res.ok) throw new Error(respBody.detail ?? "Could not send the reply.");
  return respBody;
}

// ---------- Incidents ----------

export type IncidentUpdate = { id: string; status: string; body: string; created_at: string };
export type Incident = {
  id: string;
  title: string;
  status: string;
  severity: string;
  started_at: string;
  resolved_at: string | null;
  updates: IncidentUpdate[];
};

export async function listIncidents(): Promise<Incident[]> {
  const res = await fetch(`${API_BASE}/platform/incidents`, { headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not load incidents.");
  return res.json();
}

export async function createIncident(title: string, severity: string, body: string): Promise<Incident> {
  const res = await fetch(`${API_BASE}/platform/incidents`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ title, severity, body }),
  });
  await handleAuthFailure(res);
  const respBody = await res.json();
  if (!res.ok) throw new Error(respBody.detail ?? "Could not create the incident.");
  return respBody;
}

export async function addIncidentUpdate(incidentId: string, status: string, body: string): Promise<Incident> {
  const res = await fetch(`${API_BASE}/platform/incidents/${incidentId}/updates`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ status, body }),
  });
  await handleAuthFailure(res);
  const respBody = await res.json();
  if (!res.ok) throw new Error(respBody.detail ?? "Could not post the update.");
  return respBody;
}

// ---------- Platform activity (staff logins + everything staff have done) ----------

export type PlatformAuditEntry = {
  id: string;
  timestamp: string;
  action: string;
  status: string;
  detail: Record<string, unknown>;
  entry_hash: string;
};

export async function listPlatformAudit(): Promise<PlatformAuditEntry[]> {
  const res = await fetch(`${API_BASE}/platform/audit`, { headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not load the activity log.");
  return res.json();
}

export type PlatformAuditVerification = {
  intact: boolean;
  checked: number;
  broken_at: string | null;
  reason: string;
};

export async function verifyPlatformAudit(): Promise<PlatformAuditVerification> {
  const res = await fetch(`${API_BASE}/platform/audit/verify`, { headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not verify the activity log.");
  return res.json();
}

// ---------- Externally-anchored checkpoints (app/audit/anchor.py) ----------
// Anchors every tenant's current chain head to a GitHub repo via a real
// commit - the fix for the one thing verifyPlatformAudit() above can't
// catch on its own: a full fabricated-but-self-consistent chain
// replacement (see the backend module's docstring for why).

export type AuditCheckpoint = {
  generated_at: string;
  root_hash: string;
  tenant_heads: Record<string, string>;
};

export type PublishCheckpointResult = {
  checkpoint: AuditCheckpoint;
  commit_sha: string;
  commit_url: string;
};

export async function publishAuditCheckpoint(): Promise<PublishCheckpointResult> {
  const res = await fetch(`${API_BASE}/platform/audit/checkpoint`, {
    method: "POST",
    headers: authHeaders(),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not publish a checkpoint.");
  return body;
}

export type CheckpointVerification = {
  verified: boolean;
  checkpoint: AuditCheckpoint;
  tenants: Record<string, { anchored_hash_still_present: boolean; current_chain_intact: boolean; verified: boolean }>;
};

export async function getLatestAuditCheckpoint(): Promise<CheckpointVerification> {
  const res = await fetch(`${API_BASE}/platform/audit/checkpoint/latest`, { headers: authHeaders() });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not load the latest checkpoint.");
  return body;
}

// ---------- Health snapshot ----------

export type HealthSnapshot = {
  recent_errors_last_hour: number;
  active_tenants: number;
  total_tenants: number;
  open_tickets: number;
  open_incidents: number;
};

export async function getHealthSnapshot(): Promise<HealthSnapshot> {
  const res = await fetch(`${API_BASE}/platform/health-snapshot`, { headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not load the health snapshot.");
  return res.json();
}
