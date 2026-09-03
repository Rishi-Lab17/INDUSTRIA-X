import { useEffect, useState } from "react";
import { api } from "../api";

function dot(status: string) {
  if (status === "ONLINE") return "dot-online";
  if (status === "ERROR") return "dot-offline";
  return "dot-warn";
}

export default function HealthPanel() {
  const [data, setData] = useState<{ status: string; services: Record<string, { status: string; detail: string }> } | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.health().then(setData).catch((e) => setErr(e.message));
  }, []);

  if (err) return <div className="alert alert-error">Backend unreachable: {err}</div>;
  if (!data) return <div style={{ color: "var(--muted)" }}>Probing services…</div>;

  return (
    <div>
      <div className="badge" style={{ marginBottom: 12 }}>
        <span className={`dot ${dot(data.status)}`} />
        <span>BACKEND: {data.status}</span>
      </div>
      {Object.entries(data.services).map(([k, v]) => (
        <div className="kv" key={k}>
          <span>{k.toUpperCase()}</span>
          <span>
            <span className={`dot ${dot(v.status)}`} style={{ marginRight: 8 }} />
            {v.status} — <span style={{ color: "var(--muted)" }}>{v.detail}</span>
          </span>
        </div>
      ))}
    </div>
  );
}
