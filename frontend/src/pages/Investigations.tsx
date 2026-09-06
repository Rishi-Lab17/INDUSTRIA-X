import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type Equipment, type Investigation } from "../api";
import { useRole } from "../components/equipment";

const STATUSES = ["DRAFT", "OPEN", "ANALYZING", "AWAITING_EVIDENCE",
  "TECHNICIAN_REVIEW", "VERIFICATION", "APPROVAL", "RESOLVED", "CLOSED",
  "ARCHIVED", "READY_FOR_VERIFICATION"];
const SEVERITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
const CATEGORIES = ["MECHANICAL", "ELECTRICAL", "THERMAL", "HYDRAULIC",
  "PNEUMATIC", "PROCESS", "SENSOR", "SOFTWARE", "UNKNOWN", "OTHER"];

function sevColor(s: string) {
  if (s === "CRITICAL") return "var(--critical)";
  if (s === "HIGH") return "var(--warning)";
  if (s === "MEDIUM") return "var(--accent)";
  return "var(--success)";
}

export default function Investigations() {
  const { canWrite } = useRole();
  const nav = useNavigate();
  const [items, setItems] = useState<Investigation[]>([]);
  const [total, setTotal] = useState(0);
  const [err, setErr] = useState("");
  const [q, setQ] = useState("");
  const [fStatus, setFStatus] = useState("");
  const [dlg, setDlg] = useState(false);
  const [equipment, setEquipment] = useState<Equipment[]>([]);
  const [f, setF] = useState({
    equipment_id: "", title: "", problem_statement: "",
    category: "MECHANICAL", severity: "MEDIUM", priority: 3,
  });
  const [busy, setBusy] = useState(false);

  function load() {
    api.caseList({ search: q || undefined, status: fStatus || undefined })
      .then((r) => {
        setItems(r.investigations);
        setTotal(r.total);
        setErr("");
      })
      .catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }

  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q, fStatus]);

  useEffect(() => {
    api.equipmentList().then((r) => setEquipment(r.equipment)).catch(() => setEquipment([]));
  }, []);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    if (!f.equipment_id || !f.title.trim() || !f.problem_statement.trim()) {
      setErr("Equipment, title and problem statement are required.");
      return;
    }
    setErr("");
    setBusy(true);
    try {
      const inv = await api.caseCreate({
        equipment_id: Number(f.equipment_id), title: f.title.trim(),
        problem_statement: f.problem_statement.trim(), category: f.category,
        severity: f.severity, priority: f.priority,
      });
      setDlg(false);
      setF({ equipment_id: "", title: "", problem_statement: "",
             category: "MECHANICAL", severity: "MEDIUM", priority: 3 });
      nav(`/investigations/${inv.id}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Create failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Investigations</h1>
          <p className="page-sub">Evidence-first industrial case work · {total} case{total === 1 ? "" : "s"}</p>
        </div>
        {canWrite && <button className="btn btn-ghost" onClick={() => setDlg(true)}>+ New investigation</button>}
      </div>

      {err && <div className="alert alert-error">{err}</div>}

      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="grid grid-3">
          <div className="field">
            <label>SEARCH</label>
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="vibration…" />
          </div>
          <div className="field">
            <label>STATUS</label>
            <select value={fStatus} onChange={(e) => setFStatus(e.target.value)} style={selStyle}>
              <option value="">All states</option>
              {STATUSES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </div>
        </div>
      </div>

      {items.length === 0 ? (
        <div className="panel">No investigations yet. Open the first case to begin evidence-driven work.</div>
      ) : (
        <div className="panel" style={{ padding: 8 }}>
          <table className="table">
            <thead>
              <tr><th>Case</th><th>Problem</th><th>Severity</th><th>Status</th><th>Updated</th></tr>
            </thead>
            <tbody>
              {items.map((c) => (
                <tr key={c.id}>
                  <td><Link to={`/investigations/${c.id}`}>#{c.id} {c.title}</Link></td>
                  <td style={{ maxWidth: 320 }}>{c.problem_statement.slice(0, 90)}</td>
                  <td><b style={{ color: sevColor(c.severity) }}>{c.severity}</b></td>
                  <td><span className="badge">{c.status}</span></td>
                  <td style={{ fontSize: 12 }}>{c.updated_at.slice(0, 10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {dlg && (
        <div className="modal-backdrop" onClick={() => !busy && setDlg(false)}>
          <div className="panel modal" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>New investigation</h3>
            <form onSubmit={create}>
              <div className="field">
                <label>EQUIPMENT</label>
                <select value={f.equipment_id} onChange={(e) => setF({ ...f, equipment_id: e.target.value })} style={selStyle}>
                  <option value="">Select…</option>
                  {equipment.map((e) => <option key={e.id} value={e.id}>{e.code} — {e.name}</option>)}
                </select>
              </div>
              <div className="field">
                <label>TITLE</label>
                <input value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
              </div>
              <div className="field">
                <label>PROBLEM STATEMENT</label>
                <input value={f.problem_statement} onChange={(e) => setF({ ...f, problem_statement: e.target.value })} />
              </div>
              <div className="grid grid-3">
                <div className="field">
                  <label>CATEGORY</label>
                  <select value={f.category} onChange={(e) => setF({ ...f, category: e.target.value })} style={selStyle}>
                    {CATEGORIES.map((c) => <option key={c}>{c}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>SEVERITY</label>
                  <select value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })} style={selStyle}>
                    {SEVERITIES.map((s) => <option key={s}>{s}</option>)}
                  </select>
                </div>
                <div className="field">
                  <label>PRIORITY (1–5)</label>
                  <input type="number" min={1} max={5} value={f.priority}
                    onChange={(e) => setF({ ...f, priority: Number(e.target.value) })} />
                </div>
              </div>
              <button className="btn" disabled={busy}>{busy ? "Creating…" : "Create case"}</button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

const selStyle: React.CSSProperties = {
  width: "100%", padding: 11, borderRadius: 8, background: "#081627",
  color: "var(--text)", border: "1px solid var(--border)",
};
