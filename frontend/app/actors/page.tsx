"use client";
import { ActorCell, Card, DataState, DataTable, PageHead, SyntheticTag } from "@/components/ui";
import { useSession } from "@/components/shell";
import { fmt, qs, Row, useApi } from "@/lib/api";

const TYPE_LABEL: Record<string, string> = {
  country: "Country", regional_organization: "Regional organization", global_scope: "Global scope marker", unresolved_source_actor: "Unresolved source code",
};

export default function ActorsPage() {
  const { includeSynthetic } = useSession();
  const network = useApi<Row>(`/graph/network${qs({ year: 2023, include_synthetic: includeSynthetic })}`);
  return (
    <>
      <PageHead title="Actors">
        Twelve countries have annual data. The EU, GLOBAL, IR and RU appear only in restriction records, so they have no country-year figures. IR and RU are shown as the source gives them.
      </PageHead>
      <Card title="All actors, 2023" note="Partner counts and restriction counts come from the Neo4j network query.">
        <DataState loading={network.loading} error={network.error}>
          <DataTable rowKey={(r) => r.code} rows={network.data?.nodes ?? []} columns={[
            { key: "name", label: "Actor", render: (r) => <ActorCell code={r.code} name={r.name} /> },
            { key: "type", label: "Type", render: (r) => TYPE_LABEL[r.type] ?? r.type },
            { key: "exports", label: "Exports", num: true, render: (r) => fmt.usdM(r.exports_usd_millions) },
            { key: "imports", label: "Imports", num: true, render: (r) => fmt.usdM(r.imports_usd_millions) },
            { key: "export_partners", label: "Export partners", num: true },
            { key: "import_partners", label: "Import partners", num: true },
            { key: "restrictions_imposed", label: "Measures imposed", num: true },
            { key: "restrictions_received", label: "Measures received", num: true },
          ]} />
        </DataState>
      </Card>
      {includeSynthetic && <p className="small muted"><SyntheticTag synthetic /> Restriction counts include synthetic measures. Switch them off in the sidebar to see source-backed counts only.</p>}
    </>
  );
}
