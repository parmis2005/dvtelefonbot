"""Live-Status ohne Neuladen der Seite (Abschnitt 12, 33): WebSocket, die den
Browser alle 1.5s ueber aktive Anrufe informiert.

Bewusst pollend statt event-getrieben implementiert: die eigentlichen
Gespraechs-Zustandsaenderungen passieren tief in phone/twilio_media_handler.py
(pro Anruf eine eigene, unabhaengige Session) - sie dort zusaetzlich an ein
Pub/Sub anzuschliessen, haette den bereits verifizierten Twilio-Audio-Pfad
angefasst. Ein 1.5s-Datenbank-Poll liefert fuer eine Dashboard-Statusanzeige
(nicht fuer die Audio-Echtzeitschleife selbst) ausreichend "live" wirkende
Aktualisierung, ohne dieses Risiko einzugehen.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.auth import is_session_valid
from core.logging import get_logger
from database.database import get_session_factory
from database.models import CallStatus
from database.repository import CallRepository, LeadRepository

router = APIRouter()
logger = get_logger(__name__)

_ACTIVE_STATUSES = (CallStatus.CREATED, CallStatus.RINGING, CallStatus.ANSWERED)
POLL_INTERVAL_SECONDS = 1.5

_STATUS_LABELS = {
    CallStatus.CREATED: "wird gestartet",
    CallStatus.RINGING: "klingelt",
    CallStatus.ANSWERED: "verbunden",
}


async def _active_calls_payload() -> list[dict]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        calls = await CallRepository(session).list_all(limit=200)
        active = [c for c in calls if c.status in _ACTIVE_STATUSES]
        lead_repo = LeadRepository(session)
        payload = []
        for call in active:
            lead = await lead_repo.get(call.lead_id)
            payload.append(
                {
                    "call_id": call.id,
                    "campaign_id": call.campaign_id,
                    "lead_id": call.lead_id,
                    "unternehmen": lead.unternehmen if lead else None,
                    "ansprechpartner": lead.ansprechpartner if lead else None,
                    "telefonnummer": lead.telefonnummer if lead else None,
                    "status": call.status.value,
                    "status_label": _STATUS_LABELS.get(call.status, call.status.value),
                    "started_at": call.started_at.isoformat() if call.started_at else None,
                }
            )
        return payload


@router.websocket("/ws/live-status")
async def live_status_ws(websocket: WebSocket) -> None:
    session_token = websocket.cookies.get("dario_dashboard_session")
    session_factory = get_session_factory()
    async with session_factory() as db_session:
        valid = await is_session_valid(db_session, session_token)
    if not valid:
        await websocket.close(code=4401)
        return

    await websocket.accept()
    try:
        while True:
            payload = await _active_calls_payload()
            await websocket.send_text(json.dumps({"active_calls": payload}))
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        logger.debug("Live-Status-WebSocket getrennt.")
