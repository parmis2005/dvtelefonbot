"""Liefert core/config.py::Settings mit Dashboard-Ueberschreibungen aus
database/models.py::AppSetting angewandt (Abschnitt 28 "Einstellungen").

.env bleibt die Quelle der Defaults (core/config.py::get_settings, prozessweit
gecacht). Diese Funktion ueberlagert sie zur Call-Start-Zeit mit im Dashboard
gespeicherten Werten, OHNE den gecachten Settings-Singleton selbst zu mutieren
(sonst wuerden gleichzeitige Anrufe sich gegenseitig Werte ueberschreiben,
siehe pydantic BaseModel.model_copy statt In-Place-Zuweisung).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings, get_settings
from database.repository import AppSettingRepository

# AppSetting-Schluessel -> Settings-Feldname + Typkonverter.
_STR_OVERRIDES: dict[str, str] = {
    "agent_name": "agent_name",
    "company_name": "company_name",
    "company_location": "company_location",
}
_INT_OVERRIDES: dict[str, str] = {
    "wait_timeout_seconds": "wait_timeout",
    "silence_timeout_seconds": "silence_timeout",
    "call_cooldown_seconds": "call_cooldown",
}


async def get_effective_settings(session: AsyncSession) -> Settings:
    base = get_settings()
    stored = await AppSettingRepository(session).get_all()

    updates: dict[str, str | int] = {}
    for key, field in _STR_OVERRIDES.items():
        value = stored.get(key, "").strip()
        if value:
            updates[field] = value
    for key, field in _INT_OVERRIDES.items():
        value = stored.get(key, "").strip()
        if value:
            try:
                updates[field] = int(value)
            except ValueError:
                continue

    if not updates:
        return base
    return base.model_copy(update=updates)
