import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type CaseEvidence } from "../api";

interface EvidenceWithInvestigation extends CaseEvidence {
  investigation_id: number;
  investigation_title: string;
}

export default function EvidenceCenter() {
  const [items, setItems] = useState<EvidenceWithInvestigation[]>([]);
  const [graph, setGraph] = useState<{ nodes: { id: string; label: string; kind: string }[]; edges: { from: string; to: string; relation: string }[] } | null>(null);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [filterType, setFilterType] = useState("");
  const [search, setSearch] = useState("");
  const [selectedInv, setSelectedInv] = useState<number | null>(null);

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setLoading(true);
    setErr("");
    try {
      const invs = await api.caseList({});
      const investigations = (invs as { investigations: { id: number; title: string }[] }).investigations || [];
      if (investigations.length === 0) {
        setItems([]);
        setGraph(null);
        setLoading(false);
        return;
      }
      // Fetch evidence for all investigations in parallel (company-scoped)
      const results = await Promise.all(
        investigations.map(async (inv) => {
          try {
            const r = await api.caseEvidenceList(inv.id);
            return (r.evidence || []).map((e) => ({ ...e, investigation_id: inv.id, investigation_title: inv.title }));
          } catch {
            return [];
          }
        })
      );
      const all = results.flat() as EvidenceWithInvestigation[];
      setItems(all);
      // Load graph for first investigation with evidence, or selected
      const targetInv = selectedInv ?? (all[0]?.investigation_id ?? investigations[0]?.id);
      if (targetInv) {
        setSelectedInv(targetInv);
        try {
          const g = await api.caseGraph(targetInv);
          setGraph(g as { nodes: { id: string; label: string; kind: string }[]; edges: { from: string; to: string; relation: string }[] });
        } catch {
          setGraph(null);
        }
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to load evidence");
    } finally {
      setLoading(false);
    }
  }

  const filtered = items.filter((e) => {
    if (filterType && e.type !== filterType) return false;
    if (search && !`${e.title} ${e.description} ${e.type}`.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  const types = [...new Set(items.map((e) => e.type))].sort();

  if (loading) return <div style={{ color: "var(--muted)" }}>Loading evidence…</div>;
  if (err) return <div className="alert alert-error">{err}</div>;

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Evidence Center</h1>
          <p className="page-sub">{items.length} evidence item{items.length === 1 ? "" : "s"} across your investigations — company-scoped, provenance-tracked</p>
        </div>
        <button className="btn btn-ghost" onClick={load}>Refresh</button>
      </div>

      {items.length === 0 ? (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>No evidence yet</h3>
          <p style={{ color: "var(--muted)", fontSize: 14, lineHeight: 1.6 }}>
            Evidence is created within investigations. To populate this center:
          </p>
          <ol style={{ fontSize: 14, lineHeight: 1.8, color: "var(--text-secondary)" }}>
            <li>Go to <Link to="/equipment">Equipment</Link> and register an asset (e.g., PUMP-P204)</li>
            <li>Create an investigation from that equipment</li>
            <li>Add evidence: sensor readings, documents, vision images, or technician observations</li>
            <li>Evidence will appear here with full provenance, timestamps, and graph relationships</li>
          </ol>
          <div style={{ marginTop: 12 }}>
            <Link to="/investigations"><button className="btn btn-ghost">Go to Investigations</button></Link>
          </div>
        </div>
      ) : (
        <>
          <div className="panel" style={{ marginBottom: 16 }}>
            <div className="grid grid-3">
              <div className="field">
                <label>SEARCH</label>
                <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="title, type, description…" />
              </div>
              <div className="field">
                <label>FILTER BY TYPE</label>
                <select value={filterType} onChange={(e) => setFilterType(e.target.value)} style={selStyle}>
                  <option value="">All types</option>
                  {types.map((t) => <option key={t} value={t}>{t}</option>)}
                </select>
              </div>
              <div className="field">
                <label>TOTAL</label>
                <div style={{ padding: "12px 14px", background: "#F8FAFC", border: "1px solid var(--border)", borderRadius: 10, fontWeight: 700, color: "var(--accent)" }}>{filtered.length} / {items.length}</div>
              </div>
            </div>
          </div>

          <div className="grid" style={{ gridTemplateColumns: "1fr 360px", gap: 16 }}>
            <div>
              {filtered.length === 0 ? (
                <div className="panel">No evidence matches the current filter.</div>
              ) : (
                <div className="grid">
                  {filtered.map((e) => (
                    <div key={`${e.investigation_id}-${e.id}`} className="panel" style={{ padding: 16 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
                        <b>E-{String(e.id).padStart(3, "0")} — {e.title}</b>
                        <span className="badge">{e.type}</span>
                      </div>
                      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
                        Investigation #{e.investigation_id} · {e.investigation_title} · Source: {e.source || "—"} · {e.created_at.slice(0, 10)}
                      </div>
                      {e.description && <div style={{ fontSize: 13, marginTop: 6, color: "var(--text-secondary)" }}>{e.description}</div>}
                      {e.content && <div style={{ fontSize: 12, marginTop: 4, color: "var(--muted)", whiteSpace: "pre-wrap" }}>{e.content.slice(0, 200)}</div>}
                      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap", fontSize: 12 }}>
                        <span>Confidence: <b style={{ color: e.confidence !== null && e.confidence > 0.7 ? "var(--success)" : "var(--muted)" }}>{e.confidence ?? "—"}</b></span>
                        <span>Quality: <b>{(e as unknown as { quality?: number }).quality ?? "—"}</b></span>
                        <span>Provenance: <span className="mono" style={{ fontSize: 11 }}>{JSON.stringify(e.provenance).slice(0, 60)}</span></span>
                      </div>
                      <div style={{ marginTop: 8 }}>
                        <Link to={`/investigations/${e.investigation_id}`} className="linklike" style={{ fontSize: 12 }}>Open investigation →</Link>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div>
              <div className="panel" style={{ position: "sticky", top: 24 }}>
                <h3 style={{ marginTop: 0 }}>Evidence Graph</h3>
                {!graph ? (
                  <div style={{ fontSize: 13, color: "var(--muted)" }}>Select an investigation with evidence to view its graph.</div>
                ) : (
                  <>
                    <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>{graph.nodes.length} nodes · {graph.edges.length} edges</div>
                    <div style={{ maxHeight: 300, overflow: "auto", border: "1px solid var(--border)", borderRadius: 8, padding: 8, background: "#F8FAFC" }}>
                      {graph.nodes.slice(0, 30).map((n) => (
                        <div key={n.id} style={{ fontSize: 12, padding: "4px 0", borderBottom: "1px dashed var(--border-light)" }}>
                          <span className="badge" style={{ fontSize: 10 }}>{n.kind}</span> {n.label.slice(0, 60)}
                        </div>
                      ))}
                      {graph.nodes.length > 30 && <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>+{graph.nodes.length - 30} more nodes</div>}
                    </div>
                    {graph.edges.slice(0, 10).map((ed, i) => (
                      <div key={i} style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>{ed.from} —{ed.relation}→ {ed.to}</div>
                    ))}
                  </>
                )}
                <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 10 }}>Graph is company-scoped and built from real evidence links. No fake nodes.</div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

const selStyle: React.CSSProperties = {
  width: "100%", padding: 11, borderRadius: 8, background: "#FFFFFF",
  color: "var(--text)", border: "1px solid #CBD5E1",
};
