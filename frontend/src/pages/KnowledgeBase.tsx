import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, uploadDocument, type Equipment, type KBDocument, type KBHealth } from "../api";
import { formatSize, indexDot, statusDot, SUPPORTED_LABELS, useKBRole } from "../components/kb";

export default function KnowledgeBase() {
  const { canUpload, canRetry, canArchive, canIndex } = useKBRole();
  const [docs, setDocs] = useState<KBDocument[]>([]);
  const [total, setTotal] = useState(0);
  const [kb, setKb] = useState<KBHealth | null>(null);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  // filters
  const [search, setSearch] = useState("");
  const [equipment, setEquipment] = useState<Equipment[]>([]);
  const [fEquipment, setFEquipment] = useState("");
  const [fType, setFType] = useState("");
  const [fStatus, setFStatus] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  // upload dialog
  const [dlg, setDlg] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [upEquipment, setUpEquipment] = useState("");
  const [pct, setPct] = useState(0);
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);

  const load = useCallback(() => {
    api.kbList({
      search: search || undefined,
      equipment_id: fEquipment || undefined,
      file_type: fType || undefined,
      processing_status: fStatus || undefined,
      is_archived: showArchived,
    })
      .then((r) => {
        setDocs(r.documents);
        setTotal(r.total);
        setErr("");
      })
      .catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
  }, [search, fEquipment, fType, fStatus, showArchived]);

  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);

  useEffect(() => {
    api.equipmentList().then((r) => setEquipment(r.equipment)).catch(() => setEquipment([]));
    api.kbHealth().then(setKb).catch(() => setKb(null));
  }, []);

  // Live status refresh while anything is mid-processing.
  useEffect(() => {
    if (!docs.some((d) => ["UPLOADED", "QUEUED", "PROCESSING", "RETRYING"].includes(d.processing_status))) return;
    const t = setTimeout(load, 3000);
    return () => clearTimeout(t);
  }, [docs, load]);

  async function doUpload(e: React.FormEvent) {
    e.preventDefault();
    if (!file) {
      setErr("Choose a file first.");
      return;
    }
    setErr("");
    setOk("");
    setBusy(true);
    setPct(0);
    try {
      const d = await uploadDocument(file, upEquipment ? Number(upEquipment) : null, setPct);
      setOk(d.duplicate
        ? `Identical file already stored as version ${d.version} — no new version created.`
        : `Uploaded ${d.original_filename} (v${d.version}) — ${d.processing_status}.`);
      setDlg(false);
      setFile(null);
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function retry(id: number) {
    setErr("");
    try {
      const d = await api.kbRetry(id);
      setOk(`Re-processed ${d.original_filename} — ${d.processing_status}.`);
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Retry failed");
    }
  }

  async function indexDoc(id: number, force: boolean) {
    setErr("");
    try {
      const r = force ? await api.kbReindex(id) : await api.kbIndex(id);
      setOk(`Indexing ${r.status}: ${r.detail}`);
      load();
      api.kbHealth().then(setKb).catch(() => undefined);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Indexing failed");
    }
  }

  async function archive(id: number) {
    if (!window.confirm("Archive this document? It stays auditable.")) return;
    setErr("");
    try {
      await api.kbArchive(id);
      setOk("Document archived.");
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Archive failed");
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDrag(false);
    if (e.dataTransfer.files.length > 0) setFile(e.dataTransfer.files[0]);
  }

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Knowledge Base</h1>
          <p className="page-sub">Secure company-local industrial knowledge · {total} document{total === 1 ? "" : "s"}</p>
        </div>
        {canUpload && <button className="btn btn-ghost" onClick={() => setDlg(true)}>+ Upload Document</button>}
      </div>

      {err && <div className="alert alert-error">{err}</div>}
      {ok && <div className="alert alert-ok">{ok}</div>}

      {kb && (
        <div className="panel" style={{ marginBottom: 16 }}>
          <div style={{ display: "flex", gap: 18, flexWrap: "wrap", fontSize: 13 }}>
            <span><b>{kb.indexed}</b> <span style={{ color: "var(--muted)" }}>indexed</span></span>
            <span><b>{kb.not_indexed}</b> <span style={{ color: "var(--muted)" }}>not indexed</span></span>
            <span><b>{kb.stale}</b> <span style={{ color: "var(--muted)" }}>stale</span></span>
            <span><b>{kb.failed}</b> <span style={{ color: "var(--muted)" }}>failed</span></span>
            <span><b>{kb.chunks_active}</b> <span style={{ color: "var(--muted)" }}>active chunks</span></span>
            <span style={{ color: "var(--muted)" }}>
              model: <b style={{ color: "var(--text)" }}>{kb.embedding_model.split("/").pop()}</b>
              {" "}· vector db: <b style={{ color: "var(--text)" }}>{kb.vector_db}</b>
            </span>
          </div>
        </div>
      )}

      <div className="panel" style={{ marginBottom: 16 }}>
        <div className="grid grid-3">
          <div className="field">
            <label>SEARCH FILENAME</label>
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="manual…" />
          </div>
          <div className="field">
            <label>EQUIPMENT</label>
            <select value={fEquipment} onChange={(e) => setFEquipment(e.target.value)}
              style={selStyle}>
              <option value="">All equipment</option>
              {equipment.map((e) => <option key={e.id} value={e.id}>{e.code} — {e.name}</option>)}
            </select>
          </div>
          <div className="field">
            <label>FILE TYPE</label>
            <select value={fType} onChange={(e) => setFType(e.target.value)} style={selStyle}>
              <option value="">All types</option>
              {SUPPORTED_LABELS.map((t) => <option key={t}>{t}</option>)}
            </select>
          </div>
          <div className="field">
            <label>PROCESSING STATUS</label>
            <select value={fStatus} onChange={(e) => setFStatus(e.target.value)} style={selStyle}>
              <option value="">All states</option>
              {["UPLOADED", "QUEUED", "PROCESSING", "COMPLETED", "FAILED", "RETRYING", "ARCHIVED"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>VISIBILITY</label>
            <select value={showArchived ? "arch" : "active"} onChange={(e) => setShowArchived(e.target.value === "arch")} style={selStyle}>
              <option value="active">Active</option>
              <option value="arch">Archived</option>
            </select>
          </div>
        </div>
      </div>

      {docs.length === 0 ? (
        <div className="panel">No documents match. Upload the first one to build this company&apos;s knowledge base.</div>
      ) : (
        <div className="panel" style={{ padding: 8 }}>
          <table className="table">
            <thead>
              <tr><th>Filename</th><th>Type</th><th>Size</th><th>Equipment</th><th>Ver</th><th>Status</th><th>Index</th><th>Uploaded</th><th>Actions</th></tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td><Link to={`/knowledge/${d.id}`}>{d.original_filename}</Link></td>
                  <td>{d.file_type}</td>
                  <td>{formatSize(d.file_size)}</td>
                  <td>{d.equipment_code ?? "—"}</td>
                  <td>v{d.version}</td>
                  <td><span className="badge"><span className={`dot ${statusDot(d.processing_status)}`} />{d.processing_status}</span></td>
                  <td>
                    <span className="badge" title={d.index_error ?? d.embedding_model ?? ""}>
                      <span className={`dot ${indexDot(d.index_status)}`} />{d.index_status}
                    </span>
                    {d.index_status === "STALE" && (
                      <div style={{ fontSize: 11, color: "var(--warning)", marginTop: 4 }}>newer version available</div>
                    )}
                    {d.index_status === "INDEX_FAILED" && d.index_error && (
                      <div style={{ fontSize: 11, color: "var(--critical)", marginTop: 4 }}>{d.index_error}</div>
                    )}
                    {d.chunk_count > 0 && (
                      <div style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}>{d.chunk_count} chunks</div>
                    )}
                  </td>
                  <td style={{ fontSize: 12 }}>{d.created_at.slice(0, 10)}</td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <Link to={`/knowledge/${d.id}`}>View</Link>
                    {canIndex && d.processing_status === "COMPLETED" && d.index_status !== "INDEXED" && (
                      <> · <button className="linklike" onClick={() => indexDoc(d.id, false)}>Index</button></>
                    )}
                    {canIndex && d.index_status === "INDEXED" && (
                      <> · <button className="linklike" onClick={() => indexDoc(d.id, true)}>Reindex</button></>
                    )}
                    {canIndex && (d.index_status === "INDEX_FAILED" || d.index_status === "STALE") && (
                      <> · <button className="linklike" onClick={() => indexDoc(d.id, true)}>Reindex</button></>
                    )}
                    {d.processing_status === "FAILED" && canRetry && (
                      <> · <button className="linklike" onClick={() => retry(d.id)}>Retry</button></>
                    )}
                    {canArchive && !d.is_archived && (
                      <> · <button className="linklike" onClick={() => archive(d.id)}>Archive</button></>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {dlg && (
        <div className="modal-backdrop" onClick={() => !busy && setDlg(false)}>
          <div className="panel modal" onClick={(e) => e.stopPropagation()}>
            <h3 style={{ marginTop: 0 }}>Upload Document</h3>
            <div style={{ fontSize: 12, color: "var(--muted)", marginBottom: 12 }}>
              Supported: {SUPPORTED_LABELS.join(" · ")} · Max 50 MB · Stored locally, processed locally.
            </div>
            <form onSubmit={doUpload}>
              <div
                onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
                onDragLeave={() => setDrag(false)}
                onDrop={onDrop}
                style={{
                  border: `2px dashed ${drag ? "var(--accent)" : "var(--border)"}`,
                  borderRadius: 10, padding: 22, textAlign: "center", marginBottom: 14,
                  color: "var(--muted)", fontSize: 13,
                }}>
                {file ? <b style={{ color: "var(--text)" }}>{file.name}</b> : "Drag & drop a file here, or pick below"}
                <div style={{ marginTop: 10 }}>
                  <input type="file" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
                </div>
              </div>
              <div className="field">
                <label>EQUIPMENT (OPTIONAL)</label>
                <select value={upEquipment} onChange={(e) => setUpEquipment(e.target.value)} style={selStyle}>
                  <option value="">No equipment link</option>
                  {equipment.map((e) => <option key={e.id} value={e.id}>{e.code} — {e.name}</option>)}
                </select>
              </div>
              {busy && (
                <div style={{ marginBottom: 12 }}>
                  <div style={{ height: 8, background: "#081627", borderRadius: 4 }}>
                    <div style={{ width: `${pct}%`, height: 8, borderRadius: 4, background: "var(--accent)", transition: "width .2s" }} />
                  </div>
                  <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>{pct}% uploaded…</div>
                </div>
              )}
              <button className="btn" disabled={busy || !file}>{busy ? "Uploading…" : "Upload & Process"}</button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

const selStyle: React.CSSProperties = {
  width: "100%", padding: 11, borderRadius: 8, background: "#081627",
  color: "var(--text)", border: "1px solid var(--border)",
};
