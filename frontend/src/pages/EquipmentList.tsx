import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Equipment } from "../api";
import { critColor, statusColor, useRole } from "../components/equipment";

export default function EquipmentList() {
  const { canWrite } = useRole();
  const [items, setItems] = useState<Equipment[]>([]);
  const [q, setQ] = useState("");
  const [err, setErr] = useState("");

  function load(query: string) {
    api.equipmentList(query || undefined)
      .then((r) => setItems(r.equipment))
      .catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }

  useEffect(() => load(""), []);
  useEffect(() => {
    const t = setTimeout(() => load(q), 300);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Equipment Fleet</h1>
          <p className="page-sub">Digital passports for this company&apos;s assets only.</p>
        </div>
        {canWrite && <Link to="/equipment/new"><button className="btn btn-ghost">+ Register equipment</button></Link>}
      </div>

      {err && <div className="alert alert-error">{err}</div>}

      <div className="field" style={{ maxWidth: 420 }}>
        <label>SEARCH CODE / NAME</label>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="P-204…" />
      </div>

      {items.length === 0 ? (
        <div className="panel">No equipment registered yet.</div>
      ) : (
        <div className="grid grid-3">
          {items.map((e) => (
            <Link key={e.id} to={`/equipment/${e.id}`} style={{ textDecoration: "none", color: "inherit" }}>
              <div className="panel">
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <b>{e.code}</b>
                  <span className="badge">
                    <span className={`dot ${statusColor(e.status)}`} />{e.status.replaceAll("_", " ")}
                  </span>
                </div>
                <div style={{ margin: "8px 0", fontSize: 15 }}>{e.name}</div>
                <div style={{ fontSize: 12, color: "var(--muted)" }}>{e.type} · {e.location || "—"}</div>
                <div style={{ marginTop: 10, fontSize: 12 }}>
                  CRITICALITY: <b style={{ color: critColor(e.criticality) }}>{e.criticality}</b>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
