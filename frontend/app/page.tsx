"use client";
import { ActorCell, Card, DataState, DataTable, PageHead, SyntheticTag, Tile } from "@/components/ui";
import { Columns, HBars, ProvenanceLegend } from "@/components/charts";
import { useSession } from "@/components/shell";
import { fmt, qs, Row, useApi } from "@/lib/api";

const CAVEAT_TEXT: Record<string, string> = {
  macro_semiconductor_exports_differ_from_trade_file: "Macro semiconductor exports differ from the trade file by more than 25%, so the two are shown as separate measures.",
  energy_mix_misses_100_by_over_1_point: "Energy mix shares miss 100% by more than one point.",
  supplier_label_has_no_exact_company_match: "Supplier labels have no exact company match and stay unlinked until reviewed.",
  energy_mix_share_is_negative: "Energy mix rows contain a small negative share.",
  company_profile_predates_founding: "Company profiles are dated before the company was founded.",
  eu_imposing_region_inconsistent: "EU measures list a region other than Europe.",
  all_sanctions_status_active: "Every restriction has status Active, so status cannot separate current from lifted measures.",
  budget_and_macro_risk_scores_differ: "Budget and macro risk scores differ, so each stays with its own domain.",
};

export default function OverviewPage() {
  const { includeSynthetic } = useSession();
  const s = { include_synthetic: includeSynthetic };
  const provenance = useApi<Row>("/meta/provenance");
  const tradeYears = useApi<Row[]>(`/trade/summary${qs({ group_by: "year", ...s })}`);
  const restrictionYears = useApi<Row[]>(`/restrictions/summary${qs({ group_by: "year", ...s })}`);
  const links = useApi<Row[]>(`/reports/top-links${qs({ year: 2023, limit: 8, ...s })}`);
  const domains: Row[] = provenance.data?.domains ?? [];
  const total = domains.reduce((n, d) => n + d.total, 0);
  const synthetic = domains.reduce((n, d) => n + d.synthetic, 0);
  const restrictions = domains.find((d) => d.domain === "Restrictions");

  return (
    <>
      <PageHead title="Overview">
        How semiconductor trade, technology restrictions and national AI infrastructure relate across 12 countries. Trade and country data are source-backed through 2023; 2024–25 is synthetic.
      </PageHead>
      <DataState loading={provenance.loading} error={provenance.error}>
        <div className="tiles">
          <Tile value={total.toLocaleString()} label="source records" />
          <Tile value={total ? `${((synthetic / total) * 100).toFixed(1)}%` : "–"} label="flagged synthetic" />
          <Tile value={restrictions ? (restrictions.total - restrictions.synthetic).toLocaleString() : "–"} label={`of ${restrictions?.total ?? "–"} restrictions are source-backed`} />
          <Tile value="2023" label="last fully source-backed year" />
        </div>
      </DataState>

      <div className="grid-2">
        <Card title="Trade value by year" note="All hardware types, in the trade file only.">
          <DataState loading={tradeYears.loading} error={tradeYears.error} empty={tradeYears.data?.length === 0}>
            <ProvenanceLegend />
            <Columns format={(v) => fmt.usdM(v)}
              rows={(tradeYears.data ?? []).map((r) => {
                const isSynthetic = r.synthetic_observations > 0;
                return { key: r.key, value: isSynthetic ? 0 : r.total_value_usd_millions, synthetic: isSynthetic ? r.total_value_usd_millions : 0 };
              })} />
            <details>
              <summary>Table view</summary>
              <DataTable rowKey={(r) => r.key} rows={tradeYears.data ?? []} columns={[
                { key: "key", label: "Year" },
                { key: "total_value_usd_millions", label: "Value", num: true, render: (r) => fmt.usdM(r.total_value_usd_millions) },
                { key: "observations", label: "Observations", num: true },
                { key: "synthetic_observations", label: "Synthetic", num: true },
              ]} />
            </details>
          </DataState>
        </Card>
        <Card title="Restrictions by year" note="Most measures are synthetic. Source-backed measures start in 2018.">
          <DataState loading={restrictionYears.loading} error={restrictionYears.error} empty={restrictionYears.data?.length === 0}>
            <ProvenanceLegend />
            <Columns format={(v) => fmt.num(v, 0)}
              rows={(restrictionYears.data ?? []).map((r) => ({ key: r.key, value: r.source_backed, synthetic: r.synthetic }))} />
            <details>
              <summary>Table view</summary>
              <DataTable rowKey={(r) => r.key} rows={restrictionYears.data ?? []} columns={[
                { key: "key", label: "Year" },
                { key: "source_backed", label: "Source-backed", num: true },
                { key: "synthetic", label: "Synthetic", num: true },
                { key: "avg_severity", label: "Average severity", num: true },
              ]} />
            </details>
          </DataState>
        </Card>
      </div>

      <div className="grid-2">
        <Card title="Largest trade links, 2023">
          <DataState loading={links.loading} error={links.error} empty={links.data?.length === 0}>
            <HBars format={(v) => fmt.usdM(v)} rows={(links.data ?? []).map((r) => ({
              key: `${r.exporter_actor_code}-${r.importer_actor_code}`,
              name: <><ActorCell code={r.exporter_actor_code} /> to <ActorCell code={r.importer_actor_code} /></>,
              value: r.total_value_usd_millions,
            }))} />
          </DataState>
        </Card>
        <Card title="Data provenance" note="Rows flagged synthetic by the source, per domain.">
          <DataState loading={provenance.loading} error={provenance.error}>
            <DataTable rowKey={(r) => r.domain} rows={domains} columns={[
              { key: "domain", label: "Domain" },
              { key: "total", label: "Rows", num: true, render: (r) => r.total.toLocaleString() },
              { key: "synthetic", label: "Synthetic", num: true, render: (r) => `${r.synthetic.toLocaleString()} (${((r.synthetic / r.total) * 100).toFixed(1)}%)` },
              { key: "years", label: "Source-backed years", render: (r) => `${r.first_source_year}–${r.last_source_year}` },
            ]} />
          </DataState>
        </Card>
      </div>

      <Card title="What to keep in mind" note="Found by the import checks. The source values are kept as delivered.">
        <DataState loading={provenance.loading} error={provenance.error}>
          <DataTable rowKey={(r) => r.rule} rows={provenance.data?.caveats ?? []} columns={[
            { key: "occurrences", label: "Records", num: true },
            { key: "rule", label: "Caveat", render: (r) => CAVEAT_TEXT[r.rule] ?? r.rule },
          ]} />
        </DataState>
      </Card>
      <p className="small muted"><SyntheticTag synthetic /> marks rows the source flags as synthetic. Use the switch in the sidebar to leave them out everywhere.</p>
    </>
  );
}
