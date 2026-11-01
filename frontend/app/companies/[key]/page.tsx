"use client";
import { use } from "react";
import { ActorCell, Card, DataState, DataTable, PageHead, SyntheticTag } from "@/components/ui";
import { Lines } from "@/components/charts";
import { AnnotationPanel } from "@/components/annotations";
import { fmt, Row, useApi } from "@/lib/api";

export default function CompanyPage({ params }: { params: Promise<{ key: string }> }) {
  const { key } = use(params);
  const detail = useApi<Row>(`/companies/${key}`);
  const d = detail.data;
  const history: Row[] = d?.history ?? [];
  const points = (field: string) => history.map((h) => ({ x: h.year, y: Number(h[field]), synthetic: h.is_synthetic }));

  return (
    <>
      <PageHead title={d?.company.company_name ?? "Company"}>
        {d ? `${d.company.primary_domain} · ${d.company.strategic_focus} · founded ${d.company.year_founded}` : ""}
      </PageHead>
      <DataState loading={detail.loading} error={detail.error}>
        {d && (
          <>
            <p>Headquarters: <ActorCell code={d.company.hq_actor_code} name={d.company.hq_name} /></p>
            <div className="grid-2">
              <Card title="Revenue and R&D" note="USD billions.">
                <Lines format={(v) => `$${fmt.num(v, 1)}bn`} height={220} series={[
                  { id: "rev", label: "Revenue", color: "var(--series-1)", points: points("revenue_usd_bn") },
                  { id: "rd", label: "R&D", color: "var(--series-2)", points: points("rd_expenditure_usd_bn") },
                ]} />
              </Card>
              <Card title="Trade linked through approved aliases" note="Only supplier labels an administrator has approved for this company.">
                <DataState loading={false} error={null} empty={d.approved_supplier_trade.length === 0} emptyText="No approved supplier labels. Propose one on the Curation page.">
                  <DataTable rowKey={(r) => r.supplier_label} rows={d.approved_supplier_trade} columns={[
                    { key: "supplier_label", label: "Label" },
                    { key: "value", label: "Trade value", num: true, render: (r) => fmt.usdM(r.total_value_usd_millions) },
                    { key: "observations", label: "Observations", num: true },
                    { key: "controlled_observations", label: "Controlled", num: true },
                  ]} />
                </DataState>
              </Card>
            </div>
            <div className="grid-3">
              <Card title="Annual profiles" note="The source profile ID is kept for traceability.">
                <DataTable rowKey={(r) => r.source_profile_id} rows={[...history].reverse()} columns={[
                  { key: "year", label: "Year" },
                  { key: "source_profile_id", label: "Source ID" },
                  { key: "rev", label: "Revenue", num: true, render: (r) => fmt.usdBn(r.revenue_usd_bn) },
                  { key: "rd", label: "R&D", num: true, render: (r) => fmt.usdBn(r.rd_expenditure_usd_bn) },
                  { key: "emp", label: "Employees", num: true, render: (r) => fmt.num(r.employees, 0) },
                  { key: "geopolitical_exposure", label: "Exposure" },
                  { key: "risk", label: "Sanction risk", render: (r) => r.sanction_risk_flag ? <span className="tag alert">Flagged</span> : "No" },
                  { key: "prov", label: "Provenance", render: (r) => r.predates_founding ? <span className="tag alert">Before founding</span> : <SyntheticTag synthetic={r.is_synthetic} /> },
                ]} />
              </Card>
              <Card title="Notes"><AnnotationPanel entityType="company" entityKey={key} /></Card>
            </div>
          </>
        )}
      </DataState>
    </>
  );
}
