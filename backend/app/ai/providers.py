"""AI provider abstraction. INDUSTRIA-X talks ONLY to AIProvider.

KimiK3Provider: local OpenAI-compatible HTTP (httpx). No fallback, ever.
TestProvider: deterministic scripted responses for infrastructure tests ONLY;
never presented as Kimi (labelled TEST in every surface).
"""
import json
import threading
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone

import httpx

from ..core.config import get_settings


class AIError(Exception):
    """Base with a stable machine-readable category (never stack traces)."""
    category = "MODEL_ERROR"

    def __init__(self, message: str):
        super().__init__(message)


class ModelUnavailable(AIError):
    category = "MODEL_UNAVAILABLE"


class ModelTimeout(AIError):
    category = "MODEL_TIMEOUT"


class ModelRequestInvalid(AIError):
    category = "INVALID_REQUEST"


class Generation:
    """Provider result. usage may be None → UI shows 'Usage unavailable'."""
    def __init__(self, text: str, *, usage=None, latency_ms: float = 0.0,
                 streamed: bool = False, tool_calls: list | None = None):
        self.text = text
        self.usage = usage
        self.latency_ms = latency_ms
        self.streamed = streamed
        self.tool_calls = tool_calls or []


class AIProvider(ABC):
    name = "base"
    display_name = "base"
    is_test = False
    local = True

    @abstractmethod
    def generate(self, *, messages: list[dict], timeout_s: float,
                 cancelled: threading.Event | None = None, **kwargs) -> Generation:
        """messages: [{role, content}]. Must raise AIError subclasses only."""

    def stream(self, *, messages: list[dict], timeout_s: float,
               cancelled: threading.Event | None = None, **kwargs):
        """Yield text deltas. Default: single non-streamed chunk (honest:
        callers must not claim streaming when this path is used)."""
        gen = self.generate(messages=messages, timeout_s=timeout_s,
                            cancelled=cancelled, **kwargs)
        yield gen.text
        gen.streamed = False

    @abstractmethod
    def health(self) -> dict:
        """{status: ONLINE|OFFLINE|ERROR|STARTING, latency_ms, detail, ...}.
        Must use a minimal safe probe — never production documents."""

    @abstractmethod
    def capabilities(self) -> dict:
        """{capability: {'supported': bool, 'verified_live': bool}}."""


def _auth_headers() -> dict:
    # "local" is the documented no-auth placeholder: omit the header instead
    # of sending a fake credential.
    s = get_settings()
    key = (s.KIMI_K3_API_KEY or "").strip()
    if not key or key == "local":
        return {"Content-Type": "application/json"}
    return {"Content-Type": "application/json",
            "Authorization": f"Bearer {key}"}


def _is_transient(exc: Exception, status: int | None) -> bool:
    if isinstance(exc, (httpx.ConnectError, httpx.ReadTimeout, httpx.WriteError,
                        httpx.PoolTimeout, httpx.RemoteProtocolError)):
        return True
    return status in (429, 500, 502, 503, 504)


class KimiK3Provider(AIProvider):
    """Primary model: local Kimi K3 over an OpenAI-compatible endpoint.
    Offline/absent server → ModelUnavailable (HTTP 503 downstream)."""
    name = "kimi-k3"
    display_name = "Kimi K3"

    def _url(self, path: str) -> str:
        return get_settings().KIMI_K3_BASE_URL.rstrip("/") + path

    def _payload(self, messages: list[dict], stream: bool, **kwargs) -> dict:
        s = get_settings()
        return {"model": s.KIMI_K3_MODEL, "messages": messages,
                "temperature": s.KIMI_TEMPERATURE,
                "max_tokens": kwargs.get("max_tokens", s.KIMI_MAX_TOKENS),
                "stream": stream}

    def _post(self, payload: dict, timeout_s: float) -> httpx.Response:
        s = get_settings()
        last: Exception | None = None
        for attempt in range(1 + max(0, s.KIMI_MAX_RETRIES)):
            try:
                # trust_env=False: local inference must never be routed via a
                # proxy from the environment (sovereignty + determinism).
                resp = httpx.post(
                    self._url("/chat/completions"), headers=_auth_headers(),
                    json=payload, trust_env=False,
                    timeout=httpx.Timeout(timeout_s, connect=s.KIMI_CONNECT_TIMEOUT_S))
                if resp.status_code in (401, 403):
                    raise ModelRequestInvalid(
                        f"Kimi rejected credentials (HTTP {resp.status_code})")
                if resp.status_code == 404:
                    raise ModelRequestInvalid(
                        f"Kimi model/endpoint not found (HTTP 404) at {s.KIMI_K3_BASE_URL}")
                if resp.status_code == 422:
                    raise ModelRequestInvalid("Kimi rejected the request (HTTP 422)")
                if resp.status_code >= 400:
                    if _is_transient(None, resp.status_code) and attempt < s.KIMI_MAX_RETRIES:
                        time.sleep(0.5 * attempt)
                        continue
                    raise AIError(f"Kimi request failed (HTTP {resp.status_code})")
                return resp
            except ModelRequestInvalid:
                raise
            except AIError:
                raise
            except (httpx.TimeoutException,) as e:
                last = e
                if attempt < s.KIMI_MAX_RETRIES:
                    time.sleep(0.5 * attempt)
                    continue
                raise ModelTimeout(
                    f"Kimi request timed out after {timeout_s}s") from e
            except Exception as e:
                last = e
                if _is_transient(e, None) and attempt < s.KIMI_MAX_RETRIES:
                    time.sleep(0.5 * attempt)
                    continue
                raise ModelUnavailable(
                    f"Local Kimi K3 is currently unavailable ({type(e).__name__})") from e
        raise ModelUnavailable(
            f"Local Kimi K3 is currently unavailable ({type(last).__name__})")

    def generate(self, *, messages, timeout_s, cancelled=None, **kwargs) -> Generation:
        t0 = time.time()
        resp = self._post(self._payload(messages, False, **kwargs), timeout_s)
        try:
            data = resp.json()
            text = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage")
        except Exception as e:
            raise AIError("Kimi returned an unreadable response") from e
        if cancelled is not None and cancelled.is_set():
            raise _Cancelled()
        return Generation(text, usage=usage,
                          latency_ms=round((time.time() - t0) * 1000, 1))

    def stream(self, *, messages, timeout_s, cancelled=None, **kwargs):
        s = get_settings()
        t0 = time.time()
        try:
            with httpx.stream(
                    "POST", self._url("/chat/completions"), headers=_auth_headers(),
                    json=self._payload(messages, True, **kwargs), trust_env=False,
                    timeout=httpx.Timeout(timeout_s, connect=s.KIMI_CONNECT_TIMEOUT_S)) as resp:
                if resp.status_code != 200:
                    # Reuse non-stream error mapping.
                    raise _StatusError(resp.status_code)
                for line in resp.iter_lines():
                    if cancelled is not None and cancelled.is_set():
                        raise _Cancelled()
                    line = line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"].get("content", "")
                    except Exception:
                        continue
                    if delta:
                        yield delta
        except _Cancelled:
            raise
        except _StatusError as e:
            self._raise_for_status(e.status)
        except httpx.TimeoutException as e:
            raise ModelTimeout(f"Kimi stream timed out after {timeout_s}s") from e
        except Exception as e:
            raise ModelUnavailable(
                f"Local Kimi K3 is currently unavailable ({type(e).__name__})") from e
        _ = time.time() - t0

    def _raise_for_status(self, status: int) -> None:
        if status in (401, 403):
            raise ModelRequestInvalid(f"Kimi rejected credentials (HTTP {status})")
        if status == 404:
            raise ModelRequestInvalid("Kimi model/endpoint not found (HTTP 404)")
        raise AIError(f"Kimi request failed (HTTP {status})")

    def health(self) -> dict:
        s = get_settings()
        if not s.KIMI_ENABLED:
            return {"status": "OFFLINE", "latency_ms": 0.0,
                    "detail": "Kimi disabled by configuration (KIMI_ENABLED=false)",
                    "model": s.KIMI_K3_MODEL, "endpoint": s.KIMI_K3_BASE_URL,
                    "checked_at": _now()}
        t0 = time.time()
        try:
            resp = httpx.get(self._url("/models"), headers=_auth_headers(),
                             trust_env=False,
                             timeout=httpx.Timeout(s.KIMI_CONNECT_TIMEOUT_S))
            latency = round((time.time() - t0) * 1000, 1)
            if resp.status_code != 200:
                return {"status": "ERROR", "latency_ms": latency,
                        "detail": f"Kimi /models returned HTTP {resp.status_code}",
                        "model": s.KIMI_K3_MODEL, "endpoint": s.KIMI_K3_BASE_URL,
                        "checked_at": _now()}
            return {"status": "ONLINE", "latency_ms": latency,
                    "detail": f"Kimi K3 reachable at {s.KIMI_K3_BASE_URL}",
                    "model": s.KIMI_K3_MODEL, "endpoint": s.KIMI_K3_BASE_URL,
                    "checked_at": _now()}
        except Exception as e:
            return {"status": "OFFLINE", "latency_ms": 0.0,
                    "detail": f"Local Kimi K3 is currently unavailable ({type(e).__name__})",
                    "model": s.KIMI_K3_MODEL, "endpoint": s.KIMI_K3_BASE_URL,
                    "checked_at": _now()}

    def capabilities(self) -> dict:
        # Declared family capabilities; verified_live flips only via a live
        # probe that we do not fake — offline here, so all False.
        live = self.health()["status"] == "ONLINE"
        caps = {}
        for c in ("REASONING", "CHAT", "TOOL_CALLING", "STRUCTURED_OUTPUT",
                  "CODING", "LONG_CONTEXT", "VISION"):
            caps[c] = {"supported": c != "VISION", "verified_live": live and c != "VISION"}
        return caps


class _Cancelled(Exception):
    pass


class _StatusError(Exception):
    def __init__(self, status: int):
        super().__init__(str(status))
        self.status = status


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class TestProvider(AIProvider):
    """TEST ONLY infrastructure double. Deterministic scripted output grounded
    on provided evidence — proves orchestration/citations, never intelligence.
    Selected only when AI_PROVIDER=test. UI must label it TEST."""
    name = "test"
    display_name = "Test Provider (TEST ONLY)"
    is_test = True

    def __init__(self, script: list[str] | None = None, hang: bool = False):
        self.script = script if script is not None else [
            "Grounded test answer based on the retrieved evidence."]
        self.hang = hang

    def _maybe_hang(self, cancelled) -> None:
        # A hung provider never returns (daemon worker is abandoned on timeout).
        while True:
            if cancelled is not None and cancelled.is_set():
                raise _Cancelled()
            time.sleep(0.2)

    def generate(self, *, messages, timeout_s, cancelled=None, **kwargs) -> Generation:
        if self.hang:
            self._maybe_hang(cancelled)
        if cancelled is not None and cancelled.is_set():
            raise _Cancelled()
        evidence = int(kwargs.get("evidence_count", 0) or 0)
        if evidence <= 0:
            text = ("Insufficient evidence in the current knowledge base. "
                    "Refine the query, select equipment, or upload a relevant document.")
        else:
            text = " ".join(self.script) + f" [evidence:{evidence}]"
        return Generation(text, usage=None, latency_ms=1.0)

    def stream(self, *, messages, timeout_s, cancelled=None, **kwargs):
        if self.hang:
            self._maybe_hang(cancelled)
        gen = self.generate(messages=messages, timeout_s=timeout_s,
                            cancelled=cancelled, **kwargs)
        for token in gen.text.split(" "):  # real chunked delivery, fixed content
            if cancelled is not None and cancelled.is_set():
                raise _Cancelled()
            yield token + " "
        gen.streamed = True

    def health(self) -> dict:
        return {"status": "ONLINE", "latency_ms": 0.0,
                "detail": "Test double (TEST ONLY, not Kimi)",
                "model": "test", "endpoint": "in-process", "checked_at": _now()}

    def capabilities(self) -> dict:
        return {c: {"supported": True, "verified_live": True}
                for c in ("REASONING", "CHAT", "TOOL_CALLING", "STRUCTURED_OUTPUT")}


_lock = threading.Lock()
_instance: AIProvider | None = None


def get_provider() -> AIProvider:
    global _instance
    if _instance is not None:
        return _instance
    with _lock:
        if _instance is not None:
            return _instance
        if get_settings().AI_PROVIDER.strip().lower() == "test":
            _instance = TestProvider()
        else:
            _instance = KimiK3Provider()
        return _instance


def set_provider(provider: AIProvider | None) -> None:
    """Tests only: inject or reset (None) the singleton."""
    global _instance
    with _lock:
        _instance = provider
