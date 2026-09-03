import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import HealthPanel from "../components/HealthPanel";

export default function Dashboard() {
  const { user, company } = useAuth();
  const [sov, setSov] = useState<Record<string, string | boolean> | null>(null);
  const [users, setUsers] = useState<{ email: string; role: string; name: string }[]>([]);

  useEffect(() => {
    api.sovereignty().then(setSov).catch(() => setSov(null));
    api.users().then((u) => setUsers(u.users)).catch(() => setUsers([]));
  }, []);

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Command Dashboard</h1>
          <p className="page-sub">
            Welcome, {user?.name} — {user?.role} @ {company}. All data below is live from the backend.
          </p>
        </div>
      </div>

      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        <div className="panel">
          <div className="stat-num">{users.length}</div>
          <div className="stat-label">COMPANY USERS</div>
        </div>
        <div className="panel">
          <div className="stat-num">{sov ? String(sov.ai_active_model).toUpperCase() : "…"}</div>
          <div className="stat-label">ACTIVE AI MODEL</div>
        </div>
        <div className="panel">
          <div className="stat-num">{sov && sov.external_ai === "BLOCKED" ? "BLOCKED" : "…"}</div>
          <div className="stat-label">EXTERNAL AI</div>
        </div>
      </div>

      <div className="grid grid-2">
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Sovereignty Status</h3>
          {!sov ? (
            <div style={{ color: "var(--muted)" }}>Loading…</div>
          ) : (
            (["ai_inference", "document_processing", "knowledge_base", "vector_db",
              "industrial_data", "external_ai", "external_fallback"] as const).map((k) => (
              <div className="kv" key={k}>
                <span>{k.toUpperCase().replaceAll("_", " ")}</span>
                <span>{String(sov[k])}</span>
              </div>
            ))
          )}
          {sov && <div style={{ marginTop: 10, fontSize: 12, color: "var(--muted)" }}>{String(sov.note)}</div>}
        </div>

        <div className="panel">
          <h3 style={{ marginTop: 0 }}>System Health</h3>
          <HealthPanel />
        </div>
      </div>

      <div className="panel" style={{ marginTop: 16 }}>
        <h3 style={{ marginTop: 0 }}>Team ({users.length})</h3>
        <table className="table">
          <thead>
            <tr><th>Name</th><th>Email</th><th>Role</th></tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.email}><td>{u.name}</td><td>{u.email}</td><td>{u.role}</td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
