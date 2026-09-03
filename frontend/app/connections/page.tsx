"use client";

import { useEffect, useState } from "react";
import { listConnections, createConnection, updateConnectionPolicy, type Connection } from "@/lib/api";
import { loadSession } from "@/lib/auth";

const DB_KINDS = [
  { value: "postgres", label: "PostgreSQL", defaultPort: "5432" },
  { value: "mysql", label: "MySQL / MariaDB", defaultPort: "3306" },
  { value: "mssql", label: "SQL Server", defaultPort: "1433" },
];

const emptyForm = {
  name: "",
  kind: "postgres",
  host: "",
  port: "5432",
  database: "",
  username: "",
  password: "",
  tables: "",
};

export default function ConnectionsPage() {
  const [connections, setConnections] = useState<Connection[]>([]);
  const [form, setForm] = useState(emptyForm);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [editingPolicy, setEditingPolicy] = useState<string | null>(null);
  const isAdmin = loadSession()?.role === "admin";

  function refresh() {
    listConnections().then(setConnections).catch((e) => setError(e.message));
  }

  useEffect(refresh, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const tableAllowlist = form.tables.split(",").map((t) => t.trim()).filter(Boolean);
      await createConnection({
        name: form.name, kind: form.kind, host: form.host, port: Number(form.port),
        database: form.database, username: form.username, password: form.password,
        table_allowlist: tableAllowlist, column_policy: {},
      });
      setForm(emptyForm);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-8 py-12">
      <h1 className="text-[22px] font-medium text-ink tracking-tight mb-1.5">Data sources</h1>
      <p className="text-[13.5px] text-ink-soft mb-8">
        Connect a database with a dedicated read-only credential. The connection is verified —
        not just assumed — to be incapable of writing before it&apos;s saved.
      </p>

      <div className="flex flex-col gap-3 mb-10">
        {connections.map((c) => (
          <div key={c.id} className="bg-panel border border-line rounded-[4px] px-4 py-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[13.5px] text-ink">{c.name}</div>
                <div className="text-[12px] text-ink-soft font-[family-name:var(--font-mono)] mt-0.5">
                  {c.kind} · {c.host} / {c.database}
                </div>
              </div>
              <div className="flex items-center gap-2">
                <span
                  className={`text-[11px] px-2 py-0.5 rounded-[3px] ${
                    c.verified_read_only ? "bg-teal-deep text-white" : "bg-line text-ink-soft"
                  }`}
                >
                  {c.verified_read_only ? "Read-only verified" : "Unverified"}
                </span>
                {isAdmin && (
                  <button
                    onClick={() => setEditingPolicy(editingPolicy === c.id ? null : c.id)}
                    className="text-[11.5px] text-teal hover:text-teal-deep transition-colors"
                  >
                    {editingPolicy === c.id ? "Close" : "Policy"}
                  </button>
                )}
              </div>
            </div>
            {editingPolicy === c.id && <PolicyEditor connection={c} onSaved={refresh} />}
          </div>
        ))}
        {connections.length === 0 && <div className="text-[13px] text-ink-soft">No data sources connected yet.</div>}
      </div>

      <form onSubmit={handleSubmit} className="bg-panel border border-line rounded-[4px] p-5">
        <div className="text-[13px] text-ink-soft mb-4">Connect a PostgreSQL, MySQL, or SQL Server database</div>

        <div className="mb-3">
          <label className="flex flex-col gap-1">
            <span className="text-[12px] text-ink-soft">Database type</span>
            <select
              value={form.kind}
              onChange={(e) => {
                const kind = e.target.value;
                const preset = DB_KINDS.find((k) => k.value === kind);
                setForm({ ...form, kind, port: preset?.defaultPort ?? form.port });
              }}
              className="text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink focus:outline-none focus:ring-1 focus:ring-teal"
            >
              {DB_KINDS.map((k) => (
                <option key={k.value} value={k.value}>
                  {k.label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Field label="Connection name" value={form.name} onChange={(v) => setForm({ ...form, name: v })} placeholder="Sales warehouse" />
          <Field label="Database" value={form.database} onChange={(v) => setForm({ ...form, database: v })} placeholder="demo_company" />
          <Field label="Host" value={form.host} onChange={(v) => setForm({ ...form, host: v })} placeholder="127.0.0.1" />
          <Field label="Port" value={form.port} onChange={(v) => setForm({ ...form, port: v })} placeholder="5432" />
          <Field label="Read-only username" value={form.username} onChange={(v) => setForm({ ...form, username: v })} placeholder="analytics_readonly" />
          <Field label="Password" value={form.password} onChange={(v) => setForm({ ...form, password: v })} placeholder="••••••••" type="password" />
        </div>
        <div className="mt-3">
          <Field
            label="Authorized tables (comma-separated, optional)"
            value={form.tables}
            onChange={(v) => setForm({ ...form, tables: v })}
            placeholder="sales, customers"
            required={false}
          />
        </div>

        {error && <div className="mt-3 text-[13px] text-red">{error}</div>}

        <div className="flex justify-end mt-4">
          <button
            type="submit"
            disabled={submitting}
            className="text-[13px] px-4 py-1.5 rounded-[3px] bg-teal-deep text-white disabled:opacity-40 hover:bg-teal transition-colors"
          >
            {submitting ? "Verifying…" : "Connect"}
          </button>
        </div>
      </form>
    </div>
  );
}

function columnPolicyToText(policy: Record<string, string[]>): string {
  return Object.entries(policy)
    .map(([table, cols]) => `${table}=${cols.join(",")}`)
    .join("\n");
}

function parseColumnPolicyText(text: string): Record<string, string[]> {
  const policy: Record<string, string[]> = {};
  for (const line of text.split("\n")) {
    const [table, colsPart] = line.split("=");
    const tableName = table?.trim();
    if (!tableName || colsPart === undefined) continue;
    const cols = colsPart.split(",").map((c) => c.trim()).filter(Boolean);
    if (cols.length) policy[tableName] = cols;
  }
  return policy;
}

function PolicyEditor({ connection, onSaved }: { connection: Connection; onSaved: () => void }) {
  const [tables, setTables] = useState(connection.table_allowlist.join(", "));
  const [columnPolicyText, setColumnPolicyText] = useState(columnPolicyToText(connection.column_policy));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setSaving(true);
    setError("");
    try {
      const list = tables.split(",").map((t) => t.trim()).filter(Boolean);
      await updateConnectionPolicy(connection.id, {
        table_allowlist: list,
        column_policy: parseColumnPolicyText(columnPolicyText),
      });
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
          Authorized tables — only these are visible to the agent for this connection.
        </div>
        <input
          value={tables}
          onChange={(e) => setTables(e.target.value)}
          placeholder="sales, customers"
          className="text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 w-full"
        />
      </div>

      <div>
        <div className="text-[12px] text-ink-soft mb-2">
          Column policy (optional) — one table per line, as <code>table=col1,col2</code>. Tables left
          out are unrestricted at the column level.
        </div>
        <textarea
          value={columnPolicyText}
          onChange={(e) => setColumnPolicyText(e.target.value)}
          placeholder={"sales=region,product,revenue,month"}
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

function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  required = true,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
  required?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[12px] text-ink-soft">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        required={required}
        className="text-[13px] border border-line rounded-[3px] px-2.5 py-1.5 bg-panel text-ink placeholder:text-ink-soft/50 focus:outline-none focus:ring-1 focus:ring-teal"
      />
    </label>
  );
}
