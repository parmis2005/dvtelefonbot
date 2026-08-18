"""Prompt-Editor mit automatischer Versionierung (Abschnitt 21).

Neue Gespraeche verwenden automatisch die zuletzt aktivierte Version (siehe
agent/dario.py::Dario.for_lead); laufende Gespraeche behalten ihre beim
Call-Start gepinnte Version (agent/context.py::ConversationContext.system_prompt).
Kein Backend-Neustart noetig.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth
from database.database import get_db_session
from database.models import PromptVersion
from database.repository import PromptVersionRepository
from services.dashboard_state_export import export_dashboard_state_safely

router = APIRouter(
    prefix="/api/prompt-versions", tags=["prompt-versions"], dependencies=[Depends(require_auth)]
)

DbSession = Annotated[AsyncSession, Depends(get_db_session)]

STATIC_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "dario_system_prompt.md"


class PromptVersionOut(BaseModel):
    id: int
    version_number: int
    content: str
    label: str | None
    is_active: bool
    created_at: str

    @classmethod
    def from_model(cls, v: PromptVersion) -> PromptVersionOut:
        return cls(
            id=v.id,
            version_number=v.version_number,
            content=v.content,
            label=v.label,
            is_active=v.is_active,
            created_at=v.created_at.isoformat(),
        )


class PromptVersionCreate(BaseModel):
    content: str
    label: str | None = None
    activate: bool = True


async def _ensure_seeded(repo: PromptVersionRepository) -> None:
    """Frische Installation: noch keine Version in der DB - Version 1 wird
    aus der statischen Datei prompts/dario_system_prompt.md gebildet, damit
    der Editor nicht leer startet."""
    existing = await repo.list_all(limit=1)
    if existing:
        return
    if STATIC_PROMPT_PATH.exists():
        content = STATIC_PROMPT_PATH.read_text(encoding="utf-8")
    else:
        content = "Du bist Dario, die digitale Assistenz von Digital Vision."
    await repo.create_version(content, label="Initial (aus Datei importiert)", activate=True)


@router.get("", response_model=list[PromptVersionOut])
async def list_prompt_versions(session: DbSession) -> list[PromptVersionOut]:
    repo = PromptVersionRepository(session)
    await _ensure_seeded(repo)
    versions = await repo.list_all()
    return [PromptVersionOut.from_model(v) for v in versions]


@router.get("/active", response_model=PromptVersionOut)
async def get_active_prompt_version(session: DbSession) -> PromptVersionOut:
    repo = PromptVersionRepository(session)
    await _ensure_seeded(repo)
    active = await repo.get_active()
    if active is None:
        raise HTTPException(status_code=404, detail="Keine aktive Prompt-Version")
    return PromptVersionOut.from_model(active)


@router.post("", response_model=PromptVersionOut, status_code=201)
async def create_prompt_version(payload: PromptVersionCreate, session: DbSession) -> PromptVersionOut:
    repo = PromptVersionRepository(session)
    await _ensure_seeded(repo)
    version = await repo.create_version(payload.content, label=payload.label, activate=payload.activate)
    await export_dashboard_state_safely(session, reason="prompt_version_created")
    return PromptVersionOut.from_model(version)


@router.post("/{version_id}/activate", response_model=PromptVersionOut)
async def activate_prompt_version(version_id: int, session: DbSession) -> PromptVersionOut:
    """Auch fuer 'Wiederherstellen' genutzt: eine alte Version erneut
    aktivieren erzeugt keine neue Versionsnummer, sondern markiert die
    bestehende Zeile als aktiv - die Versionshistorie bleibt vollstaendig."""
    repo = PromptVersionRepository(session)
    version = await repo.activate(version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Prompt-Version nicht gefunden")
    await export_dashboard_state_safely(session, reason="prompt_version_activated")
    return PromptVersionOut.from_model(version)
