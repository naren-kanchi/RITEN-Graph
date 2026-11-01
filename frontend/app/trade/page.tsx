"use client";
import { useEffect, useState } from "react";
import { ActorCell, Card, DataState, DataTable, PageHead, Pager, Select, SyntheticTag } from "@/components/ui";
import { Columns, HBars, ProvenanceLegend } from "@/components/charts";
import { useSession } from "@/components/shell";
import { fmt, Page, qs, Row, useApi } from "@/lib/api";

const GROUPS = [
  { value: "year", label: "Year" }, { value: "hardware_type", label: "Hardware type" }, { value: "exporter", label: "Exporter" },
  { value: "importer", label: "Importer" }, { value: "route", label: "Route" }, { value: "supplier", label: "Supplier label" },
];
const EMPTY = { year_from: "", year_to: "", quarter: "", exporter: "", importer: "", hardware_type: "", category: "", route: "", controlled: "" };

export default function TradePage() {
  const { includeSynthetic } = useSession();
  const meta = useApi<Row>("/meta/filters");
  const [f, setF] = useState(EMPTY);
  const [groupBy, setGroupBy] = useState("year");
  const [sort, setSort] = useState("period");
  const [direction, setDirection] = useState("desc");
  const [offset, setOffset] = useState(0);
  const set = (key: keyof typeof EMPTY) => (value: string) => setF((old) => ({ ...old, [key]: value }));
  const filters = { ...f, include_synthetic: includeSynthetic };
  useEffect(() => setOffset(0), [f, sort, direction, includeSynthetic]);

  const summary = useApi<Row[]>(`/trade/summary${qs({ ...filters, group_by: groupBy })}`);
  const list = useApi<Page>(`/trade${qs({ ...filters, sort, direction, limit: 25, offset })}`);
  const years = (meta.data?.years ?? []).map(String);
  const countries = (meta.data?.actors ?? []).filter((a: Row) => a.has_country_profile).map((a: Row) => ({ value: a.actor_code, label: a.actor_name }));
  const onSort = (next: string) => {
    if (next === sort) setDirection((d) => (d === "asc" ? "desc" : "asc"));
    else { setSort(next); setDirection("desc"); }
  };

  return (
    <>
      <PageHead title="Trade flows">Quarterly observations of semiconductor hardware moving between countries. Supplier names are source labels, not verified company links.</PageHead>
      <Card>
        <div className="filters">
          <Select label="From" value={f.year_from} onChange={set("year_from")} options={years} any="Any" />
          <Select label="To" value={f.year_to} onChange={set("year_to")} options={years} any="Any" />
          <Select label="Quarter" value={f.quarter} onChange={set("quarter")} options={["1", "2", "3", "4"]} />
          <Select label="Exporter" value={f.exporter} onChange={set("exporter")} options={countries} />
          <Select label="Importer" value={f.importer} onChange={set("importer")} options={countries} />
          <Select label="Hardware type" value={f.hardware_type} onChange={set("hardware_type")} options={(meta.data?.hardware_types ?? []).map((h: Row) => h.hardware_type)} />
          <Select label="Category" value={f.category} onChange={set("category")} options={["Advanced", "Standard"]} />
          <Select label="Route" value={f.route} onChange={set("route")} options={meta.data?.routes ?? []} />
          <Select label="Export control" value={f.controlled} onChange={set("controlled")} options={[{ value: "true", label: "Applied" }, { value: "false", label: "Not applied" }]} />
          <button className="btn ghost" onClick={() => setF(EMPTY)}>Clear</button>
        </div>
      </Card>
      <Card title="Trade value" actions={<Select label="Group by" value={groupBy} onChange={setGroupBy} options={GROUPS} any={null} />}>
        <DataState loading={summary.loading} error={summary.error} empty={summary.data?.length === 0}>
          <ProvenanceLegend />
          {groupBy === "year" ? (
            <Columns format={(v) => fmt.usdM(v)} rows={(summary.data ?? []).map((r) => {
              const share = r.observations ? r.synthetic_observations / r.observations : 0;
              return { key: r.key, value: r.total_value_usd_millions * (1 - share), synthetic: r.total_value_usd_millions * share };
            })} />
          ) : (
            <HBars format={(v) => fmt.usdM(v)} rows={(summary.data ?? []).slice(0, 14).map((r) => {
              const share = r.observations ? r.synthetic_observations / r.observations : 0;
              return {
                key: r.key, name: fmt.label(r.key), value: r.total_value_usd_millions * (1 - share), synthetic: r.total_value_usd_millions * share,
                detail: `${fmt.usdM(r.total_value_usd_millions)}, ${r.observations} observations, ${r.controlled_observations} under control, ${r.synthetic_observations} synthetic`,
              };
            })} />
          )}
          {groupBy !== "year" && <p className="small muted" style={{ marginTop: 8 }}>The synthetic part is estimated from each group's share of synthetic observations.</p>}
        </DataState>
      </Card>
      <Card title="Observations">
        <DataState loading={list.loading} error={list.error} empty={list.data?.total === 0}>
          {list.data && (
            <>
              <DataTable rows={list.data.items} rowKey={(r) => r.trade_id} sort={sort} direction={direction} onSort={onSort} columns={[
                { key: "year_quarter", label: "Period", sort: "period" },
                { key: "exporter", label: "Exporter", sort: "exporter", render: (r) => <ActorCell code={r.exporter_actor_code} name={r.exporter_name} /> },
                { key: "importer", label: "Importer", sort: "importer", render: (r) => <ActorCell code={r.importer_actor_code} name={r.importer_name} /> },
                { key: "hardware", label: "Hardware", sort: "hardware", render: (r) => fmt.label(r.hardware_type) },
                { key: "supplier_label", label: "Supplier label" },
                { key: "value", label: "Value", num: true, sort: "value", render: (r) => fmt.usdM(r.trade_value_usd_millions) },
                { key: "volume", label: "Units", num: true, sort: "volume", render: (r) => fmt.num(r.volume_units, 0) },
                { key: "control", label: "Control", render: (r) => r.export_control_applied ? <span className="tag alert">Factor {r.restriction_factor}</span> : "None" },
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
