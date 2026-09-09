import { useEffect, useState } from "react";
import { api } from "../api";
import { useRole } from "../components/equipment";

interface LineageNode {
  id: number;
  node_id: string;
  node_type: string;
  label: string;
  downstream_node_ids: string[];
}

export default function LineagePage() {
  const { canWrite } = useRole();
  const [nodes, setNodes] = useState<LineageNode[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.caseList9({ status: "CLOSED", page: 1, page_size: 1 })
      .then(r => {
        const cases = (r.cases as Record<string, unknown>[]) || [];
        if (cases.length > 0) {
          api.caseLineageGet9(cases[0].id as number)
            .then(r2 => setNodes((r2.nodes as LineageNode[]) || []))
            .catch(() => {});
        }
      })
      .catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }, []);

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Data Lineage</h1>
          <p className="page-sub">End-to-end data lineage · {nodes.length} nodes</p>
        </div>
        {canWrite && <button className="btn btn-ghost" onClick={() => window.location.hash = "#/lineage/new"}>+ Add Node</button>}
      </div>
      {err && <div className="alert alert-error">{err}</div>}
      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        <div className="panel"><div className="stat-label">NODES</div><div className="stat-num">{nodes.length}</div></div>
      </div>
      <div className="panel" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Lineage Graph</h3>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
          {nodes.map((n, i) => (
            <div key={i} className="panel" style={{ padding: "8px 16px", borderLeft: "3px solid var(--accent)" }}>
              <strong>{n.label || n.node_type}</strong><br />
              <span style={{ fontSize: 12, color: "var(--muted)" }}>{n.node_id} · {n.node_type}</span>
            </div>
          ))}
        </div>
        {nodes.length === 0 && <div style={{ color: "var(--muted)" }}>Select a closed case to view lineage</div>}
      </div>
    </div>
  );
}
