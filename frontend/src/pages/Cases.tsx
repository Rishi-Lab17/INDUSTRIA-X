import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useRole } from "../components/equipment";

interface CaseItem {
  id: number;
  case_number: string;
  title: string;
  status: string;
  priority: string;
  severity: string;
  opened_at: string;
}

export default function Cases() {
  const { canWrite } = useRole();
  const [items, setItems] = useState<CaseItem[]>([]);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);

  function load() {
    const params: Record<string, string | number | undefined> = { page, page_size: 20 };
    if (status) params.status = status;
    api.caseList9(params).then((r) => {
      setItems((r.cases as unknown as CaseItem[]) || []); setTotal((r.total as number) || 0); setErr("");
    }).catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }
  useEffect(() => { const t = setTimeout(load, 250); return () => clearTimeout(t); }, [status, page]);

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Cases</h1>
          <p className="page-sub">Enterprise industrial case management · {total} case{total === 1 ? "" : "s"}</p>
        </div>
        {canWrite && <button className="btn btn-ghost" onClick={() => window.location.hash = "#/cases/new"}>+ New Case</button>}
      </div>
      {err && <div className="alert alert-error">{err}</div>}
      <div style={{ marginBottom: 12 }}>
        <select value={status} onChange={e => { setStatus(e.target.value); setPage(1); }} className="input" style={{ width: "auto" }}>
          <option value="">All Statuses</option>
          <option value="OPEN">OPEN</option><option value="INVESTIGATING">INVESTIGATING</option>
          <option value="VERIFICATION">VERIFICATION</option><option value="CLOSED">CLOSED</option>
          <option value="ARCHIVED">ARCHIVED</option>
        </select>
      </div>
      <table className="table">
        <thead><tr><th>Case #</th><th>Title</th><th>Status</th><th>Priority</th><th>Severity</th><th>Opened</th></tr></thead>
        <tbody>
          {items.map((c) => (
            <tr key={c.id}><td><Link to={`/cases/${c.id}`}>{c.case_number}</Link></td>
              <td>{c.title}</td>
              <td><span className={`badge badge--${c.status.toLowerCase()}`}>{c.status}</span></td>
              <td>{c.priority}</td><td>{c.severity}</td>
              <td>{c.opened_at.slice(0, 10)}</td></tr>
          ))}
        </tbody>
      </table>
      {items.length === 0 && !err && <div className="panel" style={{ padding: 24, textAlign: "center", color: "var(--muted)" }}>No cases found</div>}
    </div>
  );
}
