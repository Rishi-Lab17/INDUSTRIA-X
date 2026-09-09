import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "../api";
import { useRole } from "../components/equipment";

interface CaseData {
  id: number;
  case_number: string;
  title: string;
  status: string;
  priority: string;
  severity: string;
  root_cause: string;
  root_cause_confidence: string;
  summary: string;
  opened_at: string;
  closed_by?: number;
}

interface TimelineEvent {
  action: string;
  detail: Record<string, unknown>;
  user_id: number | null;
  created_at: string;
}

export default function CaseDetail() {
  const { id } = useParams<{ id: string }>();
  const { canWrite } = useRole();
  const [data, setData] = useState<CaseData | null>(null);
  const [err, setErr] = useState("");
  const [activeTab, setActiveTab] = useState("overview");

  function load() {
    if (!id) return;
    api.caseGet9(Number(id)).then((r) => setData(r as unknown as CaseData)).catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }
  useEffect(() => { load(); }, [id]);

  if (err) return <div className="alert alert-error">{err}</div>;
  if (!data) return <div>Loading case…</div>;

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">{data.case_number}</h1>
          <p className="page-sub">{data.title || "Case Detail"} · {data.status || "OPEN"}</p>
        </div>
        {canWrite && <button className="btn btn-ghost" onClick={() => window.location.hash = `#/cases/${id}/edit`}>Edit</button>}
      </div>
      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        <div className="panel"><div className="stat-label">PRIORITY</div><div className="stat-num">{data.priority}</div></div>
        <div className="panel"><div className="stat-label">SEVERITY</div><div className="stat-num">{data.severity}</div></div>
        <div className="panel"><div className="stat-label">ROOT CAUSE</div><div className="stat-num" style={{ fontSize: 14 }}>{data.root_cause_confidence || "N/A"}</div></div>
      </div>
      <div className="panel" style={{ marginBottom: 16 }}>
        <p>{data.summary || "No summary provided."}</p>
      </div>
      <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
        {["overview", "timeline", "actions", "memory", "lineage"].map(t => (
          <button key={t} className={`btn ${activeTab === t ? "btn-primary" : "btn-ghost"}`} onClick={() => setActiveTab(t)}>{t.charAt(0).toUpperCase() + t.slice(1)}</button>
        ))}
      </div>
      {activeTab === "timeline" && <CaseTimeline cid={Number(id)} />}
      {activeTab === "actions" && <CaseActions cid={Number(id)} />}
      {activeTab === "memory" && <CaseMemory cid={Number(id)} />}
      {activeTab === "lineage" && <CaseLineage cid={Number(id)} />}
    </div>
  );
}

function CaseTimeline({ cid }: { cid: number }) {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  useEffect(() => { api.caseTimeline9(cid).then(r => setEvents((r.events as unknown as TimelineEvent[]) || [])).catch(() => {}); }, [cid]);
  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Timeline</h2>
      {events.map((e, i) => (
        <div key={i} className="panel" style={{ marginBottom: 8 }}>
          <strong>{e.action}</strong> · {e.created_at} — {JSON.stringify(e.detail)}
        </div>
      ))}
      {events.length === 0 && <div style={{ color: "var(--muted)" }}>No events</div>}
    </div>
  );
}

function CaseActions({ cid }: { cid: number }) {
  const [busy, setBusy] = useState(false);
  async function addAction() {
    setBusy(true);
    try { await api.caseActions9(cid, { action_type: "CORRECTIVE", description: "Corrective action", priority: "MEDIUM" }); alert("Action added"); } catch (e: any) { alert(e.message); } finally { setBusy(false); }
  }
  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Actions</h2>
      <button className="btn btn-primary" onClick={addAction} disabled={busy}>Add Corrective Action</button>
      <div style={{ color: "var(--muted)", marginTop: 12 }}>No actions yet</div>
    </div>
  );
}

function CaseMemory({ cid }: { cid: number }) {
  const [memories, setMemories] = useState<Record<string, unknown>[]>([]);
  const [feedback, setFeedback] = useState("");
  useEffect(() => { api.caseMemoryList9().then(r => setMemories((r.memories as Record<string, unknown>[]) || [])).catch(() => {}); }, []);
  async function submitFeedback(mid: number) {
    try { await api.caseMemoryFeedback9(mid, { feedback: feedback || "USEFUL" }); alert("Feedback submitted"); } catch (e: any) { alert(e.message); }
  }
  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Case Memory</h2>
      <div className="grid grid-2" style={{ marginBottom: 16 }}>
        <div className="panel"><div className="stat-label">VERIFIED MEMORIES</div><div className="stat-num">{memories.filter((m: any) => m.reliability === "VERIFIED").length}</div></div>
      </div>
      {memories.map((m, i) => (
        <div key={i} className="panel" style={{ marginBottom: 8 }}>
          <strong>{(m.failure_mode as string) || "Unknown"}</strong> — {(m.root_cause as string) || ""}
          <div style={{ fontSize: 12, color: "var(--muted)" }}>Reliability: {(m.reliability as string)} · <input style={{ width: 120 }} value={feedback} onChange={e => setFeedback(e.target.value)} /> <button className="btn btn-ghost" onClick={() => submitFeedback(m.id as number)}>Submit</button></div>
        </div>
      ))}
      {memories.length === 0 && <div style={{ color: "var(--muted)" }}>No case memories yet</div>}
    </div>
  );
}

function CaseLineage({ cid }: { cid: number }) {
  const [nodes, setNodes] = useState<Record<string, unknown>[]>([]);
  useEffect(() => { api.caseLineageGet9(cid).then(r => setNodes((r.nodes as Record<string, unknown>[]) || [])).catch(() => {}); }, [cid]);
  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Data Lineage</h2>
      <div className="grid grid-2" style={{ marginBottom: 16 }}>
        <div className="panel"><div className="stat-label">NODES</div><div className="stat-num">{nodes.length}</div></div>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {nodes.map((n, i) => (
          <div key={i} className="panel" style={{ padding: "8px 16px" }}>
            {(n.label as string) || (n.node_type as string)} ({n.node_id as string})
          </div>
        ))}
      </div>
      {nodes.length === 0 && <div style={{ color: "var(--muted)" }}>No lineage nodes</div>}
    </div>
  );
}
