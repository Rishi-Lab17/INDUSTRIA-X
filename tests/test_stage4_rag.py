"""Stage 4 tests: real local embeddings, chunking, indexing lifecycle, hybrid
retrieval + provenance, equipment scoping, versions/history, archive/delete,
cross-company isolation, RBAC, failure honesty, eval, offline, perf, audit."""
import time

from app.core.config import get_settings
from app.rag import service as rag_service
from app.rag.embeddings import (DeterministicTestProvider, FastEmbedProvider,
                                get_embedding_provider, set_embedding_provider)
from app.rag.retrieval import normalize_query
from app.rag.service import EVAL_CORPUS
from helpers import client, db

N = 0


def _next(prefix="rag"):
    global N
    N += 1
    return f"{prefix}{N}@rag.test", f"{prefix.capitalize()} Co {N}"


def _admin():
    email, company = _next()
    r = client.post("/api/auth/register", json={
        "company_name": company, "name": "Admin", "email": email,
        "password": "Str0ngPass!"})
    assert r.status_code == 201, r.text
    lr = client.post("/api/auth/login",
                     json={"email": email, "password": "Str0ngPass!"})
    assert lr.status_code == 200
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}


def _mkuser(admin_h, role, tag):
    email = f"{tag}-{role.lower()}@rag.test"
    r = client.post("/api/auth/users", headers=admin_h,
                    json={"name": tag, "email": email,
                          "password": "Str0ngPass!", "role": role})
    assert r.status_code == 201, r.text
    lr = client.post("/api/auth/login",
                     json={"email": email, "password": "Str0ngPass!"})
    assert lr.status_code == 200
    return {"Authorization": f"Bearer {lr.json()['access_token']}"}


def _equipment(h, code="P-204"):
    r = client.post("/api/equipment", headers=h,
                    json={"code": code, "name": f"Pump {code}", "type": "Pump",
                          "criticality": "HIGH"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _upload(h, content: bytes, filename: str, equipment_id=None):
    import io
    files = {"file": (filename, io.BytesIO(content), "application/octet-stream")}
    data = {}
    if equipment_id is not None:
        data["equipment_id"] = str(equipment_id)
    r = client.post("/api/documents", headers=h, files=files, data=data)
    assert r.status_code == 201, r.text
    return r.json()


def _index(h, doc_id, force=False):
    path = (f"/api/knowledge/documents/{doc_id}/"
            f"{'reindex' if force else 'index'}")
    r = client.post(path, headers=h)
    assert r.status_code == 200, r.text
    return r.json()


MANUAL = (b"Bearing inspection procedure for Pump P-204. Check bearing housing "
          b"vibration monthly with a calibrated meter. Bearing maintenance "
          b"interval is every 6 months. Replace bearings showing spalling.\n"
          b"Coupling alignment guide. Permitted angular misalignment is 0.05 mm. "
          b"Check alignment after every overhaul.\n")


def test_embedding_provider_real_and_deterministic():
    p = get_embedding_provider()
    assert isinstance(p, FastEmbedProvider) and not p.is_test
    assert p.dimension == 384
    assert "MiniLM" in p.model_name
    a = p.embed_texts(["Pump P-204 bearing vibration limit"])
    b = p.embed_texts(["Pump P-204 bearing vibration limit"])
    assert a == b and len(a[0]) == 384
    assert all(isinstance(x, float) for x in a[0])
    h = p.health()
    assert h["ok"] and h["dimension"] == 384
    t = DeterministicTestProvider()
    assert t.is_test and t.model_name.startswith("test-")


def test_chunking_and_index_lifecycle():
    ha = _admin()
    eq = _equipment(ha)
    d = _upload(ha, MANUAL, "manual.txt", equipment_id=eq)
    st = client.get(f"/api/knowledge/documents/{d['id']}/index-status",
                    headers=ha).json()
    assert st["index_status"] == "NOT_INDEXED"
    r = _index(ha, d["id"])
    assert r["status"] == "INDEXED" and r["chunks"] >= 1
    st = client.get(f"/api/knowledge/documents/{d['id']}/index-status",
                    headers=ha).json()
    assert st["index_status"] == "INDEXED"
    assert st["indexed_version"] == 1 and st["chunk_count"] >= 1
    assert st["embedding_model"] and st["indexed_at"]
    # duplicate content skipped, no new chunks
    r2 = _index(ha, d["id"])
    assert r2["detail"].startswith("Already indexed")
    # chunk metadata integrity (direct store read)
    from app.rag import store
    cands = store.fetch_candidates(_company_of(ha), limit=100)
    mine = [c for c in cands if c["doc_id"] == d["id"]]
    assert mine
    c = mine[0]
    for k in ("id", "doc_id", "company_id", "equipment_id", "filename",
              "version", "section", "source_type", "chunk_index",
              "char_count", "checksum", "embedding_model", "text"):
        assert k in c, k
    assert c["equipment_id"] == eq and c["embedding_model"]
    assert "vector" in c and len(c["vector"]) == 384
    h = client.get("/api/knowledge/health", headers=ha).json()
    assert set(h) >= {"documents_total", "indexed", "chunks_total",
                      "embedding_model", "vector_db"}


def _company_of(h):
    return client.get("/api/auth/me", headers=h).json()["user"]["company_id"]


def test_search_hybrid_provenance_and_scores():
    ha = _admin()
    eq = _equipment(ha)
    d = _upload(ha, MANUAL, "manual.txt", equipment_id=eq)
    _index(ha, d["id"])
    r = client.post("/api/knowledge/search", headers=ha, json={
        "query": "Pump P-204 bearing vibration limit", "equipment_id": eq})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "OK" and body["count"] >= 1
    assert body["normalized_query"] and body["original_query"]
    c = body["citations"][0]
    for k in ("document_id", "document_version", "chunk_id", "filename",
              "page", "section", "equipment_id", "excerpt",
              "semantic_score", "lexical_score", "combined_score",
              "initial_rank", "final_rank", "retrieval_method", "why_retrieved"):
        assert k in c, k
    assert "probability" not in str(body).lower()
    assert "confidence" not in str(body).lower()
    assert "vector" not in str(body)
    assert c["filename"] == "manual.txt" and c["equipment_id"] == eq
    assert c["excerpt"] and c["excerpt"] in _full_chunk_text(c["chunk_id"])
    assert isinstance(c["why_retrieved"], list) and c["why_retrieved"]
    assert body["context"] and body["chunks_used"] >= 1
    assert "truncated" in body or "context_truncated" in body


def _full_chunk_text(chunk_id):
    from app.rag import store
    return (store.get_chunk(chunk_id) or {}).get("text", "")


def test_equipment_scoped_retrieval():
    ha = _admin()
    e1, e2 = _equipment(ha, "P-204"), _equipment(ha, "C-301")
    d1 = _upload(ha, b"Pump P-204 bearing grease monthly.", "pump.txt", e1)
    d2 = _upload(ha, b"Compressor C-301 oil pressure check daily.", "comp.txt", e2)
    _index(ha, d1["id"])
    _index(ha, d2["id"])
    r = client.post("/api/knowledge/search", headers=ha,
                    json={"query": "bearing maintenance", "equipment_id": e1}).json()
    assert r["status"] == "OK"
    assert all(c["equipment_id"] == e1 for c in r["citations"])
    r2 = client.post("/api/knowledge/search", headers=ha,
                     json={"query": "oil pressure", "equipment_id": e2}).json()
    assert all(c["equipment_id"] == e2 for c in r2["citations"])


def test_insufficient_evidence_state():
    ha = _admin()
    eq = _equipment(ha)
    d = _upload(ha, MANUAL, "manual.txt", equipment_id=eq)
    _index(ha, d["id"])
    r = client.post("/api/knowledge/search", headers=ha, json={
        "query": "quantum flux capacitor zebras orbit Mars"})
    body = r.json()
    assert body["status"] == "INSUFFICIENT_EVIDENCE"
    assert body["citations"] == [] and body["count"] == 0
    assert "minimum_relevance_score" in body and body["best_score"] is not None
    assert "candidates" in body and body["reason"]


def test_version_consistency_and_historical():
    ha = _admin()
    eq = _equipment(ha)
    v1 = _upload(ha, b"Manual v1: torque 40Nm.", "guide.txt", eq)
    _index(ha, v1["id"])
    v2 = _upload(ha, b"Manual v2: torque 55Nm revised.", "guide.txt", eq)
    assert v2["version"] == 2
    st1 = client.get(f"/api/knowledge/documents/{v1['id']}/index-status",
                     headers=ha).json()
    assert st1["index_status"] == "STALE"  # retired on v2 creation
    _index(ha, v2["id"])
    r = client.post("/api/knowledge/search", headers=ha,
                    json={"query": "torque specification"}).json()
    assert r["status"] == "OK"
    assert all(c["document_version"] == 2 for c in r["citations"])
    assert any("55Nm" in c["excerpt"] for c in r["citations"])
    rh = client.post("/api/knowledge/search", headers=ha, json={
        "query": "torque specification", "include_historical": True,
        "top_k": 10}).json()
    assert any(c["document_version"] == 1 for c in rh["citations"])
    assert any("40Nm" in c["excerpt"] for c in rh["citations"])


def test_archive_and_delete_remove_vectors():
    ha = _admin()
    eq = _equipment(ha)
    d = _upload(ha, b"Temporary procedure text here.", "tmp.txt", eq)
    _index(ha, d["id"])
    q = {"query": "temporary procedure"}
    assert client.post("/api/knowledge/search", headers=ha,
                       json=q).json()["status"] == "OK"
    assert client.post(f"/api/documents/{d['id']}/archive", headers=ha).status_code == 200
    assert client.post("/api/knowledge/search", headers=ha,
                       json=q).json()["status"] == "INSUFFICIENT_EVIDENCE"
    rh = client.post("/api/knowledge/search", headers=ha,
                     json={**q, "include_historical": True}).json()
    assert rh["status"] == "OK"  # explicit historical still sees it
    # delete removes vectors entirely (distinctive content isolates the check)
    d2 = _upload(ha, b"Decommissioning checklist for Valve V-77 signed.", "del.txt", eq)
    _index(ha, d2["id"])
    assert client.delete(f"/api/documents/{d2['id']}", headers=ha).status_code == 200
    r = client.post("/api/knowledge/search", headers=ha, json={
        "query": "decommissioning checklist valve", "include_historical": True}).json()
    assert r["status"] == "INSUFFICIENT_EVIDENCE"


def test_cross_company_isolation_rag():
    ha, hb = _admin(), _admin()
    eq_a = _equipment(ha, "P-204")
    d = _upload(ha, b"Pump P-204 secret bearing notes.", "secret.txt", eq_a)
    _index(ha, d["id"])
    eq_b = _equipment(hb, "C-301")
    # B's search over A's terms finds nothing of A
    r = client.post("/api/knowledge/search", headers=hb, json={
        "query": "Pump P-204 secret bearing"}).json()
    assert all(c["filename"] != "secret.txt" for c in r.get("citations", []))
    # B cannot touch A's doc/chunks/equipment via RAG endpoints
    assert client.get(f"/api/knowledge/documents/{d['id']}/index-status",
                      headers=hb).status_code == 404
    assert client.post(f"/api/knowledge/documents/{d['id']}/index",
                       headers=hb).status_code in (403, 404)
    r = client.post("/api/knowledge/search", headers=hb, json={
        "query": "bearing", "document_id": d["id"]})
    assert r.status_code == 404
    r = client.post("/api/knowledge/search", headers=hb,
                    json={"query": "bearing", "equipment_id": eq_a})
    assert r.status_code == 404
    # B can still index+search its own content
    db_ = _upload(hb, b"Compressor C-301 oil notes.", "own.txt", eq_b)
    _index(hb, db_["id"])
    r = client.post("/api/knowledge/search", headers=hb,
                    json={"query": "compressor oil"}).json()
    assert r["status"] == "OK"


def test_rag_rbac():
    ha = _admin()
    he = _mkuser(ha, "ENGINEER", "rage")
    ht = _mkuser(ha, "TECHNICIAN", "ragt")
    eq = _equipment(ha)
    d = _upload(ha, MANUAL, "manual.txt", eq)
    assert client.post(f"/api/knowledge/documents/{d['id']}/index",
                       headers=ht).status_code == 403
    assert client.post(f"/api/knowledge/documents/{d['id']}/reindex",
                       headers=ht).status_code == 403
    assert client.post("/api/knowledge/reindex", headers=ht,
                       json={}).status_code == 403
    assert client.post("/api/knowledge/search", headers=ht, json={
        "query": "bearing"}).status_code in (200, 404)
    assert client.post(f"/api/knowledge/documents/{d['id']}/index",
                       headers=he).status_code == 200
    assert client.post("/api/knowledge/search",
                       json={"query": "bearing"}).status_code == 401


def test_index_failure_honest_and_retry():
    from app.rag.embeddings import EmbeddingProvider

    class Boom(EmbeddingProvider):
        name, is_test = "boom", True

        def embed_texts(self, texts):
            from app.rag.embeddings import EmbeddingError
            raise EmbeddingError("simulated outage")

        @property
        def dimension(self):
            return 8

        @property
        def model_name(self):
            return "boom-8"

    ha = _admin()
    eq = _equipment(ha)
    d = _upload(ha, b"Will fail indexing here.", "f.txt", eq)
    set_embedding_provider(Boom())
    try:
        r = client.post(f"/api/knowledge/documents/{d['id']}/index", headers=ha)
        assert r.status_code == 200
        assert r.json()["status"] == "INDEX_FAILED"
        st = client.get(f"/api/knowledge/documents/{d['id']}/index-status",
                        headers=ha).json()
        assert st["index_status"] == "INDEX_FAILED" and st["index_error"]
        # source doc untouched and still COMPLETED
        doc = client.get(f"/api/documents/{d['id']}", headers=ha).json()
        assert doc["processing_status"] == "COMPLETED"
    finally:
        set_embedding_provider(None)
    r = client.post(f"/api/knowledge/documents/{d['id']}/reindex", headers=ha)
    assert r.json()["status"] == "INDEXED"


def test_query_normalization():
    assert normalize_query("p204 vib problem") == "p-204 vibration problem"
    assert normalize_query("  TEMP Insp  ") == "temperature inspection"
    assert normalize_query("") == ""


def test_deduplication_and_why_signals():
    ha = _admin()
    eq = _equipment(ha)
    rep = (b"Grease bearings monthly. " * 40) + b"Unique tail sentence."
    d = _upload(ha, rep, "rep.txt", eq)
    _index(ha, d["id"])
    r = client.post("/api/knowledge/search", headers=ha, json={
        "query": "grease bearings monthly", "equipment_id": eq}).json()
    assert r["status"] == "OK"
    sums = [c["chunk_id"] for c in r["citations"]]
    assert len(sums) == len(set(sums))
    texts = [_full(c["chunk_id"]) for c in r["citations"]]
    assert len(set(texts)) == len(texts)
    for c in r["citations"]:
        assert isinstance(c["initial_rank"], int) and isinstance(c["final_rank"], int)
        assert "equipment_match" in c["why_retrieved"]


def _full(chunk_id):
    from app.rag import store
    return (store.get_chunk(chunk_id) or {}).get("text", "")


def test_knowledge_health_and_audit():
    ha = _admin()
    eq = _equipment(ha)
    d = _upload(ha, MANUAL, "manual.txt", eq)
    _index(ha, d["id"])
    h = client.get("/api/knowledge/health", headers=ha).json()
    assert h["documents_total"] >= 1 and h["indexed"] >= 1
    assert h["chunks_total"] >= 1 and h["chunks_active"] >= 1
    assert h["embedding_dimension"] == 384 and "MiniLM" in h["embedding_model"]
    assert h["vector_db"] == "ONLINE" and h["last_indexed_at"]
    client.post("/api/knowledge/search", headers=ha, json={"query": "bearing"})
    con = db()
    try:
        ev = con.execute(
            "SELECT detail FROM audit_events WHERE action = 'knowledge_searched'"
            " ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        con.close()
    import json as _json
    detail = _json.loads(ev[0])
    assert detail["mode"] == "general" and detail["results"] >= 1
    assert "query" in detail and len(detail["query"]) <= 200


def test_evaluation_executes_on_real_system():
    ha = _admin()
    eq = _equipment(ha, "EVAL-P204")
    for name, text in EVAL_CORPUS.items():
        d = _upload(ha, text.encode(), name, eq)
        _index(ha, d["id"])
    res = rag_service.run_evaluation(company_id=_company_of(ha),
                                     equipment_id=eq, k=5)
    assert len(res["queries"]) == 6
    for q in res["queries"]:
        assert set(q) >= {"query", "expected", "got", "rank", "mrr",
                          "precision_at_k", "recall_at_k", "latency_ms", "pass"}
        assert q["latency_ms"] >= 0
    # negative control must not fabricate evidence
    neg = [q for q in res["queries"] if q["expected"] is None][0]
    assert neg["got"] == []
    assert res["summary"]["pass_rate"] >= 0.75, res["summary"]
    r = client.get("/api/knowledge/eval", headers=ha)
    assert r.status_code == 200 and r.json()["summary"]["pass_rate"] >= 0.75


def test_offline_retrieval_after_setup():
    import socket
    ha = _admin()
    eq = _equipment(ha)
    d = _upload(ha, MANUAL, "manual.txt", eq)
    _index(ha, d["id"])
    real_create, real_getaddr = socket.create_connection, socket.getaddrinfo

    def _blocked(*a, **k):
        raise OSError("network disabled for offline test")

    socket.create_connection = _blocked
    socket.getaddrinfo = _blocked
    try:
        r = client.post("/api/knowledge/search", headers=ha,
                        json={"query": "bearing vibration"}).json()
        assert r["status"] == "OK" and r["citations"]
        d2 = _upload(ha, b"Offline index check text.", "off.txt", eq)
        assert _index(ha, d2["id"])["status"] == "INDEXED"
    finally:
        socket.create_connection, socket.getaddrinfo = real_create, real_getaddr


def test_performance_bounds():
    ha = _admin()
    eq = _equipment(ha)
    t0 = time.time()
    for i in range(15):
        body = (" ".join(f"Pump P-204 synthetic paragraph {i}-{j} with bearing "
                         f"vibration temperature notes."
                         for j in range(25))).encode()
        d = _upload(ha, body, f"syn{i}.txt", eq)
        _index(ha, d["id"])
    index_s = time.time() - t0
    t0 = time.time()
    r = client.post("/api/knowledge/search", headers=ha,
                    json={"query": "bearing vibration", "top_k": 8}).json()
    search_s = time.time() - t0
    print(f"\n[perf] 15 docs indexed in {index_s:.1f}s;"
          f" search {search_s:.2f}s, hits={r.get('count')}")
    assert r["status"] == "OK"
    assert search_s < 5.0

