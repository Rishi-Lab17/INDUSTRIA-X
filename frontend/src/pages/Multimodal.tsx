import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, type Equipment, type KBDocument, type SensorDataset, type VisionAsset } from "../api";
import { useAuth } from "../auth";

interface MMResult {
  equipment: { id: number; code: string; name: string };
  question: string;
  evidence: { id: string; type: string; source: string; description: string; data_ref: Record<string, unknown> }[];
  observations: { kind: string; text: string }[];
  timeline: { ts: number | null; kind: string; label: string }[];
  warnings: string[];
  context_chars: number;
  interpretation: { status: string; answer?: string; limitation?: string } | null;
  ai_run_id: number | null;
}

export default function Multimodal() {
  const { user } = useAuth();
  const canRun = user?.role === "COMPANY_ADMIN" || user?.role === "ENGINEER";
  const [params] = useSearchParams();
  const [equipment, setEquipment] = useState<Equipment[]>([]);
  const [eqId, setEqId] = useState("");
  const [question, setQuestion] = useState("");
  const [docs, setDocs] = useState<KBDocument[]>([]);
  const [sets, setSets] = useState<SensorDataset[]>([]);
  const [images, setImages] = useState<VisionAsset[]>([]);
  const [selDocs, setSelDocs] = useState<number[]>([]);
  const [selSets, setSelSets] = useState<number[]>([]);
  const [selImgs, setSelImgs] = useState<number[]>([]);
  const [res, setRes] = useState<MMResult | null>(null);
  const [snaps, setSnaps] = useState<{ id: number; question: string; created_at: string }[]>([]);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.equipmentList().then((r) => {
      setEquipment(r.equipment);
      const q = params.get("equipment");
      if (q && r.equipment.some((e) => String(e.id) === q)) setEqId(q);
    }).catch(() => undefined);
  }, [params]);

  useEffect(() => {
    if (!eqId) return;
    const id = Number(eqId);
    api.kbList({ equipment_id: id }).then((r) => setDocs(r.documents)).catch(() => setDocs([]));
    api.sensorList(id).then((r) => setSets(r.datasets)).catch(() => setSets([]));
    api.visionList(id).then((r) => setImages(r.images)).catch(() => setImages([]));
    api.mmList(id).then((r) => setSnaps(r.investigations)).catch(() => setSnaps([]));
    setSelDocs([]);
    setSelSets([]);
    setSelImgs([]);
    setRes(null);
  }, [eqId]);

  function toggle(list: number[], id: number, set: (v: number[]) => void) {
    set(list.includes(id) ? list.filter((x) => x !== id) : [...list, id]);
  }

  async function run() {
    if (!eqId || !question.trim()) {
      setErr("Select equipment and enter a question.");
      return;
    }
    setErr("");
    setBusy(true);
    try {
      const r = await api.mmRun({
        equipment_id: Number(eqId), question: question.trim(),
        document_ids: selDocs, dataset_ids: selSets, asset_ids: selImgs,
      });
      setRes(r as unknown as MMResult);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Run failed");
    } finally {
      setBusy(false);
    }
  }

  async function snapshot() {
    if (!res || !eqId) return;
    setErr("");
    try {
      const s = await api.mmSnapshot({
        equipment_id: Number(eqId), question,
        config: { document_ids: selDocs, dataset_ids: selSets, asset_ids: selImgs },
        results: res,
      });
      setRes(res);
      const inv = await api.mmGet(s.investigation_id);
      setRes(inv.results as unknown as MMResult);
      api.mmList(Number(eqId)).then((r) => setSnaps(r.investigations)).catch(() => undefined);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Snapshot failed");
    }
  }

  async function loadSnap(id: number) {
    setErr("");
    try {
      const inv = await api.mmGet(id);
      setRes(inv.results as unknown as MMResult);
      setQuestion(inv.question);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Load failed");
    }
  }

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Multimodal Investigation</h1>
          <p className="page-sub">Equipment + documents + sensors + images fused into evidence — observations, never diagnoses.</p>
        </div>
      </div>
      {err && <div className="alert alert-error">{err}</div>}

      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="grid grid-2">
          <div className="field">
            <label>EQUIPMENT</label>
            <select value={eqId} onChange={(e) => setEqId(e.target.value)} style={selStyle}>
              <option value="">Select…</option>
              {equipment.map((e) => <option key={e.id} value={e.id}>{e.code} — {e.name}</option>)}
            </select>
          </div>
          <div className="field">
            <label>INVESTIGATION QUESTION</label>
            <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Is vibration abnormal on this asset?" />
          </div>
        </div>
        {eqId && (
          <div className="grid grid-3">
            <div className="field">
              <label>DOCUMENTS ({selDocs.length})</label>
              <div style={{ maxHeight: 140, overflow: "auto", border: "1px solid var(--border)", borderRadius: 8, padding: 8 }}>
                {docs.map((d) => (
                  <label key={d.id} style={{ display: "block", fontSize: 12 }}>
                    <input type="checkbox" checked={selDocs.includes(d.id)} onChange={() => toggle(selDocs, d.id, setSelDocs)} /> {d.original_filename} (v{d.version})
                  </label>
                ))}
                {docs.length === 0 && <span style={{ fontSize: 12, color: "var(--muted)" }}>none linked</span>}
              </div>
            </div>
            <div className="field">
              <label>SENSOR DATASETS ({selSets.length})</label>
              <div style={{ maxHeight: 140, overflow: "auto", border: "1px solid var(--border)", borderRadius: 8, padding: 8 }}>
                {sets.map((d) => (
                  <label key={d.id} style={{ display: "block", fontSize: 12 }}>
                    <input type="checkbox" checked={selSets.includes(d.id)} onChange={() => toggle(selSets, d.id, setSelSets)} /> {d.name} ({d.row_count} rows)
                  </label>
                ))}
                {sets.length === 0 && <span style={{ fontSize: 12, color: "var(--muted)" }}>none</span>}
              </div>
            </div>
            <div className="field">
              <label>IMAGES ({selImgs.length})</label>
              <div style={{ maxHeight: 140, overflow: "auto", border: "1px solid var(--border)", borderRadius: 8, padding: 8 }}>
                {images.map((m) => (
                  <label key={m.id} style={{ display: "block", fontSize: 12 }}>
                    <input type="checkbox" checked={selImgs.includes(m.id)} onChange={() => toggle(selImgs, m.id, setSelImgs)} /> {m.filename}
                  </label>
                ))}
                {images.length === 0 && <span style={{ fontSize: 12, color: "var(--muted)" }}>none</span>}
              </div>
            </div>
          </div>
        )}
        <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
          {canRun && <button className="btn btn-ghost" onClick={run} disabled={busy}>{busy ? "Running…" : "Run investigation"}</button>}
          {canRun && res && <button className="btn btn-ghost" onClick={snapshot}>Save snapshot</button>}
        </div>
      </div>

      {res && (
        <>
          <div className="panel" style={{ marginBottom: 16 }}>
            <h3 style={{ marginTop: 0 }}>Evidence ({res.evidence.length})</h3>
            {res.evidence.map((e) => (
              <div className="kv" key={e.id}>
                <span><b>{e.type}</b> — {e.description}</span>
                <span style={{ fontSize: 11, color: "var(--muted)" }}>{e.source}</span>
              </div>
            ))}
          </div>

          <div className="panel" style={{ marginBottom: 16 }}>
            <h3 style={{ marginTop: 0 }}>Observations</h3>
            {res.observations.map((o, i) => (
              <div key={i} style={{ marginBottom: 8, fontSize: 13 }}>
                <span className="badge" style={{ marginRight: 8 }}>{o.kind}</span>{o.text}
              </div>
            ))}
          </div>

          <div className="grid grid-2">
            <div className="panel" style={{ marginBottom: 16 }}>
              <h3 style={{ marginTop: 0 }}>Timeline</h3>
              {res.timeline.map((t, i) => (
                <div className="kv" key={i}>
                  <span>{t.ts ? new Date(t.ts * 1000).toLocaleString() : "—"}</span>
                  <span style={{ fontSize: 12 }}>{t.label}</span>
                </div>
              ))}
            </div>
            <div className="panel" style={{ marginBottom: 16 }}>
              <h3 style={{ marginTop: 0 }}>Warnings &amp; limitations</h3>
              {res.warnings.map((w, i) => <div key={i} className="alert alert-warn">{w}</div>)}
              {res.warnings.length === 0 && <div style={{ fontSize: 13, color: "var(--muted)" }}>No warnings.</div>}
              <div style={{ marginTop: 8, fontSize: 12, color: "var(--muted)" }}>
                Context: {res.context_chars} chars. AI interpretation:{" "}
                {res.interpretation ? res.interpretation.status : "not requested (no AI session linked)"}
              </div>
              {res.interpretation?.answer && (
                <div style={{ marginTop: 8, fontSize: 13, whiteSpace: "pre-wrap" }}>{res.interpretation.answer}</div>
              )}
              {res.interpretation?.limitation && (
                <div style={{ marginTop: 8, fontSize: 12, color: "var(--muted)" }}>{res.interpretation.limitation}</div>
              )}
            </div>
          </div>
        </>
      )}

      {snaps.length > 0 && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Saved snapshots</h3>
          {snaps.map((s) => (
            <div className="kv" key={s.id}>
              <span style={{ cursor: "pointer" }} onClick={() => loadSnap(s.id)}><u>{s.question || `Investigation #${s.id}`}</u></span>
              <span style={{ fontSize: 12, color: "var(--muted)" }}>{s.created_at.slice(0, 10)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const selStyle: React.CSSProperties = {
  width: "100%", padding: 11, borderRadius: 8, background: "#081627",
  color: "var(--text)", border: "1px solid var(--border)",
};
