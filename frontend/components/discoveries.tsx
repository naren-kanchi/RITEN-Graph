"use client";
import { DataState } from "@/components/ui";
import { fmt, qs, Row, useApi } from "@/lib/api";

type Props = {
  edge: Row;
  year: string;
  includeSynthetic: boolean;
  /** Edges drawn in the network this year, so a hop opens only when it has records to show. */
  edges: Row[];
  active: string[] | null;
  onExplore: (suggestion: Row) => void;
  onHop: (edge: Row) => void;
};

function hopLabel(hop: Row) {
  return hop.kind === "trade"
    ? `${hop.source} → ${hop.target} ${fmt.usdM(hop.value_usd_millions)}${hop.controlled_observations ? `, ${hop.controlled_observations} controlled` : ""}`
    : `${hop.source} restricts ${hop.target}, ${hop.measures} in force`;
}

/** Interesting indirect connections around the selected edge, found and explained by /graph/discoveries. */
export function Discoveries({ edge, year, includeSynthetic, edges, active, onExplore, onHop }: Props) {
  const found = useApi<Row>(`/graph/discoveries${qs({ source: edge.source, target: edge.target, year, include_synthetic: includeSynthetic })}`);
  const drawn = (hop: Row) => edges.some((e) => e.kind === hop.kind && e.source === hop.source && e.target === hop.target);

  return (
    <section className="card discoveries" aria-labelledby="discoveries-title">
      <div className="card-head">
        <div>
          <h2 id="discoveries-title">You might also look at</h2>
          <p>Indirect connections between {edge.source} and {edge.target} in {year} that stand out, ranked by how unexpected they are.</p>
        </div>
      </div>
      <DataState loading={found.loading} error={found.error} empty={found.data?.suggestions.length === 0}
        emptyText="No third actor connects these two in an unusual way this year.">
        <ol className="suggestions">
          {(found.data?.suggestions ?? []).map((s: Row) => {
            const isActive = active?.join() === s.route.join();
            return (
              <li key={s.via} className="suggestion" aria-current={isActive || undefined}>
                <div className="row">
                  <b>{s.route.join(" → ")}</b>
                  <span className="tag source">{s.title}</span>
                  {s.synthetic_only && <span className="tag synthetic" title="Every fact behind this suggestion is synthetic">Synthetic</span>}
                </div>
                <p>{s.explanation}</p>
                {s.also.length > 0 && <p className="small muted">Also: {s.also.map((a: Row) => a.explanation).join(" ")}</p>}
                <div className="row">
                  <button className="btn ghost" onClick={() => onExplore(s)} aria-pressed={isActive}>
                    {isActive ? "Shown on the network" : `Explore via ${s.via_name}`}
                  </button>
                  <span className="chips" aria-label="Facts behind this suggestion">
                    {s.evidence.map((hop: Row) => drawn(hop)
                      ? <button key={`${hop.kind}-${hop.source}-${hop.target}`} className="chip" onClick={() => onHop(hop)} title="Open the records behind this edge">{hopLabel(hop)}</button>
                      : <span key={`${hop.kind}-${hop.source}-${hop.target}`} className="chip static">{hopLabel(hop)}</span>)}
                  </span>
                </div>
              </li>
            );
          })}
        </ol>
        {found.data && (
          <p className="small muted">
            Tested {found.data.considered} actors tied to both ends. Hubs that trade with nearly everyone count for less,
            restrictions count measures in force up to {year}, and suggestions resting only on synthetic rows rank lower.
          </p>
        )}
      </DataState>
    </section>
  );
}
