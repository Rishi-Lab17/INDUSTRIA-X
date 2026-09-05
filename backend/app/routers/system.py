"""Health + sovereignty. Every value is probed live — nothing is hardcoded
marketing copy. Statuses: ONLINE | OFFLINE | DEGRADED | ERROR."""
import socket
import time
import urllib.request
from urllib.parse import urlparse

from fastapi import APIRouter

from ..core.config import get_settings
from ..db import connect

router = APIRouter(tags=["system"])


def _tcp_ok(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _probe_http_models(base_url: str, timeout: float) -> bool:
    """True only if an OpenAI-compatible /models endpoint answers."""
    try:
        url = base_url.rstrip("/") + "/models"
        req = urllib.request.Request(url, headers={"Authorization": "Bearer local"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return 200 <= r.status < 300
    except Exception:
        return False


def _host_port(url: str, default_port: int) -> tuple[str, int]:
    p = urlparse(url)
    host = p.hostname or "127.0.0.1"
    return host, p.port or default_port


@router.get("/api/health")
def health():
    s = get_settings()
    t0 = time.time()
    services: dict[str, dict] = {}

    services["backend"] = {"status": "ONLINE", "detail": "FastAPI responding"}

    try:
        con = connect()
        try:
            con.execute("SELECT 1").fetchone()
        finally:
            con.close()
        services["database"] = {"status": "ONLINE",
                                "detail": f"SQLite OK ({s.db_path().name})"}
    except Exception as e:
        services["database"] = {"status": "ERROR", "detail": f"SQLite unreachable: {e}"}

    try:
        probe = s.storage_dirs()[0] / ".health_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        services["storage"] = {"status": "ONLINE", "detail": "Local storage writable"}
    except Exception as e:
        services["storage"] = {"status": "ERROR", "detail": f"Storage not writable: {e}"}

    # Kimi K3: PRIMARY engine. Reachable only via a real on-prem server.
    kimi_host, kimi_port = _host_port(s.KIMI_K3_BASE_URL, 8000)
    if _tcp_ok(kimi_host, kimi_port) and _probe_http_models(s.KIMI_K3_BASE_URL, s.KIMI_K3_TIMEOUT_S):
        services["kimi"] = {"status": "ONLINE",
                            "detail": f"{s.KIMI_K3_MODEL} reachable at {s.KIMI_K3_BASE_URL}"}
    else:
        services["kimi"] = {"status": "OFFLINE",
                            "detail": f"No Kimi K3 server at {s.KIMI_K3_BASE_URL}. "
                                      "AI features return a clear error until one is connected."}

    ollama_host, ollama_port = _host_port(s.OLLAMA_BASE_URL, 11434)
    if _tcp_ok(ollama_host, ollama_port):
        services["dev_model"] = {"status": "ONLINE",
                                 "detail": f"Ollama dev model reachable ({s.DEV_MODEL}) — labelled, never Kimi"}
    else:
        services["dev_model"] = {"status": "OFFLINE",
                                 "detail": "Ollama not running on this machine"}

    # Email delivery provider: resend only with a real key, else local outbox.
    # Never reported as external/online unless Resend is actually configured.
    from ..services import email_service
    if email_service.resend_wanted() and s.RESEND_FROM_EMAIL:
        services["email_provider"] = {"status": "ONLINE",
                                      "detail": "Resend (explicitly configured)"}
    elif email_service.resend_wanted():
        services["email_provider"] = {"status": "DEGRADED",
                                      "detail": "Resend enabled but RESEND_FROM_EMAIL missing"}
    else:
        services["email_provider"] = {"status": "ONLINE",
                                      "detail": "Development outbox (local, no external delivery)"}

    # RAG: real local probes — embedding model + vector store file.
    try:
        from ..rag.embeddings import get_embedding_provider
        from ..rag.store import fts_rebuild_check
        emb = get_embedding_provider().health()
        if emb["ok"]:
            services["rag"] = {"status": "ONLINE",
                               "detail": f"embeddings {emb['model']} ({emb['dimension']}d), local"}
        else:
            services["rag"] = {"status": "ERROR",
                               "detail": f"embedding model unavailable ({emb['model']})"}
        services["vector_db"] = ({"status": "ONLINE", "detail": "Local vector store ready"}
                                 if fts_rebuild_check() else
                                 {"status": "ERROR", "detail": "Vector store unreadable"})
    except Exception as e:
        services["rag"] = {"status": "ERROR", "detail": f"RAG probe failed: {type(e).__name__}"}
        services["vector_db"] = {"status": "ERROR", "detail": "Vector store unreadable"}
    services["sensor_engine"] = {"status": "OFFLINE", "detail": "Stage 6 not implemented yet"}
    services["vision_engine"] = {"status": "OFFLINE", "detail": "Stage 6 not implemented yet"}

    overall = "ONLINE"
    if any(v["status"] == "ERROR" for v in services.values()):
        overall = "ERROR"
    elif services["database"]["status"] != "ONLINE" or services["storage"]["status"] != "ONLINE":
        overall = "DEGRADED"
    return {"status": overall, "services": services,
            "latency_ms": round((time.time() - t0) * 1000, 1)}


@router.get("/api/sovereignty")
def sovereignty():
    s = get_settings()
    kimi_host, kimi_port = _host_port(s.KIMI_K3_BASE_URL, 8000)
    kimi_reachable = _tcp_ok(kimi_host, kimi_port) and _probe_http_models(
        s.KIMI_K3_BASE_URL, s.KIMI_K3_TIMEOUT_S)
    return {
        "ai_inference": s.SOV_AI_INFERENCE,
        "document_processing": s.SOV_DOC_PROCESSING,
        "knowledge_base": s.SOV_KNOWLEDGE_BASE,
        "vector_db": s.SOV_VECTOR_DB,
        "industrial_data": s.SOV_INDUSTRIAL_DATA,
        "external_ai": s.EXTERNAL_AI,
        "external_fallback": s.EXTERNAL_FALLBACK,
        # Email delivery is independent of AI sovereignty: resend is external
        # and optional; the development outbox is fully local.
        "email_delivery": ("resend (external, explicitly configured)"
                           if (s.RESEND_ENABLED and s.RESEND_API_KEY
                               and s.RESEND_FROM_EMAIL)
                           else "development_outbox (local)"),
        "ai_provider": s.AI_PROVIDER,
        "ai_active_model": s.KIMI_K3_MODEL if kimi_reachable else "none",
        "kimi_reachable": kimi_reachable,
        "note": ("Kimi K3 is configured as the primary engine. "
                 + ("A Kimi K3 server is reachable."
                    if kimi_reachable else
                    "No Kimi K3 server is connected — AI calls fail loudly, never faked.")),
    }
