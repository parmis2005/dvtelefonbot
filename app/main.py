"""FastAPI-Einstiegspunkt fuer Digital Vision Dario.

Start (Dev):
    uvicorn app.main:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from api.calls import router as calls_router
from api.leads import router as leads_router
from core.config import get_settings
from core.logging import configure_logging, get_logger
from dashboard.routes import router as dashboard_router
from database.database import init_db

logger = get_logger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "dashboard" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_dir)
    await init_db()
    logger.info(
        "Digital Vision Dario gestartet (Agent=%s, Firma=%s)",
        settings.agent_name,
        settings.company_name,
    )
    yield


app = FastAPI(
    title="Digital Vision Dario",
    description="KI-Telefonagent fuer Digital Vision Moenchengladbach",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(leads_router)
app.include_router(calls_router)
app.include_router(dashboard_router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/api/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "agent": settings.agent_name,
        "company": settings.company_name,
        "secrets_configured": settings.secrets_configured,
    }
