"""Lead-Service: Validierung + Geschaeftslogik oberhalb des Repository Layers."""

from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Lead
from database.repository import LeadRepository

_PHONE_CLEAN_RE = re.compile(r"[^\d+]")


class LeadValidationError(Exception):
    pass


def normalize_phone(raw: str) -> str:
    cleaned = _PHONE_CLEAN_RE.sub("", raw.strip())
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if cleaned.startswith("0") and not cleaned.startswith("00"):
        cleaned = "+49" + cleaned[1:]
    return cleaned


def is_valid_phone_number(raw: str) -> bool:
    cleaned = normalize_phone(raw)
    return bool(re.match(r"^\+\d{7,15}$", cleaned))


def parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "ja", "yes", "y", "wahr"}


class LeadService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = LeadRepository(session)

    async def create_lead(self, **fields) -> Lead:
        if "telefonnummer" in fields:
            if not is_valid_phone_number(fields["telefonnummer"]):
                raise LeadValidationError(f"Ungueltige Telefonnummer: {fields['telefonnummer']}")
            fields["telefonnummer"] = normalize_phone(fields["telefonnummer"])
        return await self.repo.create(**fields)

    async def update_lead(self, lead_id: int, **fields) -> Lead | None:
        if fields.get("telefonnummer"):
            if not is_valid_phone_number(fields["telefonnummer"]):
                raise LeadValidationError(f"Ungueltige Telefonnummer: {fields['telefonnummer']}")
            fields["telefonnummer"] = normalize_phone(fields["telefonnummer"])
        return await self.repo.update(lead_id, **fields)

    async def import_from_rows(self, rows: list[dict]) -> tuple[list[Lead], list[str]]:
        created: list[Lead] = []
        errors: list[str] = []
        for i, row in enumerate(rows, start=1):
            try:
                phone = row.get("telefonnummer", "").strip()
                if not phone or not is_valid_phone_number(phone):
                    errors.append(f"Zeile {i}: ungueltige Telefonnummer '{phone}'")
                    continue
                lead = await self.create_lead(
                    unternehmen=row.get("unternehmen", "").strip(),
                    ansprechpartner=row.get("ansprechpartner", "").strip() or None,
                    branche=row.get("branche", "").strip() or None,
                    website_url=row.get("website_url", "").strip() or None,
                    telefonnummer=phone,
                    email=row.get("email", "").strip() or None,
                    notizen=row.get("notizen", "").strip() or None,
                    online_auftritt_geprueft=parse_bool(row.get("online_auftritt_geprueft", False)),
                    entwurf_vorhanden=parse_bool(row.get("entwurf_vorhanden", False)),
                    entwurf_link=row.get("entwurf_link", "").strip() or None,
                )
                created.append(lead)
            except Exception as exc:  # Import soll bei einer fehlerhaften Zeile weiterlaufen
                errors.append(f"Zeile {i}: {exc}")
        return created, errors
