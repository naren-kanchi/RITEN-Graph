"use client";
import { useMemo, useState } from "react";
import { fmt, Row } from "@/lib/api";

type Props = {
  nodes: Row[];
  edges: Row[];
  selected: string | null;
  /** Actor codes of an explored route; when set, only edges along it stay bright. */
  route?: string[] | null;
  showTrade: boolean;
  showRestrictions: boolean;
  onSelect: (code: string) => void;
  onEdge: (edge: Row) => void;
};

const SIZE = 620;
const CENTER = SIZE / 2;
const RING = 245;

/** Actors sit on a fixed ring, so a node stays in place across years and filters. */
function positions(nodes: Row[]) {
  const ordered = [...nodes].sort((a, b) => a.code.localeCompare(b.code));
  const map = new Map<string, { x: number; y: number }>();
  ordered.forEach((node, i) => {
    const angle = (i / ordered.length) * Math.PI * 2 - Math.PI / 2;
    map.set(node.code, { x: CENTER + RING * Math.cos(angle), y: CENTER + RING * Math.sin(angle) });
  });
  return map;
}

function curve(a: { x: number; y: number }, b: { x: number; y: number }, bend: number) {
  const mx = (a.x + b.x) / 2 + (CENTER - (a.x + b.x) / 2) * bend;
  const my = (a.y + b.y) / 2 + (CENTER - (a.y + b.y) / 2) * bend;
  return `M${a.x},${a.y}Q${mx},${my} ${b.x},${b.y}`;
}

export function NetworkGraph({ nodes, edges, selected, route, showTrade, showRestrictions, onSelect, onEdge }: Props) {
  const [hover, setHover] = useState<Row | null>(null);
  const place = useMemo(() => positions(nodes), [nodes]);
  const maxValue = Math.max(1, ...edges.filter((e) => e.kind === "trade").map((e) => e.value_usd_millions));
  const maxTotal = Math.max(1, ...nodes.map((n) => n.exports_usd_millions + n.imports_usd_millions));
  const visible = edges.filter((e) => (e.kind === "trade" ? showTrade : showRestrictions));
  const touching = (e: Row) => !selected || e.source === selected || e.target === selected;
  const onRoute = (e: Row) => !!route && route.slice(1).some((code, i) =>
    (e.source === route[i] && e.target === code) || (e.source === code && e.target === route[i]));

  return (
    <div className="chart">
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="group" aria-label="Network of actors with trade and restriction edges">
        <defs>
          <marker id="arrow-trade" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M0,0L8,4L0,8z" fill="var(--series-1)" />
          </marker>
          <marker id="arrow-restriction" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
            <path d="M0,0L8,4L0,8z" fill="var(--series-2)" />
          </marker>
        </defs>
        {visible.map((edge) => {
          const a = place.get(edge.source);
          const b = place.get(edge.target);
          if (!a || !b) return null;
          const isTrade = edge.kind === "trade";
          const active = route ? onRoute(edge) : touching(edge);
          const label = isTrade
            ? `${edge.source} to ${edge.target}: ${fmt.usdM(edge.value_usd_millions)}${edge.is_synthetic ? " (synthetic)" : ""}`
            : `${edge.source} imposed ${edge.value_usd_millions} on ${edge.target}${edge.is_synthetic ? " (all synthetic)" : ""}`;
          const d = curve(a, b, isTrade ? 0.28 : 0.5);
          return (
            <g key={`${edge.kind}-${edge.source}-${edge.target}`} opacity={active ? 1 : 0.07}>
              <path className="net-edge" d={d} stroke={isTrade ? "var(--series-1)" : "var(--series-2)"}
                strokeWidth={isTrade ? 1 + (edge.value_usd_millions / maxValue) * 5 : 1.25}
                strokeDasharray={isTrade ? undefined : "4 3"} opacity={0.72}
                markerEnd={`url(#arrow-${isTrade ? "trade" : "restriction"})`} />
              {/* A wide invisible stroke makes thin edges easy to hover and click. */}
              <path d={d} fill="none" stroke="transparent" strokeWidth={10} style={{ cursor: "pointer" }}
                onMouseEnter={() => setHover({ ...edge, label, x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 })}
                onMouseLeave={() => setHover(null)}
                onClick={() => onEdge(edge)}>
                <title>{label}</title>
              </path>
            </g>
          );
        })}
        {nodes.map((node) => {
          const p = place.get(node.code)!;
          const size = 19 + ((node.exports_usd_millions + node.imports_usd_millions) / maxTotal) * 12;
          const isCountry = node.type === "country";
          const isSelected = selected === node.code;
          const isOnRoute = !!route?.includes(node.code);
          return (
            <g key={node.code} className="net-node" role="button" tabIndex={0} aria-pressed={isSelected}
              aria-label={`${node.name}, ${fmt.usdM(node.exports_usd_millions)} exports, ${fmt.usdM(node.imports_usd_millions)} imports`}
              onClick={() => onSelect(node.code)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onSelect(node.code); } }}>
              <circle cx={p.x} cy={p.y} r={size} fill={isCountry ? "var(--surface-2)" : "var(--surface)"}
                style={{ stroke: isSelected || isOnRoute ? "var(--ink)" : "var(--ink-2)", strokeWidth: isSelected ? 3 : isOnRoute ? 2 : 1, strokeDasharray: isCountry ? undefined : "3 2" }} />
              <text x={p.x} y={p.y + 4} textAnchor="middle" style={{ fontSize: node.code.length > 3 ? 9 : 12 }}>{node.code}</text>
            </g>
          );
        })}
      </svg>
      {hover && (
        <div className="tooltip" style={{ left: `${(hover.x / SIZE) * 100}%`, top: `${(hover.y / SIZE) * 100}%` }}>
          {hover.label}<br />Click for row-level edges
        </div>
      )}
    </div>
  );
}
