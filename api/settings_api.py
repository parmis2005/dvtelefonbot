"""Laufzeit-editierbare Dashboard-Einstellungen (Abschnitt 28).

Persistiert in database/models.py::AppSetting (nicht .env - siehe dessen
Docstring). Werte werden als Strings gespeichert und beim Lesen typisiert.
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

# Schluessel, die ueber das Dashboard editierbar UND tatsaechlich verdrahtet
# sind (siehe api/campaigns.py::create_campaign, das
# campaign_default_concurrency/campaign_max_concurrency liest). Bewusst
# schmal gehalten: agent_name/company_name/company_location/Timeouts stehen
# noch nicht hier, weil sie aktuell aus core/config.py::Settings (.env,
# prozessweit gecacht) in mehreren Modulen gelesen werden - eine echte
# Laufzeit-Ueberschreibung dieser Werte braucht eine eigene Anbindung, die
# noch aussteht, statt hier nur dekorativ editierbare Felder ohne Wirkung
# anzubieten.
_EDITABLE_KEYS = (
    "campaign_default_concurrency",
    "campaign_max_concurrency",
    "campaign_pause_between_calls_seconds",
)


class SettingsOut(BaseModel):
    values: dict[str, str]
    # Nur informativ angezeigt (Herkunft .env) - hier NICHT editierbar, siehe
    # Kommentar zu _EDITABLE_KEYS oben.
    readonly_info: dict[str, str]


class SettingsUpdate(BaseModel):
    values: dict[str, str]


def _defaults() -> dict[str, str]:
    return {
        "campaign_default_concurrency": "10",
        "campaign_max_concurrency": "10",
        "campaign_pause_between_calls_seconds": "0",
    }


def _readonly_info() -> dict[str, str]:
    settings = get_settings()
    return {
        "agent_name": settings.agent_name,
        "company_name": settings.company_name,
        "company_location": settings.company_location,
        "call_cooldown_seconds": str(settings.call_cooldown),
        "wait_timeout_seconds": str(settings.wait_timeout),
        "silence_timeout_seconds": str(settings.silence_timeout),
    }


@router.get("", response_model=SettingsOut)
async def get_dashboard_settings(session: DbSession) -> SettingsOut:
    stored = await AppSettingRepository(session).get_all()
    merged = _defaults()
    merged.update({k: v for k, v in stored.items() if k in _EDITABLE_KEYS})
    return SettingsOut(values=merged, readonly_info=_readonly_info())


@router.put("", response_model=SettingsOut)
async def update_dashboard_settings(payload: SettingsUpdate, session: DbSession) -> SettingsOut:
    repo = AppSettingRepository(session)
    to_store = {k: v for k, v in payload.values.items() if k in _EDITABLE_KEYS}
    await repo.set_many(to_store)
    stored = await repo.get_all()
    merged = _defaults()
    merged.update({k: v for k, v in stored.items() if k in _EDITABLE_KEYS})
    return SettingsOut(values=merged, readonly_info=_readonly_info())


async def get_campaign_concurrency_defaults(session: AsyncSession) -> tuple[int, int]:
    """Von api/campaigns.py genutzt: (default_concurrency, max_concurrency)."""
    stored = await AppSettingRepository(session).get_all()
    merged = _defaults()
    merged.update({k: v for k, v in stored.items() if k in _EDITABLE_KEYS})
    return int(merged["campaign_default_concurrency"]), int(merged["campaign_max_concurrency"])
