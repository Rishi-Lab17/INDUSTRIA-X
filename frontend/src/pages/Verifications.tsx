import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Investigation } from "../api";
import { useRole } from "../components/equipment";

const STATUS_COLORS: Record<string, string> = {
  PENDING: "var(--muted)", ASSIGNED: "var(--warning)", IN_REVIEW: "var(--accent)",
  INSPECTION_REQUIRED: "var(--warning)", AWAITING_EVIDENCE: "var(--accent)",
  SAFETY_REVIEW: "var(--accent)", AWAITING_APPROVAL: "var(--success)",
  APPROVED: "var(--success)", REJECTED: "var(--critical)",
  ESCALATED: "var(--warning)", BLOCKED: "var(--critical)",
  CANCELLED: "var(--muted)", COMPLETED: "var(--muted)",
};
const PRIORITY_COLORS: Record<string, string> = {
  LOW: "var(--success)", MEDIUM: "var(--warning)",
  HIGH: "var(--critical)", CRITICAL: "var(--critical)",
};

export default function Verifications() {
  const { canWrite } = useRole();
  const [items, setItems] = useState<Record<string, unknown>[]>([]);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [busy, setBusy] = useState(false);

  function load() {
    const params: Record<string, string | number | undefined> = {};
    if (status) params.status = status;
    if (priority) params.priority = priority;
    api.verificationList(params).then((r) => {
      setItems(r.verifications); setTotal(r.total); setErr("");
    }).catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }

  useEffect(() => {
    const t = setTimeout(load, 250); return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, priority]);

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Verifications</h1>
          <p className="page-sub">Technician verification + safety gate + human approval · {total} request{total === 1 ? "" : "s"}</p>
        </div>
        {canWrite && <button className="btn btn-ghost" onClick={() => window.location.hash = "#/investigations"}>+ Create from Investigation</button>}
      </div>
      {err && <div className="alert alert-error">{err}</div>}
      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="grid grid-3">
          <div className="field"><label>STATUS</label>
            <select value={status} onChange={(e) => setStatus(e.target.value)} style={selStyle}>
              <option value="">All</option>
              {["PENDING","ASSIGNED","IN_REVIEW","INSPECTION_REQUIRED","AWAITING_EVIDENCE","SAFETY_REVIEW","AWAITING_APPROVAL","APPROVED","REJECTED","ESCALATED","BLOCKED","COMPLETED"].map((s) => <option key={s}>{s}</option>)}
            </select></div>
          <div className="field"><label>PRIORITY</label>
            <select value={priority} onChange={(e) => setPriority(e.target.value)} style={selStyle}>
              <option value="">All</option>
              {["LOW","MEDIUM","HIGH","CRITICAL"].map((p) => <option key={p}>{p}</option>)}
            </select></div>
        </div>
      </div>
      {items.length === 0 ? (
        <div className="panel">No verification requests yet. Create one from an investigation after it reaches READY_FOR_VERIFICATION.</div>
      ) : (
        <div className="panel" style={{ padding: 8 }}>
          <table className="table">
            <thead><tr><th>Verification</th><th>Equipment</th><th>Priority</th><th>Status</th><th>Updated</th></tr></thead>
            <tbody>
              {items.map((v: Record<string, unknown>) => (
                <tr key={v.id}>
                  <td><Link to={`/verifications/${v.id}`}>#{v.id}</Link></td>
                  <td style={{ fontSize: 12 }}>{(v.equipment as Record<string, unknown>)?.name as string || "—"}</td>
                  <td><b style={{ color: PRIORITY_COLORS[(v.priority as string) || "MEDIUM"] }}>{(v.priority as string)}</b></td>
                  <td><span className="badge" style={{ background: STATUS_COLORS[(v.status as string) || "PENDING"] }}>{(v.status as string)}</span></td>
                  <td style={{ fontSize: 12 }}>{(v.updated_at as string)?.slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

const selStyle: React.CSSProperties = {
  width: "100%", padding: 11, borderRadius: 8, background: "#081627",
  color: "var(--text)", border: "1px solid var(--border)",
};
