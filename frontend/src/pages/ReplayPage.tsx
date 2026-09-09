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

export default function ReplayPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.caseAudit9({ page_size: 50 })
      .then(r => setEvents((r.events as AuditEvent[]) || []))
      .catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }, []);

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Replay</h1>
          <p className="page-sub">Audit event replay · {events.length} events</p>
        </div>
      </div>
      {err && <div className="alert alert-error">{err}</div>}
      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        <div className="panel"><div className="stat-label">EVENTS</div><div className="stat-num">{events.length}</div></div>
      </div>
      <table className="table">
        <thead><tr><th>Action</th><th>Detail</th><th>User</th><th>Time</th></tr></thead>
        <tbody>
          {events.map((e) => (
            <tr key={e.id}>
              <td><strong>{e.action}</strong></td>
              <td style={{ fontSize: 12 }}>{JSON.stringify(e.detail)}</td>
              <td>{e.user_id || "—"}</td>
              <td>{e.created_at.slice(0, 19)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {events.length === 0 && !err && <div className="panel" style={{ padding: 24, textAlign: "center", color: "var(--muted)" }}>No replay events</div>}
    </div>
  );
}
