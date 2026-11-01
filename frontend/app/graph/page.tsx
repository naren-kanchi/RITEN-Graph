"use client";
import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { ActorCell, Card, DataState, DataTable, PageHead, Select, SyntheticTag } from "@/components/ui";
import { NetworkGraph } from "@/components/network";
import { useSession } from "@/components/shell";
import { fmt, qs, recordNavigation, Row, useApi } from "@/lib/api";

function GraphExplorer() {
  const { includeSynthetic } = useSession();
  const search = useSearchParams();
  const meta = useApi<Row>("/meta/filters");
  const [year, setYear] = useState("2023");
  const [selected, setSelected] = useState<string | null>(search.get("focus"));
  const [showTrade, setShowTrade] = useState(true);
  const [showRestrictions, setShowRestrictions] = useState(false);
  const [edge, setEdge] = useState<Row | null>(null);
  const [source, setSource] = useState("US");
  const [target, setTarget] = useState("CN");
  const [hops, setHops] = useState("3");
  const s = { year, include_synthetic: includeSynthetic };

  const network = useApi<Row>(`/graph/network${qs(s)}`);
  const hood = useApi<Row>(selected ? `/graph/neighborhood/${selected}${qs(s)}` : null);
  const edgeRows = useApi<Row>(edge ? `/graph/edges${qs({ source: edge.source, target: edge.target, ...s })}` : null);
  const sameEnds = source === target;
  const paths = useApi<Row[]>(sameEnds ? null : `/graph/paths${qs({ source, target, max_hops: hops, limit: 10, ...s })}`);
  const reroutes = useApi<Row>(sameEnds ? null : `/graph/reroutes${qs({ source, target, ...s })}`);
  useEffect(() => { if (selected) recordNavigation("graph_neighborhood", selected); }, [selected]);

  const actors = (meta.data?.actors ?? []).map((a: Row) => ({ value: a.actor_code, label: a.actor_name }));
  const countries = (meta.data?.actors ?? []).filter((a: Row) => a.has_country_profile).map((a: Row) => ({ value: a.actor_code, label: a.actor_name }));
  const direct = reroutes.data?.direct;

  return (
    <>
      <PageHead title="Graph explorer" actions={
        <Select label="Year" value={year} onChange={setYear} options={(meta.data?.years ?? []).map(String)} any={null} />}>
        Follow trade and restriction relationships from Neo4j. Each trade edge sums one year between two actors; click an edge to see its underlying records.
      </PageHead>
      {Number(year) >= 2024 && <div className="notice">Every trade edge in {year} is synthetic.</div>}
      <div className="grid-3">
        <Card title="Network" actions={
          <span className="row">
            <label className="check"><input type="checkbox" checked={showTrade} onChange={(e) => setShowTrade(e.target.checked)} /> Trade</label>
            <label className="check"><input type="checkbox" checked={showRestrictions} onChange={(e) => setShowRestrictions(e.target.checked)} /> Restrictions</label>
            {selected && <button className="btn ghost" onClick={() => setSelected(null)}>Clear selection</button>}
          </span>}>
          <div className="legend">
            <span><i className="line" style={{ borderColor: "var(--series-1)" }} />Trade, thicker means more value</span>
            <span><i className="dash" style={{ borderColor: "var(--series-2)" }} />Restrictions imposed that year</span>
            <span>Dashed ring: not a country</span>
          </div>
          <DataState loading={network.loading} error={network.error}>
            {network.data && (
              <NetworkGraph nodes={network.data.nodes} edges={network.data.edges} selected={selected}
                showTrade={showTrade} showRestrictions={showRestrictions}
                onSelect={(code) => { setSelected(code === selected ? null : code); setEdge(null); }} onEdge={setEdge} />
            )}
          </DataState>
        </Card>
        <Card title={hood.data ? hood.data.actor.name : "Selected actor"} note={selected ? <Link href={`/actors/${selected}`}>Open full profile</Link> : undefined}>
          {!selected && <div className="state">Select an actor to see its partners, restrictions and companies.</div>}
          {selected && (
            <DataState loading={hood.loading} error={hood.error}>
              {hood.data && (
                <div className="stack">
                  <h3>Trade partners</h3>
                  {hood.data.trade.length === 0 && <p className="muted small">None in view.</p>}
                  <DataTable rowKey={(r) => `${r.partner}-${r.direction}`} rows={hood.data.trade} columns={[
                    { key: "partner", label: "Partner", render: (r) => <button className="link" onClick={() => setSelected(r.partner)}>{r.name}</button> },
                    { key: "direction", label: "Flow" },
                    { key: "value", label: "Value", num: true, render: (r) => fmt.usdM(r.value_usd_millions) },
                  ]} />
                  <h3>Restrictions this year</h3>
                  {hood.data.restrictions.length === 0 && <p className="muted small">None in view.</p>}
                  <DataTable rowKey={(r) => `${r.partner}-${r.direction}`} rows={hood.data.restrictions} columns={[
                    { key: "partner", label: "Actor", render: (r) => <button className="link" onClick={() => setSelected(r.partner)}>{r.name}</button> },
                    { key: "direction", label: "Direction" },
                    { key: "measures", label: "Measures", num: true },
                    { key: "source_backed", label: "Source-backed", num: true },
                  ]} />
                  <h3>Headquartered companies</h3>
                  {hood.data.companies.length === 0
                    ? <p className="muted small">None.</p>
                    : <p>{hood.data.companies.map((c: Row, i: number) => <span key={c.company_key}>{i > 0 && ", "}<Link href={`/companies/${c.company_key}`}>{c.name}</Link></span>)}</p>}
                </div>
              )}
            </DataState>
          )}
        </Card>
      </div>
      {edge && (
        <Card title={`Records from ${edge.source} to ${edge.target}, ${year}`} actions={<button className="btn ghost" onClick={() => setEdge(null)}>Close</button>}>
          <DataState loading={edgeRows.loading} error={edgeRows.error}>
            {edgeRows.data && (edge.kind === "trade" ? (
              <DataTable rowKey={(r) => r.trade_id} rows={edgeRows.data.trade_flows} columns={[
                { key: "trade_id", label: "Trade ID" },
                { key: "quarter", label: "Quarter", render: (r) => `Q${r.quarter}` },
                { key: "hardware", label: "Hardware", render: (r) => fmt.label(r.hardware_type) },
                { key: "category", label: "Category" },
                { key: "value", label: "Value", num: true, render: (r) => fmt.usdM(r.value_usd_millions) },
                { key: "volume_units", label: "Units", num: true },
                { key: "restricted", label: "Control", render: (r) => r.restricted ? <span className="tag alert">Factor {r.restriction_factor}</span> : "None" },
                { key: "prov", label: "Provenance", render: (r) => <SyntheticTag synthetic={r.is_synthetic} /> },
              ]} />
            ) : (
              <DataTable rowKey={(r) => r.sanction_id} rows={edgeRows.data.restrictions} columns={[
                { key: "sanction_id", label: "Measure" },
                { key: "date", label: "Date" },
                { key: "type", label: "Type", render: (r) => fmt.label(r.type) },
                { key: "tech", label: "Technology", render: (r) => fmt.label(r.affected_technology) },
                { key: "severity", label: "Severity", num: true },
                { key: "source_reference", label: "Source" },
                { key: "prov", label: "Provenance", render: (r) => <SyntheticTag synthetic={r.is_synthetic} /> },
              ]} />
            ))}
          </DataState>
        </Card>
      )}
      <Card title="Route analysis" note="Could trade between two countries pass through a third, and is that route free of restrictions?">
        <div className="filters" style={{ marginBottom: 12 }}>
          <Select label="From" value={source} onChange={setSource} options={countries} any={null} />
          <Select label="To" value={target} onChange={setTarget} options={countries} any={null} />
          <Select label="Longest path" value={hops} onChange={setHops} options={[{ value: "1", label: "1 hop" }, { value: "2", label: "2 hops" }, { value: "3", label: "3 hops" }, { value: "4", label: "4 hops" }]} any={null} />
        </div>
        {sameEnds ? <div className="state">Choose two different countries.</div> : (
          <div className="grid-2">
            <div className="stack">
              <h3>Through one intermediary</h3>
              <DataState loading={reroutes.loading} error={reroutes.error}>
                {direct && (
                  <p className="small">
                    Direct: {direct.value_usd_millions === null ? "no recorded trade" : fmt.usdM(direct.value_usd_millions)}, with {direct.restrictions} measure{direct.restrictions === 1 ? "" : "s"} between them up to {year} ({direct.source_backed_restrictions} source-backed).
                  </p>
                )}
                {reroutes.data?.via.length === 0
                  ? <p className="muted small">No intermediary trades with both countries this year.</p>
                  : <DataTable rowKey={(r) => r.via} rows={reroutes.data?.via ?? []} columns={[
                    { key: "via", label: "Via", render: (r) => <ActorCell code={r.via} name={r.via_name} /> },
                    { key: "bottleneck", label: "Weakest hop", num: true, render: (r) => fmt.usdM(r.bottleneck_usd_millions) },
                    { key: "first_hop_restrictions", label: "First hop measures", num: true },
                    { key: "second_hop_restrictions", label: "Second hop measures", num: true },
                    { key: "state", label: "Route", render: (r) => r.unrestricted ? <span className="tag ok">Unrestricted</span> : <span className="tag alert">Restricted</span> },
                  ]} />}
                <p className="small muted">Counts measures imposed in either direction up to the selected year. Every measure in the source has status Active, so lifted measures cannot be excluded. This shows where trade is recorded, not that goods were actually rerouted.</p>
              </DataState>
            </div>
            <div className="stack">
              <h3>All paths, strongest first</h3>
              <DataState loading={paths.loading} error={paths.error} empty={paths.data?.length === 0} emptyText="No directed path within this many hops.">
                <DataTable rowKey={(r) => r.route.join("-")} rows={paths.data ?? []} columns={[
                  { key: "route", label: "Route", render: (r) => r.route.join(" → ") },
                  { key: "hops", label: "Hops", num: true },
                  { key: "bottleneck", label: "Weakest hop", num: true, render: (r) => fmt.usdM(r.bottleneck_usd_millions) },
                ]} />
              </DataState>
            </div>
          </div>
        )}
      </Card>
      <NetworkTable rows={network.data?.nodes ?? []} actors={actors.length} />
    </>
  );
}

function NetworkTable({ rows }: { rows: Row[]; actors: number }) {
  return (
    <Card title="Position in the network" note="A Cypher aggregation. Broker paths counts two-step trade routes that pass through the actor.">
      <DataTable rowKey={(r) => r.code} rows={rows} columns={[
        { key: "actor", label: "Actor", render: (r) => <ActorCell code={r.code} name={r.name} /> },
        { key: "exports", label: "Exports", num: true, render: (r) => fmt.usdM(r.exports_usd_millions) },
        { key: "imports", label: "Imports", num: true, render: (r) => fmt.usdM(r.imports_usd_millions) },
        { key: "broker_paths", label: "Broker paths", num: true },
        { key: "restrictions_received", label: "Measures received", num: true },
        { key: "restrictions_imposed", label: "Measures imposed", num: true },
      ]} />
    </Card>
  );
}

export default function GraphPage() {
  return <Suspense fallback={<div className="skeleton" />}><GraphExplorer /></Suspense>;
}
