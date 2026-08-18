"""Telefonie-Verwaltung (Abschnitt 24-26): Verbindungsstatus, Caller-ID,
Verbindungstest, Testanruf.

Auth Token/Account SID verlassen den Server NIE im Klartext (siehe
_mask_sid) - Sicherheitsregel 7 aus CLAUDE.md. Die Caller-ID selbst kommt
bewusst aus .env statt frei editierbar zu sein: Twilio laesst nur zuvor
verifizierte Nummern als Absender zu, ein frei eingegebener Wert wuerde
stille Fehlschlaege erzeugen statt echter Kontrolle."""

from __future__ import annotations

import asyncio
import time
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
from services.greeting_audio import prepare_greeting_audio
from services.response_audio import prepare_initial_response_audio
from services.telephony_diagnostics import check_webhook_reachable

router = APIRouter(prefix="/api/telephony", tags=["telephony"], dependencies=[Depends(require_auth)])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
_STATUS_CACHE_TTL_SECONDS = 20.0
_status_cache: TelephonyStatusOut | None = None
_status_cache_expires_at = 0.0
_status_cache_signature: tuple[str, str, str, str] | None = None
_status_cache_lock: asyncio.Lock | None = None


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
    # Prueft aktiv, ob TWILIO_PUBLIC_BASE_URL (z.B. ngrok-Tunnel) gerade
    # tatsaechlich erreichbar ist - nicht nur, ob ein Wert in .env steht.
    # Genau diese Luecke liess einen echten Testanruf mit Twilio-Fehler 11200
    # ("Got HTTP 502 response") unbemerkt fehlschlagen, siehe CLAUDE.md.
    public_base_url_reachable: bool | None = None
    public_base_url_detail: str | None = None


class TestCallRequest(BaseModel):
    to_number: str


def _get_status_cache_lock() -> asyncio.Lock:
    global _status_cache_lock
    if _status_cache_lock is None:
        _status_cache_lock = asyncio.Lock()
    return _status_cache_lock


def clear_telephony_status_cache() -> None:
    global _status_cache, _status_cache_expires_at, _status_cache_signature
    _status_cache = None
    _status_cache_expires_at = 0.0
    _status_cache_signature = None


def _status_signature() -> tuple[str, str, str, str]:
    settings = get_settings()
    return (
        settings.twilio_account_sid,
        settings.twilio_auth_token,
        settings.twilio_caller_id,
        settings.twilio_public_base_url,
    )


async def _build_telephony_status() -> TelephonyStatusOut:
    settings = get_settings()
    url_reachable, url_detail = await check_webhook_reachable(settings.twilio_public_base_url)

    configured = bool(settings.twilio_account_sid and settings.twilio_auth_token)
    if not configured:
        return TelephonyStatusOut(
            configured=False,
            connected=False,
            detail="TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN fehlen in .env",
            caller_id=None,
            account_sid_masked=None,
            public_base_url_configured=bool(settings.twilio_public_base_url),
            public_base_url_reachable=url_reachable,
            public_base_url_detail=url_detail,
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
            public_base_url_reachable=url_reachable,
            public_base_url_detail=url_detail,
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
        public_base_url_reachable=url_reachable,
        public_base_url_detail=url_detail,
    )


async def _get_telephony_status_cached() -> TelephonyStatusOut:
    global _status_cache, _status_cache_expires_at, _status_cache_signature
    now = time.monotonic()
    signature = _status_signature()
    if (
        _status_cache is not None
        and _status_cache_signature == signature
        and now < _status_cache_expires_at
    ):
        return _status_cache

    async with _get_status_cache_lock():
        now = time.monotonic()
        signature = _status_signature()
        if (
            _status_cache is not None
            and _status_cache_signature == signature
            and now < _status_cache_expires_at
        ):
            return _status_cache
        status = await _build_telephony_status()
        _status_cache = status
        _status_cache_signature = signature
        _status_cache_expires_at = time.monotonic() + _STATUS_CACHE_TTL_SECONDS
        return status


@router.get("/status", response_model=TelephonyStatusOut)
async def telephony_status() -> TelephonyStatusOut:
    return await _get_telephony_status_cached()


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

    # Erreichbarkeit VOR dem Anruf pruefen statt erst danach im Twilio-
    # Debugger zu entdecken: ein Testanruf, der klingelt, angenommen wird
    # und dann sofort mit einer Fehleransage abbricht (Twilio-Fehler 11200
    # "Got HTTP 502 response"), weil der Tunnel/das Backend nicht erreichbar
    # war, ist fuer den Kunden verwirrend UND kostet trotzdem Geld.
    url_reachable, url_detail = await check_webhook_reachable(settings.twilio_public_base_url)
    if not url_reachable:
        raise HTTPException(
            status_code=502,
            detail=(
                f"TWILIO_PUBLIC_BASE_URL ({settings.twilio_public_base_url}) ist gerade nicht "
                f"erreichbar ({url_detail}) - kein Anruf ausgeloest. Laeuft der Tunnel (z.B. "
                "ngrok) und das Backend (uvicorn)? Stimmt die URL noch mit dem aktuellen Tunnel "
                "ueberein?"
            ),
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
    status_callback_url = f"{settings.twilio_public_base_url}/twilio/status?call_id={call.id}"
    try:
        await prepare_greeting_audio(session, lead_id=lead.id, call_id=call.id)
        await prepare_initial_response_audio(session, lead_id=lead.id, call_id=call.id)
    except Exception as exc:
        await call_service.mark_failed(call.id)
        raise HTTPException(
            status_code=502,
            detail=f"Audio konnte nicht vorbereitet werden: {exc}",
        ) from exc

    try:
        call_sid = await asyncio.get_event_loop().run_in_executor(
            None, provider.start_outbound_call, payload.to_number, webhook_url, status_callback_url
        )
    except Exception as exc:
        await call_service.mark_failed(call.id)
        raise HTTPException(status_code=502, detail=f"Testanruf fehlgeschlagen: {exc}") from exc

    await CallRepository(session).update(call.id, twilio_call_sid=call_sid)
    return {"call_id": call.id, "twilio_call_sid": call_sid, "to_number": payload.to_number}
