"""Model registry + capability-gated router + cached health.

The registry NEVER fabricates: capabilities carry verified_live flags, and an
absent runtime reports OFFLINE/ERROR with a clear reason. Routing maps tasks
to local capabilities; anything without a local model returns an explicit
unavailable capability — never an external service.
"""
import logging
import threading
import time

from ..core.config import get_settings
from .providers import get_provider

logger = logging.getLogger("industria-x.ai")

TASK_MODELS = {
    "reasoning": "kimi-k3",
    "document_qa": "kimi-k3",
    "tool_planning": "kimi-k3",
    "coding": "kimi-k3",
    "vision": None,        # Stage 6 model — no local runtime yet
    "embedding": None,     # served by Stage 4 embedding provider, not chat
}

TASK_CAPABILITY = {
    "reasoning": "REASONING",
    "document_qa": "CHAT",
    "tool_planning": "TOOL_CALLING",
    "coding": "CODING",
    "vision": "VISION",
    "embedding": None,
}

_cache_lock = threading.Lock()
_health_cache: dict = {}
HEALTH_TTL_S = 30


def model_entry() -> dict:
    """The single configured chat model record."""
    s = get_settings()
    p = get_provider()
    caps = p.capabilities()
    return {
        "id": s.KIMI_K3_MODEL if not p.is_test else "test",
        "provider": p.name,
        "display_name": p.display_name,
        "local": p.local,
        "is_test": p.is_test,
        "capabilities": caps,
        "context_limit": None,  # unknown until a runtime reports it
        "endpoint": s.KIMI_K3_BASE_URL if not p.is_test else "in-process",
        "version": None,
    }


def list_models() -> list[dict]:
    entry = model_entry()
    entry["last_health_check"] = cached_health().get("checked_at")
    entry["status"] = cached_health().get("status")
    entry["error"] = (None if entry["status"] in ("ONLINE",)
                      else cached_health().get("detail"))
    return [entry]


def cached_health(force: bool = False) -> dict:
    now = time.monotonic()
    with _cache_lock:
        if (not force and _health_cache
                and now - _health_cache.get("_t", 0) < HEALTH_TTL_S):
            return {k: v for k, v in _health_cache.items() if k != "_t"}
    try:
        h = get_provider().health()
    except Exception as e:  # never crash callers on probe failure
        logger.warning("AI health probe failed: %s", type(e).__name__)
        h = {"status": "ERROR", "latency_ms": 0.0,
             "detail": "Health probe failed", "model": "unknown",
             "endpoint": "unknown"}
    with _cache_lock:
        _health_cache.clear()
        _health_cache.update(h)
        _health_cache["_t"] = now
    return h


def route(task: str) -> dict:
    """Returns {provider, model} or raises UnavailableCapability."""
    from .providers import ModelUnavailable
    model_id = TASK_MODELS.get(task)
    if model_id is None:
        if task == "embedding":
            return {"provider": "stage4-embeddings", "model": "local-embedding",
                    "note": "served by Stage 4 embedding provider, not chat"}
        raise ModelUnavailable(f"No local model for task '{task}' (capability unavailable)")
    need = TASK_CAPABILITY.get(task)
    if need:
        cap = model_entry()["capabilities"].get(need, {})
        if not cap.get("supported"):
            raise ModelUnavailable(
                f"Capability {need} not supported for task '{task}'")
    s = get_settings()
    return {"provider": get_provider().name,
            "model": s.KIMI_K3_MODEL if not get_provider().is_test else "test"}


def validate_ai_config() -> list[str]:
    """Startup diagnostics. Returns warnings; never raises for Kimi offline."""
    s = get_settings()
    warnings = []
    if s.AI_PROVIDER.strip().lower() not in ("kimi-k3", "kimi", "test"):
        warnings.append(f"Unknown AI_PROVIDER={s.AI_PROVIDER!r} (want kimi-k3|test)")
    for key in ("KIMI_CONNECT_TIMEOUT_S", "KIMI_K3_TIMEOUT_S", "KIMI_MAX_RETRIES",
                "AI_MAX_MESSAGE_CHARS", "AI_MAX_CONTEXT_CHARS", "AI_MEMORY_MESSAGES",
                "AI_MAX_TOOL_CALLS_PER_RUN", "AI_RUNS_PER_USER",
                "AI_RUNS_PER_USER_WINDOW_S", "AI_RUNS_PER_COMPANY",
                "AI_RUNS_PER_COMPANY_WINDOW_S"):
        if getattr(s, key, 1) < 0:
            warnings.append(f"{key} must be >= 0")
    if s.KIMI_MAX_TOKENS <= 0:
        warnings.append("KIMI_MAX_TOKENS must be > 0")
    if not (0.0 <= s.KIMI_TEMPERATURE <= 2.0):
        warnings.append("KIMI_TEMPERATURE should be within 0..2")
    for w in warnings:
        logger.warning("AI config: %s", w)
    return warnings
