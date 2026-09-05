import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type KBDocument, type KBPreview } from "../api";
import { formatSize, indexDot, statusDot, useKBRole } from "../components/kb";

export default function DocumentDetail() {
  const { id } = useParams();
  const did = Number(id);
  const nav = useNavigate();
  const { canRetry, canArchive, canIndex } = useKBRole();
  const [doc, setDoc] = useState<KBDocument | null>(null);
  const [preview, setPreview] = useState<KBPreview | null>(null);
  const [err, setErr] = useState("");
  const [ok, setOk] = useState("");
  const [copied, setCopied] = useState(false);

  function load() {
    api.kbGet(did)
      .then(setDoc)
      .catch((e) => setErr(e instanceof Error ? e.message : "Load failed"));
    api.kbPreview(did)
      .then(setPreview)
      .catch(() => setPreview(null));
  }

  useEffect(load, [did]);

  async function download() {
    setErr("");
    try {
      const blob = await api.kbDownload(did);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = doc?.original_filename ?? `document-${did}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Download failed");
    }
  }

  async function retry() {
    setErr("");
    try {
      const d = await api.kbRetry(did);
      setDoc(d);
      setOk(`Re-processed — ${d.processing_status}.`);
      const p = await api.kbPreview(did).catch(() => null);
      if (p) setPreview(p);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Retry failed");
    }
  }

  async function index(force: boolean) {
    setErr("");
    setOk("");
    try {
      const r = force ? await api.kbReindex(did) : await api.kbIndex(did);
      setOk(`Indexing ${r.status}: ${r.detail}`);
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Indexing failed");
    }
  }

  async function archive() {
    if (!window.confirm("Archive this document? It stays auditable.")) return;
    setErr("");
    try {
      await api.kbArchive(did);
      setOk("Document archived.");
      load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Archive failed");
    }
  }

  async function remove() {
    if (!window.confirm("Permanently delete this file and record? The audit event is kept.")) return;
    setErr("");
    try {
      await api.kbDelete(did);
      nav("/knowledge");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Delete failed");
    }
  }

  function copyHash() {
    if (!doc) return;
    navigator.clipboard.writeText(doc.sha256_hash)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => setErr("Copy failed"));
  }

  if (!doc) return <div>{err ? <div className="alert alert-error">{err}</div> : "Loading document…"}</div>;

  const rows: [string, React.ReactNode][] = [
    ["FILENAME", doc.original_filename],
    ["FILE TYPE", doc.file_type],
    ["SIZE", formatSize(doc.file_size)],
    ["VERSION", `v${doc.version}${doc.parent_document_id ? ` (previous: #${doc.parent_document_id})` : " (original)"}`],
    ["EQUIPMENT", doc.equipment_code ?? "—"],
    ["UPLOADER", doc.uploader_name ?? "—"],
    ["UPLOADED", doc.created_at],
    ["PAGE COUNT", doc.page_count !== null ? String(doc.page_count) : "—"],
    ["OCR USED", doc.ocr_used ? "yes" : "no"],
    ["PROCESSING STARTED", doc.processing_started_at ?? "—"],
    ["PROCESSING FINISHED", doc.processing_completed_at ?? "—"],
  ];

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">{doc.original_filename}</h1>
          <p className="page-sub">Knowledge Base record #{doc.id}</p>
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button className="btn btn-ghost" onClick={download}>Download</button>
          {canIndex && doc.processing_status === "COMPLETED" && doc.index_status !== "INDEXED" && (
            <button className="btn btn-ghost" onClick={() => index(false)}>Index</button>
          )}
          {canIndex && doc.index_status === "INDEXED" && (
            <button className="btn btn-ghost" onClick={() => index(true)}>Reindex</button>
          )}
          {doc.processing_status === "FAILED" && canRetry && (
            <button className="btn btn-ghost" onClick={retry}>Retry</button>
          )}
          {canArchive && !doc.is_archived && (
            <button className="btn btn-ghost" onClick={archive}>Archive</button>
          )}
          {canArchive && (
            <button className="btn btn-ghost" onClick={remove}>Delete</button>
          )}
        </div>
      </div>

      {err && <div className="alert alert-error">{err}</div>}
      {ok && <div className="alert alert-ok">{ok}</div>}

      <div className="grid grid-2">
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Metadata</h3>
          <div style={{ marginBottom: 12 }}>
            <span className="badge"><span className={`dot ${statusDot(doc.processing_status)}`} />{doc.processing_status}</span>
            {doc.is_archived && <span className="badge" style={{ marginLeft: 8 }}>ARCHIVED</span>}
            <span className="badge" style={{ marginLeft: 8 }} title={doc.index_error ?? doc.embedding_model ?? ""}>
              <span className={`dot ${indexDot(doc.index_status)}`} />INDEX: {doc.index_status}
            </span>
          </div>
          <div className="kv"><span>CHUNKS</span><span>{doc.chunk_count}{doc.embedding_model ? ` · ${doc.embedding_model.split("/").pop()}` : ""}</span></div>
          {doc.index_status === "STALE" && (
            <div className="alert alert-warn">A newer document version exists — this index is historical.</div>
          )}
          {doc.index_error && (
            <div className="alert alert-error" style={{ marginTop: 12 }}>{doc.index_error}</div>
          )}
          {rows.map(([k, v]) => (
            <div className="kv" key={k}><span>{k}</span><span>{v}</span></div>
          ))}
          <div className="kv">
            <span>SHA-256</span>
            <span className="mono">{doc.sha256_hash.slice(0, 24)}…
              <button className="linklike" style={{ marginLeft: 8 }} onClick={copyHash}>
                {copied ? "copied!" : "copy full"}
              </button>
            </span>
          </div>
          {doc.processing_error && (
            <div className="alert alert-error" style={{ marginTop: 12 }}>{doc.processing_error}</div>
          )}
          {doc.processing_note && (
            <div className="alert alert-warn" style={{ marginTop: 12 }}>{doc.processing_note}</div>
          )}
        </div>

        <div className="panel">
          <h3 style={{ marginTop: 0 }}>Extracted Content Preview</h3>
          {!preview || !preview.extracted_text ? (
            <div style={{ color: "var(--muted)", fontSize: 13 }}>
              No extracted text available
              {preview ? ` (status: ${preview.processing_status})` : ""}.
            </div>
          ) : (
            <div className="preview-box">{preview.extracted_text.slice(0, 8000)}</div>
          )}
        </div>
      </div>

      <div className="auth-switch"><Link to="/knowledge">Back to Knowledge Base</Link></div>
    </div>
  );
}
