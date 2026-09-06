/** Interactive evidence graph (pure SVG, no chart lib).
 * Force-ish radial layout computed deterministically from node ids.
 * Zoom/pan, kind + hypothesis filters, search, node select, support/
 * contradict edge coloring, band-colored hypothesis nodes.
 */
import { useMemo, useState } from "react";

export interface GNode {
  id: string;
  kind: string;
  label: string;
  status?: string;
  support?: number;
  band?: string;
  similarity?: number;
}

export interface GEdge {
  from: string;
  to: string;
  relation: string;
}

const KIND_COLORS: Record<string, string> = {
  equipment: "#1677B7",
  investigation: "#00A6C7",
  hypothesis: "#D99000",
  sensor: "#16845B",
  document: "#7C6FF0",
  image: "#C2703D",
  observation: "#3DA5C2",
  evidence: "#9DB2C3",
  case: "#6B7F93",
  test: "#D9363E",
};

const EDGE_COLORS: Record<string, string> = {
  SUPPORTS: "#16845B",
  CONTRADICTS: "#D9363E",
};

function hashStr(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export default function EvidenceGraph({ nodes, edges, onSelect }: {
  nodes: GNode[];
  edges: GEdge[];
  onSelect: (node: GNode | null, edge: GEdge | null) => void;
}) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState<[number, number]>([0, 0]);
  const [drag, setDrag] = useState<[number, number] | null>(null);
  const [kindFilter, setKindFilter] = useState("");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<string | null>(null);

  const W = 900;
  const H = 560;

  const layout = useMemo(() => {
    const pos = new Map<string, [number, number]>();
    const cx = W / 2;
    const cy = H / 2;
    const inv = nodes.find((n) => n.kind === "investigation");
    if (inv) pos.set(inv.id, [cx, cy]);
    const rest = nodes.filter((n) => n.kind !== "investigation");
    const R = Math.min(W, H) / 2 - 90;
    rest.forEach((n, i) => {
      const a = (2 * Math.PI * i) / Math.max(1, rest.length) + (hashStr(n.id) % 100) / 500;
      const rr = R * (0.55 + ((hashStr(n.id) >> 8) % 100) / 220);
      pos.set(n.id, [cx + rr * Math.cos(a), cy + rr * Math.sin(a) * 0.8]);
    });
    return pos;
  }, [nodes]);

  const visible = useMemo(() => {
    const qq = q.trim().toLowerCase();
    return new Set(
      nodes
        .filter((n) => !kindFilter || n.kind === kindFilter)
        .filter((n) => !qq || n.label.toLowerCase().includes(qq))
        .map((n) => n.id)
    );
  }, [nodes, kindFilter, q]);

  const kinds = useMemo(() => [...new Set(nodes.map((n) => n.kind))].sort(), [nodes]);

  function pickNode(id: string) {
    setSel(id);
    onSelect(nodes.find((n) => n.id === id) ?? null, null);
  }

  function onDown(e: React.MouseEvent) {
    setDrag([e.clientX, e.clientY]);
  }

  function onMove(e: React.MouseEvent) {
    if (!drag) return;
    const dx = (e.clientX - drag[0]) / zoom;
    const dy = (e.clientY - drag[1]) / zoom;
    setPan(([x, y]) => [x + dx, y + dy]);
    setDrag([e.clientX, e.clientY]);
  }

  return (
    <div>
      <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap", alignItems: "center" }}>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search nodes…"
          aria-label="Search graph nodes"
          style={{ padding: 8, borderRadius: 8, border: "1px solid var(--border)", background: "#081627", color: "var(--text)" }} />
        <select value={kindFilter} onChange={(e) => setKindFilter(e.target.value)} aria-label="Filter by node kind"
          style={{ padding: 8, borderRadius: 8, background: "#081627", color: "var(--text)", border: "1px solid var(--border)" }}>
          <option value="">All kinds</option>
          {kinds.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <button className="btn btn-ghost" style={{ padding: "6px 12px" }} onClick={() => setZoom((z) => Math.min(3, z + 0.2))}>Zoom +</button>
        <button className="btn btn-ghost" style={{ padding: "6px 12px" }} onClick={() => setZoom((z) => Math.max(0.4, z - 0.2))}>Zoom −</button>
        <button className="btn btn-ghost" style={{ padding: "6px 12px" }} onClick={() => { setZoom(1); setPan([0, 0]); }}>Reset</button>
        <span style={{ fontSize: 12, color: "var(--muted)" }}>{visible.size}/{nodes.length} nodes · drag to pan</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", background: "#081627", borderRadius: 8, border: "1px solid var(--border)", cursor: drag ? "grabbing" : "grab" }}
        role="img" aria-label="Evidence graph"
        onMouseDown={onDown} onMouseMove={onMove} onMouseUp={() => setDrag(null)} onMouseLeave={() => setDrag(null)}>
        <g transform={`translate(${W / 2 + pan[0]},${H / 2 + pan[1]}) scale(${zoom}) translate(${-W / 2},${-H / 2})`}>
          {edges.map((e, i) => {
            const a = layout.get(e.from);
            const b = layout.get(e.to);
            if (!a || !b || !visible.has(e.from) || !visible.has(e.to)) return null;
            const color = EDGE_COLORS[e.relation] ?? "#24445C";
            const dash = e.relation === "CONTRADICTS" ? "6 3" : undefined;
            return (
              <g key={i} onClick={(ev) => { ev.stopPropagation(); onSelect(null, e); }}
                style={{ cursor: "pointer" }}>
                <line x1={a[0]} y1={a[1]} x2={b[0]} y2={b[1]} stroke={color}
                  strokeWidth={e.relation === "SUPPORTS" || e.relation === "CONTRADICTS" ? 2.5 : 1.2}
                  strokeDasharray={dash} opacity={0.9} />
                <text x={(a[0] + b[0]) / 2} y={(a[1] + b[1]) / 2 - 4}
                  fill="var(--muted)" fontSize={9} textAnchor="middle">{e.relation}</text>
              </g>
            );
          })}
          {nodes.filter((n) => visible.has(n.id)).map((n) => {
            const p = layout.get(n.id);
            if (!p) return null;
            const color = KIND_COLORS[n.kind] ?? "#9DB2C3";
            const selected = sel === n.id;
            const r = n.kind === "investigation" ? 22 : n.kind === "hypothesis" ? 18 : 13;
            return (
              <g key={n.id} onClick={(ev) => { ev.stopPropagation(); pickNode(n.id); }}
                style={{ cursor: "pointer" }} role="button" aria-label={`${n.kind}: ${n.label}`} tabIndex={0}
                onKeyDown={(ev) => { if (ev.key === "Enter") pickNode(n.id); }}>
                <circle cx={p[0]} cy={p[1]} r={r} fill="#0B1F33" stroke={color}
                  strokeWidth={selected ? 3.5 : 2} />
                {n.kind === "hypothesis" && n.band && (
                  <circle cx={p[0]} cy={p[1]} r={r - 6} fill="none"
                    stroke={n.band === "High" ? "var(--success)" : n.band === "Low" ? "var(--critical)" : "var(--warning)"}
                    strokeWidth={2.5} />
                )}
                <text x={p[0]} y={p[1] + r + 13} fill="var(--text)" fontSize={10.5}
                  textAnchor="middle">{n.label.slice(0, 26)}{n.label.length > 26 ? "…" : ""}</text>
                <text x={p[0]} y={p[1] + r + 25} fill="var(--muted)" fontSize={8.5} textAnchor="middle">{n.kind}</text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
