"use client";
import { FormEvent, useState } from "react";
import { Card, DataState, DataTable, PageHead, Select } from "@/components/ui";
import { useSession } from "@/components/shell";
import { api, fmt, Page, Row, useApi } from "@/lib/api";

export default function AdminPage() {
  const { user } = useSession();
  const reconciliation = useApi<Row>("/admin/reconciliation");
  const batches = useApi<Row[]>("/admin/import-batches");
  const quality = useApi<Row>("/admin/data-quality?limit=1");
  const audit = useApi<Page>("/admin/audit-log?limit=20");
  const users = useApi<Row[]>("/admin/users");
  const metrics = useApi<Row>("/admin/metrics");
  const [form, setForm] = useState({ username: "", password: "", role: "analyst" });
  const [formError, setFormError] = useState<string | null>(null);
  const [syncState, setSyncState] = useState<string | null>(null);

  if (reconciliation.error?.includes("Administrator")) {
    return (
      <>
        <PageHead title="Administration" />
        <div className="state error" role="alert">This page needs the Administrator role.</div>
      </>
    );
  }

  async function createUser(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    try {
      await api("/admin/users", { method: "POST", body: form });
      setForm({ username: "", password: "", role: "analyst" });
      users.reload();
    } catch (err: any) {
      setFormError(err.message);
    }
  }

  async function sync() {
    setSyncState("Rebuilding the graph from PostgreSQL…");
    try {
      await api("/admin/graph/sync", { method: "POST" });
      setSyncState("Graph rebuilt and reconciled.");
      reconciliation.reload();
    } catch (err: any) {
      setSyncState(err.message);
    }
  }

  const rec = reconciliation.data;
  const routes = Object.entries(metrics.data?.routes ?? {}).map(([route, m]: [string, any]) => ({ route, ...m })).sort((a, b) => b.count - a.count).slice(0, 12);

  return (
    <>
      <PageHead title="Administration">Data imports, cross-database reconciliation, audit history and accounts.</PageHead>
      <div className="grid-2">
        <Card title="Reconciliation" note="PostgreSQL row counts against the audited expectation." actions={<button className="btn ghost" onClick={sync}>Rebuild graph</button>}>
          {syncState && <p className="small" role="status" style={{ marginBottom: 8 }}>{syncState}</p>}
          <DataState loading={reconciliation.loading} error={reconciliation.error}>
            {rec && (
              <DataTable rowKey={(r) => r.table} rows={Object.entries(rec.relational).map(([table, v]: [string, any]) => ({ table, ...v }))} columns={[
                { key: "table", label: "Table", render: (r) => <code>{r.table}</code> },
                { key: "actual", label: "Rows", num: true },
                { key: "expected", label: "Expected", num: true },
                { key: "state", label: "", render: (r) => r.actual === r.expected ? <span className="tag ok">Match</span> : <span className="tag alert">Mismatch</span> },
              ]} />
            )}
          </DataState>
        </Card>
        <Card title="Neo4j projection" note="Nodes and relationships loaded from PostgreSQL.">
          <DataState loading={reconciliation.loading} error={reconciliation.error}>
            {rec && (
              <>
                <p style={{ marginBottom: 8 }}>{rec.graph_mismatches.length === 0 ? <span className="tag ok">All counts match</span> : <span className="tag alert">{rec.graph_mismatches.join("; ")}</span>}</p>
                <DataTable rowKey={(r) => r.name} rows={[
                  ...Object.entries(rec.graph.nodes).map(([name, n]) => ({ name, kind: "Node", n })),
                  ...Object.entries(rec.graph.relationships).map(([name, n]) => ({ name, kind: "Relationship", n })),
                ]} columns={[
                  { key: "name", label: "Name", render: (r) => <code>{r.name}</code> },
                  { key: "kind", label: "Kind" },
                  { key: "n", label: "Count", num: true, render: (r) => Number(r.n).toLocaleString() },
                ]} />
              </>
            )}
          </DataState>
        </Card>
      </div>
      <div className="grid-2">
        <Card title="Import batches" note="A failed batch changes nothing and keeps its reasons.">
          <DataState loading={batches.loading} error={batches.error}>
            <DataTable rowKey={(r) => r.batch_id} rows={batches.data ?? []} columns={[
              { key: "batch_id", label: "Batch", num: true },
              { key: "started", label: "Started", render: (r) => fmt.date(r.started_at) },
              { key: "status", label: "Status", render: (r) => <span className={`tag ${r.status === "succeeded" ? "ok" : "alert"}`}>{r.status}</span> },
              { key: "errors", label: "Errors", num: true },
              { key: "caveats", label: "Caveats", num: true },
              { key: "v", label: "Data version", render: (r) => <code>{r.data_version ?? "–"}</code> },
            ]} />
          </DataState>
        </Card>
        <Card title="Data quality" note={quality.data ? `Batch ${quality.data.batch_id}` : undefined}>
          <DataState loading={quality.loading} error={quality.error}>
            <DataTable rowKey={(r) => r.rule} rows={quality.data?.summary ?? []} columns={[
              { key: "rule", label: "Rule", render: (r) => fmt.label(r.rule) },
              { key: "source_file", label: "File" },
              { key: "occurrences", label: "Records", num: true },
            ]} />
          </DataState>
        </Card>
      </div>
      <Card title="Audit log" note="Written by a database trigger on every change to notes and supplier links.">
        <DataState loading={audit.loading} error={audit.error} empty={audit.data?.items.length === 0} emptyText="No changes recorded yet.">
          <DataTable rowKey={(r) => r.audit_id} rows={audit.data?.items ?? []} columns={[
            { key: "when", label: "When", render: (r) => fmt.date(r.logged_at) },
            { key: "username", label: "User", render: (r) => r.username ?? "–" },
            { key: "table_name", label: "Table", render: (r) => <code>{r.table_name}</code> },
            { key: "operation", label: "Change" },
            { key: "row_pk", label: "Row", num: true },
            { key: "after", label: "Summary", render: (r) => <span className="small">{(r.new_row ?? r.old_row)?.note ?? (r.new_row ?? r.old_row)?.status ?? ""}</span> },
          ]} />
        </DataState>
      </Card>
      <div className="grid-2">
        <Card title="Accounts">
          <form className="filters" onSubmit={createUser} style={{ marginBottom: 12 }}>
            <label className="field">Username
              <input type="text" required pattern="[A-Za-z0-9_.\-]{3,40}" autoComplete="off" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
            </label>
            <label className="field">Password (10+ characters)
              <input type="password" required minLength={10} autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </label>
            <Select label="Role" value={form.role} onChange={(v) => setForm({ ...form, role: v })} any={null} options={[{ value: "analyst", label: "Analyst" }, { value: "admin", label: "Administrator" }]} />
            <button className="btn" type="submit">Create</button>
          </form>
          {formError && <p className="error-text" role="alert">{formError}</p>}
          <DataState loading={users.loading} error={users.error}>
            <DataTable rowKey={(r) => r.user_id} rows={users.data ?? []} columns={[
              { key: "username", label: "User" },
              { key: "role", label: "Role" },
              { key: "active", label: "Status", render: (r) => r.is_active ? <span className="tag ok">Active</span> : <span className="tag alert">Deactivated</span> },
              { key: "act", label: "", render: (r) => r.user_id !== user?.user_id && (
                <button className="link" onClick={() => api(`/admin/users/${r.user_id}`, { method: "PATCH", body: { is_active: !r.is_active } }).then(users.reload).catch((e) => setFormError(e.message))}>
                  {r.is_active ? "Deactivate" : "Reactivate"}
                </button>
              ) },
            ]} />
          </DataState>
        </Card>
        <Card title="API metrics" note={metrics.data ? `Cache: ${metrics.data.cache.hit} hits, ${metrics.data.cache.miss} misses, ${metrics.data.cache.bypass} bypassed. Since the API started.` : undefined}>
          <DataState loading={metrics.loading} error={metrics.error} empty={routes.length === 0}>
            <DataTable rowKey={(r) => r.route} rows={routes} columns={[
              { key: "route", label: "Route", render: (r) => <code>{r.route}</code> },
              { key: "count", label: "Requests", num: true },
              { key: "p50_ms", label: "p50 ms", num: true },
              { key: "p95_ms", label: "p95 ms", num: true },
              { key: "errors", label: "5xx", num: true },
            ]} />
          </DataState>
        </Card>
      </div>
    </>
  );
}
