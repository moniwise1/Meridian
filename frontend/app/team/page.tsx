"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  listUsers, inviteTeammate, listTeamInvites, revokeTeamInvite, updateUserRowScope, updateUserRole,
  deleteUser, getBillingStatus, listPlans,
  type TeamUser, type TeamInvite, type BillingStatus, type Plan,
} from "@/lib/api";
import { loadSession } from "@/lib/auth";

const ROLE_OPTIONS = ["analyst", "manager", "executive", "viewer", "admin"];

function rowScopeToText(scope: Record<string, string[]>): string {
  return Object.entries(scope)
    .map(([column, values]) => `${column}=${values.join(",")}`)
    .join("\n");
}

function parseRowScopeText(text: string): Record<string, string[]> {
  const scope: Record<string, string[]> = {};
  for (const line of text.split("\n")) {
    const [column, valuesPart] = line.split("=");
    const columnName = column?.trim();
    if (!columnName || valuesPart === undefined) continue;
    const values = valuesPart.split(",").map((v) => v.trim()).filter(Boolean);
    if (values.length) scope[columnName] = values;
  }
  return scope;
}

export default function TeamPage() {
  const [users, setUsers] = useState<TeamUser[]>([]);
  const [invites, setInvites] = useState<TeamInvite[]>([]);
  const [billing, setBilling] = useState<BillingStatus | null>(null);
  const [plans, setPlans] = useState<Plan[]>([]);
  const [error, setError] = useState("");
  const [editingUser, setEditingUser] = useState<string | null>(null);
  const [addingOpen, setAddingOpen] = useState(false);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const isAdmin = loadSession()?.role === "admin";

  function refresh() {
    listUsers()
      .then(setUsers)
      .catch((e) => setError(e.message));
    listTeamInvites()
      .then(setInvites)
      .catch(() => {
        /* Team page still works without this - it only adds the pending-invites list. */
      });
    getBillingStatus()
      .then(setBilling)
      .catch(() => {
        /* Team page still works without this - it only adds the plan-limit banner. */
      });
    listPlans().then(setPlans).catch(() => {});
  }

  useEffect(refresh, []);

  const pendingInvites = invites.filter((i) => i.status === "pending");

  async function handleRevoke(inviteId: string) {
    setError("");
    try {
      await revokeTeamInvite(inviteId);
      setRevokingId(null);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleRoleChange(userId: string, newRole: string) {
    setError("");
    try {
      await updateUserRole(userId, newRole);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleRemove(userId: string) {
    setError("");
    try {
      await deleteUser(userId);
      setRemovingId(null);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!isAdmin) {
    return (
      <div className="max-w-3xl mx-auto px-8 py-12">
        <div className="text-[13.5px] text-ink-soft">Only admins can manage teammates.</div>
      </div>
    );
  }

  // Source of truth for the limit is always the backend
  // (app/api/routes_auth.py's invite_teammate, 402 once a plan's seat cap
  // is hit) - this is just so the UI doesn't invite someone to fill out a
  // form that's guaranteed to fail. Free (no plan) is a hardcoded 1-seat
  // cap on the backend (see seat_limit_for(None) in
  // app/billing/plans.py); a paid plan's real limit comes from
  // GET /billing/plans, keyed by billing.plan. Counts pending invites
  // alongside real accounts, matching the backend - otherwise this banner
  // would understate usage right up until every pending invite is
  // accepted at once.
  const currentPlan = billing?.plan ? plans.find((p) => p.key === billing.plan) : null;
  const seatLimit = billing?.tier === "free" ? 1 : currentPlan?.seat_limit ?? null;
  const seatsUsed = users.length + pendingInvites.length;
  const atSeatLimit = seatLimit !== null && seatsUsed >= seatLimit;

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Team</h1>
      <p className="text-[13.5px] text-ink-soft mb-4">
        Row-level access restricts which rows a teammate&apos;s questions can see, by column value —
        e.g. a regional manager scoped to <code>region=South-East</code> never sees other regions&apos;
        data, regardless of what they ask. An empty scope is unrestricted.
      </p>

      {billing && (
        <div
          className={`mb-6 rounded-[4px] border px-4 py-3 text-[12.5px] ${
            seatLimit === null ? "border-line bg-panel text-ink-soft" : atSeatLimit ? "border-amber bg-amber-soft text-amber" : "border-line bg-panel text-ink-soft"
          }`}
        >
          {billing.tier === "free" ? (
            <>
              Free plan — limited to 1 account ({seatsUsed} of 1 used).{" "}
              <Link href="/billing" className="underline hover:no-underline">
                Subscribe
              </Link>{" "}
              to add teammates.
            </>
          ) : seatLimit === null ? (
            <>{currentPlan?.label ?? "Your plan"} — no limit on the number of teammate accounts.</>
          ) : (
            <>
              {currentPlan?.label ?? "Your plan"} — up to {seatLimit} accounts ({seatsUsed} of {seatLimit} used).
              {atSeatLimit && (
                <>
                  {" "}
                  <Link href="/billing" className="underline hover:no-underline">
                    Upgrade
                  </Link>{" "}
                  to add more teammates.
                </>
              )}
            </>
          )}
        </div>
      )}

      {error && <div className="mb-4 text-[13px] text-red">{error}</div>}

      <div className="mb-6">
        {!addingOpen ? (
          <button
            onClick={() => setAddingOpen(true)}
            disabled={atSeatLimit}
            className="text-[13px] px-4 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
          >
            Invite teammate
          </button>
        ) : (
          <InviteTeammateForm
            onClose={() => setAddingOpen(false)}
            onInvited={() => {
              setAddingOpen(false);
              refresh();
            }}
          />
        )}
      </div>

      {pendingInvites.length > 0 && (
        <div className="mb-6">
          <div className="text-[12.5px] text-ink-soft mb-2">
            Pending invites — accept within 24 hours or they&apos;re automatically revoked.
          </div>
          <div className="flex flex-col gap-2">
            {pendingInvites.map((inv) => (
              <div
                key={inv.id}
                className="flex items-center justify-between gap-3 bg-panel border border-line rounded-[4px] px-4 py-2.5"
              >
                <div className="min-w-0">
                  <div className="text-[13px] text-ink truncate">{inv.email}</div>
                  <div className="text-[11.5px] text-ink-soft font-[family-name:var(--font-mono)] mt-0.5">
                    {inv.role} · invited by {inv.invited_by_email} · expires{" "}
                    {new Date(inv.expires_at).toLocaleString()}
                  </div>
                </div>
                {revokingId === inv.id ? (
                  <div className="flex items-center gap-2 shrink-0">
                    <button
                      onClick={() => handleRevoke(inv.id)}
                      className="text-[11.5px] px-2.5 py-1 rounded-[3px] bg-red text-white hover:opacity-90 transition-opacity"
                    >
                      Confirm revoke
                    </button>
                    <button
                      onClick={() => setRevokingId(null)}
                      className="text-[11.5px] text-ink-soft hover:text-ink transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setRevokingId(inv.id)}
                    className="shrink-0 text-[11.5px] text-red hover:opacity-70 transition-opacity"
                  >
                    Revoke
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="flex flex-col gap-3">
        {users.map((u) => (
          <div key={u.id} className="bg-panel border border-line rounded-[4px] px-4 py-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[13.5px] text-ink">{u.email}</div>
                {u.created_at && (
                  <div className="text-[11.5px] text-ink-soft font-[family-name:var(--font-mono)] mt-0.5">
                    joined {new Date(u.created_at).toLocaleDateString()}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] px-2 py-0.5 rounded-[3px] bg-line text-ink-soft font-[family-name:var(--font-mono)]">
                  {Object.keys(u.row_scope).length === 0 ? "Unrestricted" : rowScopeToText(u.row_scope)}
                </span>
                <select
                  value={u.role}
                  onChange={(e) => handleRoleChange(u.id, e.target.value)}
                  className="text-[12px] border border-line rounded-[3px] px-2 py-1 bg-panel text-ink capitalize"
                >
                  {ROLE_OPTIONS.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
                <button
                  onClick={() => setEditingUser(editingUser === u.id ? null : u.id)}
                  className="text-[11.5px] text-teal hover:text-teal-deep transition-colors"
                >
                  {editingUser === u.id ? "Close" : "Row access"}
                </button>
                <button
                  onClick={() => setRemovingId(removingId === u.id ? null : u.id)}
                  className="text-[11.5px] text-red hover:opacity-70 transition-opacity"
                >
                  Remove
                </button>
              </div>
            </div>

            {removingId === u.id && (
              <div className="mt-3 pt-3 border-t border-line flex items-center justify-between gap-3">
                <div className="text-[12.5px] text-red">
                  Remove {u.email} from this organization? They&apos;ll lose access immediately.
                </div>
                <button
                  onClick={() => handleRemove(u.id)}
                  className="shrink-0 text-[12.5px] px-3 py-1.5 rounded-[3px] bg-red text-white hover:opacity-90 transition-opacity"
                >
                  Confirm remove
                </button>
              </div>
            )}

            {editingUser === u.id && <RowScopeEditor user={u} onSaved={refresh} />}
          </div>
        ))}
        {users.length === 0 && !error && (
          <div className="text-[13px] text-ink-soft">No teammates yet.</div>
        )}
      </div>
    </div>
  );
}

function InviteTeammateForm({ onClose, onInvited }: { onClose: () => void; onInvited: () => void }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("analyst");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await inviteTeammate(email, role);
      onInvited();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="bg-panel border border-line rounded-[4px] p-4 flex flex-col gap-3">
      <p className="text-[12px] text-ink-soft">
        They&apos;ll get an email with a link to join — it expires in 24 hours if not accepted.
      </p>
      <div className="grid grid-cols-2 gap-3">
        <label className="flex flex-col gap-1">
          <span className="text-[12px] text-ink-soft">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="teammate@company.com"
            className="text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[12px] text-ink-soft">Role</span>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink"
          >
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <div className="text-[12.5px] text-red">{error}</div>}
      <div className="flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onClose}
          className="text-[12.5px] px-3 py-1.5 rounded-[3px] text-ink-soft hover:text-ink transition-colors"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={saving}
          className="text-[12.5px] px-3 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
        >
          {saving ? "Sending…" : "Send invite"}
        </button>
      </div>
    </form>
  );
}

function RowScopeEditor({ user, onSaved }: { user: TeamUser; onSaved: () => void }) {
  const [text, setText] = useState(rowScopeToText(user.row_scope));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setSaving(true);
    setError("");
    try {
      await updateUserRowScope(user.id, parseRowScopeText(text));
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mt-3 pt-3 border-t border-line flex flex-col gap-3">
      <div>
        <div className="text-[12px] text-ink-soft mb-2">
          One column per line, as <code>column=value1,value2</code>. Every question this teammate
          asks is filtered to rows matching all lines.
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={"region=South-East"}
          rows={3}
          className="text-[13px] font-[family-name:var(--font-mono)] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 w-full resize-y"
        />
      </div>
      <div className="flex items-center justify-end gap-2">
        {error && <div className="text-[12px] text-red mr-auto">{error}</div>}
        <button
          onClick={save}
          disabled={saving}
          className="text-[12.5px] px-3 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
        >
          {saving ? "Saving…" : "Save"}
        </button>
      </div>
    </div>
  );
}
