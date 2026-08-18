"""FastAPI-Einstiegspunkt fuer Digital Vision Dario.

Start (Dev):
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.auth import router as auth_router
from api.calls import router as calls_router
from api.campaigns import router as campaigns_router
from api.do_not_call import router as do_not_call_router
from api.leads import router as leads_router
from api.live_status import router as live_status_router
from api.prompt_versions import router as prompt_versions_router
from api.settings_api import router as settings_router
from api.telephony import router as telephony_router
from api.twilio import router as twilio_router
from api.voices import router as voices_router
from core.config import get_settings
from core.logging import configure_logging, get_logger
from dashboard.routes import router as dashboard_router
from database.database import init_db
from services.campaign_service import get_campaign_manager

logger = get_logger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "dashboard" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_dir)
    await init_db()
    await get_campaign_manager().resume_after_restart()
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

# Next.js-Dashboard laeuft als eigenes Frontend (Vercel/lokal auf anderem
# Port) - Cookies (Session-Auth, siehe core/auth.py) erfordern
# allow_credentials=True + eine explizite Origin-Liste statt "*".
_cors_origins = ["http://localhost:3000", "http://127.0.0.1:3000"]
_cors_origins += [o.strip() for o in get_settings().dashboard_frontend_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(leads_router)
app.include_router(calls_router)
app.include_router(campaigns_router)
app.include_router(do_not_call_router)
app.include_router(prompt_versions_router)
app.include_router(voices_router)
app.include_router(settings_router)
app.include_router(telephony_router)
app.include_router(live_status_router)
app.include_router(twilio_router)
app.include_router(dashboard_router)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/api/health")
async def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "agent": settings.agent_name,
        "company": settings.company_name,
        "runtime": {
            "pid": os.getpid(),
            "source_root": str(Path(__file__).resolve().parent.parent),
        },
        "secrets_configured": settings.secrets_configured,
    }
