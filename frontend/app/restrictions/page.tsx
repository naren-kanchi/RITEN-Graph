"use client";
import { FormEvent, useEffect, useState } from "react";
import { ActorCell, Card, DataState, DataTable, PageHead, Pager, Select, SyntheticTag } from "@/components/ui";
import { Columns, HBars, ProvenanceLegend } from "@/components/charts";
import { useSession } from "@/components/shell";
import { fmt, Page, qs, Row, useApi } from "@/lib/api";

const GROUPS = [
  { value: "year", label: "Year" }, { value: "type", label: "Type" }, { value: "imposer", label: "Imposing actor" },
  { value: "target", label: "Target actor" }, { value: "technology", label: "Technology" }, { value: "severity", label: "Severity" },
];
const EMPTY = { year_from: "", year_to: "", imposer: "", target: "", restriction_type: "", technology: "", min_severity: "", q: "" };

export default function RestrictionsPage() {
  const { includeSynthetic } = useSession();
  const meta = useApi<Row>("/meta/filters");
  const [f, setF] = useState(EMPTY);
  const [search, setSearch] = useState("");
  const [groupBy, setGroupBy] = useState("year");
  const [sort, setSort] = useState("date");
  const [direction, setDirection] = useState("desc");
  const [offset, setOffset] = useState(0);
  const set = (key: keyof typeof EMPTY) => (value: string) => setF((old) => ({ ...old, [key]: value }));
  const filters = { ...f, include_synthetic: includeSynthetic };
  useEffect(() => setOffset(0), [f, sort, direction, includeSynthetic]);

  const summary = useApi<Row[]>(`/restrictions/summary${qs({ ...filters, group_by: groupBy })}`);
  const list = useApi<Page>(`/restrictions${qs({ ...filters, sort, direction, limit: 25, offset })}`);
  const years = (meta.data?.years ?? []).map(String);
  const actors = (meta.data?.actors ?? []).map((a: Row) => ({ value: a.actor_code, label: a.actor_name }));
  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    set("q")(search.trim());
    if (search.trim()) setSort("relevance");
  };
  const onSort = (next: string) => {
    if (next === sort) setDirection((d) => (d === "asc" ? "desc" : "asc"));
    else { setSort(next); setDirection("desc"); }
  };

  return (
    <>
      <PageHead title="Restrictions">Sanctions and export controls between actors. 945 of the 987 measures are synthetic, so check the provenance column before drawing conclusions.</PageHead>
      <Card>
        <div className="stack">
          <form className="row" onSubmit={onSubmit} role="search">
            <label className="field" style={{ flex: 1, minWidth: 220 }}>Search descriptions, technologies and sources
              <input type="search" value={search} placeholder='For example: "section 301" or lithography' onChange={(e) => setSearch(e.target.value)} />
            </label>
            <button className="btn" type="submit" style={{ alignSelf: "flex-end" }}>Search</button>
          </form>
          <div className="filters">
            <Select label="From" value={f.year_from} onChange={set("year_from")} options={years} any="Any" />
            <Select label="To" value={f.year_to} onChange={set("year_to")} options={years} any="Any" />
            <Select label="Imposed by" value={f.imposer} onChange={set("imposer")} options={actors} />
            <Select label="Target" value={f.target} onChange={set("target")} options={actors} />
            <Select label="Type" value={f.restriction_type} onChange={set("restriction_type")} options={meta.data?.restriction_types ?? []} />
            <Select label="Technology" value={f.technology} onChange={set("technology")} options={meta.data?.technologies ?? []} />
            <Select label="Minimum severity" value={f.min_severity} onChange={set("min_severity")} options={["1", "2", "3", "4", "5"]} any="Any" />
            <button className="btn ghost" onClick={() => { setF(EMPTY); setSearch(""); setSort("date"); }}>Clear</button>
          </div>
        </div>
      </Card>
      <Card title="Measures" actions={<Select label="Group by" value={groupBy} onChange={setGroupBy} options={GROUPS} any={null} />}>
        <DataState loading={summary.loading} error={summary.error} empty={summary.data?.length === 0}>
          <ProvenanceLegend />
          {groupBy === "year" || groupBy === "severity" ? (
            <Columns format={(v) => fmt.num(v, 0)} rows={(summary.data ?? []).map((r) => ({ key: r.key, value: r.source_backed, synthetic: r.synthetic }))} />
          ) : (
            <HBars format={(v) => fmt.num(v, 0)} rows={(summary.data ?? []).slice(0, 14).map((r) => ({ key: r.key, name: fmt.label(r.key), value: r.source_backed, synthetic: r.synthetic }))} />
          )}
        </DataState>
      </Card>
      <Card title="Records">
        <DataState loading={list.loading} error={list.error} empty={list.data?.total === 0}>
          {list.data && (
            <>
              <DataTable rows={list.data.items} rowKey={(r) => r.sanction_id} sort={sort} direction={direction} onSort={onSort} columns={[
                { key: "date", label: "Date", sort: "date", render: (r) => r.date_implemented },
                { key: "imposer", label: "Imposed by", render: (r) => <ActorCell code={r.imposing_actor_code} name={r.imposing_name} /> },
                { key: "target", label: "Target", render: (r) => <ActorCell code={r.target_actor_code} name={r.target_name} /> },
                { key: "type", label: "Type", render: (r) => fmt.label(r.restriction_type) },
                { key: "tech", label: "Technology", render: (r) => fmt.label(r.affected_technology) },
                { key: "description", label: "Description" },
                { key: "severity", label: "Severity", num: true, sort: "severity", render: (r) => r.severity_level },
                { key: "impact", label: "Est. impact", num: true, sort: "impact", render: (r) => fmt.usdBn(r.economic_impact_usd_bn_est) },
                { key: "source_reference", label: "Source", render: (r) => <span className="small">{r.source_reference}</span> },
                { key: "prov", label: "Provenance", render: (r) => <SyntheticTag synthetic={r.is_synthetic} /> },
              ]} />
              <Pager page={list.data} onOffset={setOffset} />
            </>
          )}
        </DataState>
      </Card>
    </>
  );
}
