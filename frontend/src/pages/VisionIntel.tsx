import { useEffect, useRef, useState } from "react";
import { api, authedBlob, type Equipment, type VisionAnnotation, type VisionAsset } from "../api";
import { useAuth } from "../auth";

const LABELS = ["corrosion", "crack", "leakage", "damaged insulation",
  "discoloration", "unusual component condition", "other"];

function useRole() {
  const { user } = useAuth();
  return {
    canAnalyze: user?.role === "COMPANY_ADMIN" || user?.role === "ENGINEER",
    userId: user?.id,
    isAdmin: user?.role === "COMPANY_ADMIN",
  };
}

export default function VisionIntel() {
  const { canAnalyze, userId, isAdmin } = useRole();
  const [images, setImages] = useState<VisionAsset[]>([]);
  const [equipment, setEquipment] = useState<Equipment[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [asset, setAsset] = useState<VisionAsset | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [anns, setAnns] = useState<VisionAnnotation[]>([]);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [busy, setBusy] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [upEq, setUpEq] = useState("");
  const [zoom, setZoom] = useState(1);
  const [analysis, setAnalysis] = useState<Record<string, unknown> | null>(null);
  // annotation draft (normalized coords)
  const [draft, setDraft] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  const [label, setLabel] = useState(LABELS[0]);
  const [note, setNote] = useState("");
  const [drawing, setDrawing] = useState<{ x: number; y: number } | null>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);

  function loadList() {
    api.visionList().then((r) => setImages(r.images)).catch((e) => setErr(e instanceof Error ? e.message : String(e)));
    api.equipmentList().then((r) => setEquipment(r.equipment)).catch(() => undefined);
  }
  useEffect(loadList, []);

  async function select(id: number) {
    setSel(id);
    setErr("");
    setAnalysis(null);
    setDraft(null);
    try {
      const a = await api.visionGet(id);
      setAsset(a);
      const blob = await authedBlob(`/api/vision/images/${id}/file`);
      setUrl((old) => {
        if (old) URL.revokeObjectURL(old);
        return URL.createObjectURL(blob);
      });
      setAnns((await api.visionAnnotations(id)).annotations);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Load failed");
    }
  }

  async function upload(e: React.FormEvent) {
    e.preventDefault();
    if (!file || !upEq) {
      setErr("Choose an image and equipment.");
      return;
    }
    setErr("");
    setOk("");
    setBusy(true);
    try {
      const a = await api.visionUpload(file, Number(upEq));
      setOk(`Uploaded ${a.filename} (${a.width}x${a.height}), quality ${a.quality_status}.`);
      setFile(null);
      loadList();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function runOcr() {
    if (sel === null) return;
    setErr("");
    try {
      const r = await api.visionOcr(sel);
      setOk(r.ocr_status === "COMPLETED" ? "OCR completed." : `OCR: ${r.ocr_status}. ${r.note}`);
      if (sel !== null) select(sel);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "OCR failed");
    }
  }

  async function runAnalyze() {
    if (sel === null) return;
    setErr("");
    try {
      setAnalysis(await api.visionAnalyze(sel));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Analysis failed");
    }
  }

  function toNorm(e: React.MouseEvent): { x: number; y: number } {
    const el = imgRef.current;
    if (!el) return { x: 0, y: 0 };
    const r = el.getBoundingClientRect();
    return {
      x: Math.min(1, Math.max(0, (e.clientX - r.left) / r.width)),
      y: Math.min(1, Math.max(0, (e.clientY - r.top) / r.height)),
    };
  }

  function onDown(e: React.MouseEvent) {
    setDrawing(toNorm(e));
    setDraft(null);
  }

  function onUp(e: React.MouseEvent) {
    if (!drawing) return;
    const p = toNorm(e);
    const x = Math.min(drawing.x, p.x);
    const y = Math.min(drawing.y, p.y);
    const w = Math.abs(p.x - drawing.x);
    const h = Math.abs(p.y - drawing.y);
    setDrawing(null);
    if (w > 0.01 && h > 0.01) setDraft({ x, y, w, h });
  }

  async function saveAnn(e: React.FormEvent) {
    e.preventDefault();
    if (sel === null || !draft) return;
    setErr("");
    try {
      await api.visionAnnotate(sel, { ...draft, label, note });
      setOk("Evidence region saved as a potential visual indication (not a diagnosis).");
      setDraft(null);
      setNote("");
      setAnns((await api.visionAnnotations(sel)).annotations);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Save failed");
    }
  }

  async function delAnn(id: number) {
    if (sel === null || !window.confirm("Delete this region?")) return;
    try {
      await api.visionAnnotDelete(sel, id);
      setAnns((await api.visionAnnotations(sel)).annotations);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Delete failed");
    }
  }

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Vision Intelligence</h1>
          <p className="page-sub">Local inspection imagery — human-marked regions only, no automated diagnosis.</p>
        </div>
      </div>
      {err && <div className="alert alert-error">{err}</div>}
      {ok && <div className="alert alert-ok">{ok}</div>}

      <div className="grid grid-2" style={{ gridTemplateColumns: "300px 1fr" }}>
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Images</h3>
          <form onSubmit={upload} style={{ marginBottom: 14 }}>
            <div className="field">
              <label>IMAGE (JPG/PNG/WEBP)</label>
              <input type="file" accept=".jpg,.jpeg,.png,.webp" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            </div>
            <div className="field">
              <label>EQUIPMENT</label>
              <select value={upEq} onChange={(e) => setUpEq(e.target.value)} style={selStyle}>
                <option value="">Select…</option>
                {equipment.map((e) => <option key={e.id} value={e.id}>{e.code}</option>)}
              </select>
            </div>
            <button className="btn" disabled={busy || !file}>Upload</button>
          </form>
          {images.map((m) => (
            <div key={m.id} onClick={() => select(m.id)}
              style={{ padding: "8px 10px", borderRadius: 8, cursor: "pointer", marginBottom: 6, border: "1px solid var(--border)", background: sel === m.id ? "rgba(0,166,199,.14)" : "transparent" }}>
              <div style={{ fontSize: 13, fontWeight: 700 }}>{m.filename}</div>
              <div style={{ fontSize: 11, color: "var(--muted)" }}>{m.equipment_code} · {m.width}x{m.height} · {m.quality_status}</div>
            </div>
          ))}
          {images.length === 0 && <div style={{ fontSize: 13, color: "var(--muted)" }}>No images yet.</div>}
        </div>

        <div>
          {!asset ? (
            <div className="panel">Select an image to inspect.</div>
          ) : (
            <>
              <div className="panel" style={{ marginBottom: 16 }}>
                <h3 style={{ marginTop: 0 }}>{asset.filename} <span className="badge">{asset.quality_status}</span></h3>
                <div style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "center", flexWrap: "wrap" }}>
                  <button className="btn btn-ghost" onClick={() => setZoom((z) => Math.min(4, z + 0.25))}>Zoom +</button>
                  <button className="btn btn-ghost" onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}>Zoom −</button>
                  <span style={{ fontSize: 12, color: "var(--muted)" }}>Drag on the image to mark an evidence region.</span>
                </div>
                <div style={{ overflow: "auto", maxHeight: 520, border: "1px solid var(--border)", borderRadius: 8 }}>
                  <div style={{ position: "relative", width: `${100 * zoom}%` }}>
                    {url && (
                      <img ref={imgRef} src={url} alt={asset.filename}
                        style={{ width: "100%", display: "block", cursor: "crosshair", userSelect: "none" }}
                        onMouseDown={onDown} onMouseUp={onUp} draggable={false} />
                    )}
                    {anns.map((a) => (
                      <div key={a.id} title={`${a.label}: ${a.note}`}
                        style={{
                          position: "absolute", left: `${a.x * 100}%`, top: `${a.y * 100}%`,
                          width: `${a.w * 100}%`, height: `${a.h * 100}%`,
                          border: "2px solid var(--warning)", background: "rgba(217,144,0,.15)",
                          borderRadius: 4, pointerEvents: "none",
                        }} />
                    ))}
                    {draft && (
                      <div style={{
                        position: "absolute", left: `${draft.x * 100}%`, top: `${draft.y * 100}%`,
                        width: `${draft.w * 100}%`, height: `${draft.h * 100}%`,
                        border: "2px dashed var(--accent)", background: "rgba(0,166,199,.15)", borderRadius: 4,
                      }} />
                    )}
                  </div>
                </div>
                {draft && (
                  <form onSubmit={saveAnn} style={{ marginTop: 10 }}>
                    <div className="grid grid-3">
                      <div className="field">
                        <label>LABEL</label>
                        <select value={label} onChange={(e) => setLabel(e.target.value)} style={selStyle}>
                          {LABELS.map((l) => <option key={l}>{l}</option>)}
                        </select>
                      </div>
                      <div className="field">
                        <label>NOTE</label>
                        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="observation note" />
                      </div>
                      <div className="field">
                        <label>&nbsp;</label>
                        <button className="btn">Save region</button>
                      </div>
                    </div>
                  </form>
                )}
                <div style={{ marginTop: 10 }}>
                  <h4 style={{ margin: "8px 0" }}>Evidence markers ({anns.length})</h4>
                  {anns.map((a) => (
                    <div className="kv" key={a.id}>
                      <span>{a.label}{a.note ? ` — ${a.note}` : ""}</span>
                      <span>
                        {(a.created_by === userId || isAdmin) && (
                          <button className="linklike" onClick={() => delAnn(a.id)}>delete</button>
                        )}
                      </span>
                    </div>
                  ))}
                  {anns.length === 0 && <div style={{ fontSize: 12, color: "var(--muted)" }}>No regions marked.</div>}
                </div>
              </div>

              <div className="panel" style={{ marginBottom: 16 }}>
                <h3 style={{ marginTop: 0 }}>Metadata &amp; quality</h3>
                <div className="kv"><span>DIMENSIONS</span><span>{asset.width}x{asset.height}</span></div>
                <div className="kv"><span>SIZE / MIME</span><span>{asset.file_size} B · {asset.mime_type}</span></div>
                <div className="kv"><span>SHA-256</span><span className="mono">{asset.sha256_hash.slice(0, 24)}…</span></div>
                <div className="kv"><span>OCR</span><span>{asset.ocr_status}{asset.ocr_text ? `: ${asset.ocr_text.slice(0, 120)}` : ""}</span></div>
                <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
                  {canAnalyze && <button className="btn btn-ghost" onClick={runOcr}>Run OCR (local)</button>}
                  {canAnalyze && <button className="btn btn-ghost" onClick={runAnalyze}>Analyze</button>}
                </div>
                {analysis !== null && (
                  <div style={{ marginTop: 8, fontSize: 13 }}>
                    <div>Status: <b>{String((analysis as { status?: string }).status)}</b></div>
                    {((analysis as { findings?: string[] }).findings ?? []).map((f, i) => (
                      <div key={i} style={{ marginTop: 4 }}>• {f}</div>
                    ))}
                    <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
                      {String((analysis as { limitation?: string }).limitation ?? (analysis as { reason?: string }).reason ?? "")}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

const selStyle: React.CSSProperties = {
  width: "100%", padding: 11, borderRadius: 8, background: "#081627",
  color: "var(--text)", border: "1px solid var(--border)",
};
