"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { ActorCell, Card, DataState, DataTable, PageHead, Pager, Select, SyntheticTag } from "@/components/ui";
import { useSession } from "@/components/shell";
import { fmt, Page, qs, Row, useApi } from "@/lib/api";

export default function CompaniesPage() {
  const { includeSynthetic } = useSession();
  const meta = useApi<Row>("/meta/filters");
  const [f, setF] = useState({ year: "2023", hq: "", domain: "", sanction_risk: "", exposure: "", q: "" });
  const [offset, setOffset] = useState(0);
  const set = (key: keyof typeof f) => (value: string) => setF((old) => ({ ...old, [key]: value }));
  useEffect(() => setOffset(0), [f, includeSynthetic]);
  const list = useApi<Page>(`/companies${qs({ ...f, include_synthetic: includeSynthetic, limit: 25, offset })}`);
  const countries = (meta.data?.actors ?? []).filter((a: Row) => a.has_country_profile).map((a: Row) => ({ value: a.actor_code, label: a.actor_name }));

  return (
    <>
      <PageHead title="Companies">22 companies with one profile per year. The source changes its company ID every year, so these are grouped under a stable internal key.</PageHead>
      <Card>
        <div className="filters">
          <label className="field">Name
            <input type="search" value={f.q} onChange={(e) => set("q")(e.target.value)} />
          </label>
          <Select label="Year" value={f.year} onChange={set("year")} options={(meta.data?.years ?? []).map(String)} any={null} />
          <Select label="Headquarters" value={f.hq} onChange={set("hq")} options={countries} />
          <Select label="Domain" value={f.domain} onChange={set("domain")} options={meta.data?.domains ?? []} />
          <Select label="Exposure" value={f.exposure} onChange={set("exposure")} options={["Medium", "High"]} />
          <Select label="Sanction risk" value={f.sanction_risk} onChange={set("sanction_risk")} options={[{ value: "true", label: "Flagged" }, { value: "false", label: "Not flagged" }]} />
        </div>
      </Card>
      <Card>
        <DataState loading={list.loading} error={list.error} empty={list.data?.total === 0} emptyText="No companies match. A synthetic-only year needs synthetic rows switched on.">
          {list.data && (
            <>
              <DataTable rows={list.data.items} rowKey={(r) => r.company_key} columns={[
                { key: "company_name", label: "Company", render: (r) => <Link href={`/companies/${r.company_key}`}>{r.company_name}</Link> },
                { key: "hq", label: "Headquarters", render: (r) => <ActorCell code={r.hq_actor_code} name={r.hq_name} /> },
                { key: "primary_domain", label: "Domain" },
                { key: "rev", label: "Revenue", num: true, render: (r) => fmt.usdBn(r.revenue_usd_bn) },
                { key: "rd", label: "R&D", num: true, render: (r) => fmt.usdBn(r.rd_expenditure_usd_bn) },
                { key: "emp", label: "Employees", num: true, render: (r) => fmt.num(r.employees, 0) },
                { key: "geopolitical_exposure", label: "Exposure" },
                { key: "risk", label: "Sanction risk", render: (r) => r.sanction_risk_flag ? <span className="tag alert">Flagged</span> : "No" },
                { key: "prov", label: "Provenance", render: (r) => r.predates_founding ? <span className="tag alert" title={`Founded ${r.year_founded}`}>Before founding</span> : <SyntheticTag synthetic={r.is_synthetic} /> },
              ]} />
              <Pager page={list.data} onOffset={setOffset} />
            </>
          )}
        </DataState>
      </Card>
    </>
  );
}
