"""FastAPI-Router fuer Call-Verwaltung (Abschnitt 52).

POST /api/calls stoesst einen echten Outbound-Call ueber Asterisk/ARI an.
Ist kein Asterisk-Server erreichbar, wird das als 502 mit Klartext-Fehler
zurueckgemeldet - es wird niemals ein erfolgreicher Call vorgetaeuscht.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agent.dario import Dario
from app.bootstrap import build_app_context
from core.config import get_settings
from database.database import get_db_session
from database.models import Call
from database.repository import CallRepository
from phone.ari import AriError
from phone.asterisk import AsteriskProvider
from phone.call_controller import CallController
from services.call_service import CallNotAllowedError, CallService
from tools.call_tools import ToolExecutor

router = APIRouter(prefix="/api/calls", tags=["calls"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class CallCreate(BaseModel):
    lead_id: int
    phone_number: str | None = None  # informativ, massgeblich ist lead.telefonnummer


class CallOut(BaseModel):
    id: int
    lead_id: int
    status: str
    result: str | None
    started_at: str | None = None
    ended_at: str | None = None
    duration: int | None = None
    summary: str | None = None

    @classmethod
    def from_model(cls, call: Call) -> CallOut:
        return cls(
            id=call.id,
            lead_id=call.lead_id,
            status=call.status.value if hasattr(call.status, "value") else call.status,
            result=(call.result.value if hasattr(call.result, "value") else call.result),
            started_at=call.started_at.isoformat() if call.started_at else None,
            ended_at=call.ended_at.isoformat() if call.ended_at else None,
            duration=call.duration,
            summary=call.summary,
        )


@router.get("", response_model=list[CallOut])
async def list_calls(session: DbSession) -> list[CallOut]:
    calls = await CallRepository(session).list_all()
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
        from voice.tts.piper_tts import LocalTTSProvider

        stt = LocalWhisperProvider(settings.whisper_cpp_binary, settings.whisper_model_path, settings.whisper_language)
        tts = LocalTTSProvider(settings.piper_binary, settings.piper_model_path, settings.piper_speaker)

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


@router.post("/{call_id}/hangup", response_model=CallOut)
async def hangup_call(call_id: int, session: DbSession) -> CallOut:
    settings = get_settings()
    call_service = CallService(session, settings)
    call = await call_service.hangup(call_id, result="MANUAL_HANGUP")
    if call is None:
        raise HTTPException(status_code=404, detail="Call nicht gefunden")
    return CallOut.from_model(call)
