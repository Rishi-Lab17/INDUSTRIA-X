import { useEffect, useState } from "react";
import { api } from "../api";
import { useRole } from "../components/equipment";

interface MemoryItem {
  id: number;
  equipment_type: string;
  failure_mode: string;
  root_cause: string;
  reliability: string;
  created_at: string;
}

export default function MemoryPage() {
  const { canWrite } = useRole();
  const [memories, setMemories] = useState<MemoryItem[]>([]);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState("");
  const [page, setPage] = useState(1);

  function load() {
    api.caseMemoryList9({ page, page_size: 20 }).then(r => {
      setMemories((r.memories as unknown as MemoryItem[]) || []);
      setTotal((r.total as number) || 0); setErr("");
    }).catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [page]);

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Case Memory</h1>
          <p className="page-sub">Reusable case knowledge · {total} memory{total === 1 ? "" : "s"}</p>
        </div>
        {canWrite && <button className="btn btn-ghost" onClick={() => window.location.hash = "#/memory/new"}>+ Add Memory</button>}
      </div>
      {err && <div className="alert alert-error">{err}</div>}
      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        <div className="panel"><div className="stat-label">TOTAL</div><div className="stat-num">{total}</div></div>
        <div className="panel"><div className="stat-label">VERIFIED</div><div className="stat-num" style={{ color: "var(--success)" }}>{memories.filter((m) => m.reliability === "VERIFIED").length}</div></div>
        <div className="panel"><div className="stat-label">DRAFT</div><div className="stat-num" style={{ color: "var(--warning)" }}>{memories.filter((m) => m.reliability === "DRAFT").length}</div></div>
      </div>
      <table className="table">
        <thead><tr><th>Equipment Type</th><th>Failure Mode</th><th>Root Cause</th><th>Reliability</th><th>Created</th></tr></thead>
        <tbody>
          {memories.map((m) => (
            <tr key={m.id}>
              <td>{m.equipment_type || "—"}</td>
              <td>{m.failure_mode || "—"}</td>
              <td style={{ fontSize: 13 }}>{(m.root_cause || "").slice(0, 60)}</td>
              <td><span className={`badge badge--${m.reliability.toLowerCase()}`}>{m.reliability}</span></td>
              <td>{m.created_at.slice(0, 10)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {memories.length === 0 && !err && <div className="panel" style={{ padding: 24, textAlign: "center", color: "var(--muted)" }}>No case memories found</div>}
    </div>
  );
}
