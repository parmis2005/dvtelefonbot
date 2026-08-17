"""Telefonie-Verwaltung (Abschnitt 24-26): Verbindungsstatus, Caller-ID,
Verbindungstest, Testanruf.

Auth Token/Account SID verlassen den Server NIE im Klartext (siehe
_mask_sid) - Sicherheitsregel 7 aus CLAUDE.md. Die Caller-ID selbst kommt
bewusst aus .env statt frei editierbar zu sein: Twilio laesst nur zuvor
verifizierte Nummern als Absender zu, ein frei eingegebener Wert wuerde
stille Fehlschlaege erzeugen statt echter Kontrolle."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import require_auth
from core.config import get_settings
from database.database import get_db_session
from database.repository import CallRepository, LeadRepository
from phone.twilio_voice import TwilioConfigError, TwilioProvider
from services.call_service import CallService

router = APIRouter(prefix="/api/telephony", tags=["telephony"], dependencies=[Depends(require_auth)])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def _mask_sid(sid: str) -> str:
    if len(sid) <= 8:
        return "***"
    return f"{sid[:4]}...{sid[-4:]}"


class TelephonyStatusOut(BaseModel):
    provider: str = "twilio"
    configured: bool
    connected: bool
    detail: str
    caller_id: str | None
    account_sid_masked: str | None
    public_base_url_configured: bool


class TestCallRequest(BaseModel):
    to_number: str


@router.get("/status", response_model=TelephonyStatusOut)
async def telephony_status() -> TelephonyStatusOut:
    settings = get_settings()
    configured = bool(settings.twilio_account_sid and settings.twilio_auth_token)
    if not configured:
        return TelephonyStatusOut(
            configured=False,
            connected=False,
            detail="TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN fehlen in .env",
            caller_id=None,
            account_sid_masked=None,
            public_base_url_configured=bool(settings.twilio_public_base_url),
        )

    try:
        provider = TwilioProvider(
            settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_caller_id
        )
    except TwilioConfigError as exc:
        return TelephonyStatusOut(
            configured=False,
            connected=False,
            detail=str(exc),
            caller_id=None,
            account_sid_masked=None,
            public_base_url_configured=bool(settings.twilio_public_base_url),
        )

    connected, detail = await asyncio.get_event_loop().run_in_executor(
        None, provider.verify_credentials
    )
    return TelephonyStatusOut(
        configured=True,
        connected=connected,
        detail=detail,
        caller_id=settings.twilio_caller_id or None,
        account_sid_masked=_mask_sid(settings.twilio_account_sid),
        public_base_url_configured=bool(settings.twilio_public_base_url),
    )


@router.post("/test-call")
async def trigger_test_call(payload: TestCallRequest, session: DbSession) -> dict:
    """Loest einen ECHTEN, kostenpflichtigen Testanruf aus - die Bestaetigung
    liegt im Frontend-Modal (Von/An/Agent/Stimme, Abbrechen/Jetzt testen).
    Nutzt exakt denselben Pfad wie app/twilio_test_call.py, also die volle
    Dario-Conversation-Engine, keine vorgefertigte Ansage."""
    settings = get_settings()
    if not settings.twilio_public_base_url or not settings.twilio_caller_id:
        raise HTTPException(
            status_code=502,
            detail="TWILIO_PUBLIC_BASE_URL/TWILIO_CALLER_ID fehlt in .env.",
        )

    lead_repo = LeadRepository(session)
    lead = await lead_repo.get_by_phone(payload.to_number)
    if lead is None:
        lead = await lead_repo.create(
            unternehmen="Dashboard-Testanruf",
            ansprechpartner="Testperson",
            telefonnummer=payload.to_number,
            branche="Test",
            online_auftritt_geprueft=True,
            entwurf_vorhanden=True,
            entwurf_link="https://beispiel.digital-vision-entwurf.de/demo",
        )

    call_service = CallService(session, settings)
    allowed, reason = await call_service.can_start_call(lead.id)
    if not allowed:
        raise HTTPException(status_code=409, detail=reason)

    try:
        provider = TwilioProvider(
            settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_caller_id
        )
    except TwilioConfigError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    call = await call_service.start_call(lead.id)
    webhook_url = f"{settings.twilio_public_base_url}/twilio/voice?call_id={call.id}"
    try:
        call_sid = await asyncio.get_event_loop().run_in_executor(
            None, provider.start_outbound_call, payload.to_number, webhook_url
        )
    except Exception as exc:
        await call_service.mark_failed(call.id)
        raise HTTPException(status_code=502, detail=f"Testanruf fehlgeschlagen: {exc}") from exc

    await CallRepository(session).update(call.id, twilio_call_sid=call_sid)
    return {"call_id": call.id, "twilio_call_sid": call_sid, "to_number": payload.to_number}
