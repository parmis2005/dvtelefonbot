"""FastAPI-Router fuer Lead-Verwaltung (Abschnitt 52)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database.database import get_db_session
from database.models import Lead, LeadStatus, PreferredContact
from database.repository import CallRepository, LeadRepository
from services.lead_service import LeadService, LeadValidationError

router = APIRouter(prefix="/api/leads", tags=["leads"])


class LeadCreate(BaseModel):
    unternehmen: str
    ansprechpartner: str | None = None
    branche: str | None = None
    website_url: str | None = None
    telefonnummer: str
    email: str | None = None
    notizen: str | None = None
    online_auftritt_geprueft: bool = False
    entwurf_vorhanden: bool = False
    entwurf_link: str | None = None


class LeadUpdate(BaseModel):
    unternehmen: str | None = None
    ansprechpartner: str | None = None
    branche: str | None = None
    website_url: str | None = None
    telefonnummer: str | None = None
    email: str | None = None
    notizen: str | None = None
    online_auftritt_geprueft: bool | None = None
    entwurf_vorhanden: bool | None = None
    entwurf_link: str | None = None
    status: LeadStatus | None = None
    preferred_contact: PreferredContact | None = None
    callback_note: str | None = None
    do_not_call: bool | None = None


class LeadOut(BaseModel):
    id: int
    unternehmen: str
    ansprechpartner: str | None
    branche: str | None
    website_url: str | None
    telefonnummer: str
    email: str | None
    notizen: str | None
    online_auftritt_geprueft: bool
    entwurf_vorhanden: bool
    entwurf_link: str | None
    status: LeadStatus
    preferred_contact: PreferredContact
    do_not_call: bool
    callback_note: str | None

    model_config = {"from_attributes": True}


DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("", response_model=list[LeadOut])
async def list_leads(session: DbSession) -> list[Lead]:
    return await LeadRepository(session).list_all()


@router.get("/{lead_id}")
async def get_lead(lead_id: int, session: DbSession) -> dict:
    lead = await LeadRepository(session).get(lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead nicht gefunden")
    calls = await CallRepository(session).list_for_lead(lead_id)
    return {
        "lead": LeadOut.model_validate(lead).model_dump(),
        "calls": [
            {
                "id": c.id,
                "status": c.status,
                "result": c.result,
                "started_at": c.started_at,
                "ended_at": c.ended_at,
                "duration": c.duration,
                "summary": c.summary,
                "transcript": c.transcript,
            }
            for c in calls
        ],
    }


@router.post("", response_model=LeadOut, status_code=201)
async def create_lead(payload: LeadCreate, session: DbSession) -> Lead:
    try:
        return await LeadService(session).create_lead(**payload.model_dump())
    except LeadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/{lead_id}", response_model=LeadOut)
async def update_lead(lead_id: int, payload: LeadUpdate, session: DbSession) -> Lead:
    try:
        lead = await LeadService(session).update_lead(
            lead_id, **{k: v for k, v in payload.model_dump().items() if v is not None}
        )
    except LeadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead nicht gefunden")
    return lead
