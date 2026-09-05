"""Local embedding providers. Production uses onnx weights on this machine
(fastembed); tests may inject the deterministic test provider, which is
explicitly labelled and never mixed with real vectors (model name is stored
per chunk and enforced at search/index time)."""
import hashlib
import random
import threading
from abc import ABC, abstractmethod
from datetime import datetime, timezone

from ..core.config import get_settings


class EmbeddingError(Exception):
    pass


class EmbeddingProvider(ABC):
    name = "base"
    is_test = False

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...

    def embed_query(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    @property
    @abstractmethod
    def dimension(self) -> int:
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        ...

    def health(self) -> dict:
        try:
            vec = self.embed_query("health probe")
            ok = len(vec) == self.dimension and all(
                isinstance(x, float) for x in vec)
        except Exception:
            ok = False
        return {"provider": self.name, "model": self.model_name,
                "dimension": self.dimension, "ok": ok,
                "checked_at": datetime.now(timezone.utc).isoformat()}


class FastEmbedProvider(EmbeddingProvider):
    """Real local embeddings (onnxruntime, cached HF weights, offline after
    first download). Model identity/dimension come from the live model."""
    name = "fastembed"

    def __init__(self):
        self._lock = threading.Lock()
        self._model = None
        self._dim: int | None = None

    def _load(self):
        if self._model is not None:
            return self._model
        with self._lock:
            if self._model is not None:
                return self._model
            s = get_settings()
            try:
                from fastembed import TextEmbedding
            except ImportError as e:
                raise EmbeddingError(
                    "fastembed is not installed (pip install fastembed)") from e
            try:
                self._model = TextEmbedding(s.EMBEDDING_MODEL)
            except Exception as e:
                raise EmbeddingError(
                    f"Local embedding model unavailable: {s.EMBEDDING_MODEL}."
                    " Run once with network to cache it, then offline works."
                    f" ({type(e).__name__})") from e
            return self._model

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        try:
            vecs = [list(map(float, v)) for v in model.embed(texts)]
        except Exception as e:
            raise EmbeddingError(
                f"Local embedding failed ({type(e).__name__})") from e
        if vecs:
            self._dim = len(vecs[0])
        return vecs

    @property
    def dimension(self) -> int:
        if self._dim is None:
            self.embed_query("dimension probe")
        assert self._dim is not None
        return self._dim

    @property
    def model_name(self) -> str:
        return get_settings().EMBEDDING_MODEL


class DeterministicTestProvider(EmbeddingProvider):
    """Test-only embeddings: seeded PRNG per text (deterministic, cheap).
    model_name is_test=True so production code can refuse to mix them."""
    name = "test-deterministic"
    is_test = True

    def __init__(self, dimension: int = 64):
        self._dim = dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        out = []
        for t in texts:
            seed = int.from_bytes(hashlib.sha256(t.encode()).digest()[:8], "big")
            rng = random.Random(seed)
            out.append([rng.uniform(-1.0, 1.0) for _ in range(self._dim)])
        return out

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def model_name(self) -> str:
        return "test-deterministic-64"


_lock = threading.Lock()
_instance: EmbeddingProvider | None = None


def get_embedding_provider() -> EmbeddingProvider:
    global _instance
    if _instance is not None:
        return _instance
    with _lock:
        if _instance is not None:
            return _instance
        s = get_settings()
        if s.EMBEDDING_PROVIDER == "test-deterministic":
            _instance = DeterministicTestProvider()
        else:
            _instance = FastEmbedProvider()
        return _instance


def set_embedding_provider(provider: EmbeddingProvider | None) -> None:
    """Tests only: inject or reset (None) the singleton."""
    global _instance
    with _lock:
        _instance = provider


def embedding_metadata() -> dict:
    """Registry record: provider, model, dimension, timestamp. Changing the
    model invalidates existing vectors (enforced, never silently mixed)."""
    p = get_embedding_provider()
    return {"provider": p.name, "model_name": p.model_name,
            "dimension": p.dimension, "is_test": p.is_test,
            "created_at": datetime.now(timezone.utc).isoformat()}
