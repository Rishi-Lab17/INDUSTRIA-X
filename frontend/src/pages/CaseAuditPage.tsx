import { useEffect, useState } from "react";
import { api } from "../api";

interface AuditEvent {
  id: number;
  action: string;
  detail: Record<string, unknown>;
  entity_type: string;
  entity_id: number;
  user_id: number;
  created_at: string;
}

export default function CaseAuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState("");
  const [action, setAction] = useState("");
  const [page, setPage] = useState(1);

  function load() {
    const params: Record<string, string | number | undefined> = { page, page_size: 50 };
    if (action) params.action = action;
    api.caseAudit9(params).then(r => {
      setEvents((r.events as AuditEvent[]) || []);
      setTotal((r.total as number) || 0); setErr("");
    }).catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [action, page]);

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Audit Center</h1>
          <p className="page-sub">Searchable audit log · {total} events</p>
        </div>
      </div>
      {err && <div className="alert alert-error">{err}</div>}
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        <input className="input" placeholder="Filter by action..." value={action} onChange={e => { setAction(e.target.value); setPage(1); }} style={{ width: 250 }} />
        <button className="btn btn-ghost" onClick={load}>Search</button>
      </div>
      <table className="table">
        <thead><tr><th>ID</th><th>Action</th><th>Entity</th><th>User</th><th>Time</th></tr></thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id}>
              <td>{e.id}</td>
              <td><strong>{e.action}</strong></td>
              <td>{e.entity_type}:{e.entity_id}</td>
              <td>{e.user_id || "—"}</td>
              <td>{e.created_at.slice(0, 19)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {events.length === 0 && !err && <div className="panel" style={{ padding: 24, textAlign: "center", color: "var(--muted)" }}>No audit events found</div>}
    </div>
  );
}
