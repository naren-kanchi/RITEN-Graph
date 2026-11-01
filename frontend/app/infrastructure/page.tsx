"use client";
import { useMemo, useState } from "react";
import { ActorCell, Card, DataState, DataTable, PageHead, Select, SyntheticTag } from "@/components/ui";
import { LineSeries, Lines, SERIES_COLORS } from "@/components/charts";
import { useSession } from "@/components/shell";
import { fmt, qs, Row, useApi } from "@/lib/api";

const METRICS = [
  { value: "total_ai_investment_usd_bn", label: "Total AI investment (USD bn)" },
  { value: "datacenter_investment_usd_bn", label: "Data-centre investment (USD bn)" },
  { value: "semiconductor_subsidies_usd_bn", label: "Semiconductor subsidies (USD bn)" },
  { value: "national_supercomputer_projects", label: "Supercomputer projects" },
  { value: "ai_datacenter_energy_twh", label: "AI data-centre energy (TWh)" },
  { value: "pct_grid_used_by_ai", label: "Grid used by AI (%)" },
  { value: "ai_grid_stress_index", label: "AI grid stress index" },
  { value: "total_grid_capacity_gw", label: "Grid capacity (GW)" },
  { value: "gdp_usd_bn", label: "GDP (USD bn)" },
  { value: "tech_sector_pct_gdp", label: "Tech sector (% of GDP)" },
  { value: "dedollarization_index", label: "De-dollarization index" },
  { value: "budget_risk_score", label: "Risk score, budget file" },
  { value: "energy_risk_score", label: "Risk score, energy file" },
  { value: "macro_risk_score", label: "Risk score, macro file" },
  { value: "budget_sovereignty_index", label: "AI sovereignty, budget file" },
  { value: "macro_sovereignty_index", label: "AI sovereignty, macro file" },
];
const MAX_SERIES = SERIES_COLORS.length;

export default function InfrastructurePage() {
  const { includeSynthetic } = useSession();
  const [year, setYear] = useState("2023");
  const [metric, setMetric] = useState(METRICS[0].value);
  // Each country keeps its colour slot while selected, so removing one never repaints the others.
  const [slots, setSlots] = useState<(string | null)[]>(["US", "CN", "IN", null]);
  const codes = slots.filter(Boolean) as string[];

  const table = useApi<Row[]>(`/infrastructure/compare${qs({ year, include_synthetic: includeSynthetic })}`);
  const trend = useApi<Row[]>(codes.length ? `/infrastructure/trend${qs({ metric, codes: codes.join(","), include_synthetic: includeSynthetic })}` : null);
  const meta = useApi<Row>("/meta/filters");
  const countries: Row[] = (meta.data?.actors ?? []).filter((a: Row) => a.has_country_profile);

  function toggle(code: string) {
    setSlots((old) => {
      const at = old.indexOf(code);
      if (at >= 0) return old.map((s, i) => (i === at ? null : s));
      const free = old.indexOf(null);
      return free >= 0 ? old.map((s, i) => (i === free ? code : s)) : old;
    });
  }

  const series: LineSeries[] = useMemo(() => codes.map((code) => {
    const points = (trend.data ?? []).filter((r) => r.actor_code === code);
    return {
      id: code, label: points[0]?.actor_name ?? code, color: SERIES_COLORS[slots.indexOf(code)],
      points: points.map((p) => ({ x: p.year, y: Number(p.value), synthetic: p.is_synthetic })),
    };
  }).filter((s) => s.points.length > 0), [trend.data, slots]); // eslint-disable-line

  return (
    <>
      <PageHead title="AI infrastructure">
        National AI spending beside the grid that has to power it. These are country-year totals from the budget, energy and macro files, not individual data-centre records.
      </PageHead>
      <Card title="Trend" actions={<Select label="Measure" value={metric} onChange={setMetric} options={METRICS} any={null} />}
        note={`Choose up to ${MAX_SERIES} countries.`}>
        <div className="chips" style={{ marginBottom: 12 }}>
          {countries.map((c) => {
            const slot = slots.indexOf(c.actor_code);
            return (
              <button key={c.actor_code} className="chip" aria-pressed={slot >= 0} disabled={slot < 0 && codes.length >= MAX_SERIES} onClick={() => toggle(c.actor_code)}>
                {slot >= 0 && <i style={{ width: 8, height: 8, borderRadius: 2, background: SERIES_COLORS[slot], display: "inline-block" }} />}
                {c.actor_name}
              </button>
            );
          })}
        </div>
        <DataState loading={trend.loading} error={trend.error} empty={series.length === 0} emptyText="Choose at least one country.">
          <Lines series={series} format={(v) => fmt.num(v, Math.abs(v) < 10 ? 2 : 0)} />
        </DataState>
      </Card>
      <Card title="Country comparison" actions={<Select label="Year" value={year} onChange={setYear} options={(meta.data?.years ?? []).map(String)} any={null} />}
        note="Budget, energy and macro risk scores are separate measures. They are never merged.">
        <DataState loading={table.loading} error={table.error} empty={table.data?.length === 0} emptyText="This year is entirely synthetic. Turn on synthetic rows in the sidebar to see it.">
          <DataTable rowKey={(r) => r.actor_code} rows={table.data ?? []} columns={[
            { key: "actor", label: "Country", render: (r) => <ActorCell code={r.actor_code} name={r.actor_name} /> },
            { key: "inv", label: "AI investment", num: true, render: (r) => fmt.usdBn(r.total_ai_investment_usd_bn) },
            { key: "dc", label: "Data centres", num: true, render: (r) => fmt.usdBn(r.datacenter_investment_usd_bn) },
            { key: "sub", label: "Chip subsidies", num: true, render: (r) => fmt.usdBn(r.semiconductor_subsidies_usd_bn) },
            { key: "national_supercomputer_projects", label: "Supercomputers", num: true },
            { key: "twh", label: "AI energy (TWh)", num: true, render: (r) => fmt.num(r.ai_datacenter_energy_twh) },
            { key: "ai_grid_stress_index", label: "Grid stress", num: true },
            { key: "energy_constraint_level", label: "Constraint" },
            { key: "gdp", label: "GDP", num: true, render: (r) => fmt.usdBn(r.gdp_usd_bn) },
            { key: "budget_risk_score", label: "Budget risk", num: true },
            { key: "energy_risk_score", label: "Energy risk", num: true },
            { key: "macro_risk_score", label: "Macro risk", num: true },
            { key: "prov", label: "Provenance", render: (r) => <SyntheticTag synthetic={r.is_synthetic} /> },
          ]} />
        </DataState>
      </Card>
    </>
  );
}
