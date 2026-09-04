import { loadSession, clearSession } from "@/lib/auth";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

class AuthError extends Error {}

function authHeaders(): Record<string, string> {
  const session = loadSession();
  if (!session) throw new AuthError("Not signed in.");
  return { Authorization: `Bearer ${session.token}` };
}

async function handleAuthFailure(res: Response) {
  if (res.status === 401) {
    clearSession();
    if (typeof window !== "undefined") window.location.href = "/login";
    throw new AuthError("Session expired. Please sign in again.");
  }
}

// ---------- Public status page ----------
// Unauthenticated by design (mirrors backend GET /status) - no
// authHeaders(), no session, no handleAuthFailure.

export type PublicIncidentUpdate = { status: string; body: string; created_at: string };
export type PublicIncident = {
  id: string;
  title: string;
  status: string;
  severity: string;
  started_at: string;
  resolved_at: string | null;
  updates: PublicIncidentUpdate[];
};
export type PublicStatus = { operational: boolean; incidents: PublicIncident[] };

export async function getPublicStatus(): Promise<PublicStatus> {
  const res = await fetch(`${API_BASE}/status`);
  if (!res.ok) throw new Error("Could not load status.");
  return res.json();
}

// ---------- Auth ----------

export type AuthResponse = {
  access_token: string;
  token_type: string;
  tenant_id: string;
  user_id: string;
  role: string;
};

export async function register(companyName: string, email: string, password: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ company_name: companyName, email, password }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not create your account.");
  return body;
}

// Login is a two-step handshake once MFA is involved (see
// app/api/routes_mfa.py's module docstring on the backend for why). Exactly
// one of two shapes comes back — mirrors backend's LoginResponse exactly:
// - mfa_required false: access_token is set, same as a plain login always
//   was — the common case, unchanged for any tenant that hasn't turned MFA on.
// - mfa_required true: access_token is null, pre_auth_token is set instead.
//   mfa_setup_required tells the caller which of the two next screens to
//   show — a code prompt (already enrolled) or a QR setup screen (the
//   org's policy requires MFA but this user hasn't enrolled yet).
export type LoginResult = {
  mfa_required: boolean;
  mfa_setup_required: boolean;
  pre_auth_token: string | null;
  access_token: string | null;
  token_type: string;
  tenant_id: string;
  user_id: string;
  role: string;
};

export async function login(email: string, password: string): Promise<LoginResult> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Incorrect email or password.");
  return body;
}

// ---------- MFA (TOTP authenticator apps) ----------

export type MfaEnrollment = { secret: string; qr_code: string };
export type MfaStatus = { enabled: boolean; tenant_requires_mfa: boolean };

// Self-service — the caller already has a real session (authHeaders()).

export async function getMfaStatus(): Promise<MfaStatus> {
  const res = await fetch(`${API_BASE}/auth/mfa/status`, { headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not load two-factor status.");
  return res.json();
}

export async function startMfaSetup(): Promise<MfaEnrollment> {
  const res = await fetch(`${API_BASE}/auth/mfa/setup`, { method: "POST", headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not start two-factor setup.");
  return res.json();
}

export async function confirmMfaSetup(code: string): Promise<void> {
  const res = await fetch(`${API_BASE}/auth/mfa/confirm`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ code }),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Incorrect code.");
}

export async function disableMfa(code: string): Promise<void> {
  const res = await fetch(`${API_BASE}/auth/mfa/disable`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ code }),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not disable two-factor authentication.");
}

export async function setMfaPolicy(requireMfa: boolean): Promise<void> {
  const res = await fetch(`${API_BASE}/auth/mfa/policy`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ require_mfa: requireMfa }),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not update this setting.");
}

// Login-time — no real session yet, redeems the pre_auth_token from login().

export async function verifyMfaLogin(preAuthToken: string, code: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/mfa/verify-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pre_auth_token: preAuthToken, code }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Incorrect code.");
  return body;
}

export async function setupMfaLogin(preAuthToken: string): Promise<MfaEnrollment> {
  const res = await fetch(`${API_BASE}/auth/mfa/setup-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pre_auth_token: preAuthToken }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not start two-factor setup.");
  return body;
}

export async function confirmMfaLogin(preAuthToken: string, code: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/mfa/confirm-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pre_auth_token: preAuthToken, code }),
  });
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Incorrect code.");
  return body;
}

// ---------- Connections ----------

export type Connection = {
  id: string;
  name: string;
  kind: string;
  host: string;
  database: string;
  verified_read_only: boolean;
  table_allowlist: string[];
  column_policy: Record<string, string[]>;
  // Connector-specific params that don't fit host/port/database - e.g.
  // Snowflake's {warehouse, schema?, role?}. Empty for every other kind.
  extra_config: Record<string, string>;
};

export async function listConnections(): Promise<Connection[]> {
  const res = await fetch(`${API_BASE}/connections`, { headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not load data sources.");
  return res.json();
}

export type CreateConnectionInput = {
  name: string;
  kind: string;
  host: string;
  port: number;
  database: string;
  username: string;
  password: string;
  table_allowlist: string[];
  column_policy: Record<string, string[]>;
  extra_config?: Record<string, string>;
};

export async function createConnection(input: CreateConnectionInput): Promise<Connection> {
  const res = await fetch(`${API_BASE}/connections`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(input),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not create the connection.");
  return body;
}

export async function updateConnectionPolicy(
  connectionId: string,
  input: { table_allowlist?: string[]; column_policy?: Record<string, string[]> },
): Promise<Connection> {
  const res = await fetch(`${API_BASE}/connections/${connectionId}/policy`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(input),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not update the policy.");
  return body;
}

// ---------- Documents ----------

export type DocumentSummary = {
  id: string;
  filename: string;
  kind: string;
  char_count: number;
  truncated: boolean;
  ocr_pages_used: number;
  created_at: string;
};

export type DocumentDetail = DocumentSummary & { extracted_text: string };

export async function uploadDocument(file: File): Promise<DocumentSummary> {
  const form = new FormData();
  form.append("file", file);
  // No Content-Type header here on purpose — the browser sets
  // multipart/form-data with the correct boundary itself; setting it
  // manually breaks the upload.
  const res = await fetch(`${API_BASE}/documents/upload`, {
    method: "POST",
    headers: authHeaders(),
    body: form,
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not upload this document.");
  return body;
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  const res = await fetch(`${API_BASE}/documents`, { headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not load documents.");
  return res.json();
}

export async function getDocument(documentId: string): Promise<DocumentDetail> {
  const res = await fetch(`${API_BASE}/documents/${documentId}`, { headers: authHeaders() });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not load this document.");
  return body;
}

export async function deleteDocument(documentId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/documents/${documentId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  await handleAuthFailure(res);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "Could not delete this document.");
  }
}

// ---------- Team ----------

export type TeamUser = {
  id: string;
  email: string;
  role: string;
  row_scope: Record<string, string[]>;
  created_at: string;
};

export async function listUsers(): Promise<TeamUser[]> {
  const res = await fetch(`${API_BASE}/auth/users`, { headers: authHeaders() });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not load teammates.");
  return body;
}

export async function addTeammate(email: string, password: string, role: string): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/auth/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ email, password, role }),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not add teammate.");
  return body;
}

export async function updateUserRowScope(
  userId: string,
  rowScope: Record<string, string[]>,
): Promise<TeamUser> {
  const res = await fetch(`${API_BASE}/auth/users/${userId}/row_scope`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ row_scope: rowScope }),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not update row-level access.");
  return body;
}

export async function updateUserRole(userId: string, role: string): Promise<TeamUser> {
  const res = await fetch(`${API_BASE}/auth/users/${userId}/role`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ role }),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not update this teammate's role.");
  return body;
}

export async function deleteUser(userId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/auth/users/${userId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  await handleAuthFailure(res);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "Could not remove this teammate.");
  }
}

// ---------- Billing ----------

export type BillingStatus = {
  subscription_status: "none" | "pending" | "active" | "cancelled" | "refunded";
  tier: "free" | "pro";
  // Which of the 3 plans below - null when not on a paid plan.
  plan: "basic" | "pro" | "premium" | null;
  paid_at: string | null;
  refund_eligible_until: string | null;
  subscription_expires_at: string | null;
  plan_code: string | null;
};

export async function getBillingStatus(): Promise<BillingStatus> {
  const res = await fetch(`${API_BASE}/billing/status`, { headers: authHeaders() });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not load billing status.");
  return body;
}

export type Plan = {
  key: string;
  label: string;
  amount: number; // smallest currency unit (kobo for NGN)
  seat_limit: number | null;
  connection_limit: number | null;
  features: string[];
  tagline: string;
  configured: boolean;
};

export async function listPlans(): Promise<Plan[]> {
  const res = await fetch(`${API_BASE}/billing/plans`, { headers: authHeaders() });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not load plans.");
  return body;
}

export async function subscribe(plan: string, callbackUrl: string): Promise<{ authorization_url: string; reference: string }> {
  const res = await fetch(`${API_BASE}/billing/subscribe`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ plan, callback_url: callbackUrl }),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not start checkout.");
  return body;
}

export async function verifyPayment(reference: string): Promise<BillingStatus> {
  const res = await fetch(`${API_BASE}/billing/verify?reference=${encodeURIComponent(reference)}`, {
    headers: authHeaders(),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not verify payment.");
  return body;
}

export async function cancelSubscription(): Promise<BillingStatus> {
  const res = await fetch(`${API_BASE}/billing/cancel`, {
    method: "POST",
    headers: authHeaders(),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not cancel the subscription.");
  return body;
}

// ---------- Ask ----------

export type StepEvent = {
  type: "step";
  step: string;
  status: "running" | "done" | "error";
  detail?: string;
};

export type Anomaly = {
  what: string;
  magnitude: string;
  timeframe: string;
  segment: string;
  evidence: string;
  confidence: string;
  possible_explanations: string[];
};

export type Investigation = { dimension: string; breakdown: { group: string; total: number }[] };

export type ForecastPoint = { period: string; projected_value: number };
export type Forecast = {
  group: string;
  method: string;
  periods_used: number;
  trend_direction: "up" | "down" | "flat";
  points: ForecastPoint[];
  caveat: string;
};

export type ResultEvent = {
  type: "result";
  final: true;
  query_id: string;
  // Only present when reopened via getAnalysis() (per-user pin state) — a
  // freshly-run /ask/stream result doesn't check pins, so this is absent
  // there rather than always false.
  pinned?: boolean;
  // null for a cache hit or a document-only analysis - neither creates/
  // updates a Conversation row (see app/agents/planner.py), so there's
  // nothing to chain a follow-up onto.
  conversation_id: string | null;
  resolved_question: string;
  sql: string;
  sql_rationale: string;
  row_count: number;
  duration_ms: number;
  truncated: boolean;
  data_quality: {
    row_count: number;
    completeness_pct: number;
    duplicate_pct: number;
    missing_by_column: Record<string, number>;
    outlier_notes: string[];
    notes: string[];
  };
  metrics: Record<string, unknown>;
  by_group: { group: string; total: number }[] | null;
  anomalies: Anomaly[];
  investigation: Investigation[];
  forecast: Forecast[];
  documents_used: string[];
  insight:
    | {
        what: string;
        where: string;
        when: string;
        contributors: string;
        data_quality_caveat: string;
        confidence: string;
        confidence_explanation: string;
        next_question: string;
      }
    | { error: string };
  preview_rows: Record<string, unknown>[];
};

export async function askStream(
  input: {
    // A document can be the data source on its own now - see
    // app/agents/planner.py's document-only branch on the backend.
    connection_id: string | null;
    question: string;
    conversation_id?: string | null;
    document_ids?: string[];
  },
  onEvent: (evt: StepEvent | ResultEvent) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/ask/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(input),
  });
  await handleAuthFailure(res);
  if (!res.ok) {
    // A rejection before streaming starts (e.g. rate/concurrency limited)
    // comes back as a plain JSON error body, not an SSE stream.
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "Could not start the analysis.");
  }
  if (!res.body) throw new Error("No response stream from server.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (line.startsWith("data:")) {
        const jsonStr = line.slice(5).trim();
        if (jsonStr) onEvent(JSON.parse(jsonStr));
      }
    }
  }
}

// ---------- Risk scan ----------

export type ScannedAnomaly = Anomaly & { table: string };

export type ScanResultEvent = {
  type: "result";
  final: true;
  tables_scanned: string[];
  tables_skipped: string[];
  anomalies: ScannedAnomaly[];
};

export async function scanStream(
  input: { connection_id: string },
  onEvent: (evt: StepEvent | ScanResultEvent) => void,
): Promise<void> {
  const res = await fetch(`${API_BASE}/scan/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify(input),
  });
  await handleAuthFailure(res);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? "Could not start the scan.");
  }
  if (!res.body) throw new Error("No response stream from server.");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.trim();
      if (line.startsWith("data:")) {
        const jsonStr = line.slice(5).trim();
        if (jsonStr) onEvent(JSON.parse(jsonStr));
      }
    }
  }
}

// ---------- Artifacts ----------

export type Artifact = { id: string; kind: string; title: string; url: string };

export async function generateReport(queryId: string): Promise<Artifact> {
  const res = await fetch(`${API_BASE}/artifacts/report/${queryId}`, { method: "POST", headers: authHeaders() });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not generate the report.");
  return body;
}

export async function generatePresentation(queryId: string): Promise<Artifact> {
  const res = await fetch(`${API_BASE}/artifacts/presentation/${queryId}`, { method: "POST", headers: authHeaders() });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not generate the presentation.");
  return body;
}

export async function generateExport(queryId: string, format: "csv" | "xlsx"): Promise<Artifact> {
  const res = await fetch(`${API_BASE}/artifacts/export/${queryId}?format=${format}`, {
    method: "POST",
    headers: authHeaders(),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not export the result.");
  return body;
}

export async function emailArtifact(
  queryId: string,
  recipient: string,
  artifactId?: string,
  confirmed = false,
): Promise<{ status: string; reason: string }> {
  const res = await fetch(`${API_BASE}/artifacts/email`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ query_id: queryId, recipient, artifact_id: artifactId, confirmed }),
  });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not send the email.");
  return body;
}

// ---------- History ----------

export type AnalysisSummary = {
  query_id: string;
  question: string;
  connection_id: string;
  row_count: number;
  duration_ms: number;
  // Per-user, not per-tenant — see PinnedAnalysis's docstring on the backend.
  pinned: boolean;
  created_at: string;
};

export async function listAnalyses(pinnedOnly = false): Promise<AnalysisSummary[]> {
  const res = await fetch(
    `${API_BASE}/history/analyses${pinnedOnly ? "?pinned_only=true" : ""}`,
    { headers: authHeaders() },
  );
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not load past analyses.");
  return res.json();
}

export async function getAnalysis(queryId: string): Promise<ResultEvent> {
  const res = await fetch(`${API_BASE}/history/analyses/${queryId}`, { headers: authHeaders() });
  await handleAuthFailure(res);
  const body = await res.json();
  if (!res.ok) throw new Error(body.detail ?? "Could not load this analysis.");
  return body;
}

export async function pinAnalysis(queryId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/history/analyses/${queryId}/pin`, {
    method: "PUT",
    headers: authHeaders(),
  });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not pin this analysis.");
}

export async function unpinAnalysis(queryId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/history/analyses/${queryId}/pin`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not unpin this analysis.");
}

export type ArtifactHistoryEntry = {
  id: string;
  kind: string;
  title: string;
  source_query_id: string | null;
  url: string;
  created_at: string;
};

export async function listArtifactHistory(kind?: string): Promise<ArtifactHistoryEntry[]> {
  const qs = kind ? `?kind=${encodeURIComponent(kind)}` : "";
  const res = await fetch(`${API_BASE}/history/artifacts${qs}`, { headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not load generated artifacts.");
  return res.json();
}

// ---------- Support ----------

export type TicketMessage = {
  id: string;
  author_type: "customer" | "staff";
  author_label: string;
  body: string;
  created_at: string;
};

export type SupportTicket = {
  id: string;
  subject: string;
  status: "open" | "in_progress" | "resolved" | "closed";
  priority: "low" | "normal" | "high" | "urgent";
  created_at: string;
  updated_at: string;
  messages: TicketMessage[];
};

export async function listMyTickets(): Promise<SupportTicket[]> {
  const res = await fetch(`${API_BASE}/support/tickets`, { headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not load support tickets.");
  return res.json();
}

export async function createTicket(subject: string, body: string, priority = "normal"): Promise<SupportTicket> {
  const res = await fetch(`${API_BASE}/support/tickets`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ subject, body, priority }),
  });
  await handleAuthFailure(res);
  const respBody = await res.json();
  if (!res.ok) throw new Error(respBody.detail ?? "Could not create the ticket.");
  return respBody;
}

export async function replyToTicket(ticketId: string, body: string): Promise<SupportTicket> {
  const res = await fetch(`${API_BASE}/support/tickets/${ticketId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ body }),
  });
  await handleAuthFailure(res);
  const respBody = await res.json();
  if (!res.ok) throw new Error(respBody.detail ?? "Could not send the reply.");
  return respBody;
}

// ---------- Audit ----------

export type AuditEntry = {
  id: string;
  timestamp: string;
  action: string;
  status: string;
  connection_id: string | null;
  query_id: string | null;
  detail: Record<string, unknown>;
  entry_hash: string;
};

export async function listAudit(): Promise<AuditEntry[]> {
  const res = await fetch(`${API_BASE}/audit`, { headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not load the audit log.");
  return res.json();
}

export type AuditVerification = {
  intact: boolean;
  checked: number;
  broken_at: string | null;
  reason: string;
};

export async function verifyAuditChain(): Promise<AuditVerification> {
  const res = await fetch(`${API_BASE}/audit/verify`, { headers: authHeaders() });
  await handleAuthFailure(res);
  if (!res.ok) throw new Error("Could not verify the audit log.");
  return res.json();
}
