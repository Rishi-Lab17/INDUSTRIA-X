"""INDUSTRIA-X backend (Stage 1: foundation + auth + system)."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .core.config import get_settings
from .db import init_db
from .routers import auth, company, equipment, system


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    get_settings()  # resolve settings early so misconfig fails fast
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
app.include_router(company.router)
app.include_router(equipment.router)
app.include_router(system.router)


@app.get("/")
def root():
    s = get_settings()
    return {"app": s.APP_NAME, "env": s.APP_ENV, "ai_provider": s.AI_PROVIDER,
            "docs": "/docs"}
