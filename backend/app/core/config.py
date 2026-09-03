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

    # --- Email (SMTP). All credentials from env; never hardcoded. ---
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    SMTP_TIMEOUT_S: int = 10
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "INDUSTRIA-X"

    # --- Firebase phone auth (verification only; authZ stays in INDUSTRIA-X) ---
    FIREBASE_PROJECT_ID: str = ""
    FIREBASE_CREDENTIALS_FILE: str = ""

    STORAGE_DOCUMENTS: str = "./storage/documents"
    STORAGE_IMAGES: str = "./storage/images"
    STORAGE_SENSORS: str = "./storage/sensor_data"
    STORAGE_REPORTS: str = "./storage/reports"
    STORAGE_TEMP: str = "./storage/temporary"

    AI_PROVIDER: str = "kimi-k3"
    AI_ACTIVE_MODEL: str = "kimi-k3"
    KIMI_K3_BASE_URL: str = "http://127.0.0.1:8000/v1"
    KIMI_K3_MODEL: str = "kimi-k3"
    KIMI_K3_TIMEOUT_S: int = 5
    OLLAMA_BASE_URL: str = "http://127.0.0.1:11434"
    DEV_MODEL: str = "hf.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF:Q4_K_M"

    VECTOR_DB_PATH: str = "./database/vectors.db"

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
