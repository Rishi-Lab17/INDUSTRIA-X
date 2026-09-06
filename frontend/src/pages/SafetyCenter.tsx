import { useEffect, useState } from "react";
import { api } from "../api";
import { useRole } from "../components/equipment";

export default function SafetyCenter() {
  const { canWrite } = useRole();
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.verificationSafetyCenter().then((r) => setData(r)).catch((e) => setErr(String(e)));
  }, []);

  if (err) return <div className="alert alert-error">{err}</div>;
  if (!data) return <div>Loading safety center…</div>;

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Safety Center</h1>
          <p className="page-sub">Active safety reviews, blocked verifications, hazards, and permits</p>
        </div>
      </div>
      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        <div className="panel"><div className="stat-label">ACTIVE REVIEWS</div><div className="stat-num">{(data.active_reviews as number) || 0}</div></div>
        <div className="panel"><div className="stat-label">BLOCKED</div><div className="stat-num" style={{ color: "var(--critical)" }}>{(data.blocked as number) || 0}</div></div>
        <div className="panel"><div className="stat-label">HIGH RISK</div><div className="stat-num" style={{ color: "var(--warning)" }}>{(data.high_risk as number) || 0}</div></div>
      </div>
      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        <div className="panel"><div className="stat-label">AWAITING APPROVAL</div><div className="stat-num" style={{ color: "var(--success)" }}>{(data.awaiting_approval as number) || 0}</div></div>
        <div className="panel"><div className="stat-label">EXPIRED PERMITS</div><div className="stat-num" style={{ color: "var(--critical)" }}>{(data.expired_permits as number) || 0}</div></div>
        <div className="panel"><div className="stat-label">OPEN HAZARDS</div><div className="stat-num" style={{ color: "var(--warning)" }}>{(data.open_hazards as number) || 0}</div></div>
      </div>
      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Safety Status Summary</h3>
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          All values are real backend data. Safety gate is a backend-enforced blocking control, not a UI badge.
          Platform workflow policies, not universal industrial safety standards.
        </div>
      </div>
    </div>
  );
}
