"use client";
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";

type Tip = { x: number; y: number; content: ReactNode } | null;

/** Draw at the container's real width, so 11px text stays 11px on every page. */
function useWidth(initial: number) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(initial);
  useEffect(() => {
    if (!ref.current) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry.contentRect.width > 0) setWidth(Math.round(entry.contentRect.width));
    });
    observer.observe(ref.current);
    return () => observer.disconnect();
  }, []);
  return { ref, width };
}

function niceMax(value: number): number {
  if (value <= 0) return 1;
  const power = 10 ** Math.floor(Math.log10(value));
  const step = [1, 2, 2.5, 5, 10].find((s) => s * power >= value) ?? 10;
  return step * power;
}

/** Horizontal bars, optionally split into source-backed and synthetic segments. */
export function HBars({ rows, format }: {
  rows: { key: string; name: ReactNode; value: number; synthetic?: number; detail?: string }[];
  format: (value: number) => string;
}) {
  const max = Math.max(...rows.map((r) => r.value + (r.synthetic ?? 0)), 0) || 1;
  return (
    <div className="hbar">
      {rows.map((r) => {
        const total = r.value + (r.synthetic ?? 0);
        const title = r.detail ?? (r.synthetic !== undefined ? `${format(r.value)} source-backed, ${format(r.synthetic)} synthetic` : format(total));
        return (
          <div key={r.key} style={{ display: "contents" }}>
            <span className="name">{r.name}</span>
            <span className="track" title={title}>
              {r.value > 0 && <span className="seg" style={{ width: `${(r.value / max) * 100}%`, background: "var(--series-1)" }} />}
              {(r.synthetic ?? 0) > 0 && <span className="seg hatch" style={{ width: `${((r.synthetic ?? 0) / max) * 100}%` }} />}
            </span>
            <span className="val">{format(total)}</span>
          </div>
        );
      })}
    </div>
  );
}

export function ProvenanceLegend() {
  return (
    <div className="legend">
      <span><i style={{ background: "var(--series-1)" }} />Source-backed</span>
      <span><i className="seg hatch" />Synthetic</span>
    </div>
  );
}

/** Vertical columns over time; synthetic periods are hatched so they cannot pass for observed data. */
export function Columns({ rows, format, height = 200 }: {
  rows: { key: string; value: number; synthetic: number }[]; format: (value: number) => string; height?: number;
}) {
  const [tip, setTip] = useState<Tip>(null);
  const { ref, width } = useWidth(640);
  const pad = { top: 8, right: 8, bottom: 22, left: 52 };
  const innerH = height - pad.top - pad.bottom;
  const innerW = width - pad.left - pad.right;
  const max = niceMax(Math.max(...rows.map((r) => r.value + r.synthetic), 0));
  const y = (v: number) => pad.top + innerH - (v / max) * innerH;
  const band = innerW / Math.max(rows.length, 1);
  const barW = Math.min(36, band * 0.62);
  return (
    <div className="chart" ref={ref} onMouseLeave={() => setTip(null)}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Column chart by period">
        <defs>
          <pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <rect width="6" height="6" fill="var(--surface)" />
            <rect width="3" height="6" fill="var(--series-2)" />
          </pattern>
        </defs>
        {[0, 0.5, 1].map((f) => (
          <g key={f}>
            <line x1={pad.left} x2={width - pad.right} y1={y(max * f)} y2={y(max * f)} stroke={f === 0 ? "var(--axis)" : "var(--grid)"} />
            <text x={pad.left - 8} y={y(max * f) + 4} textAnchor="end">{format(max * f)}</text>
          </g>
        ))}
        {rows.map((r, i) => {
          const x = pad.left + band * i + (band - barW) / 2;
          const synthTop = y(r.value + r.synthetic);
          const valueTop = y(r.value);
          const showTip = () => setTip({
            x: ((x + barW / 2) / width) * 100, y: (synthTop / height) * 100,
            content: <><b>{r.key}</b><br />{format(r.value)} source-backed<br />{format(r.synthetic)} synthetic</>,
          });
          return (
            <g key={r.key}>
              {r.value > 0 && <rect x={x} y={valueTop} width={barW} height={Math.max(0, y(0) - valueTop)} fill="var(--series-1)" rx={r.synthetic > 0 ? 0 : 3} />}
              {r.synthetic > 0 && <rect x={x} y={synthTop} width={barW} height={Math.max(0, valueTop - synthTop - (r.value > 0 ? 2 : 0))} fill="url(#hatch)" stroke="var(--series-2)" rx={2} />}
              <text x={x + barW / 2} y={height - 6} textAnchor="middle">{r.key}</text>
              <rect x={pad.left + band * i} y={pad.top} width={band} height={innerH} fill="transparent" onMouseEnter={showTip} onMouseMove={showTip} />
            </g>
          );
        })}
      </svg>
      {tip && <div className="tooltip" style={{ left: `${tip.x}%`, top: `${tip.y}%` }}>{tip.content}</div>}
    </div>
  );
}

export const SERIES_COLORS = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-4)"];

export type LineSeries = { id: string; label: string; color: string; points: { x: number; y: number; synthetic?: boolean }[] };

/** One y-axis, 2px lines, a crosshair tooltip. Synthetic stretches are dashed. */
export function Lines({ series, format, height = 260 }: { series: LineSeries[]; format: (v: number) => string; height?: number }) {
  const [hoverX, setHoverX] = useState<number | null>(null);
  const { ref, width } = useWidth(720);
  const pad = { top: 12, right: 112, bottom: 24, left: 56 };
  const xs = useMemo(() => [...new Set(series.flatMap((s) => s.points.map((p) => p.x)))].sort((a, b) => a - b), [series]);
  const values = series.flatMap((s) => s.points.map((p) => p.y));
  const minY = Math.min(0, ...values);
  const maxY = niceMax(Math.max(...values, 0));
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;
  const px = (x: number) => pad.left + (xs.length > 1 ? ((x - xs[0]) / (xs[xs.length - 1] - xs[0])) * innerW : innerW / 2);
  const py = (y: number) => pad.top + innerH - ((y - minY) / (maxY - minY || 1)) * innerH;

  function segments(points: LineSeries["points"]) {
    const solid: string[] = [];
    const dashed: string[] = [];
    for (let i = 1; i < points.length; i++) {
      const line = `M${px(points[i - 1].x)},${py(points[i - 1].y)}L${px(points[i].x)},${py(points[i].y)}`;
      (points[i].synthetic ? dashed : solid).push(line);
    }
    return { solid: solid.join(""), dashed: dashed.join("") };
  }

  const hasSynthetic = series.some((s) => s.points.some((p) => p.synthetic));
  return (
    <div>
      <div className="legend">
        {series.map((s) => <span key={s.id}><i className="line" style={{ borderColor: s.color }} />{s.label}</span>)}
        {hasSynthetic && <span><i className="dash" />Synthetic years</span>}
      </div>
      <div className="chart" ref={ref} onMouseLeave={() => setHoverX(null)}>
        <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Line chart over time"
          onMouseMove={(e) => {
            const box = e.currentTarget.getBoundingClientRect();
            const vx = ((e.clientX - box.left) / box.width) * width;
            let best = xs[0];
            for (const x of xs) if (Math.abs(px(x) - vx) < Math.abs(px(best) - vx)) best = x;
            setHoverX(best ?? null);
          }}>
          {[0, 0.25, 0.5, 0.75, 1].map((f) => {
            const value = minY + (maxY - minY) * f;
            return (
              <g key={f}>
                <line x1={pad.left} x2={width - pad.right} y1={py(value)} y2={py(value)} stroke={f === 0 ? "var(--axis)" : "var(--grid)"} />
                <text x={pad.left - 8} y={py(value) + 4} textAnchor="end">{format(value)}</text>
              </g>
            );
          })}
          {xs.map((x) => <text key={x} x={px(x)} y={height - 6} textAnchor="middle">{x}</text>)}
          {series.map((s) => {
            const { solid, dashed } = segments(s.points);
            const last = s.points[s.points.length - 1];
            return (
              <g key={s.id}>
                <path d={solid} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" />
                <path d={dashed} fill="none" stroke={s.color} strokeWidth={2} strokeDasharray="5 4" />
                {last && series.length <= 4 && <text className="label" x={px(last.x) + 8} y={py(last.y) + 4}>{s.label}</text>}
              </g>
            );
          })}
          {hoverX !== null && (
            <g>
              <line x1={px(hoverX)} x2={px(hoverX)} y1={pad.top} y2={pad.top + innerH} stroke="var(--axis)" />
              {series.map((s) => {
                const point = s.points.find((p) => p.x === hoverX);
                return point ? <circle key={s.id} cx={px(point.x)} cy={py(point.y)} r={4} fill={s.color} stroke="var(--surface)" strokeWidth={2} /> : null;
              })}
            </g>
          )}
        </svg>
        {hoverX !== null && (
          <div className="tooltip" style={{ left: `${(px(hoverX) / width) * 100}%`, top: 8, transform: "translate(-50%, 0)" }}>
            <b>{hoverX}</b>
            {series.map((s) => {
              const point = s.points.find((p) => p.x === hoverX);
              return point ? <div key={s.id}>{s.label}: {format(point.y)}{point.synthetic ? " (synthetic)" : ""}</div> : null;
            })}
          </div>
        )}
      </div>
    </div>
  );
}
