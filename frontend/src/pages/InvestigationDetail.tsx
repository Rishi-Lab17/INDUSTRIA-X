import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type CaseEvidence, type CaseHypothesis, type Investigation } from "../api";
import { useRole } from "../components/equipment";
import EvidenceGraph, { type GEdge, type GNode } from "../components/EvidenceGraph";

const BAND_COLOR: Record<string, string> = {
  High: "var(--success)", "Medium-High": "var(--accent)",
  Medium: "var(--warning)", Low: "var(--critical)",
};

const NEXT_STATUSES = ["OPEN", "ANALYZING", "AWAITING_EVIDENCE", "TECHNICIAN_REVIEW",
  "VERIFICATION", "APPROVAL", "RESOLVED", "CLOSED", "ARCHIVED", "READY_FOR_VERIFICATION"];

export default function InvestigationDetail() {
  const { id } = useParams();
  const iid = Number(id);
  const { canWrite, role } = useRole();
  const [inv, setInv] = useState<Investigation | null>(null);
  const [hyps, setHyps] = useState<CaseHypothesis[]>([]);
  const [evidence, setEvidence] = useState<CaseEvidence[]>([]);
  const [graph, setGraph] = useState<{ nodes: GNode[]; edges: GEdge[] } | null>(null);
  const [selNode, setSelNode] = useState<GNode | null>(null);
  const [selEdge, setSelEdge] = useState<GEdge | null>(null);
  const [missing, setMissing] = useState<{ hypothesis_id: number; hypothesis: string; slot: string; title: string; priority: string }[]>([]);
  const [nbe, setNbe] = useState<{ id: number; rank: number; title: string; kind: string; priority: string; effort: string; safety: string; expected_value: string; discriminative_value: number; rationale: Record<string, string>; status: string }[]>([]);
  const [conf, setConf] = useState<{ hypothesis_id: number; title: string; support_score: number; confidence_band: string; trigger: string }[]>([]);
  const [similar, setSimilar] = useState<{ id: number; title: string; similarity: number }[]>([]);
  const [similarNote, setSimilarNote] = useState<string | null>(null);
  const [assumptions, setAssumptions] = useState<{ id: number; text: string; status: string }[]>([]);
  const [conflicts, setConflicts] = useState<{ id: number; description: string; recommendation: string; status: string }[]>([]);
  const [health, setHealth] = useState<Record<string, number | string> | null>(null);
  const [readiness, setReadiness] = useState<{ ready: boolean; state: string; reasons: string[] } | null>(null);
  const [timeline, setTimeline] = useState<{ action: string; created_at: string }[]>([]);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  // forms
  const [evForm, setEvForm] = useState({ type: "SENSOR", title: "", description: "" });
  const [hypTitle, setHypTitle] = useState("");
  const [linkSel, setLinkSel] = useState<Record<number, { eid: string; rel: string }>>({});
  const [simSel, setSimSel] = useState<Record<number, { slot: string; outcome: string }>>({});
  const [simOut, setSimOut] = useState<Record<number, Record<string, unknown> | null>>({});
  const [copilotQ, setCopilotQ] = useState("");
  const [copilotA, setCopilotA] = useState("");

  const load = useCallback(() => {
    api.caseGet(iid).then((r) => setInv(r.investigation)).catch((e) => setErr(e instanceof Error ? e.message : String(e)));
    api.caseHypotheses(iid).then((r) => setHyps(r.hypotheses)).catch(() => undefined);
    api.caseEvidenceList(iid).then((r) => setEvidence(r.evidence)).catch(() => undefined);
    api.caseGraph(iid).then(setGraph).catch(() => undefined);
    api.caseMissing(iid).then((r) => setMissing(r.missing)).catch(() => undefined);
    api.caseNBE(iid).then((r) => setNbe(r.recommendations)).catch(() => undefined);
    api.caseConfidence(iid).then((r) => setConf(r.history)).catch(() => undefined);
    api.caseSimilar(iid).then((r) => {
      setSimilar(r.cases);
      setSimilarNote(r.note);
    }).catch(() => undefined);
    api.caseAssumptions(iid).then((r) => setAssumptions(r.assumptions)).catch(() => undefined);
    api.caseConflicts(iid).then((r) => setConflicts(r.conflicts)).catch(() => undefined);
    api.caseHealth(iid).then(setHealth).catch(() => undefined);
    api.caseReadiness(iid).then(setReadiness).catch(() => undefined);
    api.caseTimeline(iid).then((r) => setTimeline(r.events)).catch(() => undefined);
  }, [iid]);

  useEffect(load, [load]);

  async function act(p: Promise<unknown>, msg?: string) {
    setErr("");
    setOk("");
    try {
      await p;
      if (msg) setOk(msg);
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Action failed");
    }
  }

  async function addEvidence(e: React.FormEvent) {
    e.preventDefault();
    await act(api.caseEvidenceAdd(iid, {
      type: evForm.type, title: evForm.title, description: evForm.description,
    }), "Evidence added.");
    setEvForm({ type: "SENSOR", title: "", description: "" });
  }

  async function generate() {
    setErr("");
    try {
      const r = await api.caseHypothesisGenerate(iid);
      setOk(`Generated ${r.created.length} hypotheses. ${r.notes.join(" ")}` +
        (r.ai.available ? "" : " (AI review unavailable — deterministic only)"));
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Generate failed");
    }
  }

  async function simulate(hid: number) {
    const s = simSel[hid] ?? { slot: "", outcome: "positive" };
    if (!s.slot) {
      setErr("Pick an evidence slot to simulate.");
      return;
    }
    setErr("");
    try {
      const r = await api.caseSimulate(iid, { hypothesis_id: hid, slot: s.slot, outcome: s.outcome });
      setSimOut((m) => ({ ...m, [hid]: r }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Simulation failed");
    }
  }

  async function askCopilot(e: React.FormEvent) {
    e.preventDefault();
    if (!copilotQ.trim()) return;
    setErr("");
    try {
      const r = await api.caseCopilot(iid, copilotQ.trim());
      setCopilotA(r.answer);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Copilot failed");
    }
  }

  if (!inv) return <div>{err ? <div className="alert alert-error">{err}</div> : "Loading case…"}</div>;
  const hypMissing = (hid: number) => missing.filter((m) => m.hypothesis_id === hid);
  const slots = [...new Set(missing.flatMap(() => [])), ...new Set(missing.map((m) => m.slot))];

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">#{inv.id} {inv.title}</h1>
          <p className="page-sub">{inv.category} · <b style={{ color: inv.severity === "CRITICAL" ? "var(--critical)" : "var(--warning)" }}>{inv.severity}</b> · <span className="badge">{inv.status}</span></p>
          <p className="page-sub">{inv.problem_statement}</p>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          {canWrite && (
            <select aria-label="Change status" defaultValue="" onChange={(e) => {
              if (e.target.value) act(api.caseStatus(iid, e.target.value), `Status → ${e.target.value}`);
              e.target.value = "";
            }} style={selStyle}>
              <option value="">Set status…</option>
              {NEXT_STATUSES.filter((s) => s !== inv.status).map((s) => <option key={s}>{s}</option>)}
            </select>
          )}
        </div>
      </div>

      {err && <div className="alert alert-error">{err}</div>}
      {ok && <div className="alert alert-ok">{ok}</div>}

      <div className="grid grid-3" style={{ marginBottom: 16 }}>
        <div className="panel">
          <div className="stat-label">READINESS</div>
          <div className="stat-num" style={{ color: readiness?.ready ? "var(--success)" : "var(--warning)" }}>
            {readiness ? readiness.state.replaceAll("_", " ") : "…"}
          </div>
          {readiness && !readiness.ready && (
            <div style={{ fontSize: 12, color: "var(--muted)" }}>{readiness.reasons.join("; ")}</div>
          )}
        </div>
        <div className="panel">
          <div className="stat-label">EVIDENCE / HYPOTHESES</div>
          <div className="stat-num">{evidence.length} / {hyps.length}</div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>
            health overall: {health ? `${(health.overall as number).toFixed?.(0) ?? health.overall}` : "…"}
          </div>
        </div>
        <div className="panel">
          <div className="stat-label">LEADING HYPOTHESIS</div>
          <div className="stat-num" style={{ fontSize: 18 }}>
            {hyps.length ? `${hyps[0].title} (${hyps[0].support_score})` : "none yet"}
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>
            {hyps.length ? `confidence: ${hyps[0].confidence_band}` : "generate hypotheses below"}
          </div>
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Hypotheses ({hyps.length})</h3>
        {canWrite && (
          <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
            <button className="btn btn-ghost" onClick={generate}>Generate from evidence</button>
            <input value={hypTitle} onChange={(e) => setHypTitle(e.target.value)} placeholder="Custom hypothesis title…"
              style={{ padding: 8, borderRadius: 8, border: "1px solid var(--border)", background: "#081627", color: "var(--text)" }} />
            <button className="btn btn-ghost" onClick={() => {
              if (hypTitle.trim()) act(api.caseHypothesisCreate(iid, { title: hypTitle.trim() }), "Hypothesis added.");
              setHypTitle("");
            }}>Add custom</button>
          </div>
        )}
        {hyps.length === 0 && <div style={{ color: "var(--muted)", fontSize: 13 }}>No hypotheses yet — generate from evidence or add manually.</div>}
        {hyps.map((h) => (
          <div key={h.id} className="panel" style={{ marginBottom: 10, background: "#0B1F33" }}>
            <div style={{ display: "flex", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
              <b>#{h.rank} {h.title}</b>
              <span>
                <span className="badge">support {h.support_score}</span>{" "}
                <span className="badge">contradiction {h.contradiction_score}</span>{" "}
                <span className="badge">coverage {h.completeness}%</span>{" "}
                <b style={{ color: BAND_COLOR[h.confidence_band] ?? "var(--text)" }}>{h.confidence_band}</b>{" "}
                <span className="badge">{h.status}</span>
              </span>
            </div>
            {h.description && <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 4 }}>{h.description}</div>}
            <div className="grid grid-3" style={{ marginTop: 8 }}>
              <div>
                <div style={{ fontSize: 12, color: "var(--success)", fontWeight: 700 }}>SUPPORTING ({h.supporting.length})</div>
                {h.supporting.map((e) => <div key={e.id} style={{ fontSize: 12 }}>+ {e.title} <span style={{ color: "var(--muted)" }}>[{e.type}]</span></div>)}
              </div>
              <div>
                <div style={{ fontSize: 12, color: "var(--critical)", fontWeight: 700 }}>CONTRADICTING ({h.contradicting.length})</div>
                {h.contradicting.map((e) => <div key={e.id} style={{ fontSize: 12 }}>− {e.title} <span style={{ color: "var(--muted)" }}>[{e.type}]</span></div>)}
              </div>
              <div>
                <div style={{ fontSize: 12, color: "var(--muted)", fontWeight: 700 }}>NEUTRAL ({h.neutral.length})</div>
                {h.neutral.map((e) => <div key={e.id} style={{ fontSize: 12 }}>= {e.title}</div>)}
              </div>
            </div>
            {hypMissing(h.id).length > 0 && (
              <div style={{ fontSize: 12, color: "var(--warning)", marginTop: 6 }}>
                Missing: {hypMissing(h.id).map((m) => `${m.title} (${m.priority})`).join("; ")}
              </div>
            )}
            {canWrite && (
              <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
                <select aria-label="Link evidence"
                  value={linkSel[h.id]?.eid ?? ""}
                  onChange={(e) => setLinkSel({ ...linkSel, [h.id]: { ...(linkSel[h.id] ?? { rel: "SUPPORTS" }), eid: e.target.value } })}
                  style={{ ...selStyle, width: 220 }}>
                  <option value="">Link evidence…</option>
                  {evidence.map((e) => <option key={e.id} value={e.id}>E-{e.id} {e.title}</option>)}
                </select>
                <select aria-label="Relation"
                  value={linkSel[h.id]?.rel ?? "SUPPORTS"}
                  onChange={(e) => setLinkSel({ ...linkSel, [h.id]: { ...(linkSel[h.id] ?? { eid: "" }), rel: e.target.value } })}
                  style={{ ...selStyle, width: 150 }}>
                  {["SUPPORTS", "CONTRADICTS", "NEUTRAL"].map((r) => <option key={r}>{r}</option>)}
                </select>
                <button className="btn btn-ghost" style={{ padding: "6px 12px" }} onClick={() => {
                  const s = linkSel[h.id];
                  if (s?.eid) act(api.caseLink(iid, h.id, { evidence_id: Number(s.eid), relation: s.rel }));
                }}>Link</button>
                <select aria-label="Set status" defaultValue="" onChange={(e) => {
                  if (e.target.value) act(api.caseHypothesisStatus(iid, h.id, e.target.value));
                  e.target.value = "";
                }} style={{ ...selStyle, width: 150 }}>
                  <option value="">Set status…</option>
                  {["ACTIVE", "SUPPORTED", "WEAKENED", "REJECTED", "CONFIRMED", "UNKNOWN"].map((s) => <option key={s}>{s}</option>)}
                </select>
              </div>
            )}
            <div style={{ marginTop: 8, fontSize: 12 }}>
              <b>What-if:</b>{" "}
              <select aria-label="Evidence slot"
                value={simSel[h.id]?.slot ?? ""}
                onChange={(e) => setSimSel({ ...simSel, [h.id]: { ...(simSel[h.id] ?? { outcome: "positive" }), slot: e.target.value } })}
                style={{ ...selStyle, width: 200, display: "inline-block" }}>
                <option value="">Pick evidence…</option>
                {slots.map((s) => <option key={s} value={s}>{s}</option>)}
              </select>{" "}
              <select aria-label="Outcome"
                value={simSel[h.id]?.outcome ?? "positive"}
                onChange={(e) => setSimSel({ ...simSel, [h.id]: { ...(simSel[h.id] ?? { slot: "" }), outcome: e.target.value } })}
                style={{ ...selStyle, width: 120, display: "inline-block" }}>
                <option value="positive">positive</option>
                <option value="negative">negative</option>
              </select>{" "}
              <button className="btn btn-ghost" style={{ padding: "6px 12px" }} onClick={() => simulate(h.id)}>Simulate</button>
              {simOut[h.id] !== undefined && simOut[h.id] !== null && (
                <div style={{ marginTop: 4, color: "var(--muted)" }}>
                  deltas: {JSON.stringify((simOut[h.id] as { deltas: unknown }).deltas)} ·
                  ranks after: {JSON.stringify((simOut[h.id] as { ranks_after: unknown }).ranks_after)}
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="grid grid-2">
        <div className="panel" style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Evidence ({evidence.length})</h3>
          <form onSubmit={addEvidence} style={{ marginBottom: 10 }}>
            <div className="grid grid-3">
              <div className="field">
                <label>TYPE</label>
                <select value={evForm.type} onChange={(e) => setEvForm({ ...evForm, type: e.target.value })} style={selStyle}>
                  {["SENSOR", "DOCUMENT", "IMAGE", "OCR", "RAG", "TECHNICIAN", "MANUAL", "MAINTENANCE_HISTORY", "INSPECTION", "SYSTEM"].map((t) => <option key={t}>{t}</option>)}
                </select>
              </div>
              <div className="field">
                <label>TITLE</label>
                <input value={evForm.title} onChange={(e) => setEvForm({ ...evForm, title: e.target.value })} />
              </div>
              <div className="field">
                <label>&nbsp;</label>
                <button className="btn">Add evidence</button>
              </div>
            </div>
            <div className="field">
              <label>DESCRIPTION</label>
              <input value={evForm.description} onChange={(e) => setEvForm({ ...evForm, description: e.target.value })} />
            </div>
          </form>
          {role === "TECHNICIAN" && (
            <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>
              Technicians may add TECHNICIAN / MANUAL observations only.
            </div>
          )}
          {evidence.map((e) => (
            <div className="kv" key={e.id}>
              <span><b>E-{String(e.id).padStart(3, "0")}</b> {e.title} <span style={{ color: "var(--muted)" }}>[{e.type}]</span></span>
              <span style={{ fontSize: 11, color: "var(--muted)" }}>
                {e.created_at.slice(0, 10)}
                {canWrite && (
                  <> · <button className="linklike" onClick={() => act(api.caseEvidenceArchive(iid, e.id), "Archived.")}>archive</button></>
                )}
              </span>
            </div>
          ))}
        </div>

        <div className="panel" style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Next-Best-Evidence</h3>
          <NBEList iid={iid} items={nbe} onDone={() => load()} canWrite={canWrite} />
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Evidence Graph</h3>
        {graph ? (
          <EvidenceGraph nodes={graph.nodes} edges={graph.edges}
            onSelect={(n, e) => { setSelNode(n); setSelEdge(e); }} />
        ) : <div style={{ color: "var(--muted)" }}>Loading graph…</div>}
        {(selNode || selEdge) && (
          <div className="panel" style={{ marginTop: 10, background: "#0B1F33" }}>
            {selNode && (
              <div style={{ fontSize: 13 }}>
                <b>{selNode.kind}</b>: {selNode.label}
                {Object.entries(selNode).filter(([k]) => !["id", "kind", "ref", "label"].includes(k)).map(([k, v]) => (
                  <div key={k} className="kv"><span>{k.toUpperCase()}</span><span>{String(v)}</span></div>
                ))}
              </div>
            )}
            {selEdge && !selNode && (
              <div style={{ fontSize: 13 }}><b>{selEdge.relation}</b>: {selEdge.from} → {selEdge.to}</div>
            )}
          </div>
        )}
      </div>

      <div className="grid grid-2">
        <div className="panel" style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Confidence evolution</h3>
          <ConfidenceChart iid={iid} />
        </div>
        <div className="panel" style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Investigation copilot</h3>
          <form onSubmit={askCopilot} style={{ display: "flex", gap: 8, marginBottom: 8 }}>
            <input value={copilotQ} onChange={(e) => setCopilotQ(e.target.value)}
              placeholder="What do we know? What is missing? What next?" style={{ flex: 1 }} />
            <button className="btn btn-ghost">Ask</button>
          </form>
          {copilotA && <div style={{ fontSize: 13, whiteSpace: "pre-wrap" }}>{copilotA}</div>}
          <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 6 }}>
            Grounded in recorded evidence only. Try: “What supports the leading hypothesis?”
          </div>
        </div>
      </div>

      <div className="grid grid-3">
        <div className="panel" style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Assumptions</h3>
          <Assumptions iid={iid} items={assumptions} reload={load} canWrite={canWrite} />
        </div>
        <div className="panel" style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Conflicts</h3>
          {conflicts.length === 0 && <div style={{ fontSize: 13, color: "var(--muted)" }}>No conflicts detected.</div>}
          {conflicts.map((c) => (
            <div key={c.id} style={{ fontSize: 13, marginBottom: 8 }}>
              <span className="badge">{c.status}</span> {c.description}
              <div style={{ fontSize: 12, color: "var(--muted)" }}>Next action: {c.recommendation}</div>
              {c.status === "OPEN" && canWrite && (
                <button className="linklike" onClick={() =>
                  act(api.caseConflictStatus(iid, c.id, "RESOLVED"), "Conflict resolved.")}>
                  mark resolved
                </button>
              )}
            </div>
          ))}
          {canWrite && (
            <button className="btn btn-ghost" style={{ marginTop: 6 }} onClick={async () => {
              setErr("");
              try {
                await api.caseConflictsRefresh(iid);
                load();
              } catch (e) {
                setErr(e instanceof Error ? e.message : "Detection failed");
              }
            }}>
              Re-run detection
            </button>
          )}
        </div>
        <div className="panel" style={{ marginBottom: 16 }}>
          <h3 style={{ marginTop: 0 }}>Similar cases</h3>
          <SimilarList items={similar} note={similarNote} />
        </div>
      </div>

      <div className="panel" style={{ marginBottom: 16 }}>
        <h3 style={{ marginTop: 0 }}>Timeline</h3>
        {timeline.map((t, i) => (
          <div className="kv" key={i}>
            <span>{t.action.replaceAll("_", " ")}</span>
            <span style={{ fontSize: 12, color: "var(--muted)" }}>{t.created_at}</span>
          </div>
        ))}
        {timeline.length === 0 && <div style={{ fontSize: 13, color: "var(--muted)" }}>No events yet.</div>}
      </div>
    </div>
  );
}

function NBEList({ iid, items, onDone, canWrite }: {
  iid: number; onDone: () => void; canWrite: boolean;
  items: { id: number; rank: number; title: string; kind: string; priority: string;
           effort: string; safety: string; expected_value: string;
           discriminative_value: number; rationale: Record<string, string>; status: string }[];
}) {
  const [err, setErr] = useState("");
  if (items.length === 0) return <div style={{ fontSize: 13, color: "var(--muted)" }}>No recommendations — generate from missing evidence when hypotheses exist.</div>;
  return (
    <div>
      {err && <div className="alert alert-error">{err}</div>}
      {items.map((r) => (
        <div key={r.id} className="panel" style={{ marginBottom: 8, background: "#0B1F33" }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 8 }}>
            <b>#{r.rank} {r.title}</b>
            <span className="badge">{r.priority}</span>
          </div>
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
            value {r.discriminative_value} · effort {r.effort} · safety {r.safety} · {r.kind}
          </div>
          <div style={{ fontSize: 13, marginTop: 4 }}>{r.rationale.why}</div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>Distinguishes: {r.rationale.distinguishes}</div>
          <div style={{ fontSize: 12, color: "var(--muted)" }}>{r.rationale.uncertainty}</div>
          {canWrite && (
            <button className="linklike" onClick={() => {
              api.caseRecoStatus(iid, r.id, "DONE").then(onDone).catch((e) =>
                setErr(e instanceof Error ? e.message : "Update failed"));
            }}>mark done</button>
          )}
        </div>
      ))}
    </div>
  );
}

function ConfidenceChart({ iid }: { iid: number }) {
  const [hist, setHist] = useState<{ hypothesis_id: number; title: string; support_score: number; confidence_band: string }[]>([]);
  useEffect(() => {
    api.caseConfidence(iid).then((r) => setHist(r.history)).catch(() => setHist([]));
  }, [iid]);
  if (hist.length === 0) return <div style={{ fontSize: 13, color: "var(--muted)" }}>No scoring events yet.</div>;
  const byHyp = new Map<number, { title: string; pts: number[] }>();
  hist.forEach((h) => {
    if (!byHyp.has(h.hypothesis_id)) byHyp.set(h.hypothesis_id, { title: h.title, pts: [] });
    byHyp.get(h.hypothesis_id)!.pts.push(h.support_score);
  });
  const colors = ["var(--accent)", "var(--warning)", "var(--success)", "var(--critical)"];
  const W = 520;
  const H = 200;
  const maxPts = Math.max(...[...byHyp.values()].map((v) => v.pts.length), 1);
  const X = (i: number) => 40 + (i / Math.max(1, maxPts - 1)) * (W - 60);
  const Y = (v: number) => H - 24 - (v / 100) * (H - 48);
  let ci = 0;
  const series = [...byHyp.entries()].map(([id, v]) => ({ id, ...v, color: colors[(ci++) % colors.length] }));
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", background: "#081627", borderRadius: 8, border: "1px solid var(--border)" }} role="img" aria-label="Confidence evolution chart">
      {[0, 25, 50, 75, 100].map((v) => (
        <g key={v}>
          <line x1={40} y1={Y(v)} x2={W - 20} y2={Y(v)} stroke="#1d3a52" strokeWidth={1} />
          <text x={34} y={Y(v) + 3} fill="var(--muted)" fontSize={9} textAnchor="end">{v}</text>
        </g>
      ))}
      {series.map((s) => (
        <g key={s.id}>
          <polyline points={s.pts.map((v, i) => `${X(i)},${Y(v)}`).join(" ")}
            fill="none" stroke={s.color} strokeWidth={2} />
          {s.pts.map((v, i) => <circle key={i} cx={X(i)} cy={Y(v)} r={3} fill={s.color} />)}
          <text x={X(s.pts.length - 1) + 6} y={Y(s.pts[s.pts.length - 1]) + 3} fill={s.color} fontSize={10}>
            {s.title.slice(0, 20)}
          </text>
        </g>
      ))}
    </svg>
  );
}

function Assumptions({ iid, items, reload, canWrite }: {
  iid: number; reload: () => void; canWrite: boolean;
  items: { id: number; text: string; status: string }[];
}) {
  const [err, setErr] = useState("");
  return (
    <div>
      {err && <div className="alert alert-error">{err}</div>}
      {items.length === 0 && <div style={{ fontSize: 13, color: "var(--muted)" }}>No assumptions recorded.</div>}
      {items.map((a) => (
        <div className="kv" key={a.id}>
          <span>{a.text}</span>
          <span>
            <span className="badge">{a.status}</span>{" "}
            {canWrite && a.status !== "VERIFIED" && (
              <button className="linklike" onClick={() => {
                api.caseAssumptionStatus(iid, a.id, "VERIFIED").then(reload).catch((e) =>
                  setErr(e instanceof Error ? e.message : "Update failed"));
              }}>verify</button>
            )}
          </span>
        </div>
      ))}
    </div>
  );
}

function SimilarList({ items, note }: {
  note: string | null;
  items: { id: number; title: string; similarity: number }[];
}) {
  if (items.length === 0) {
    return <div style={{ fontSize: 13, color: "var(--muted)" }}>{note ?? "No similar cases."}</div>;
  }
  return (
    <div>
      {items.map((c) => (
        <div className="kv" key={c.id}>
          <span>Case #{c.id} — {c.title}</span>
          <span><b>{c.similarity}%</b> similarity</span>
        </div>
      ))}
    </div>
  );
}

const selStyle: React.CSSProperties = {
  width: "100%", padding: 11, borderRadius: 8, background: "#081627",
  color: "var(--text)", border: "1px solid var(--border)",
};
