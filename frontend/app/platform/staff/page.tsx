"use client";

import { useEffect, useState } from "react";
import {
  listStaff, inviteStaff, listStaffInvites, revokeStaffInvite, updateStaffRole, deleteStaff,
  type Staff, type StaffInvite,
} from "@/lib/platformApi";
import { loadPlatformSession } from "@/lib/platformAuth";

export default function PlatformStaffPage() {
  const [staff, setStaff] = useState<Staff[]>([]);
  const [invites, setInvites] = useState<StaffInvite[]>([]);
  const [search, setSearch] = useState("");
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("support");
  const [busy, setBusy] = useState(false);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [revokingId, setRevokingId] = useState<string | null>(null);
  const isOwner = loadPlatformSession()?.role === "owner";

  function refresh() {
    listStaff()
      .then(setStaff)
      .catch((e) => setError(e.message));
    listStaffInvites()
      .then(setInvites)
      .catch(() => {
        /* Staff page still works without this - it only adds the pending-invites list. */
      });
  }

  useEffect(refresh, []);

  const pendingInvites = invites.filter((i) => i.status === "pending");
  const q = search.trim().toLowerCase();
  const filteredStaff = q ? staff.filter((s) => s.email.toLowerCase().includes(q) || s.role.includes(q)) : staff;

  async function handleInvite(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await inviteStaff(email, role);
      setEmail("");
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function handleRevokeInvite(inviteId: string) {
    setError("");
    try {
      await revokeStaffInvite(inviteId);
      setRevokingId(null);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleRoleChange(staffId: string, newRole: string) {
    setError("");
    try {
      await updateStaffRole(staffId, newRole);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  async function handleRemove(staffId: string) {
    setError("");
    try {
      await deleteStaff(staffId);
      setRemovingId(null);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }

  if (!isOwner) {
    return (
      <div className="max-w-3xl mx-auto px-8 py-12">
        <div className="text-[13.5px] text-ink-soft">Only an owner can manage staff accounts.</div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Staff</h1>
      <p className="text-[13.5px] text-ink-soft mb-8">
        Meridian&apos;s own internal team — separate from any customer&apos;s users, with its own
        login at /platform/login. <strong className="text-ink font-medium">Owner</strong> has full
        access, including managing staff and deleting tenants.{" "}
        <strong className="text-ink font-medium">Support</strong> can handle tenants and tickets but
        can&apos;t manage staff or delete a tenant.
      </p>

      {error && <div className="mb-6 text-[13px] text-red">{error}</div>}

      <form onSubmit={handleInvite} className="bg-panel border border-line rounded-[4px] p-5 mb-8">
        <p className="text-[12px] text-ink-soft mb-3">
          They&apos;ll get an email with a link to join — it expires in 24 hours if not accepted.
        </p>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="teammate@yourcompany.com"
            required
            className="text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50"
          />
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="text-[13px] border border-line rounded-[3px] px-2 py-1.5 bg-panel text-ink"
          >
            <option value="support">Support</option>
            <option value="owner">Owner</option>
          </select>
        </div>
        <div className="flex items-center justify-end">
          <button
            type="submit"
            disabled={busy}
            className="text-[13px] px-4 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
          >
            {busy ? "Sending…" : "Send invite"}
          </button>
        </div>
      </form>

      {pendingInvites.length > 0 && (
        <div className="mb-8">
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
                      onClick={() => handleRevokeInvite(inv.id)}
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

      <input
        type="text"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Search by email or role…"
        className="w-full mb-4 text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
      />

      <div className="flex flex-col gap-2">
        {filteredStaff.map((s) => (
          <div key={s.id} className="bg-panel border border-line rounded-[4px] px-4 py-3">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="text-[13.5px] text-ink truncate">{s.email}</div>
                <div className="text-[11.5px] text-ink-soft font-[family-name:var(--font-mono)] mt-0.5">
                  joined {new Date(s.created_at).toLocaleDateString()}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <select
                  value={s.role}
                  onChange={(e) => handleRoleChange(s.id, e.target.value)}
                  className="text-[12px] border border-line rounded-[3px] px-2 py-1 bg-panel text-ink"
                >
                  <option value="support">Support</option>
                  <option value="owner">Owner</option>
                </select>
                <button
                  onClick={() => setRemovingId(removingId === s.id ? null : s.id)}
                  className="text-[11.5px] text-red hover:opacity-70 transition-opacity"
                >
                  Remove
                </button>
              </div>
            </div>

            {removingId === s.id && (
              <div className="mt-3 pt-3 border-t border-line flex items-center justify-between gap-3">
                <div className="text-[12.5px] text-red">
                  Remove {s.email}&apos;s access to the internal admin panel? They can be re-added
                  later if needed.
                </div>
                <button
                  onClick={() => handleRemove(s.id)}
                  className="shrink-0 text-[12.5px] px-3 py-1.5 rounded-[3px] bg-red text-white hover:opacity-90 transition-opacity"
                >
                  Confirm remove
                </button>
              </div>
            )}
          </div>
        ))}
        {filteredStaff.length === 0 && (
          <div className="text-[13px] text-ink-soft">
            {staff.length === 0 ? "No staff yet." : "No staff match your search."}
          </div>
        )}
      </div>
    </div>
  );
}
