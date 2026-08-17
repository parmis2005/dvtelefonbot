"""Laufzeit-editierbare Dashboard-Einstellungen (Abschnitt 28).

Persistiert in database/models.py::AppSetting (nicht .env - siehe dessen
Docstring). Werte werden als Strings gespeichert und beim Lesen typisiert.

Wirkung ohne Backend-Neustart: alle hier editierbaren Werte werden bei jedem
NEUEN Call-Start ueber services/effective_settings.py::get_effective_settings
gelesen und auf die .env-Basiswerte ueberlagert (agent_name/company_name/
company_location/wait_timeout/silence_timeout in app/bootstrap.py::
build_app_context, call_cooldown in services/call_service.py::CallService).
Ein bereits laufendes Gespraech behaelt seine beim Start gepinnten Werte -
exakt dasselbe Prinzip wie bei Prompt-Version und Stimme (siehe CLAUDE.md).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth
from core.config import get_settings
from database.database import get_db_session
from database.repository import AppSettingRepository

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_auth)])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]

# Alle Schluessel, die ueber das Dashboard editierbar UND tatsaechlich
# verdrahtet sind - siehe Moduldocstring fuer die jeweilige Anbindung.
_EDITABLE_KEYS = (
    "campaign_default_concurrency",
    "campaign_max_concurrency",
    "campaign_pause_between_calls_seconds",
    "agent_name",
    "company_name",
    "company_location",
    "wait_timeout_seconds",
    "silence_timeout_seconds",
    "call_cooldown_seconds",
)


class SettingsOut(BaseModel):
    values: dict[str, str]


class SettingsUpdate(BaseModel):
    values: dict[str, str]


def _defaults() -> dict[str, str]:
    """Fallback-Werte, solange noch keine Dashboard-Ueberschreibung
    gespeichert wurde - aus der .env-Konfiguration (core/config.py::Settings)
    uebernommen, damit das Einstellungen-Formular nie leer/willkuerlich
    startet, sondern den tatsaechlich aktiven Wert zeigt."""
    settings = get_settings()
    return {
        "campaign_default_concurrency": "10",
        "campaign_max_concurrency": "10",
        "campaign_pause_between_calls_seconds": "0",
        "agent_name": settings.agent_name,
        "company_name": settings.company_name,
        "company_location": settings.company_location,
        "wait_timeout_seconds": str(settings.wait_timeout),
        "silence_timeout_seconds": str(settings.silence_timeout),
        "call_cooldown_seconds": str(settings.call_cooldown),
    }


async def _merged_settings(session: AsyncSession) -> dict[str, str]:
    stored = await AppSettingRepository(session).get_all()
    merged = _defaults()
    merged.update({k: v for k, v in stored.items() if k in _EDITABLE_KEYS and v.strip()})
    return merged


@router.get("", response_model=SettingsOut)
async def get_dashboard_settings(session: DbSession) -> SettingsOut:
    return SettingsOut(values=await _merged_settings(session))


@router.put("", response_model=SettingsOut)
async def update_dashboard_settings(payload: SettingsUpdate, session: DbSession) -> SettingsOut:
    repo = AppSettingRepository(session)
    to_store = {k: v for k, v in payload.values.items() if k in _EDITABLE_KEYS}
    await repo.set_many(to_store)
    return SettingsOut(values=await _merged_settings(session))


async def get_campaign_concurrency_defaults(session: AsyncSession) -> tuple[int, int]:
    """Von api/campaigns.py genutzt: (default_concurrency, max_concurrency)."""
    merged = await _merged_settings(session)
    return int(merged["campaign_default_concurrency"]), int(merged["campaign_max_concurrency"])
