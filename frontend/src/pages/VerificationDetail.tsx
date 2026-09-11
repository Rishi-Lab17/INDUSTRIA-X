import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { api, type CaseEvidence, type CaseHypothesis } from "../api";
import { useRole } from "../components/equipment";

const SEV_COLOR: Record<string, string> = {
  NORMAL: "var(--success)", MINOR: "var(--accent)",
  MODERATE: "var(--warning)", SEVERE: "var(--critical)", CRITICAL: "var(--critical)",
};

export default function VerificationDetail() {
  const { id } = useParams();
  const vid = Number(id);
  const { canWrite, role } = useRole();
  const [v, setV] = useState<Record<string, unknown> | null>(null);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  // actions
  const [statusAction, setStatusAction] = useState("");
  const [obsType, setObsType] = useState("VISUAL");
  const [obsDesc, setObsDesc] = useState("");
  const [obsSev, setObsSev] = useState("NORMAL");
  const [measParam, setMeasParam] = useState("");
  const [measValue, setMeasValue] = useState("");
  const [measUnit, setMeasUnit] = useState("");
  const [comments, setComments] = useState("");

  const load = useCallback(() => {
    api.verificationGet(vid).then((r) => setV(r)).catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [vid]);

  useEffect(load, [load]);

  async function act(p: Promise<unknown>, msg?: string) {
    setErr(""); setOk("");
    try { await p; if (msg) setOk(msg); load(); }
    catch (e) { setErr(e instanceof Error ? e.message : "Action failed"); }
  }

  async function doStatus() {
    if (!statusAction) return;
    await act(api.verificationUpdateStatus(vid, statusAction), `Status → ${statusAction}`);
    setStatusAction("");
  }

  async function evaluateSafetyGate() {
    await act(api.verificationEvaluateSafetyGate(vid), "Safety gate evaluated");
  }

  async function addObservation(e: React.FormEvent) {
    e.preventDefault();
    if (!obsDesc.trim()) return;
    await act(api.verificationAddObservation(vid, {
      equipment_id: (v as Record<string, unknown>)?.equipment_id || 0,
      observation_type: obsType, description: obsDesc.trim(), severity: obsSev,
    }), "Observation added.");
    setObsDesc("");
  }

  async function addMeasurement(e: React.FormEvent) {
    e.preventDefault();
    const val = Number(measValue);
    if (!measParam || isNaN(val) || !measUnit) { setErr("Parameter, value, and unit required."); return; }
    await act(api.verificationAddMeasurement(vid, {
      equipment_id: (v as Record<string, unknown>)?.equipment_id || 0,
      parameter: measParam, value: val, unit: measUnit,
    }), "Measurement recorded.");
    setMeasParam(""); setMeasValue(""); setMeasUnit("");
  }

  async function evaluateSafety() {
    await act(api.verificationEvaluateSafetyGate(vid), "Safety gate evaluated.");
  }

  async function requestApproval() {
    await act(api.verificationRequestApproval(vid, { approval_level: "TECHNICIAN_REVIEWER" }), "Approval requested.");
  }

  async function approve() {
    const r = window.confirm("Approve this verification? This action is audited.");
    if (!r) return;
    await act(api.verificationApprove(vid, { decision: "APPROVE", reason: "Verified and safe." }), "Approved.");
  }

  async function reject() {
    const r = window.confirm("Reject this verification? A reason is required.");
    if (!r) return;
    const reason = prompt("Reason for rejection:");
    if (!reason) return;
    await act(api.verificationReject(vid, { decision: "REJECT", reason }), "Rejected.");
  }

  if (!v) return <div>{err ? <div className="alert alert-error">{err}</div> : "Loading verification…"}</div>;
  const inv = v.investigation as Record<string, unknown> | null;
  const eq = v.equipment as Record<string, unknown> | null;
  const scorecard = api.verificationScorecard(vid);

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Verification #{vid}</h1>
          <p className="page-sub">
            {(inv?.title as string) || "—"} · <b style={{ color: (v.priority as string) === "CRITICAL" ? "var(--critical)" : "var(--warning)" }}>{(v.priority as string)}</b> ·
            <span className="badge" style={{ background: "var(--accent)" }}>{(v.status as string)}</span>
          </p>
          <p className="page-sub">{(eq?.name as string) || "—"} · {(inv?.problem_statement as string) || "—"}</p>
        </div>
        {canWrite && (
          <div style={{ display: "flex", gap: 8 }}>
            <select aria-label="Change status" defaultValue="" onChange={(e) => { setStatusAction(e.target.value); }} style={selStyle}>
              {["PENDING","ASSIGNED","IN_REVIEW","INSPECTION_REQUIRED","AWAITING_EVIDENCE","SAFETY_REVIEW","AWAITING_APPROVAL","APPROVED","REJECTED","ESCALATED","BLOCKED","COMPLETED"].filter((s) => s !== (v.status as string)).map((s) => <option key={s}>{s}</option>)}
            </select>
            <button className="btn" onClick={doStatus}>Set</button>
          </div>
        )}
      </div>
      {err && <div className="alert alert-error">{err}</div>}
      {ok && <div className="alert alert-ok">{ok}</div>}

      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        <div className="panel"><div className="stat-label">STATUS</div><div className="stat-num">{(v.status as string)}</div></div>
        <div className="panel"><div className="stat-label">PRIORITY</div><div className="stat-num" style={{ color: (v.priority as string) === "HIGH" || (v.priority as string) === "CRITICAL" ? "var(--critical)" : "var(--accent)" }}>{(v.priority as string)}</div></div>
        <div className="panel"><div className="stat-label">ASSIGNED</div><div className="stat-num" style={{ fontSize: 14 }}>{(v.assigned_technician_id ? "Technician" : "Unassigned")}</div></div>
      </div>

      <div className="grid grid-2">
        <div className="panel" style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Technician Actions</h3>
          <form onSubmit={addObservation} style={{ marginBottom: 10 }}>
            <div className="grid grid-3">
              <div className="field"><label>TYPE</label><select value={obsType} onChange={(e) => setObsType(e.target.value)} style={selStyle}>
                {["VISUAL","AUDITORY","MEASUREMENT","MECHANICAL","ELECTRICAL","THERMAL","PROCESS","SAFETY","OTHER"].map((t) => <option key={t}>{t}</option>)}
              </select></div>
              <div className="field"><label>SEVERITY</label><select value={obsSev} onChange={(e) => setObsSev(e.target.value)} style={selStyle}>
                {["NORMAL","MINOR","MODERATE","SEVERE","CRITICAL"].map((s) => <option key={s}>{s}</option>)}
              </select></div>
              <div className="field"><label>&nbsp;</label><button className="btn">Add</button></div>
            </div>
            <div className="field"><label>DESCRIPTION</label><input value={obsDesc} onChange={(e) => setObsDesc(e.target.value)} placeholder="Observation…" /></div>
          </form>
          <form onSubmit={addMeasurement} style={{ marginBottom: 10 }}>
            <div className="grid grid-3">
              <div className="field"><label>PARAMETER</label><input value={measParam} onChange={(e) => setMeasParam(e.target.value)} placeholder="Vibration" style={selStyle} /></div>
              <div className="field"><label>VALUE</label><input type="number" value={measValue} onChange={(e) => setMeasValue(e.target.value)} style={selStyle} /></div>
              <div className="field"><label>UNIT</label><input value={measUnit} onChange={(e) => setMeasUnit(e.target.value)} placeholder="mm/s" style={selStyle} /></div>
            </div>
            <button className="btn" type="submit">Record Measurement</button>
          </form>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>Technicians: use observations and measurements to document inspection. Safety gate is backend-enforced.</div>
        </div>

        <div className="panel" style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Safety Gate</h3>
          <button className="btn btn-ghost" onClick={evaluateSafetyGate} style={{ marginBottom: 8 }}>Evaluate Safety Gate</button>
          <div style={{ fontSize: 13 }}>
            <span className="badge">{(v.status as string)}</span>{" "}
            {canWrite && (
              <>
                <button className="linklike" onClick={requestApproval}>Request Approval</button>
                {" "}<button className="linklike" onClick={approve}>Approve</button>
                {" "}<button className="linklike" onClick={reject}>Reject</button>
              </>
            )}
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
            Safety gate is a backend control. AI cannot approve — only authorized humans can.
          </div>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Reason</h3>
        <div style={{ fontSize: 13 }}>{(v.reason as string) || "No reason recorded."}</div>
        {(v.instructions as string) && <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>Instructions: {(v.instructions as string)}</div>}
        {(v.safety_requirements as string) && <div style={{ fontSize: 12, color: "var(--muted)" }}>Safety: {(v.safety_requirements as string)}</div>}
      </div>

      <div className="panel">
        <h3 style={{ marginTop: 0 }}>Timeline</h3>
        <div style={{ fontSize: 13, color: "var(--muted)" }}>
          Created: {(v.created_at as string)?.slice(0, 10)} · Updated: {(v.updated_at as string)?.slice(0, 10)}
          {(v.completed_at ? ` · Completed: ${(v.completed_at as string)?.slice(0, 10)}` : "")}
        </div>
      </div>
    </div>
  );
}

const selStyle: React.CSSProperties = {
  width: "100%", padding: 11, borderRadius: 8, background: "#F8FAFC",
  color: "var(--text)", border: "1px solid var(--border)",
};
