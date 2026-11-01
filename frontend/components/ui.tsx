"use client";
import { ReactNode, useId } from "react";
import { Page, Row } from "@/lib/api";

export function PageHead({ title, children, actions }: { title: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {children && <p>{children}</p>}
      </div>
      {actions}
    </header>
  );
}

export function Card({ title, note, children, actions }: { title?: string; note?: ReactNode; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card-head">
          <div>
            {title && <h2>{title}</h2>}
            {note && <p>{note}</p>}
          </div>
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

/** One place for the loading, error and empty states every data view needs. */
export function DataState({ loading, error, empty, emptyText, children }: {
  loading: boolean; error: string | null; empty?: boolean; emptyText?: string; children: ReactNode;
}) {
  if (error) return <div className="state error" role="alert">{error}</div>;
  if (loading) return <div className="skeleton" role="status" aria-label="Loading" />;
  if (empty) return <div className="state">{emptyText ?? "Nothing matches these filters."}</div>;
  return <>{children}</>;
}

export function SyntheticTag({ synthetic }: { synthetic: boolean }) {
  return synthetic
    ? <span className="tag synthetic" title="The source flags this row as synthetic">Synthetic</span>
    : <span className="tag source" title="The source does not flag this row as synthetic">Source</span>;
}

export type Column = {
  key: string;
  label: string;
  num?: boolean;
  sort?: string;
  render?: (row: Row) => ReactNode;
};

export function DataTable({ columns, rows, rowKey, sort, direction, onSort }: {
  columns: Column[]; rows: Row[]; rowKey: (row: Row, index: number) => string | number;
  sort?: string; direction?: string; onSort?: (sort: string) => void;
}) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={c.num ? "num" : undefined}
                aria-sort={c.sort && sort === c.sort ? (direction === "asc" ? "ascending" : "descending") : undefined}>
                {c.sort && onSort
                  ? <button onClick={() => onSort(c.sort!)}>{c.label}{sort === c.sort ? (direction === "asc" ? " ▲" : " ▼") : ""}</button>
                  : c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={rowKey(row, index)}>
              {columns.map((c) => (
                <td key={c.key} className={c.num ? "num" : undefined}>{c.render ? c.render(row) : row[c.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Pager({ page, onOffset }: { page: Page; onOffset: (offset: number) => void }) {
  const end = Math.min(page.offset + page.limit, page.total);
  return (
    <div className="pager">
      <span>{page.total === 0 ? "No rows" : `${(page.offset + 1).toLocaleString()}–${end.toLocaleString()} of ${page.total.toLocaleString()}`}</span>
      <span className="row">
        <button className="btn ghost" disabled={page.offset === 0} onClick={() => onOffset(Math.max(0, page.offset - page.limit))}>Previous</button>
        <button className="btn ghost" disabled={end >= page.total} onClick={() => onOffset(page.offset + page.limit)}>Next</button>
      </span>
    </div>
  );
}

export function Select({ label, value, onChange, options, any = "All" }: {
  label: string; value: string; onChange: (value: string) => void;
  options: (string | { value: string; label: string })[]; any?: string | null;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(e) => onChange(e.target.value)}>
        {any !== null && <option value="">{any}</option>}
        {options.map((o) => {
          const item = typeof o === "string" ? { value: o, label: o.replaceAll("_", " ") } : o;
          return <option key={item.value} value={item.value}>{item.label}</option>;
        })}
      </select>
    </div>
  );
}

export function Tile({ value, label }: { value: ReactNode; label: string }) {
  return <div className="tile"><b>{value}</b><span>{label}</span></div>;
}

export function ActorCell({ code, name }: { code: string; name?: string }) {
  return <a href={`/actors/${code}`}>{name && name !== code ? name : code}</a>;
}
