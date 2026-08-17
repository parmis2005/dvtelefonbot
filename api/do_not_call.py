"""Sperrliste-Verwaltung (Abschnitt 25). Die eigentliche Durchsetzung passiert
serverseitig VOR jedem Outbound-Call in services/call_service.py::CallService.
can_start_call (genutzt von jedem Call-Startpfad: Einzelanruf, Kampagne,
Testanruf) - dieser Router bildet nur die Verwaltungsoberflaeche ab."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth
from database.database import get_db_session
from database.models import DoNotCall
from database.repository import DoNotCallRepository, LeadRepository

router = APIRouter(
    prefix="/api/do-not-call", tags=["do-not-call"], dependencies=[Depends(require_auth)]
)

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class DoNotCallOut(BaseModel):
    id: int
    telefonnummer: str
    reason: str | None
    created_at: str

    @classmethod
    def from_model(cls, entry: DoNotCall) -> DoNotCallOut:
        return cls(
            id=entry.id,
            telefonnummer=entry.telefonnummer,
            reason=entry.reason,
            created_at=entry.created_at.isoformat(),
        )


class DoNotCallCreate(BaseModel):
    telefonnummer: str
    reason: str | None = None


@router.get("", response_model=list[DoNotCallOut])
async def list_do_not_call(session: DbSession) -> list[DoNotCallOut]:
    entries = await DoNotCallRepository(session).list_all()
    return [DoNotCallOut.from_model(e) for e in entries]


@router.post("", response_model=DoNotCallOut, status_code=201)
async def add_do_not_call(payload: DoNotCallCreate, session: DbSession) -> DoNotCallOut:
    entry = await DoNotCallRepository(session).add(payload.telefonnummer, payload.reason)
    lead = await LeadRepository(session).get_by_phone(payload.telefonnummer)
    if lead is not None:
        await LeadRepository(session).set_do_not_call(lead.id, True)
    return DoNotCallOut.from_model(entry)


@router.delete("/{phone_number}", status_code=204)
async def remove_do_not_call(phone_number: str, session: DbSession) -> None:
    removed = await DoNotCallRepository(session).remove(phone_number)
    if not removed:
        raise HTTPException(status_code=404, detail="Eintrag nicht gefunden")
