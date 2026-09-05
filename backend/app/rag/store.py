"""Persistent LOCAL vector database (SQLite file, no server, no cloud).

Tables: chunks (metadata + text + active flag), embeddings (float32 blob),
chunks_fts (FTS5 porter index for the lexical arm, kept in sync).
Never exposed to the browser; raw vectors never leave this module's callers
except as in-memory arrays for scoring.
"""
import sqlite3
import struct
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..core.config import ROOT, get_settings

_lock = threading.Lock()


def _path() -> Path:
    s = get_settings()
    p = Path(s.VECTOR_DB_PATH)
    return p if p.is_absolute() else ROOT / p


def connect() -> sqlite3.Connection:
    db = _path()
    db.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db), check_same_thread=False, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    return con


def init_store() -> None:
    con = connect()
    try:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS chunks(
          id TEXT PRIMARY KEY,
          doc_id INTEGER NOT NULL,
          company_id INTEGER NOT NULL,
          equipment_id INTEGER,
          filename TEXT NOT NULL,
          version INTEGER NOT NULL,
          page INTEGER,
          section TEXT,
          source_type TEXT NOT NULL,
          chunk_index INTEGER NOT NULL,
          char_count INTEGER NOT NULL,
          checksum TEXT NOT NULL,
          embedding_model TEXT NOT NULL,
          active INTEGER NOT NULL DEFAULT 1,
          created_at TEXT NOT NULL,
          text TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_company ON chunks(company_id, active);
        CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id, version);
        CREATE INDEX IF NOT EXISTS idx_chunks_equipment ON chunks(equipment_id);
        CREATE TABLE IF NOT EXISTS embeddings(
          chunk_id TEXT PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
          vector BLOB NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
          text, content='chunks', content_rowid='rowid', tokenize='porter');
        """)
        # Migrate legacy contentless FTS (manual sync, unmaintainable) to
        # content-synced FTS (triggers keep it consistent automatically).
        row = con.execute("SELECT sql FROM sqlite_master WHERE name='chunks_fts'"
                          ).fetchone()
        if row and "content=''" in (row[0] or ""):
            con.execute("DROP TABLE chunks_fts")
            con.execute("CREATE VIRTUAL TABLE chunks_fts USING fts5("
                        "text, content='chunks', content_rowid='rowid',"
                        " tokenize='porter')")
        # Sync triggers (SQLite does not create these automatically).
        con.executescript("""
        CREATE TRIGGER IF NOT EXISTS chunks_fts_ai AFTER INSERT ON chunks BEGIN
          INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_fts_ad AFTER DELETE ON chunks BEGIN
          INSERT INTO chunks_fts(chunks_fts, rowid, text)
          VALUES ('delete', old.rowid, old.text);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_fts_au AFTER UPDATE ON chunks BEGIN
          INSERT INTO chunks_fts(chunks_fts, rowid, text)
          VALUES ('delete', old.rowid, old.text);
          INSERT INTO chunks_fts(rowid, text) VALUES (new.rowid, new.text);
        END;
        """)
        # Self-heal: index any chunk rows missing from the FTS index.
        con.execute("INSERT INTO chunks_fts(rowid, text)"
                    " SELECT rowid, text FROM chunks WHERE rowid NOT IN"
                    " (SELECT rowid FROM chunks_fts)")
        con.commit()
    finally:
        con.close()


def _pack(vec: list[float]) -> bytes:
    return struct.pack(f"<{len(vec)}f", *vec)


def _unpack(blob: bytes) -> list[float]:
    n = len(blob) // 4
    return list(struct.unpack(f"<{n}f", blob))


def upsert_chunks(doc_id: int, company_id: int, chunks: list[dict],
                  vectors: list[list[float]], meta: dict) -> list[str]:
    """Replace this doc's chunks (same version) with fresh ones. Returns ids."""
    import uuid as _uuid
    ts = datetime.now(timezone.utc).isoformat()
    ids = [f"c_{_uuid.uuid4().hex[:12]}" for _ in chunks]
    with _lock:
        con = connect()
        try:
            con.execute("PRAGMA foreign_keys=ON;")
            old = con.execute("SELECT id FROM chunks WHERE doc_id = ?"
                              " AND version = ?",
                              (doc_id, meta["version"])).fetchall()
            for (cid,) in old:
                con.execute("DELETE FROM embeddings WHERE chunk_id = ?", (cid,))
                con.execute("DELETE FROM chunks WHERE id = ?", (cid,))
            for i, (ch, vec, cid) in enumerate(zip(chunks, vectors, ids)):
                con.execute(
                    "INSERT INTO chunks (id, doc_id, company_id, equipment_id, filename,"
                    " version, page, section, source_type, chunk_index, char_count,"
                    " checksum, embedding_model, active, created_at, text)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (cid, doc_id, company_id, meta.get("equipment_id"),
                     meta["filename"], meta["version"], ch.get("page"),
                     ch.get("section"), ch["source_type"], i, ch["char_count"],
                     ch["checksum"], meta["embedding_model"], 1, ts, ch["text"]))
                con.execute("INSERT INTO embeddings (chunk_id, vector) VALUES (?,?)",
                            (cid, _pack(vec)))
            con.commit()
        finally:
            con.close()
    return ids


def set_doc_active(doc_id: int, active: bool) -> int:
    """Activate/deactivate ALL chunks of a doc row (archive / version retire).
    Returns affected count."""
    con = connect()
    try:
        cur = con.execute("UPDATE chunks SET active = ? WHERE doc_id = ?",
                          (1 if active else 0, doc_id))
        con.commit()
        return cur.rowcount
    finally:
        con.close()


def delete_doc(doc_id: int) -> int:
    """Remove all chunks/vectors/fts rows of a doc row. Returns removed count."""
    con = connect()
    try:
        ids = [r[0] for r in con.execute(
            "SELECT id FROM chunks WHERE doc_id = ?", (doc_id,)).fetchall()]
        for cid in ids:
            con.execute("DELETE FROM embeddings WHERE chunk_id = ?", (cid,))
        cur = con.execute("DELETE FROM chunks WHERE doc_id = ?", (doc_id,))
        con.commit()
        return cur.rowcount
    finally:
        con.close()


def fetch_candidates(company_id: int, *, active_only: bool = True,
                     equipment_id: int | None = None,
                     doc_id: int | None = None,
                     source_types: list[str] | None = None,
                     embedding_model: str | None = None,
                     limit: int = 2000) -> list[dict]:
    """Load chunk rows + vectors for scoring (bounded; never whole-table
    blindly — company filter always applies)."""
    q = ("SELECT c.*, e.vector FROM chunks c JOIN embeddings e"
         " ON e.chunk_id = c.id WHERE c.company_id = ?")
    params: list = [company_id]
    if active_only:
        q += " AND c.active = 1"
    if equipment_id is not None:
        q += " AND c.equipment_id = ?"
        params.append(equipment_id)
    if doc_id is not None:
        q += " AND c.doc_id = ?"
        params.append(doc_id)
    if source_types:
        q += " AND c.source_type IN (%s)" % ",".join("?" * len(source_types))
        params += source_types
    if embedding_model:
        q += " AND c.embedding_model = ?"
        params.append(embedding_model)
    q += " ORDER BY c.id LIMIT ?"
    params.append(limit)
    con = connect()
    try:
        rows = con.execute(q, params).fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        d = dict(r)
        d["vector"] = _unpack(r["vector"])
        out.append(d)
    return out


def lexical_candidates(company_id: int, query: str, *, active_only: bool = True,
                       equipment_id: int | None = None,
                       doc_id: int | None = None,
                       source_types: list[str] | None = None,
                       limit: int = 200) -> list[tuple[dict, float]]:
    """FTS5 BM25 candidates. Returns (chunk, bm25_rank) — rank is negative,
    closer to zero is better."""
    filt, fparams = "", []
    if active_only:
        filt += " AND c.active = 1"
    if equipment_id is not None:
        filt += " AND c.equipment_id = ?"
        fparams.append(equipment_id)
    if doc_id is not None:
        filt += " AND c.doc_id = ?"
        fparams.append(doc_id)
    if source_types:
        filt += " AND c.source_type IN (%s)" % ",".join("?" * len(source_types))
        fparams += source_types
    # Sanitize MATCH: quote terms to avoid FTS syntax errors on odd input.
    safe = " ".join(f'"{t}"' for t in query.split()[:32]) or '""'
    # Subquery forces the FTS index as the driving loop: bm25() returns NULL
    # when SQLite instead iterates the content table first and probes FTS.
    q = ("SELECT c.*, m.rank FROM (SELECT rowid, bm25(chunks_fts) AS rank"
         " FROM chunks_fts WHERE chunks_fts MATCH ?) m"
         " JOIN chunks c ON c.rowid = m.rowid"
         " WHERE c.company_id = ?" + filt +
         " ORDER BY m.rank LIMIT ?")
    params = [safe, company_id] + fparams + [limit]
    con = connect()
    try:
        rows = con.execute(q, params).fetchall()
    except Exception:
        return []
    finally:
        try:
            con.close()
        except Exception:
            pass
    out = []
    for r in rows:
        d = dict(r)
        rank = d.pop("rank", None)
        if rank is None:
            continue  # unrankable row: drop, never cite blindly
        out.append((d, float(rank)))
    return out


def get_chunk(chunk_id: str) -> dict | None:
    con = connect()
    try:
        r = con.execute("SELECT * FROM chunks WHERE id = ?", (chunk_id,)).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def stats(company_id: int | None = None) -> dict:
    con = connect()
    try:
        filt, params = "", []
        if company_id is not None:
            filt, params = "WHERE company_id = ?", [company_id]
        n = con.execute(f"SELECT COUNT(*) FROM chunks {filt}", params).fetchone()[0]
        a = con.execute(f"SELECT COUNT(*) FROM chunks {filt}"
                        + (" AND " if filt else "WHERE ") + "active = 1",
                        params).fetchone()[0]
        models = [r[0] for r in con.execute(
            f"SELECT DISTINCT embedding_model FROM chunks {filt}", params).fetchall()]
        last = con.execute(f"SELECT MAX(created_at) FROM chunks {filt}",
                           params).fetchone()[0]
        return {"chunks_total": n, "chunks_active": a,
                "embedding_models": models, "last_indexed_at": last}
    finally:
        con.close()


def fts_rebuild_check() -> bool:
    """True when FTS index is usable (segment readable)."""
    try:
        con = connect()
        try:
            con.execute("SELECT count(*) FROM chunks_fts").fetchone()
            return True
        finally:
            con.close()
    except Exception:
        return False
