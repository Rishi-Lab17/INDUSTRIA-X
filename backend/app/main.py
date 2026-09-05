"""INDUSTRIA-X backend (Stage 1: foundation + auth + system)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings
from .db import init_db
from .routers import ai, auth, company, documents, equipment, knowledge, system
from .routers import investigations as investigations_router
from .routers import sensors as sensors_router
from .routers import vision as vision_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    get_settings()  # resolve settings early so misconfig fails fast
    try:
        from .ai.registry import validate_ai_config
        validate_ai_config()  # warnings only; Kimi offline never blocks startup
    except Exception:
        pass
    try:
        from .rag.store import init_store
        init_store()
    except Exception:
        pass  # vector store initializes lazily on first RAG use
    yield


app = FastAPI(title="INDUSTRIA-X", version="0.1.0-stage1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(ai.router)
app.include_router(company.router)
app.include_router(documents.router)
app.include_router(knowledge.router)
app.include_router(sensors_router.router)
app.include_router(vision_router.router)
app.include_router(investigations_router.router)
app.include_router(equipment.router)
app.include_router(system.router)


@app.get("/")
def root():
    s = get_settings()
    return {"app": s.APP_NAME, "env": s.APP_ENV, "ai_provider": s.AI_PROVIDER,
            "docs": "/docs"}
