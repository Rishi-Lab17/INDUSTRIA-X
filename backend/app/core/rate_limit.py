"""In-memory sliding-window rate limiter (per-process, prototype-grade).

Used for OTP verify/resend brute-force and cooldown protection. For a
multi-process deployment this must move to Redis — tracked for Stage 10.
"""
import threading
import time

_lock = threading.Lock()
_hits: dict[str, list[float]] = {}


def _prune(key: str, now: float, window_s: int) -> list[float]:
    calls = [t for t in _hits.get(key, []) if now - t < window_s]
    _hits[key] = calls
    return calls


def allow(key: str, max_calls: int, window_s: int) -> tuple[bool, int]:
    """Returns (allowed, retry_after_seconds). Records the call if allowed."""
    now = time.monotonic()
    with _lock:
        calls = _prune(key, now, window_s)
        if len(calls) >= max_calls:
            oldest = min(calls)
            retry_after = int(oldest + window_s - now) + 1
            return False, max(1, retry_after)
        calls.append(now)
        _hits[key] = calls
        return True, 0


def reset(key: str) -> None:
    with _lock:
        _hits.pop(key, None)


def reset_all() -> None:
    """Tests only."""
    with _lock:
        _hits.clear()
