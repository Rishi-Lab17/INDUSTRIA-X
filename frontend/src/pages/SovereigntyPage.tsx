import { useEffect, useState } from "react";
import { api } from "../api";
import { useRole } from "../components/equipment";

interface SovereigntyData {
  status: string;
  checks: { check: string; status: string; detail: string }[];
  config: Record<string, unknown>;
}

export default function SovereigntyPage() {
  const { canWrite } = useRole();
  const [data, setData] = useState<SovereigntyData | null>(null);
  const [err, setErr] = useState("");
  const [config, setConfig] = useState<Record<string, string>>({});

  useEffect(() => {
    api.caseSovereignty9().then(r => setData(r as unknown as SovereigntyData)).catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }, []);

  async function saveConfig() {
    try {
      await api.caseSovereigntyUpdate9(config);
      alert("Sovereignty config updated");
    } catch (e: any) { alert(e.message); }
  }

  if (err) return <div className="alert alert-error">{err}</div>;
  if (!data) return <div>Loading sovereignty…</div>;

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Sovereignty Center</h1>
          <p className="page-sub">Local-processing guarantees · status: {data.status}</p>
        </div>
        {canWrite && <button className="btn btn-ghost" onClick={saveConfig}>Save Config</button>}
      </div>
      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        <div className="panel"><div className="stat-label">OVERALL</div><div className="stat-num" style={{ color: data.status === "PASS" ? "var(--success)" : "var(--warning)" }}>{data.status}</div></div>
        <div className="panel"><div className="stat-label">EXTERNAL AI</div><div className="stat-num" style={{ color: "var(--critical)" }}>{(data.config as Record<string, string>).external_ai_policy || "BLOCKED"}</div></div>
        <div className="panel"><div className="stat-label">STORAGE</div><div className="stat-num">{(data.config as Record<string, string>).document_storage || "LOCAL"}</div></div>
      </div>
      <div className="panel" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Checks</h3>
        {data.checks.map((ch, i) => (
          <div key={i} style={{ padding: "8px 0", borderBottom: "1px solid var(--border)" }}>
            <span className={`badge badge--${ch.status.toLowerCase()}`}>{ch.check}</span>{" "}{ch.detail}
          </div>
        ))}
      </div>
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Configuration</h3>
        {Object.entries(data.config as Record<string, string>).map(([k, v]) => (
          <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "4px 0", fontSize: 13 }}>
            <span style={{ color: "var(--muted)" }}>{k}</span><strong>{v}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}
