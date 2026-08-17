"""FastAPI-Router fuer Twilio Programmable Voice.

Drei Endpunkte:
  POST /twilio/voice    - TwiML-Webhook, von Twilio aufgerufen sobald der
                           Anruf angenommen wurde. Liefert die Anweisung,
                           den Call an unsere Media-Stream-WebSocket zu haengen.
  POST /twilio/status   - Status-Callback (ringing/answered/completed/...),
                           haelt den Call-Datensatz aktuell.
  WS   /twilio/media-stream - bidirektionale Audio-Bruecke zu Darios
                           STT -> Conversation Engine -> TTS Pipeline
                           (siehe phone/twilio_media_handler.py).

Beide POST-Webhooks werden per Twilio-Signatur validiert (sofern
TWILIO_VALIDATE_SIGNATURE=true, Standard) - nur echte Twilio-Requests werden
akzeptiert.
"""

from __future__ import annotations

import json

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)

from agent.dario import Dario
from app.bootstrap import build_app_context, get_tts_provider
from core.config import get_settings
from core.logging import get_logger
from database.database import get_session_factory
from database.models import CallStatus
from database.repository import CallRepository
from phone.twilio_media_handler import TwilioMediaStreamSession
from phone.twilio_voice import TwilioProvider
from services.call_service import CallService
from services.tts_cache import ensure_cached_tts
from tools.call_tools import ToolExecutor
from voice.stt.whisper_cpp import LocalWhisperProvider

router = APIRouter(prefix="/twilio", tags=["twilio"])
logger = get_logger(__name__)

_TWILIO_STATUS_MAP = {
    "queued": CallStatus.CREATED,
    "initiated": CallStatus.CREATED,
    "ringing": CallStatus.RINGING,
    "in-progress": CallStatus.ANSWERED,
    "completed": CallStatus.COMPLETED,
    "busy": CallStatus.BUSY,
    "failed": CallStatus.FAILED,
    "no-answer": CallStatus.NO_ANSWER,
    "canceled": CallStatus.FAILED,
}


async def _validate_twilio_request(request: Request, form: dict) -> None:
    settings = get_settings()
    if not settings.twilio_validate_signature:
        return
    signature = request.headers.get("X-Twilio-Signature", "")
    provider = TwilioProvider(
        settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_caller_id
    )
    full_url = str(request.url)
    if not provider.validate_signature(full_url, form, signature):
        logger.warning("Ungueltige Twilio-Signatur fuer %s", full_url)
        raise HTTPException(status_code=403, detail="Ungueltige Twilio-Signatur")


@router.post("/voice")
async def twilio_voice_webhook(request: Request, call_id: int = Query(...)) -> Response:
    form = dict(await request.form())
    await _validate_twilio_request(request, form)
    twilio_call_sid = form.get("CallSid")
    call_status = form.get("CallStatus")
    logger.info(
        "[CALL] incoming Twilio callback callSid=%s call_id=%s status=%s",
        twilio_call_sid,
        call_id,
        call_status,
    )

    settings = get_settings()
    # call_id steht zusaetzlich als Query-Param in der URL (guenstiger,
    # harmloser Fallback), massgeblich ist aber das <Parameter>-Element -
    # siehe TwilioProvider.build_connect_stream_twiml fuer den Hintergrund.
    ws_url = (
        settings.twilio_public_base_url.replace("https://", "wss://").replace("http://", "ws://")
        + f"/twilio/media-stream?call_id={call_id}"
    )
    twiml = TwilioProvider.build_connect_stream_twiml(ws_url, call_id)
    logger.info("TwiML-Webhook fuer Call %s ausgeliefert (Stream: %s)", call_id, ws_url)
    return Response(content=twiml, media_type="application/xml")


@router.post("/status")
async def twilio_status_webhook(request: Request, call_id: int = Query(...)) -> dict:
    form = dict(await request.form())
    await _validate_twilio_request(request, form)

    call_status = form.get("CallStatus", "")
    twilio_call_sid = form.get("CallSid")
    mapped = _TWILIO_STATUS_MAP.get(call_status)
    logger.info(
        "[CALL] incoming Twilio status callback callSid=%s call_id=%s status=%s mapped=%s",
        twilio_call_sid,
        call_id,
        call_status,
        mapped,
    )

    if mapped is None:
        return {"ok": True}

    settings = get_settings()
    session_factory = get_session_factory()
    async with session_factory() as session:
        if twilio_call_sid:
            call = await CallRepository(session).get(call_id)
            if call is not None and call.twilio_call_sid != twilio_call_sid:
                await CallRepository(session).update(call_id, twilio_call_sid=twilio_call_sid)
        call_service = CallService(session, settings)
        if mapped == CallStatus.BUSY:
            await call_service.mark_busy(call_id)
        elif mapped == CallStatus.NO_ANSWER:
            await call_service.mark_no_answer(call_id)
        elif mapped == CallStatus.FAILED:
            await call_service.mark_failed(call_id)
        elif mapped == CallStatus.COMPLETED:
            # bereits von _hangup_real_call/_on_session_end als beendet
            # markiert, falls die Media-Stream-Session lief; sonst nachholen.
            call = await CallRepository(session).get(call_id)
            if call and call.status not in (CallStatus.COMPLETED, CallStatus.HANGUP):
                await call_service.complete(call_id)
        else:
            await CallRepository(session).update(call_id, status=mapped)
    return {"ok": True}


async def _await_start_event(websocket: WebSocket) -> dict:
    """Liest WebSocket-Nachrichten, bis das "start"-Event kommt, und gibt es
    zurueck. call_id kommt aus <Parameter> (customParameters), NICHT aus der
    URL-Query - Twilio reicht Query-Parameter in der Stream-URL nicht
    zuverlaessig durch (Fehler 31920 "WebSocket Handshake Error")."""
    while True:
        raw = await websocket.receive_text()
        msg = json.loads(raw)
        if msg.get("event") == "start":
            start = msg.get("start", {})
            logger.info(
                "[WS] start received streamSid=%s callSid=%s",
                start.get("streamSid"),
                start.get("callSid"),
            )
            return msg
        if msg.get("event") == "connected":
            logger.info("[WS] connected")
            continue


@router.websocket("/media-stream")
async def twilio_media_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    logger.info("[WS] connected")

    try:
        start_msg = await _await_start_event(websocket)
    except WebSocketDisconnect:
        logger.info("Media Stream vor dem start-Event getrennt.")
        return

    start = start_msg["start"]
    custom_params = start.get("customParameters", {})
    call_id_raw = custom_params.get("call_id") or websocket.query_params.get("call_id")
    if call_id_raw is None:
        logger.error(
            "Media Stream ohne call_id (weder customParameters noch Query) - "
            "schliesse Verbindung. start-Event: %s",
            start,
        )
        await websocket.close(code=4400)
        return
    call_id = int(call_id_raw)
    stream_sid = start["streamSid"]
    twilio_call_sid = start.get("callSid")
    logger.info(
        "Twilio Media Stream gestartet: call_id=%s streamSid=%s callSid=%s",
        call_id, stream_sid, twilio_call_sid,
    )

    session_factory = get_session_factory()

    async with session_factory() as session:
        call = await CallRepository(session).get(call_id)
        if call is None:
            logger.error("Media Stream fuer unbekannten Call %s - schliesse Verbindung", call_id)
            await websocket.close(code=4404)
            return
        if twilio_call_sid and call.twilio_call_sid != twilio_call_sid:
            await CallRepository(session).update(call_id, twilio_call_sid=twilio_call_sid)

        # Mit Session: liest Dashboard-Ueberschreibungen (Agent-Name/Firma/
        # Standort/Wartezeit/Stille-Timeout/Cooldown, siehe
        # services/effective_settings.py) - ein NEUER Call bekommt automatisch
        # die zuletzt im Dashboard gespeicherten Werte.
        ctx = await build_app_context(session)
        settings = ctx.settings

        tool_executor = ToolExecutor(session, ctx.email_provider, ctx.whatsapp_provider, settings.company_name)
        dario = await Dario.for_lead(
            session, settings, ctx.business_config, ctx.engine, tool_executor, call.lead_id, call_id
        )

        stt = LocalWhisperProvider(
            settings.whisper_cpp_binary, settings.whisper_model_path, settings.whisper_language
        )
        tts = await get_tts_provider(session)
        opening = dario.opening_line()
        call_service = CallService(session, settings)
        try:
            greeting_audio = await ensure_cached_tts(tts, opening, label="greeting", call_id=call_id)
        except Exception:
            logger.exception(
                "Begruessungs-Audio im Media-Stream fehlgeschlagen (Call %s)",
                call_id,
            )
            await call_service.mark_failed(call_id)
            try:
                await websocket.close(code=1011)
            except RuntimeError:
                pass
            return
        twilio_provider = TwilioProvider(
            settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_caller_id
        )

        session_handler = TwilioMediaStreamSession(
            websocket=websocket,
            dario=dario,
            call_service=call_service,
            call_id=call_id,
            stt=stt,
            tts=tts,
            twilio_provider=twilio_provider,
            stream_sid=stream_sid,
            twilio_call_sid=twilio_call_sid,
            silence_timeout_ms=int(settings.silence_timeout * 1000),
            wait_timeout_seconds=settings.wait_timeout,
            greeting_audio_path=str(greeting_audio.path),
        )
        try:
            await session_handler.run()
        except WebSocketDisconnect:
            logger.info("Twilio Media Stream (Call %s) getrennt.", call_id)
        else:
            # Session normal beendet (Gespraech regulaer abgeschlossen) -
            # WebSocket explizit sauber schliessen statt den Verbindungsabbau
            # implizit dem ASGI-Server zu ueberlassen, sonst kommt bei
            # manchen Clients ein abrupter Verbindungsabbruch statt eines
            # regulaeren Close-Handshakes an.
            try:
                await websocket.close()
            except RuntimeError:
                pass  # bereits getrennt
