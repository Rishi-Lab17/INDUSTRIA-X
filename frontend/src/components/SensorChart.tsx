/** Lightweight SVG time-series chart (no external chart lib).
 * Props: points [{t, v}], anomalies [{ts}], threshold lines, downsampling flag.
 * Pure presentation — all math is server-side. */
import { useMemo, useState } from "react";

export interface ChartPoint {
  t: number;
  v: number;
}

export interface AnomalyMark {
  ts: number;
  value: number;
}

const W = 760;
const H = 260;
const PAD = { l: 64, r: 12, t: 12, b: 28 };

function fmtTime(ts: number) {
  const d = new Date(ts * 1000);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export default function SensorChart({ points, anomalies, threshold, downsampled, unit }: {
  points: ChartPoint[];
  anomalies?: AnomalyMark[];
  threshold?: { gt?: number | null; lt?: number | null };
  downsampled?: boolean;
  unit?: string | null;
}) {
  const [zoom, setZoom] = useState<[number, number] | null>(null);
  const view = useMemo(() => {
    if (points.length === 0) return null;
    const xs = points.map((p) => p.t);
    const ys = points.map((p) => p.v);
    const x0 = zoom ? zoom[0] : Math.min(...xs);
    const x1 = zoom ? zoom[1] : Math.max(...xs);
    const span = x1 - x0 || 1;
    const lo = Math.min(...ys);
    const hi = Math.max(...ys);
    const pad = (hi - lo || 1) * 0.08;
    const y0 = lo - pad;
    const y1 = hi + pad;
    const X = (t: number) => PAD.l + ((t - x0) / span) * (W - PAD.l - PAD.r);
    const Y = (v: number) => PAD.t + (1 - (v - y0) / (y1 - y0)) * (H - PAD.t - PAD.b);
    const inView = points.filter((p) => p.t >= x0 && p.t <= x1);
    const path = inView.map((p, i) => `${i === 0 ? "M" : "L"}${X(p.t).toFixed(1)},${Y(p.v).toFixed(1)}`).join(" ");
    const ticks = [0, 1, 2, 3, 4].map((i) => x0 + (span * i) / 4);
    return { X, Y, path, ticks, y0, y1, x0, x1 };
  }, [points, zoom]);

  if (!view || points.length === 0) {
    return <div style={{ color: "var(--muted)", fontSize: 13 }}>No data points in range.</div>;
  }

  const reset = () => setZoom(null);
  const zoomSel = (frac: number) => {
    const xs = points.map((p) => p.t);
    const lo = Math.min(...xs);
    const hi = Math.max(...xs);
    const span = (hi - lo) * frac;
    setZoom([hi - span, hi]);
  };

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 8, flexWrap: "wrap", alignItems: "center" }}>
        {[["1h", 1 / 24], ["6h", 0.25], ["24h", 1], ["7d", 7], ["30d", 30]].map(([label, days]) => (
          <button key={label as string} className="btn btn-ghost" style={{ padding: "4px 10px", fontSize: 12 }}
            onClick={() => {
              const xs = points.map((p) => p.t);
              const hi = Math.max(...xs);
              setZoom([hi - (days as number) * 86400, hi]);
            }}>
            {label}
          </button>
        ))}
        <button className="btn btn-ghost" style={{ padding: "4px 10px", fontSize: 12 }} onClick={() => zoomSel(0.25)}>Last 25%</button>
        <button className="btn btn-ghost" style={{ padding: "4px 10px", fontSize: 12 }} onClick={reset}>Reset</button>
        {downsampled && <span style={{ fontSize: 12, color: "var(--warning)" }}>Downsampled for display — raw source preserved.</span>}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", background: "#081627", borderRadius: 8, border: "1px solid var(--border)" }} role="img" aria-label="Sensor time series chart">
        {view.ticks.map((t, i) => (
          <g key={i}>
            <line x1={view.X(t)} y1={PAD.t} x2={view.X(t)} y2={H - PAD.b} stroke="#1d3a52" strokeWidth={1} />
            <text x={view.X(t)} y={H - 8} fill="var(--muted)" fontSize={10} textAnchor="middle">{fmtTime(t)}</text>
          </g>
        ))}
        {[0, 0.5, 1].map((f) => {
          const v = view.y0 + (view.y1 - view.y0) * f;
          return (
            <g key={f}>
              <line x1={PAD.l} y1={view.Y(v)} x2={W - PAD.r} y2={view.Y(v)} stroke="#1d3a52" strokeWidth={1} />
              <text x={PAD.l - 6} y={view.Y(v) + 3} fill="var(--muted)" fontSize={10} textAnchor="end">{v.toFixed(2)}</text>
            </g>
          );
        })}
        {threshold?.gt !== undefined && threshold.gt !== null && (
          <line x1={PAD.l} y1={view.Y(threshold.gt)} x2={W - PAD.r} y2={view.Y(threshold.gt)} stroke="var(--critical)" strokeWidth={1.5} strokeDasharray="6 3" />
        )}
        {threshold?.lt !== undefined && threshold.lt !== null && (
          <line x1={PAD.l} y1={view.Y(threshold.lt)} x2={W - PAD.r} y2={view.Y(threshold.lt)} stroke="var(--critical)" strokeWidth={1.5} strokeDasharray="6 3" />
        )}
        <path d={view.path} fill="none" stroke="var(--accent)" strokeWidth={1.5} />
        {(anomalies ?? []).map((a, i) => (
          <circle key={i} cx={view.X(a.ts)} cy={view.Y(a.value)} r={4} fill="var(--critical)" stroke="#fff" strokeWidth={1}>
            <title>{`Anomaly ${a.value} @ ${fmtTime(a.ts)}`}</title>
          </circle>
        ))}
      </svg>
      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
        {unit ? `Unit: ${unit} · ` : ""}{points.length} points shown · red dots = statistical anomalies (observation only, not a failure diagnosis)
      </div>
    </div>
  );
}
