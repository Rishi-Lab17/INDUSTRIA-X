import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";

const CRITS = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
const STATUSES = ["OPERATIONAL", "DEGRADED", "UNDER_MAINTENANCE", "DECOMMISSIONED"];

export default function EquipmentForm() {
  const { id } = useParams();
  const editing = id !== undefined && id !== "new";
  const nav = useNavigate();
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({
    code: "", name: "", type: "", manufacturer: "", model: "",
    serial_number: "", location: "", criticality: "MEDIUM",
    status: "OPERATIONAL", installed_at: "", commissioned_at: "",
  });

  useEffect(() => {
    if (!editing) return;
    api.equipmentGet(Number(id))
      .then((e) => setF({
        code: e.code, name: e.name, type: e.type, manufacturer: e.manufacturer,
        model: e.model, serial_number: e.serial_number, location: e.location,
        criticality: e.criticality, status: e.status,
        installed_at: e.installed_at ?? "", commissioned_at: e.commissioned_at ?? "",
      }))
      .catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }, [editing, id]);

  function set(k: string, v: string) {
    setF((p) => ({ ...p, [k]: v }));
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setErr("");
    setBusy(true);
    const body: Record<string, unknown> = { ...f };
    if (!body.installed_at) delete body.installed_at;
    if (!body.commissioned_at) delete body.commissioned_at;
    try {
      const saved = editing
        ? await api.equipmentUpdate(Number(id), body)
        : await api.equipmentCreate(body);
      nav(`/equipment/${saved.id}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  const textFields: [string, string][] = [
    ["code", "EQUIPMENT CODE (E.G. P-204)"], ["name", "NAME"], ["type", "TYPE (E.G. CENTRIFUGAL PUMP)"],
    ["manufacturer", "MANUFACTURER"], ["model", "MODEL"], ["serial_number", "SERIAL NUMBER"],
    ["location", "LOCATION"], ["installed_at", "INSTALLED (YYYY-MM-DD, OPTIONAL)"],
    ["commissioned_at", "COMMISSIONED (YYYY-MM-DD, OPTIONAL)"],
  ];

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">{editing ? "Edit Equipment" : "Register Equipment"}</h1>
          <p className="page-sub">Saved to your company only. Code must be unique per company.</p>
        </div>
      </div>
      <div className="panel" style={{ maxWidth: 640 }}>
        {err && <div className="alert alert-error">{err}</div>}
        <form onSubmit={submit}>
          {textFields.map(([k, label]) => (
            <div className="field" key={k}>
              <label>{label}</label>
              <input value={(f as Record<string, string>)[k]} onChange={(e) => set(k, e.target.value)} />
            </div>
          ))}
          <div className="grid grid-2">
            <div className="field">
              <label>CRITICALITY</label>
              <select value={f.criticality} onChange={(e) => set("criticality", e.target.value)}
                style={{ width: "100%", padding: 11, borderRadius: 8, background: "#081627", color: "var(--text)", border: "1px solid var(--border)" }}>
                {CRITS.map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
            <div className="field">
              <label>STATUS</label>
              <select value={f.status} onChange={(e) => set("status", e.target.value)}
                style={{ width: "100%", padding: 11, borderRadius: 8, background: "#081627", color: "var(--text)", border: "1px solid var(--border)" }}>
                {STATUSES.map((s) => <option key={s}>{s}</option>)}
              </select>
            </div>
          </div>
          <button className="btn" disabled={busy}>{busy ? "Saving…" : editing ? "Save changes" : "Register"}</button>
        </form>
        <div className="auth-switch"><Link to="/equipment">Back to fleet</Link></div>
      </div>
    </div>
  );
}
