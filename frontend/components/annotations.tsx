"use client";
import { FormEvent, useState } from "react";
import { api, fmt, Page, qs, Row, useApi } from "@/lib/api";
import { DataState } from "./ui";
import { useSession } from "./shell";

/** Notes attached to a record. Source facts stay read-only; this is where people add their reading of them. */
export function AnnotationPanel({ entityType, entityKey }: { entityType: string; entityKey: string }) {
  const { user } = useSession();
  const notes = useApi<Page>(`/annotations${qs({ entity_type: entityType, entity_key: entityKey, limit: 50 })}`);
  const [text, setText] = useState("");
  const [editing, setEditing] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function run(action: () => Promise<unknown>) {
    setError(null);
    try {
      await action();
      notes.reload();
      return true;
    } catch (err: any) {
      setError(err.message);
      return false;
    }
  }

  async function add(event: FormEvent) {
    event.preventDefault();
    const ok = await run(() => api("/annotations", { method: "POST", body: { entity_type: entityType, entity_key: entityKey, note: text } }));
    if (ok) setText("");
  }

  const canEdit = (note: Row) => user && (user.role === "admin" || user.user_id === note.created_by);

  return (
    <div className="stack">
      <DataState loading={notes.loading} error={notes.error} empty={notes.data?.items.length === 0} emptyText="No notes on this record yet.">
        {notes.data?.items.map((note) => (
          <div key={note.annotation_id} style={{ borderBottom: "1px solid var(--grid)", paddingBottom: 8 }}>
            {editing === note.annotation_id ? (
              <form className="stack" onSubmit={async (e) => {
                e.preventDefault();
                if (await run(() => api(`/annotations/${note.annotation_id}`, { method: "PATCH", body: { note: editText } }))) setEditing(null);
              }}>
                <textarea aria-label="Edit note" value={editText} onChange={(e) => setEditText(e.target.value)} />
                <span className="row">
                  <button className="btn" type="submit">Save</button>
                  <button className="btn ghost" type="button" onClick={() => setEditing(null)}>Cancel</button>
                </span>
              </form>
            ) : (
              <>
                <p style={{ whiteSpace: "pre-wrap" }}>{note.note}</p>
                <span className="small muted row">
                  {note.author} · {fmt.date(note.updated_at)}
                  {canEdit(note) && (
                    <>
                      <button className="link" onClick={() => { setEditing(note.annotation_id); setEditText(note.note); }}>Edit</button>
                      <button className="link" onClick={() => run(() => api(`/annotations/${note.annotation_id}`, { method: "DELETE" }))}>Delete</button>
                    </>
                  )}
                </span>
              </>
            )}
          </div>
        ))}
      </DataState>
      <form className="stack" onSubmit={add}>
        <label className="field">Add a note
          <textarea value={text} maxLength={2000} onChange={(e) => setText(e.target.value)} />
        </label>
        <span><button className="btn" type="submit" disabled={!text.trim()}>Save note</button></span>
        {error && <p className="error-text" role="alert">{error}</p>}
      </form>
    </div>
  );
}
