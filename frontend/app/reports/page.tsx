"use client";
import { useState } from "react";
import Link from "next/link";
import { ActorCell, Card, Column, DataState, DataTable, PageHead, Select, SyntheticTag } from "@/components/ui";
import { useSession } from "@/components/shell";
import { fmt, qs, Row, useApi } from "@/lib/api";

const YEARS = Array.from({ length: 11 }, (_, i) => String(2015 + i));

type Report = {
  id: string; title: string; question: string; technique: string; path: string; usesYear?: boolean; usesMinMeasures?: boolean;
  rowKey: (r: Row) => string | number; columns: Column[];
};

const provenance: Column = { key: "prov", label: "Provenance", render: (r) => <SyntheticTag synthetic={r.is_synthetic} /> };

const REPORTS: Report[] = [
  {
    id: "links", title: "Top trade links", question: "Which directed links carry the most value, and how much of each exporter's trade do they represent?",
    technique: "CTE, GROUP BY, RANK and SUM window functions", path: "/reports/top-links", usesYear: true,
    rowKey: (r) => `${r.exporter_actor_code}-${r.importer_actor_code}`,
    columns: [
      { key: "rank", label: "Rank", num: true },
      { key: "ex", label: "Exporter", render: (r) => <ActorCell code={r.exporter_actor_code} name={r.exporter_name} /> },
      { key: "im", label: "Importer", render: (r) => <ActorCell code={r.importer_actor_code} name={r.importer_name} /> },
      { key: "v", label: "Value", num: true, render: (r) => fmt.usdM(r.total_value_usd_millions) },
      { key: "share_of_year_pct", label: "% of year", num: true },
      { key: "share_of_exporter_pct", label: "% of exporter", num: true },
      { key: "controlled_observations", label: "Controlled", num: true },
      provenance,
    ],
  },
  {
    id: "targets", title: "Restriction targets", question: "Who receives the most measures, and from how many different actors?",
    technique: "JOIN, GROUP BY, HAVING, COUNT DISTINCT", path: "/reports/restriction-targets", usesMinMeasures: true,
    rowKey: (r) => r.target_actor_code,
    columns: [
      { key: "t", label: "Target", render: (r) => <ActorCell code={r.target_actor_code} name={r.target_name} /> },
      { key: "measures", label: "Measures", num: true },
      { key: "source_backed", label: "Source-backed", num: true },
      { key: "distinct_imposers", label: "Imposing actors", num: true },
      { key: "avg_severity", label: "Avg. severity", num: true },
      { key: "i", label: "Est. impact", num: true, render: (r) => fmt.usdBn(r.est_impact_usd_bn) },
    ],
  },
  {
    id: "grid", title: "Grid pressure", question: "Which countries have above-average AI grid stress, and how much are they investing?",
    technique: "View with correlated subqueries", path: "/reports/grid-pressure", usesYear: true,
    rowKey: (r) => r.actor_code,
    columns: [
      { key: "a", label: "Country", render: (r) => <ActorCell code={r.actor_code} name={r.actor_name} /> },
      { key: "ai_grid_stress_index", label: "Grid stress", num: true },
      { key: "above_year_average", label: "Above average by", num: true },
      { key: "energy_constraint_level", label: "Constraint" },
      { key: "p", label: "Planned expansion", num: true, render: (r) => `${fmt.num(r.planned_expansion_gw, 1)} GW` },
      { key: "inv", label: "AI investment", num: true, render: (r) => fmt.usdBn(r.total_ai_investment_usd_bn) },
      provenance,
    ],
  },
  {
    id: "controls", title: "Hardware under control", question: "Which hardware types are most often under export control?",
    technique: "Aggregate FILTER, HAVING, partial index", path: "/reports/hardware-controls",
    rowKey: (r) => r.hardware_type,
    columns: [
      { key: "h", label: "Hardware", render: (r) => fmt.label(r.hardware_type) },
      { key: "hardware_category", label: "Category" },
      { key: "observations", label: "Observations", num: true },
      { key: "controlled_observations", label: "Controlled", num: true },
      { key: "controlled_pct", label: "% controlled", num: true },
      { key: "avg_factor_when_controlled", label: "Avg. factor", num: true },
    ],
  },
  {
    id: "mutual", title: "Mutual restrictions", question: "Which pairs of actors have each imposed measures on the other?",
    technique: "CTE and self-join", path: "/reports/mutual-restrictions",
    rowKey: (r) => `${r.actor_a}-${r.actor_b}`,
    columns: [
      { key: "a", label: "Actor A", render: (r) => <ActorCell code={r.actor_a} /> },
      { key: "b", label: "Actor B", render: (r) => <ActorCell code={r.actor_b} /> },
      { key: "a_on_b", label: "A on B", num: true },
      { key: "b_on_a", label: "B on A", num: true },
      { key: "source_backed", label: "Source-backed", num: true },
      { key: "max_severity", label: "Highest severity", num: true },
    ],
  },
  {
    id: "risk", title: "Company risk", question: "Which exposed companies sit in countries receiving the most measures?",
    technique: "JOIN with a scalar subquery", path: "/reports/company-risk", usesYear: true,
    rowKey: (r) => r.company_key,
    columns: [
      { key: "c", label: "Company", render: (r) => <Link href={`/companies/${r.company_key}`}>{r.company_name}</Link> },
      { key: "h", label: "HQ", render: (r) => <ActorCell code={r.hq_actor_code} /> },
      { key: "primary_domain", label: "Domain" },
      { key: "geopolitical_exposure", label: "Exposure" },
      { key: "f", label: "Sanction risk", render: (r) => r.sanction_risk_flag ? <span className="tag alert">Flagged</span> : "No" },
      { key: "hq_restrictions_received", label: "Measures on HQ", num: true },
      { key: "rv", label: "Revenue", num: true, render: (r) => fmt.usdBn(r.revenue_usd_bn) },
      provenance,
    ],
  },
];

export default function ReportsPage() {
  const { includeSynthetic } = useSession();
  const [active, setActive] = useState(REPORTS[0].id);
  const [year, setYear] = useState("2023");
  const [minMeasures, setMinMeasures] = useState("1");
  const report = REPORTS.find((r) => r.id === active)!;
  const result = useApi<Row[]>(`${report.path}${qs({
    include_synthetic: includeSynthetic, year: report.usesYear ? year : undefined, min_measures: report.usesMinMeasures ? minMeasures : undefined,
  })}`);

  return (
    <>
      <PageHead title="Reports">Analytical questions answered in PostgreSQL. Each one names the SQL technique it relies on.</PageHead>
      <div className="tabs" role="tablist">
        {REPORTS.map((r) => <button key={r.id} role="tab" aria-selected={r.id === active} onClick={() => setActive(r.id)}>{r.title}</button>)}
      </div>
      <Card title={report.question} note={<>SQL: {report.technique}</>} actions={
        <span className="filters">
          {report.usesYear && <Select label="Year" value={year} onChange={setYear} options={YEARS} any={null} />}
          {report.usesMinMeasures && (
            <label className="field">At least this many measures
              <input type="number" min={1} max={1000} value={minMeasures} onChange={(e) => setMinMeasures(e.target.value)} />
            </label>
          )}
        </span>}>
        <DataState loading={result.loading} error={result.error} empty={result.data?.length === 0} emptyText="No rows. A synthetic-only year needs synthetic rows switched on.">
          <DataTable rows={result.data ?? []} rowKey={report.rowKey} columns={report.columns} />
        </DataState>
      </Card>
    </>
  );
}
