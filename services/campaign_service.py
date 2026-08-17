"""CampaignManager: orchestriert Sammelanrufe mit begrenzter Parallelitaet
(Abschnitt 9-11 der Dashboard-Spec).

Wichtig: der Manager fuehrt die Gespraeche NICHT selbst. Jeder gestartete
Anruf laeuft komplett unabhaengig ueber den bereits verifizierten Twilio-Pfad
(TwilioProvider.start_outbound_call -> /twilio/voice -> /twilio/media-stream,
siehe api/twilio.py, app/twilio_test_call.py) mit seiner eigenen Dario-/STT-/
TTS-Session. Der Manager entscheidet nur, WANN ein neuer Anruf gestartet
werden darf (max_concurrent) und WELCHER Lead als naechstes dran ist -
implementiert als In-Process-Polling-Loop (asyncio.Task pro Kampagne), da
dies ein einzelner, dauerhaft laufender Backend-Prozess ist (kein Serverless).

Restart-Sicherheit: der "verbleibend"-Zustand wird NICHT im Speicher gehalten,
sondern bei jedem Tick aus der Datenbank rekonstruiert (Call-Zeilen mit
campaign_id) - ein Neustart des Backends verliert daher keine Fortschritts-
information, sondern nur laufende asyncio.Tasks (siehe resume_after_restart).
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from core.config import Settings, get_settings
from core.logging import get_logger
from database.database import get_session_factory
from database.models import CallResult, CallStatus, CampaignStatus
from database.repository import CallRepository, CampaignRepository, LeadRepository
from phone.twilio_voice import TwilioConfigError, TwilioProvider
from services.call_service import CallService
from services.telephony_diagnostics import check_webhook_reachable

logger = get_logger(__name__)

POLL_INTERVAL_SECONDS = 3.0
_ACTIVE_CALL_STATUSES = (CallStatus.CREATED, CallStatus.RINGING, CallStatus.ANSWERED)


class CampaignManager:
    """Prozessweiter Singleton (siehe get_campaign_manager()). Haelt pro
    laufender Kampagne genau einen asyncio.Task."""

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}

    def is_active(self, campaign_id: int) -> bool:
        task = self._tasks.get(campaign_id)
        return task is not None and not task.done()

    async def start(self, campaign_id: int) -> None:
        if self.is_active(campaign_id):
            return
        session_factory = get_session_factory()
        async with session_factory() as session:
            campaign_repo = CampaignRepository(session)
            campaign = await campaign_repo.get(campaign_id)
            if campaign is None:
                raise ValueError(f"Kampagne {campaign_id} nicht gefunden")
            if campaign.status in (CampaignStatus.STOPPED, CampaignStatus.COMPLETED):
                raise ValueError(f"Kampagne ist bereits beendet ({campaign.status.value})")
            await campaign_repo.update(
                campaign_id,
                status=CampaignStatus.RUNNING,
                started_at=campaign.started_at or datetime.utcnow(),
            )
        task = asyncio.create_task(self._run_campaign(campaign_id))
        self._tasks[campaign_id] = task

    async def pause(self, campaign_id: int) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await CampaignRepository(session).update(campaign_id, status=CampaignStatus.PAUSED)

    async def resume(self, campaign_id: int) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            campaign = await CampaignRepository(session).get(campaign_id)
            if campaign is None:
                raise ValueError(f"Kampagne {campaign_id} nicht gefunden")
            if campaign.status != CampaignStatus.PAUSED:
                raise ValueError("Nur eine pausierte Kampagne kann fortgesetzt werden")
            await CampaignRepository(session).update(campaign_id, status=CampaignStatus.RUNNING)
        if not self.is_active(campaign_id):
            task = asyncio.create_task(self._run_campaign(campaign_id))
            self._tasks[campaign_id] = task

    async def stop(self, campaign_id: int) -> None:
        session_factory = get_session_factory()
        async with session_factory() as session:
            await CampaignRepository(session).update(campaign_id, status=CampaignStatus.STOPPED)

    async def resume_after_restart(self) -> None:
        """Beim Backend-Start aufgerufen (siehe app/main.py): eine Kampagne,
        die beim letzten Prozessende RUNNING war, hat garantiert keinen
        laufenden asyncio.Task mehr (der Prozess wurde beendet) - sie wird
        defensiv auf PAUSED gesetzt, damit sie nicht unbeaufsichtigt neue,
        potenziell kostenpflichtige Anrufe ausloest. Der Nutzer muss im
        Dashboard bewusst auf 'Fortsetzen' klicken."""
        session_factory = get_session_factory()
        async with session_factory() as session:
            repo = CampaignRepository(session)
            running = await repo.list_running_or_paused()
            for campaign in running:
                if campaign.status == CampaignStatus.RUNNING and not self.is_active(campaign.id):
                    logger.warning(
                        "Kampagne %s war nach Neustart noch als RUNNING markiert - "
                        "setze defensiv auf PAUSED (kein automatischer Wiederanlauf "
                        "kostenpflichtiger Anrufe ohne Nutzerbestaetigung).",
                        campaign.id,
                    )
                    await repo.update(campaign.id, status=CampaignStatus.PAUSED)

    async def _run_campaign(self, campaign_id: int) -> None:
        settings = get_settings()
        session_factory = get_session_factory()
        logger.info("Kampagnen-Orchestrator gestartet: campaign_id=%s", campaign_id)
        try:
            while True:
                async with session_factory() as session:
                    campaign_repo = CampaignRepository(session)
                    campaign = await campaign_repo.get(campaign_id)
                    if campaign is None:
                        return
                    if campaign.status in (CampaignStatus.STOPPED, CampaignStatus.COMPLETED):
                        logger.info("Kampagne %s beendet (%s)", campaign_id, campaign.status.value)
                        return

                    lead_ids: list[int] = json.loads(campaign.lead_ids_json)

                    attempted_lead_ids = await self._attempted_lead_ids(session, campaign_id)
                    remaining_lead_ids = [lid for lid in lead_ids if lid not in attempted_lead_ids]

                    if not remaining_lead_ids:
                        active = await self._active_call_count(session, campaign_id)
                        if active == 0:
                            await campaign_repo.update(
                                campaign_id,
                                status=CampaignStatus.COMPLETED,
                                processed_count=len(attempted_lead_ids),
                                finished_at=datetime.utcnow(),
                            )
                            logger.info("Kampagne %s abgeschlossen.", campaign_id)
                            return
                        await campaign_repo.update(
                            campaign_id, processed_count=len(attempted_lead_ids)
                        )
                    elif campaign.status == CampaignStatus.RUNNING:
                        active = await self._active_call_count(session, campaign_id)
                        free_slots = max(0, campaign.max_concurrent - active)
                        if free_slots > 0 and not await self._webhook_reachable(settings):
                            # Transiente Infrastruktur-Nichterreichbarkeit
                            # (z.B. Tunnel/Backend gerade nicht erreichbar,
                            # siehe api/telephony.py fuer den Hintergrund:
                            # Twilio-Fehler 11200) - KEINE neuen Anrufe in
                            # diesem Tick, aber die verbleibenden Leads
                            # bleiben fuer den naechsten Tick unangetastet
                            # (kein permanentes "uebersprungen" wie bei
                            # Do-Not-Call/ungueltiger Nummer).
                            logger.warning(
                                "Kampagne %s: TWILIO_PUBLIC_BASE_URL gerade nicht erreichbar - "
                                "starte in diesem Tick keine neuen Anrufe.",
                                campaign_id,
                            )
                            free_slots = 0
                        for lead_id in remaining_lead_ids[:free_slots]:
                            await self._attempt_lead(session, settings, campaign_id, lead_id)
                        if free_slots > 0:
                            await campaign_repo.update(
                                campaign_id,
                                processed_count=len(
                                    await self._attempted_lead_ids(session, campaign_id)
                                ),
                            )

                await asyncio.sleep(POLL_INTERVAL_SECONDS)
        finally:
            self._tasks.pop(campaign_id, None)

    @staticmethod
    async def _webhook_reachable(settings: Settings) -> bool:
        reachable, _ = await check_webhook_reachable(settings.twilio_public_base_url)
        return reachable

    @staticmethod
    async def _attempted_lead_ids(session, campaign_id: int) -> set[int]:
        calls = await CallRepository(session).list_for_campaign(campaign_id)
        return {c.lead_id for c in calls}

    @staticmethod
    async def _active_call_count(session, campaign_id: int) -> int:
        calls = await CallRepository(session).list_for_campaign(campaign_id)
        return sum(1 for c in calls if c.status in _ACTIVE_CALL_STATUSES)

    @staticmethod
    async def _attempt_lead(session, settings: Settings, campaign_id: int, lead_id: int) -> None:
        call_service = CallService(session, settings)
        lead_repo = LeadRepository(session)
        call_repo = CallRepository(session)

        lead = await lead_repo.get(lead_id)
        if lead is None:
            return

        allowed, reason = await call_service.can_start_call(lead_id)
        if not allowed:
            call = await call_repo.create(
                lead_id=lead_id,
                campaign_id=campaign_id,
                status=CallStatus.FAILED,
                result=(
                    CallResult.DO_NOT_CALL if "Sperrliste" in reason or "Do-Not-Call" in reason
                    else CallResult.UNKNOWN
                ),
                summary=f"Nicht angerufen (Kampagne): {reason}",
            )
            await call_repo.mark_ended(call.id, CallStatus.FAILED, result=call.result)
            logger.info("Kampagne %s: Lead %s uebersprungen (%s)", campaign_id, lead_id, reason)
            return

        if not settings.twilio_public_base_url or not settings.twilio_caller_id:
            call = await call_repo.create(
                lead_id=lead_id,
                campaign_id=campaign_id,
                status=CallStatus.FAILED,
                result=CallResult.UNKNOWN,
                summary="Nicht angerufen: TWILIO_PUBLIC_BASE_URL/TWILIO_CALLER_ID fehlt in .env",
            )
            await call_repo.mark_ended(call.id, CallStatus.FAILED, result=call.result)
            return

        try:
            provider = TwilioProvider(
                settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_caller_id
            )
        except TwilioConfigError as exc:
            call = await call_repo.create(
                lead_id=lead_id,
                campaign_id=campaign_id,
                status=CallStatus.FAILED,
                result=CallResult.UNKNOWN,
                summary=f"Nicht angerufen: {exc}",
            )
            await call_repo.mark_ended(call.id, CallStatus.FAILED, result=call.result)
            return

        call = await call_repo.create(
            lead_id=lead_id, campaign_id=campaign_id, status=CallStatus.CREATED
        )
        webhook_url = f"{settings.twilio_public_base_url}/twilio/voice?call_id={call.id}"
        try:
            call_sid = await asyncio.get_event_loop().run_in_executor(
                None, provider.start_outbound_call, lead.telefonnummer, webhook_url
            )
            await call_repo.update(call.id, twilio_call_sid=call_sid)
            logger.info(
                "Kampagne %s: Anruf gestartet fuer Lead %s (Call %s, SID %s)",
                campaign_id, lead_id, call.id, call_sid,
            )
        except Exception as exc:
            logger.error("Kampagne %s: Anruf fuer Lead %s fehlgeschlagen: %s", campaign_id, lead_id, exc)
            await call_repo.mark_ended(call.id, CallStatus.FAILED, result=CallResult.UNKNOWN)


_campaign_manager: CampaignManager | None = None


def get_campaign_manager() -> CampaignManager:
    global _campaign_manager
    if _campaign_manager is None:
        _campaign_manager = CampaignManager()
    return _campaign_manager
