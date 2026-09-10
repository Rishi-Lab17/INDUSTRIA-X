import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import HealthPanel from "../components/HealthPanel";

export default function Dashboard() {
  const { user, company } = useAuth();
  const [sov, setSov] = useState<Record<string, string | boolean> | null>(null);
  const [users, setUsers] = useState<{ email: string; role: string; name: string }[]>([]);
  const [health, setHealth] = useState<Record<string, { status: string; detail: string }> | null>(null);

  useEffect(() => {
    api.sovereignty().then(setSov).catch(() => setSov(null));
    api.users().then((u) => setUsers(u.users)).catch(() => setUsers([]));
    api.health().then((h) => setHealth((h as { services: Record<string, { status: string; detail: string }> }).services)).catch(() => setHealth(null));
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
          <div className="stat-num" style={{ fontSize: 18 }}>{health ? (health["kimi"]?.status === "ONLINE" ? "KIMI ONLINE" : "KIMI OFFLINE") : sov ? String(sov.ai_active_model).toUpperCase() : "…"}</div>
          <div className="stat-label">PRIMARY KIMI K3</div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>{health?.["kimi"]?.detail?.slice(0, 60) ?? (sov?.note ? String(sov.note).slice(0, 60) : "")}</div>
        </div>
        <div className="panel">
          <div className="stat-num" style={{ fontSize: 16 }}>{health ? (health["dev_model"]?.status === "ONLINE" ? "DEV ONLINE" : "DEV OFFLINE") : "…"}</div>
          <div className="stat-label">LOCAL DEV MODEL</div>
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>{health?.["dev_model"]?.detail ?? "Ollama dev model (labelled, never Kimi)"}</div>
        </div>
      </div>
      {health && health["kimi"]?.status !== "ONLINE" && health["dev_model"]?.status !== "ONLINE" && (
        <div className="alert alert-warn" style={{ marginBottom: 16 }}>
          No local AI model is currently connected. <b>PRIMARY KIMI K3</b> is unavailable (2.8T params require datacenter GPUs / on-prem vLLM). <b>DEV MODEL</b> Ollama is not running on this machine. Evidence retrieval, RAG, and investigations work offline; AI generation will return a clear “unavailable” message. Start <span className="mono">ollama run {String(sov?.ai_provider ?? "dev-model")}</span> to enable the labelled dev model — it will never be reported as Kimi K3, and External AI remains <b>{String(sov?.external_ai ?? "BLOCKED")}</b> per sovereignty.
        </div>
      )}
      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        <div className="panel">
          <div className="stat-label">EXTERNAL AI</div>
          <div className="stat-num" style={{ color: sov?.external_ai === "BLOCKED" ? "var(--success)" : "var(--critical)" }}>{sov ? String(sov.external_ai) : "…"}</div>
          <div style={{ fontSize: 11, color: "var(--muted)" }}>Sovereignty: no silent fallback</div>
        </div>
        <div className="panel">
          <div className="stat-label">VECTOR DB</div>
          <div className="stat-num" style={{ fontSize: 18 }}>{health?.["vector_db"]?.status ?? "…"}</div>
          <div style={{ fontSize: 11, color: "var(--muted)" }}>{health?.["vector_db"]?.detail ?? "Local"}</div>
        </div>
        <div className="panel">
          <div className="stat-label">RAG</div>
          <div className="stat-num" style={{ fontSize: 18 }}>{health?.["rag"]?.status ?? "…"}</div>
          <div style={{ fontSize: 11, color: "var(--muted)" }}>{health?.["rag"]?.detail ?? "Local embeddings"}</div>
        </div>
      </div>

      <div className="grid grid-2">
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Sovereignty Status</h3>
          {!sov ? (
            <div style={{ color: "var(--muted)" }}>Loading…</div>
          ) : (
            (["ai_inference", "document_processing", "knowledge_base", "vector_db",
              "industrial_data", "external_ai", "external_fallback",
              "email_delivery"] as const).map((k) => (
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
