"use client";
import { use, useEffect } from "react";
import Link from "next/link";
import { ActorCell, Card, DataState, DataTable, PageHead, SyntheticTag, Tile } from "@/components/ui";
import { HBars, Lines } from "@/components/charts";
import { AnnotationPanel } from "@/components/annotations";
import { useSession } from "@/components/shell";
import { fmt, qs, recordNavigation, Row, useApi } from "@/lib/api";

export default function ActorPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = use(params);
  const { includeSynthetic } = useSession();
  const profile = useApi<Row>(`/actors/${code}/profile${qs({ include_synthetic: includeSynthetic })}`);
  useEffect(() => recordNavigation("actor_profile", code), [code]);
  const d = profile.data;
  const observations: Row[] = d?.observations ?? [];
  const toPoints = (key: string) => observations.map((o) => ({ x: o.year, y: Number(o[key]), synthetic: o.is_synthetic }));

  return (
    <>
      <PageHead title={d?.actor.actor_name ?? code} actions={<Link className="small" href={`/graph?focus=${code}`}>Open in graph explorer</Link>}>
        {d ? [d.actor.region, d.actor.alliance_bloc].filter(Boolean).join(" · ") || d.actor.review_note : "Actor profile"}
      </PageHead>
      <DataState loading={profile.loading} error={profile.error}>
        {d && (
          <>
            {d.actor.actor_type !== "country" && <div className="notice">{d.actor.review_note}. This actor appears only in restriction records, so there are no trade or country-year figures.</div>}
            <div className="tiles">
              <Tile value={fmt.usdM(d.exposure.exports_usd_millions)} label="exports, 2015–2025" />
              <Tile value={fmt.usdM(d.exposure.imports_usd_millions)} label="imports, 2015–2025" />
              <Tile value={`${fmt.num(d.exposure.controlled_trade_share_pct)}%`} label="trade value under export control" />
              <Tile value={d.exposure.restrictions_received} label="measures received" />
              <Tile value={d.exposure.restrictions_imposed} label="measures imposed" />
            </div>
            {observations.length > 0 && (
              <div className="grid-2">
                <Card title="AI investment" note="Total and data-centre investment, USD billions.">
                  <Lines format={(v) => `$${fmt.num(v, 1)}bn`} height={220} series={[
                    { id: "total", label: "Total", color: "var(--series-1)", points: toPoints("total_ai_investment_usd_bn") },
                    { id: "dc", label: "Data centres", color: "var(--series-2)", points: toPoints("datacenter_investment_usd_bn") },
                  ]} />
                </Card>
                <Card title="AI grid stress" note="AI grid stress index from the energy file.">
                  <Lines format={(v) => fmt.num(v)} height={220} series={[
                    { id: "stress", label: "Grid stress", color: "var(--series-1)", points: toPoints("ai_grid_stress_index") },
                  ]} />
                </Card>
              </div>
            )}
            <div className="grid-2">
              {d.partners.length > 0 && (
                <Card title="Trade partners" note="Largest directed links across all years in view.">
                  <HBars format={(v) => fmt.usdM(v)} rows={d.partners.map((p: Row) => ({
                    key: `${p.partner}-${p.direction}`,
                    name: <><ActorCell code={p.partner} /> <span className="muted">{p.direction}</span></>,
                    value: p.total_value_usd_millions,
                  }))} />
                </Card>
              )}
              <Card title="Restrictions" note="Grouped by direction and type.">
                <DataState loading={false} error={null} empty={d.restrictions.length === 0} emptyText="No measures in view.">
                  <DataTable rowKey={(r) => `${r.direction}-${r.restriction_type}`} rows={d.restrictions} columns={[
                    { key: "direction", label: "Direction" },
                    { key: "restriction_type", label: "Type", render: (r) => fmt.label(r.restriction_type) },
                    { key: "measures", label: "Measures", num: true },
                    { key: "source_backed", label: "Source-backed", num: true },
                    { key: "avg_severity", label: "Avg. severity", num: true },
                  ]} />
                </DataState>
              </Card>
              {d.companies.length > 0 && (
                <Card title="Headquartered companies">
                  <DataTable rowKey={(r) => r.company_key} rows={d.companies} columns={[
                    { key: "company_name", label: "Company", render: (r) => <Link href={`/companies/${r.company_key}`}>{r.company_name}</Link> },
                    { key: "primary_domain", label: "Domain" },
                  ]} />
                </Card>
              )}
              <Card title="Notes"><AnnotationPanel entityType="actor" entityKey={code} /></Card>
            </div>
            {observations.length > 0 && (
              <Card title="Annual observations" note="Each risk score stays with its own source domain, because the domains disagree.">
                <DataTable rowKey={(r) => r.year} rows={[...observations].reverse()} columns={[
                  { key: "year", label: "Year" },
                  { key: "total_ai_investment_usd_bn", label: "AI investment", num: true, render: (r) => fmt.usdBn(r.total_ai_investment_usd_bn) },
                  { key: "national_supercomputer_projects", label: "Supercomputer projects", num: true },
                  { key: "ai_datacenter_energy_twh", label: "AI energy (TWh)", num: true, render: (r) => fmt.num(r.ai_datacenter_energy_twh) },
                  { key: "energy_constraint_level", label: "Grid constraint" },
                  { key: "gdp_usd_bn", label: "GDP", num: true, render: (r) => fmt.usdBn(r.gdp_usd_bn) },
                  { key: "budget_risk_score", label: "Budget risk", num: true },
                  { key: "energy_risk_score", label: "Energy risk", num: true },
                  { key: "macro_risk_score", label: "Macro risk", num: true },
                  { key: "is_synthetic", label: "Provenance", render: (r) => <SyntheticTag synthetic={r.is_synthetic} /> },
                ]} />
              </Card>
            )}
          </>
        )}
      </DataState>
    </>
  );
}
