"""FastAPI-Router fuer Call-Verwaltung (Abschnitt 52).

POST /api/calls stoesst einen echten Outbound-Call ueber Asterisk/ARI an.
Ist kein Asterisk-Server erreichbar, wird das als 502 mit Klartext-Fehler
zurueckgemeldet - es wird niemals ein erfolgreicher Call vorgetaeuscht.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agent.dario import Dario
from app.bootstrap import build_app_context, get_tts_provider
from core.auth import require_auth
from core.config import get_settings
from database.database import get_db_session
from database.models import Call, CallStatus
from database.repository import CallRepository, LeadRepository
from phone.ari import AriError
from phone.asterisk import AsteriskProvider
from phone.call_controller import CallController
from phone.twilio_voice import TwilioConfigError, TwilioProvider
from services.call_service import CallNotAllowedError, CallService
from tools.call_tools import ToolExecutor

router = APIRouter(prefix="/api/calls", tags=["calls"], dependencies=[Depends(require_auth)])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]

_ACTIVE_STATUSES = (CallStatus.CREATED, CallStatus.RINGING, CallStatus.ANSWERED)


class CallCreate(BaseModel):
    lead_id: int
    phone_number: str | None = None  # informativ, massgeblich ist lead.telefonnummer


class CallOut(BaseModel):
    id: int
    lead_id: int
    campaign_id: int | None
    status: str
    result: str | None
    started_at: str | None = None
    ended_at: str | None = None
    duration: int | None = None
    summary: str | None = None
    transcript: str | None = None
    twilio_call_sid: str | None = None

    @classmethod
    def from_model(cls, call: Call) -> CallOut:
        return cls(
            id=call.id,
            lead_id=call.lead_id,
            campaign_id=call.campaign_id,
            status=call.status.value if hasattr(call.status, "value") else call.status,
            result=(call.result.value if hasattr(call.result, "value") else call.result),
            started_at=call.started_at.isoformat() if call.started_at else None,
            ended_at=call.ended_at.isoformat() if call.ended_at else None,
            duration=call.duration,
            summary=call.summary,
            transcript=call.transcript,
            twilio_call_sid=call.twilio_call_sid,
        )


@router.get("", response_model=list[CallOut])
async def list_calls(
    session: DbSession,
    campaign_id: int | None = None,
    lead_id: int | None = None,
    active_only: bool = False,
) -> list[CallOut]:
    repo = CallRepository(session)
    if campaign_id is not None:
        calls = await repo.list_for_campaign(campaign_id)
    elif lead_id is not None:
        calls = await repo.list_for_lead(lead_id)
    else:
        calls = await repo.list_all()
    if active_only:
        calls = [c for c in calls if c.status in _ACTIVE_STATUSES]
    return [CallOut.from_model(c) for c in calls]


@router.get("/{call_id}", response_model=CallOut)
async def get_call(call_id: int, session: DbSession) -> CallOut:
    call = await CallRepository(session).get(call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Call nicht gefunden")
    return CallOut.from_model(call)


@router.post("", response_model=CallOut, status_code=201)
async def create_call(payload: CallCreate, session: DbSession) -> CallOut:
    settings = get_settings()
    call_service = CallService(session, settings)

    try:
        allowed, reason = await call_service.can_start_call(payload.lead_id)
        if not allowed:
            raise HTTPException(status_code=409, detail=reason)

        ctx = build_app_context()

        async def dario_factory(lead_id: int, call_id: int) -> Dario:
            tool_executor = ToolExecutor(session, ctx.email_provider, ctx.whatsapp_provider, settings.company_name)
            return await Dario.for_lead(session, settings, ctx.business_config, ctx.engine, tool_executor, lead_id, call_id)

        from voice.stt.whisper_cpp import LocalWhisperProvider

        stt = LocalWhisperProvider(settings.whisper_cpp_binary, settings.whisper_model_path, settings.whisper_language)
        tts = await get_tts_provider(session)

        async with AsteriskProvider(
            settings.asterisk_ari_url,
            settings.asterisk_username,
            settings.asterisk_password,
            settings.asterisk_ari_app,
            settings.asterisk_sip_trunk,
            settings.asterisk_caller_id,
        ) as provider:
            controller = CallController(session, settings, provider, stt, tts, dario_factory)
            call_id = await controller.start_outbound_call(payload.lead_id)

        call = await CallRepository(session).get(call_id)
        return CallOut.from_model(call)

    except CallNotAllowedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except AriError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Asterisk/ARI nicht erreichbar - kein Call gestartet: {exc}",
        ) from exc


@router.post("/twilio", response_model=CallOut, status_code=201)
async def create_twilio_call(payload: CallCreate, session: DbSession) -> CallOut:
    """Startet einen echten Anruf ueber den verifizierten Twilio-Pfad (siehe
    app/twilio_test_call.py, phone/twilio_voice.py) - genutzt fuer Einzelanrufe
    aus dem Dashboard (Abschnitt 8 "Einzelanrufe"). Die Bestaetigung
    ('Jetzt anrufen wirklich ausloesen?') liegt bewusst im Frontend-Modal,
    NICHT hier - dieser Endpunkt wird erst nach der Nutzerbestaetigung
    aufgerufen und loest dann unmittelbar einen echten, kostenpflichtigen
    Anruf aus."""
    settings = get_settings()
    call_service = CallService(session, settings)

    allowed, reason = await call_service.can_start_call(payload.lead_id)
    if not allowed:
        raise HTTPException(status_code=409, detail=reason)

    if not settings.twilio_public_base_url or not settings.twilio_caller_id:
        raise HTTPException(
            status_code=502,
            detail="TWILIO_PUBLIC_BASE_URL/TWILIO_CALLER_ID fehlt in .env - kein Call gestartet.",
        )

    lead = await LeadRepository(session).get(payload.lead_id)
    if lead is None:
        raise HTTPException(status_code=404, detail="Lead nicht gefunden")

    try:
        provider = TwilioProvider(
            settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_caller_id
        )
    except TwilioConfigError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    call = await call_service.start_call(payload.lead_id)
    webhook_url = f"{settings.twilio_public_base_url}/twilio/voice?call_id={call.id}"
    try:
        call_sid = await asyncio.get_event_loop().run_in_executor(
            None, provider.start_outbound_call, lead.telefonnummer, webhook_url
        )
    except Exception as exc:
        await call_service.mark_failed(call.id)
        raise HTTPException(status_code=502, detail=f"Anruf fehlgeschlagen: {exc}") from exc

    call = await CallRepository(session).update(call.id, twilio_call_sid=call_sid)
    return CallOut.from_model(call)


@router.post("/{call_id}/hangup", response_model=CallOut)
async def hangup_call(call_id: int, session: DbSession) -> CallOut:
    """Beendet einen laufenden Anruf WIRKLICH: hat der Call eine
    Twilio-Call-SID, wird zuerst Twilio angewiesen, den echten Anruf zu
    beenden (siehe TwilioProvider.end_call) - erst danach der DB-Status
    gesetzt. Kein reines Setzen eines Datenbank-Flags (vgl. CLAUDE.md
    Sicherheitsregel 5 zu end_call)."""
    settings = get_settings()
    call_service = CallService(session, settings)

    call = await CallRepository(session).get(call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="Call nicht gefunden")

    if call.twilio_call_sid and settings.twilio_account_sid and settings.twilio_auth_token:
        try:
            provider = TwilioProvider(
                settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_caller_id
            )
            await asyncio.get_event_loop().run_in_executor(
                None, provider.end_call, call.twilio_call_sid
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502, detail=f"Anruf konnte nicht beendet werden: {exc}"
            ) from exc

    updated = await call_service.hangup(call_id, result="MANUAL_HANGUP")
    return CallOut.from_model(updated)
