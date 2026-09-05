"""INDUSTRIA-X backend settings. Paths resolve relative to the project root
(parent of backend/), so the server must be started from the root:
    python -m uvicorn app.main:app --app-dir backend --port 8000
"""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(ROOT / ".env"), extra="ignore")

    APP_NAME: str = "INDUSTRIA-X"
    APP_ENV: str = "local"
    BACKEND_PORT: int = 8000
    DATABASE_URL: str = "./database/industria-x.db"

    JWT_SECRET: str = "change-me-to-a-long-random-secret-min-32-chars"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 720
    OTP_EXPIRE_MINUTES: int = 5
    OTP_MAX_ATTEMPTS: int = 5
    OTP_VERIFY_MAX_PER_WINDOW: int = 10
    OTP_VERIFY_WINDOW_S: int = 600
    OTP_RESEND_COOLDOWN_S: int = 60
    OTP_RESEND_MAX_PER_HOUR: int = 5
    BCRYPT_ROUNDS: int = 12

    # --- Email OTP delivery (Resend API). Credentials from env; never hardcoded.
    # The Resend call happens ONLY in the FastAPI backend, never the frontend.
    # RESEND_ENABLED=true AND a key → Resend; otherwise development outbox
    # (local) or loud refusal (other envs). Never crashes for a missing key.
    RESEND_ENABLED: bool = True
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = ""
    RESEND_FROM_NAME: str = "INDUSTRIA-X"
    RESEND_BASE_URL: str = "https://api.resend.com"
    RESEND_TIMEOUT_S: int = 15

    # Local-dev outbox: when Resend is unconfigured AND APP_ENV=local, the
    # verification email is written here as a file instead of being sent.
    # The API/UI never carry the code. Production refuses (502) instead.
    DEV_OUTBOX_DIR: str = "./storage/temporary/dev-outbox"

    # --- Firebase phone auth (verification only; authZ stays in INDUSTRIA-X) ---
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_CREDENTIALS_FILE: str = ""

    STORAGE_DOCUMENTS: str = "./storage/documents"
    STORAGE_IMAGES: str = "./storage/images"
    STORAGE_SENSORS: str = "./storage/sensor_data"
    STORAGE_REPORTS: str = "./storage/reports"
    STORAGE_TEMP: str = "./storage/temporary"
    MAX_UPLOAD_SIZE_MB: int = 50

    # --- Stage 3 knowledge base: all local, no external calls ---
    OCR_ENABLED: bool = True
    OCR_PROVIDER: str = "tesseract"
    OCR_TIMEOUT_S: int = 60
    DOC_MAX_ROWS: int = 20000
    EXTRACT_MAX_CHARS: int = 500000

    AI_PROVIDER: str = "kimi-k3"
    AI_ACTIVE_MODEL: str = "kimi-k3"
    # Placeholder for the operator's on-prem Kimi K3 server (OpenAI-compatible).
    # Uses a port nothing else binds so health probes never hit our own backend
    # (that self-hit caused the /v1/models 404 noise). Set the real URL in .env.
    KIMI_K3_BASE_URL: str = "http://127.0.0.1:11436/v1"
    KIMI_K3_MODEL: str = "kimi-k3"
    KIMI_K3_API_KEY: str = "local"
    KIMI_K3_TIMEOUT_S: int = 5
    # --- Stage 5 AI workbench (local-first; Kimi K3 primary, no fallback) ---
    KIMI_ENABLED: bool = True
    KIMI_CONNECT_TIMEOUT_S: int = 5
    KIMI_MAX_RETRIES: int = 2
    KIMI_MAX_TOKENS: int = 1024
    KIMI_TEMPERATURE: float = 0.2
    AI_MAX_MESSAGE_CHARS: int = 4000
    AI_MAX_CONTEXT_CHARS: int = 12000
    AI_MEMORY_MESSAGES: int = 20
    AI_MAX_TOOL_CALLS_PER_RUN: int = 5
    AI_RUNS_PER_USER: int = 30
    AI_RUNS_PER_USER_WINDOW_S: int = 300
    AI_RUNS_PER_COMPANY: int = 200
    AI_RUNS_PER_COMPANY_WINDOW_S: int = 300
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    DEV_MODEL: str = "hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M"

    VECTOR_DB_PATH: str = "./database/vectors.db"

    # --- Stage 4 private RAG (all local; onnx embedding model + sqlite store) ---
    EMBEDDING_PROVIDER: str = "fastembed"
    EMBEDDING_MODEL: str = "sentence-transformers/all-MiniLM-L6-v2"
    CHUNK_TARGET_CHARS: int = 800
    CHUNK_MIN_CHARS: int = 200
    CHUNK_MAX_CHARS: int = 2000
    CHUNK_OVERLAP_CHARS: int = 120
    RETRIEVAL_TOP_K: int = 8
    RETRIEVAL_CANDIDATES: int = 40
    RETRIEVAL_ALPHA: float = 0.6
    MIN_RELEVANCE_SCORE: float = 0.25
    RERANK_EQUIPMENT_BOOST: float = 0.15
    RERANK_PHRASE_BOOST: float = 0.10
    MAX_CONTEXT_CHUNKS: int = 8
    MAX_CONTEXT_CHARS: int = 12000

    # --- Stage 6 multimodal (all local; numpy + PIL, no external calls) ---
    SENSOR_MAX_ROWS: int = 100000
    SENSOR_MAX_CHANNELS: int = 32
    CHART_MAX_POINTS: int = 2000
    FFT_MIN_SAMPLES: int = 64
    IMAGE_MAX_DIMENSION: int = 4096
    ANOMALY_DEFAULT_METHOD: str = "rolling_zscore"
    ANOMALY_DEFAULT_WINDOW: int = 60
    ANOMALY_DEFAULT_THRESHOLD: float = 3.0

    SOV_AI_INFERENCE: str = "LOCAL"
    SOV_DOC_PROCESSING: str = "LOCAL"
    SOV_KNOWLEDGE_BASE: str = "LOCAL"
    SOV_VECTOR_DB: str = "LOCAL"
    SOV_INDUSTRIAL_DATA: str = "LOCAL"
    EXTERNAL_AI: str = "BLOCKED"
    EXTERNAL_FALLBACK: str = "DISABLED"

    def db_path(self) -> Path:
        p = Path(self.DATABASE_URL.replace("sqlite:///", ""))
        return p if p.is_absolute() else ROOT / p

    def storage_dirs(self) -> list[Path]:
        out = []
        for v in (self.STORAGE_DOCUMENTS, self.STORAGE_IMAGES,
                  self.STORAGE_SENSORS, self.STORAGE_REPORTS, self.STORAGE_TEMP):
            p = Path(v)
            out.append(p if p.is_absolute() else ROOT / p)
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
