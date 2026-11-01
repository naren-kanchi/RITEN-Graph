"use client";
import { FormEvent, useState } from "react";
import Link from "next/link";
import { Card, DataState, DataTable, PageHead, Select } from "@/components/ui";
import { useSession } from "@/components/shell";
import { api, fmt, Page, qs, Row, useApi } from "@/lib/api";

const ENTITY_LINK: Record<string, (key: string) => string | null> = {
  actor: (k) => `/actors/${k}`, company: (k) => `/companies/${k}`, trade_flow: () => null, restriction: () => null,
};

export default function CurationPage() {
  const { user } = useSession();
  const isAdmin = user?.role === "admin";
  const [statusFilter, setStatusFilter] = useState("");
  const unlinked = useApi<Row[]>("/aliases/unlinked-labels");
  const aliases = useApi<Page>(`/aliases${qs({ status: statusFilter })}`);
  const companies = useApi<Page>("/companies?limit=50");
  const linked = useApi<Row[]>("/reports/company-supplier-trade");
  const notes = useApi<Page>("/annotations?limit=20");

  const [form, setForm] = useState({ supplier_label_id: "", company_key: "", evidence: "", confidence: "medium" });
  const [formError, setFormError] = useState<string | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [reviewError, setReviewError] = useState<string | null>(null);
  const [noteForm, setNoteForm] = useState({ entity_type: "restriction", entity_key: "", note: "" });
  const [noteError, setNoteError] = useState<string | null>(null);

  function refresh() {
    aliases.reload();
    unlinked.reload();
    linked.reload();
  }

  async function propose(event: FormEvent) {
    event.preventDefault();
    setFormError(null);
    try {
      await api("/aliases", { method: "POST", body: { ...form, supplier_label_id: Number(form.supplier_label_id), company_key: Number(form.company_key) } });
      setForm({ supplier_label_id: "", company_key: "", evidence: "", confidence: "medium" });
      refresh();
    } catch (err: any) {
      setFormError(err.message);
    }
  }

  async function review(decision: "approved" | "rejected") {
    setReviewError(null);
    try {
      await api("/aliases/review", { method: "POST", body: { alias_ids: selected, decision } });
      setSelected([]);
      refresh();
    } catch (err: any) {
      setReviewError(err.message);
    }
  }

  async function remove(id: number) {
    setReviewError(null);
    try {
      await api(`/aliases/${id}`, { method: "DELETE" });
      setSelected((old) => old.filter((x) => x !== id));
      refresh();
    } catch (err: any) {
      setReviewError(err.message);
    }
  }

  async function addNote(event: FormEvent) {
    event.preventDefault();
    setNoteError(null);
    try {
      await api("/annotations", { method: "POST", body: noteForm });
      setNoteForm({ ...noteForm, entity_key: "", note: "" });
      notes.reload();
    } catch (err: any) {
      setNoteError(err.message);
    }
  }

  const items = aliases.data?.items ?? [];
  const pending = items.filter((a) => a.status === "proposed");

  return (
    <>
      <PageHead title="Curation">
        Source records are read-only. This is where you add your own reading of them: link a supplier label to a company with evidence, or leave a note. Links count in reports only after a different administrator approves them.
      </PageHead>
      <div className="grid-2">
        <Card title="Propose a supplier link" note="Names alone are not evidence. Say why this label is this company.">
          <form className="stack" onSubmit={propose}>
            <div className="filters">
              <Select label="Supplier label" value={form.supplier_label_id} onChange={(v) => setForm({ ...form, supplier_label_id: v })} any="Choose…"
                options={(unlinked.data ?? []).map((l) => ({ value: String(l.supplier_label_id), label: l.supplier_label }))} />
              <Select label="Company" value={form.company_key} onChange={(v) => setForm({ ...form, company_key: v })} any="Choose…"
                options={[...(companies.data?.items ?? [])].sort((a, b) => a.company_name.localeCompare(b.company_name)).map((c) => ({ value: String(c.company_key), label: c.company_name }))} />
              <Select label="Confidence" value={form.confidence} onChange={(v) => setForm({ ...form, confidence: v })} any={null} options={["low", "medium", "high"]} />
            </div>
            <label className="field">Evidence
              <textarea required minLength={10} maxLength={1000} value={form.evidence} onChange={(e) => setForm({ ...form, evidence: e.target.value })} />
            </label>
            <span><button className="btn" type="submit" disabled={!form.supplier_label_id || !form.company_key || form.evidence.trim().length < 10}>Propose link</button></span>
            {formError && <p className="error-text" role="alert">{formError}</p>}
          </form>
        </Card>
        <Card title="Trade through approved links">
          <DataState loading={linked.loading} error={linked.error} empty={linked.data?.length === 0} emptyText="No approved links yet.">
            <DataTable rowKey={(r) => `${r.company_key}-${r.supplier_label}`} rows={linked.data ?? []} columns={[
              { key: "c", label: "Company", render: (r) => <Link href={`/companies/${r.company_key}`}>{r.company_name}</Link> },
              { key: "supplier_label", label: "Label" },
              { key: "v", label: "Trade value", num: true, render: (r) => fmt.usdM(r.total_value_usd_millions) },
              { key: "observations", label: "Observations", num: true },
            ]} />
          </DataState>
        </Card>
      </div>

      <Card title="Proposals" actions={
        <Select label="Status" value={statusFilter} onChange={setStatusFilter} options={["proposed", "approved", "rejected"]} />}>
        <DataState loading={aliases.loading} error={aliases.error} empty={items.length === 0} emptyText="No proposals yet.">
          <DataTable rowKey={(r) => r.alias_id} rows={items} columns={[
            ...(isAdmin ? [{
              key: "pick", label: "", render: (r: Row) => r.status === "proposed" && (
                <input type="checkbox" aria-label={`Select proposal for ${r.supplier_label}`} checked={selected.includes(r.alias_id)}
                  onChange={(e) => setSelected((old) => e.target.checked ? [...old, r.alias_id] : old.filter((x) => x !== r.alias_id))} />
              ),
            }] : []),
            { key: "supplier_label", label: "Label" },
            { key: "company_name", label: "Company" },
            { key: "evidence", label: "Evidence" },
            { key: "confidence", label: "Confidence" },
            { key: "status", label: "Status", render: (r) => <span className={`tag ${r.status === "approved" ? "ok" : r.status === "rejected" ? "alert" : "source"}`}>{r.status}</span> },
            { key: "proposer", label: "Proposed by" },
            { key: "reviewer", label: "Reviewed by", render: (r) => r.reviewer ?? "–" },
            { key: "actions", label: "", render: (r) => (isAdmin || (r.proposed_by === user?.user_id && r.status === "proposed")) && <button className="link" onClick={() => remove(r.alias_id)}>Delete</button> },
          ]} />
        </DataState>
        {isAdmin && pending.length > 0 && (
          <div className="row" style={{ marginTop: 10 }}>
            <button className="btn" disabled={!selected.length} onClick={() => review("approved")}>Approve selected</button>
            <button className="btn danger" disabled={!selected.length} onClick={() => review("rejected")}>Reject selected</button>
            <span className="small muted">Applied together: if one fails, none change. You cannot review your own proposal.</span>
          </div>
        )}
        {reviewError && <p className="error-text" role="alert">{reviewError}</p>}
      </Card>

      <div className="grid-2">
        <Card title="Unlinked supplier labels" note="Largest trade value first. These stay out of company figures.">
          <DataState loading={unlinked.loading} error={unlinked.error}>
            <div style={{ maxHeight: 340, overflow: "auto" }}>
              <DataTable rowKey={(r) => r.supplier_label_id} rows={unlinked.data ?? []} columns={[
                { key: "supplier_label", label: "Label" },
                { key: "observations", label: "Observations", num: true },
                { key: "v", label: "Trade value", num: true, render: (r) => fmt.usdM(r.total_value_usd_millions) },
              ]} />
            </div>
          </DataState>
        </Card>
        <Card title="Recent notes">
          <form className="stack" onSubmit={addNote} style={{ marginBottom: 12 }}>
            <div className="filters">
              <Select label="Record type" value={noteForm.entity_type} onChange={(v) => setNoteForm({ ...noteForm, entity_type: v })} any={null}
                options={[{ value: "restriction", label: "Restriction" }, { value: "trade_flow", label: "Trade flow" }, { value: "actor", label: "Actor" }, { value: "company", label: "Company" }]} />
              <label className="field">Record ID
                <input type="text" required placeholder="For example SC0001" value={noteForm.entity_key} onChange={(e) => setNoteForm({ ...noteForm, entity_key: e.target.value.trim() })} />
              </label>
            </div>
            <label className="field">Note
              <textarea required maxLength={2000} value={noteForm.note} onChange={(e) => setNoteForm({ ...noteForm, note: e.target.value })} />
            </label>
            <span><button className="btn" type="submit" disabled={!noteForm.entity_key || !noteForm.note.trim()}>Save note</button></span>
            {noteError && <p className="error-text" role="alert">{noteError}</p>}
          </form>
          <DataState loading={notes.loading} error={notes.error} empty={notes.data?.items.length === 0} emptyText="No notes yet.">
            <DataTable rowKey={(r) => r.annotation_id} rows={notes.data?.items ?? []} columns={[
              { key: "record", label: "Record", render: (r) => {
                const href = ENTITY_LINK[r.entity_type]?.(r.entity_key);
                const text = `${fmt.label(r.entity_type)} ${r.entity_key}`;
                return href ? <Link href={href}>{text}</Link> : text;
              } },
              { key: "note", label: "Note" },
              { key: "author", label: "By" },
              { key: "del", label: "", render: (r) => (isAdmin || r.created_by === user?.user_id) && (
                <button className="link" onClick={() => api(`/annotations/${r.annotation_id}`, { method: "DELETE" }).then(notes.reload).catch((e) => setNoteError(e.message))}>Delete</button>
              ) },
            ]} />
          </DataState>
        </Card>
      </div>
    </>
  );
}
