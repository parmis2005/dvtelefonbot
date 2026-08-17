"""Sammelanrufe / Kampagnen (Abschnitt 9-11).

Orchestrierung uebernimmt services/campaign_service.py::CampaignManager -
dieser Router startet/pausiert/stoppt sie nur und liefert Fortschritts-
Zahlen fuer die Live-Ansicht.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.settings_api import get_campaign_concurrency_defaults
from core.auth import require_auth
from database.database import get_db_session
from database.models import Campaign
from database.repository import CallRepository, CampaignRepository, LeadRepository
from services.campaign_service import get_campaign_manager

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"], dependencies=[Depends(require_auth)])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]

_ACTIVE_STATUSES = ("CREATED", "RINGING", "ANSWERED")


class CampaignCreate(BaseModel):
    name: str
    lead_ids: list[int]
    max_concurrent: int | None = None


class CampaignOut(BaseModel):
    id: int
    name: str
    status: str
    total_count: int
    processed_count: int
    active_count: int
    max_concurrent: int
    created_at: str
    started_at: str | None
    finished_at: str | None

    @classmethod
    async def from_model(cls, campaign: Campaign, session: AsyncSession) -> CampaignOut:
        calls = await CallRepository(session).list_for_campaign(campaign.id)
        active = sum(1 for c in calls if c.status.value in _ACTIVE_STATUSES)
        return cls(
            id=campaign.id,
            name=campaign.name,
            status=campaign.status.value,
            total_count=campaign.total_count,
            processed_count=campaign.processed_count,
            active_count=active,
            max_concurrent=campaign.max_concurrent,
            created_at=campaign.created_at.isoformat(),
            started_at=campaign.started_at.isoformat() if campaign.started_at else None,
            finished_at=campaign.finished_at.isoformat() if campaign.finished_at else None,
        )


@router.get("", response_model=list[CampaignOut])
async def list_campaigns(session: DbSession) -> list[CampaignOut]:
    campaigns = await CampaignRepository(session).list_all()
    return [await CampaignOut.from_model(c, session) for c in campaigns]


@router.get("/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: int, session: DbSession) -> CampaignOut:
    campaign = await CampaignRepository(session).get(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Kampagne nicht gefunden")
    return await CampaignOut.from_model(campaign, session)


@router.post("", response_model=CampaignOut, status_code=201)
async def create_campaign(payload: CampaignCreate, session: DbSession) -> CampaignOut:
    if not payload.lead_ids:
        raise HTTPException(status_code=422, detail="Mindestens ein Kontakt erforderlich.")

    lead_repo = LeadRepository(session)
    for lead_id in payload.lead_ids:
        if await lead_repo.get(lead_id) is None:
            raise HTTPException(status_code=422, detail=f"Lead {lead_id} nicht gefunden.")

    default_concurrency, max_concurrency = await get_campaign_concurrency_defaults(session)
    max_concurrent = payload.max_concurrent or default_concurrency
    max_concurrent = min(max_concurrent, max_concurrency)

    campaign = await CampaignRepository(session).create(
        name=payload.name,
        lead_ids_json=json.dumps(payload.lead_ids),
        max_concurrent=max_concurrent,
    )
    return await CampaignOut.from_model(campaign, session)


async def _refetch(session: AsyncSession, campaign_id: int) -> Campaign:
    """CampaignManager.start/pause/resume/stop aendern den Datensatz ueber
    eine EIGENE, kurzlebige Session (services/campaign_service.py) - ein
    einfaches erneutes .get() auf der Request-Session wuerde wegen
    SQLAlchemys Identity Map das veraltete, bereits im Speicher gehaltene
    Objekt zurueckgeben statt den frisch committeten Stand. session.refresh()
    erzwingt einen echten Reload."""
    campaign = await CampaignRepository(session).get(campaign_id)
    if campaign is None:
        raise HTTPException(status_code=404, detail="Kampagne nicht gefunden")
    await session.refresh(campaign)
    return campaign


@router.post("/{campaign_id}/start", response_model=CampaignOut)
async def start_campaign(campaign_id: int, session: DbSession) -> CampaignOut:
    try:
        await get_campaign_manager().start(campaign_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    campaign = await _refetch(session, campaign_id)
    return await CampaignOut.from_model(campaign, session)


@router.post("/{campaign_id}/pause", response_model=CampaignOut)
async def pause_campaign(campaign_id: int, session: DbSession) -> CampaignOut:
    await _refetch(session, campaign_id)  # 404, falls unbekannt
    await get_campaign_manager().pause(campaign_id)
    campaign = await _refetch(session, campaign_id)
    return await CampaignOut.from_model(campaign, session)


@router.post("/{campaign_id}/resume", response_model=CampaignOut)
async def resume_campaign(campaign_id: int, session: DbSession) -> CampaignOut:
    try:
        await get_campaign_manager().resume(campaign_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    campaign = await _refetch(session, campaign_id)
    return await CampaignOut.from_model(campaign, session)


@router.post("/{campaign_id}/stop", response_model=CampaignOut)
async def stop_campaign(campaign_id: int, session: DbSession) -> CampaignOut:
    await _refetch(session, campaign_id)  # 404, falls unbekannt
    await get_campaign_manager().stop(campaign_id)
    campaign = await _refetch(session, campaign_id)
    return await CampaignOut.from_model(campaign, session)
