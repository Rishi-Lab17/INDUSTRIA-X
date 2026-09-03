import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type Equipment } from "../api";
import { critColor, statusColor, useRole } from "../components/equipment";

interface HistItem {
  id: number;
  user_id: number;
  action: string;
  detail: string;
  created_at: string;
}

export default function EquipmentDetail() {
  const { id } = useParams();
  const eid = Number(id);
  const nav = useNavigate();
  const { canWrite, canDelete, canHistory } = useRole();
  const [eq, setEq] = useState<Equipment | null>(null);
  const [qr, setQr] = useState<string | null>(null);
  const [hist, setHist] = useState<HistItem[]>([]);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");

  useEffect(() => {
    api.equipmentGet(eid)
      .then(setEq)
      .catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
    api.equipmentQr(eid)
      .then((b) => setQr(URL.createObjectURL(b)))
      .catch(() => setQr(null));
    api.equipmentHistory(eid)
      .then((r) => setHist(r.history))
      .catch(() => setHist([]));
    return () => {
      if (qr) URL.revokeObjectURL(qr);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eid]);

  async function deactivate() {
    if (!window.confirm(`Deactivate ${eq?.code}? History is preserved.`)) return;
    setErr("");
    try {
      const r = await api.equipmentDelete(eid);
      setOk(r.message);
      setTimeout(() => nav("/equipment"), 1000);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Deactivation failed");
    }
  }

  if (!eq) return <div>{err ? <div className="alert alert-error">{err}</div> : "Loading passport…"}</div>;

  const rows: [string, string][] = [
    ["EQUIPMENT ID", eq.code], ["NAME", eq.name], ["TYPE", eq.type],
    ["MANUFACTURER", eq.manufacturer || "—"], ["MODEL", eq.model || "—"],
    ["SERIAL NUMBER", eq.serial_number || "—"], ["LOCATION", eq.location || "—"],
    ["INSTALLED", eq.installed_at ?? "—"], ["COMMISSIONED", eq.commissioned_at ?? "—"],
    ["CREATED", eq.created_at], ["UPDATED", eq.updated_at],
  ];

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">{eq.code} — {eq.name}</h1>
          <p className="page-sub">Equipment Digital Passport</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {canWrite && <Link to={`/equipment/${eid}/edit`}><button className="btn btn-ghost">Edit</button></Link>}
          {canDelete && <button className="btn btn-ghost" onClick={deactivate}>Deactivate</button>}
        </div>
      </div>

      {err && <div className="alert alert-error">{err}</div>}
      {ok && <div className="alert alert-ok">{ok}</div>}

      <div className="grid grid-2">
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Passport</h3>
          <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
            <span className="badge"><span className={`dot ${statusColor(eq.status)}`} />{eq.status.replaceAll("_", " ")}</span>
            <span className="badge">CRITICALITY: <b style={{ color: critColor(eq.criticality) }}>{eq.criticality}</b></span>
          </div>
          {rows.map(([k, v]) => (
            <div className="kv" key={k}><span>{k}</span><span>{v}</span></div>
          ))}
          {Object.keys(eq.metadata).length > 0 && (
            <div className="kv"><span>METADATA</span><span>{JSON.stringify(eq.metadata)}</span></div>
          )}
        </div>

        <div>
          <div className="panel" style={{ textAlign: "center", marginBottom: 16 }}>
            <h3 style={{ marginTop: 0 }}>Asset QR</h3>
            {qr ? (
              <img src={qr} alt={`QR for ${eq.code}`} style={{ width: 220, height: 220, borderRadius: 8, background: "#fff", padding: 8 }} />
            ) : (
              <div style={{ color: "var(--muted)" }}>QR unavailable</div>
            )}
            <div style={{ marginTop: 8, fontSize: 12, color: "var(--muted)" }}>
              Scan to open passport /equipment/{eq.id}
            </div>
          </div>

          <div className="panel">
            <h3 style={{ marginTop: 0 }}>History</h3>
            {!canHistory ? (
              <div style={{ fontSize: 13, color: "var(--muted)" }}>History is visible to admins and engineers.</div>
            ) : hist.length === 0 ? (
              <div style={{ fontSize: 13, color: "var(--muted)" }}>No recorded events.</div>
            ) : (
              hist.map((h) => (
                <div className="kv" key={h.id}>
                  <span>{h.action.replaceAll("_", " ")}</span>
                  <span style={{ color: "var(--muted)", fontSize: 12 }}>{h.created_at}</span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
