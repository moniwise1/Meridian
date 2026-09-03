"use client";

import { useEffect, useState } from "react";
import { listUsers, updateUserRowScope, type TeamUser } from "@/lib/api";
import { loadSession } from "@/lib/auth";

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
  const [error, setError] = useState("");
  const [editingUser, setEditingUser] = useState<string | null>(null);
  const isAdmin = loadSession()?.role === "admin";

  function refresh() {
    listUsers()
      .then(setUsers)
      .catch((e) => setError(e.message));
  }

  useEffect(refresh, []);

  if (!isAdmin) {
    return (
      <div className="max-w-3xl mx-auto px-8 py-12">
        <div className="text-[13.5px] text-ink-soft">Only admins can manage teammates.</div>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Team</h1>
      <p className="text-[13.5px] text-ink-soft mb-8">
        Row-level access restricts which rows a teammate&apos;s questions can see, by column value —
        e.g. a regional manager scoped to <code>region=South-East</code> never sees other regions&apos;
        data, regardless of what they ask. An empty scope is unrestricted.
      </p>

      {error && <div className="mb-4 text-[13px] text-red">{error}</div>}

      <div className="flex flex-col gap-3">
        {users.map((u) => (
          <div key={u.id} className="bg-panel border border-line rounded-[4px] px-4 py-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[13.5px] text-ink">{u.email}</div>
                <div className="text-[12px] text-ink-soft capitalize mt-0.5">{u.role}</div>
              </div>
              <div className="flex items-center gap-2">
                <span className="text-[11px] px-2 py-0.5 rounded-[3px] bg-line text-ink-soft font-[family-name:var(--font-mono)]">
                  {Object.keys(u.row_scope).length === 0 ? "Unrestricted" : rowScopeToText(u.row_scope)}
                </span>
                <button
                  onClick={() => setEditingUser(editingUser === u.id ? null : u.id)}
                  className="text-[11.5px] text-teal hover:text-teal-deep transition-colors"
                >
                  {editingUser === u.id ? "Close" : "Row access"}
                </button>
              </div>
            </div>
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
