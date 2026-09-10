import { useEffect, useState } from "react";
import { api } from "../api";
import HealthPanel from "../components/HealthPanel";

export default function SystemHealth() {
  const [sov, setSov] = useState<Record<string, string | boolean> | null>(null);

  useEffect(() => {
    api.sovereignty().then(setSov).catch(() => setSov(null));
  }, []);

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">System Health</h1>
          <p className="page-sub">Live status of backend, database, storage, AI, RAG and engines</p>
        </div>
      </div>
      <HealthPanel />
      {sov && (
        <div className="panel" style={{ marginTop: 16 }}>
          <h3 style={{ marginTop: 0 }}>Sovereignty Configuration</h3>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, fontSize: 13 }}>
            {Object.entries(sov).map(([k, v]) => (
              <div key={k} style={{ display: "flex", justifyContent: "space-between" }}>
                <span style={{ color: "var(--muted)" }}>{k.replace(/_/g, " ")}</span>
                <strong>{String(v)}</strong>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}