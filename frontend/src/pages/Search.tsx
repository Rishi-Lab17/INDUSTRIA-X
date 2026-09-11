import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Citation, type Equipment, type SearchResult } from "../api";
import { useAuth } from "../auth";

function WhyList({ c }: { c: Citation }) {
  const labels: Record<string, string> = {
    equipment_match: "Equipment match",
    keyword_match: "Keyword match",
    semantic_similarity: "Semantic similarity",
    exact_phrase: "Exact phrase",
    current_version: "Current document version",
    historical_version: "Historical version",
  };
  return (
    <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
      Why retrieved?{" "}
      {c.why_retrieved.map((w) => (
        <span key={w} className="badge" style={{ marginRight: 6, marginBottom: 4 }}>
          ✓ {labels[w] ?? w}
        </span>
      ))}
    </div>
  );
}

export default function Search() {
  const { user } = useAuth();
  const isStaff = user?.role === "COMPANY_ADMIN" || user?.role === "ENGINEER";
  const [query, setQuery] = useState("");
  const [equipment, setEquipment] = useState<Equipment[]>([]);
  const [fEquipment, setFEquipment] = useState("");
  const [historical, setHistorical] = useState(false);
  const [res, setRes] = useState<SearchResult | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.equipmentList().then((r) => setEquipment(r.equipment)).catch(() => setEquipment([]));
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!query.trim()) return;
    setErr("");
    setBusy(true);
    try {
      const r = await api.kbSearch({
        query: query.trim(),
        equipment_id: fEquipment ? Number(fEquipment) : undefined,
        include_historical: historical,
      });
      setRes(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Search failed");
      setRes(null);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="topbar">
        <div>
          <h1 className="page-title">Knowledge Search</h1>
          <p className="page-sub">
            Private retrieval over your company&apos;s indexed documents — local vectors, cited evidence, no AI answers here.
          </p>
        </div>
        {isStaff && <Link to="/eval"><button className="btn btn-ghost">Retrieval eval</button></Link>}
      </div>

      {err && <div className="alert alert-error">{err}</div>}

      <div className="panel" style={{ marginBottom: 16 }}>
        <form onSubmit={submit}>
          <div className="field">
            <label>QUERY</label>
            <input value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="Pump P-204 bearing inspection requirements" />
          </div>
          <div className="grid grid-3">
            <div className="field">
              <label>EQUIPMENT SCOPE (OPTIONAL)</label>
              <select value={fEquipment} onChange={(e) => setFEquipment(e.target.value)} style={selStyle}>
                <option value="">Whole company</option>
                {equipment.map((e) => <option key={e.id} value={e.id}>{e.code} — {e.name}</option>)}
              </select>
            </div>
            <div className="field">
              <label>VERSIONS</label>
              <select value={historical ? "hist" : "cur"} onChange={(e) => setHistorical(e.target.value === "hist")} style={selStyle}>
                <option value="cur">Current only</option>
                <option value="hist">Include historical</option>
              </select>
            </div>
            <div className="field">
              <label>&nbsp;</label>
              <button className="btn" disabled={busy || !query.trim()}>
                {busy ? "Searching…" : "Search evidence"}
              </button>
            </div>
          </div>
        </form>
        {res && (
          <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 8 }}>
            normalized: <b>{res.normalized_query}</b> · mode: <b>{res.mode}</b>
          </div>
        )}
      </div>

      {res?.status === "INSUFFICIENT_EVIDENCE" && (
        <div className="panel">
          <h3 style={{ marginTop: 0 }}>INSUFFICIENT_EVIDENCE</h3>
          <div className="kv"><span>CANDIDATES EXAMINED</span><span>{res.candidates}</span></div>
          <div className="kv"><span>STRONGEST SCORE</span><span>{res.best_score ?? "none"}</span></div>
          <div className="kv"><span>MINIMUM RELEVANCE</span><span>{res.minimum_relevance_score}</span></div>
          <div className="kv"><span>REASON</span><span>{res.reason}</span></div>
          <div style={{ fontSize: 13, color: "var(--muted)", marginTop: 10 }}>
            No conclusion is drawn from weak evidence. Gather more evidence or refine the query —
            Stage 7 will turn this into Next-Best-Evidence.
          </div>
        </div>
      )}

      {res?.status === "OK" && (
        <div className="grid" style={{ gap: 12 }}>
          {res.citations.map((c) => (
            <div className="panel" key={c.chunk_id}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
                <b>
                  <Link to={`/knowledge/${c.document_id}`}>{c.filename}</Link>
                  {" "}· v{c.document_version}
                  {c.page ? ` · p.${c.page}` : ""}
                  {c.section ? ` · ${c.section}` : ""}
                </b>
                <span className="badge">#{c.final_rank} · {c.retrieval_method} · {c.combined_score}</span>
              </div>
              <div className="preview-box" style={{ marginTop: 10, maxHeight: 160 }}>{c.excerpt}</div>
              <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 6 }}>
                semantic {c.semantic_score} · lexical {c.lexical_score}
                {c.equipment_id ? ` · equipment #${c.equipment_id}` : ""} · chunk {c.chunk_id}
              </div>
              <WhyList c={c} />
            </div>
          ))}
          {res.context_truncated && (
            <div className="alert alert-warn">Evidence context was truncated at the configured limit — provenance preserved.</div>
          )}
        </div>
      )}
    </div>
  );
}

const selStyle: React.CSSProperties = {
  width: "100%", padding: 11, borderRadius: 8, background: "#F8FAFC",
  color: "var(--text)", border: "1px solid var(--border)",
};
