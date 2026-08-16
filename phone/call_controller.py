"""Call Controller: verbindet ARI-Events mit der Dario Conversation Engine.

Implementiert die in Abschnitt 49 geforderten Funktionen. Der aktuelle
Audio-Pfad ist turn-basiert (ARI record -> STT -> Dario -> TTS -> ARI play),
was fuer ein erstes lauffaehiges Telefonat ausreicht. Echtes Streaming-Audio
per ExternalMedia/RTP (fuer verzoegerungsfreies Barge-In) ist in
phone/asterisk.py::start_external_media vorbereitet und kann in einer
naechsten Ausbaustufe angeschlossen werden (siehe README, Abschnitt "Grenzen
der aktuellen Version").

Erfordert einen laufenden, konfigurierten Asterisk-Server (ARI aktiviert).
Ohne Server schlaegt der Verbindungsaufbau mit einer echten AriError fehl.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from agent.dario import Dario
from core.config import Settings
from core.logging import get_logger, mask_phone
from database.models import CallStatus
from database.repository import CallRepository, LeadRepository
from phone.asterisk import AsteriskProvider
from services.call_service import CallNotAllowedError, CallService
from voice.stt.base import SpeechToTextProvider
from voice.tts.base import TextToSpeechProvider

logger = get_logger(__name__)

# Asterisk-Recordings landen typischerweise hier (siehe asterisk.conf: astspooldir)
DEFAULT_RECORDING_DIR = "/var/spool/asterisk/recording"


class CallController:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        provider: AsteriskProvider,
        stt: SpeechToTextProvider,
        tts: TextToSpeechProvider,
        dario_factory,
        recording_dir: str = DEFAULT_RECORDING_DIR,
        sounds_dir: str = "/var/lib/asterisk/sounds/dario",
    ):
        self.session = session
        self.settings = settings
        self.provider = provider
        self.stt = stt
        self.tts = tts
        self.dario_factory = dario_factory  # async Callable[[lead_id, call_id], Dario]
        self.recording_dir = Path(recording_dir)
        self.sounds_dir = Path(sounds_dir)
        self.call_service = CallService(session, settings)
        self._active_channels: dict[str, dict] = {}

    # --- Outbound-Aufbau ------------------------------------------------

    async def start_outbound_call(self, lead_id: int) -> int:
        allowed, reason = await self.call_service.can_start_call(lead_id)
        if not allowed:
            raise CallNotAllowedError(reason)

        lead_repo = LeadRepository(self.session)
        lead = await lead_repo.get(lead_id)
        call = await self.call_service.start_call(lead_id)

        handle = await self.provider.start_outbound_call(
            lead.telefonnummer, caller_id=self.settings.asterisk_caller_id
        )
        self._active_channels[handle.provider_channel_id] = {"lead_id": lead_id, "call_id": call.id}
        logger.info(
            "Outbound-Call gestartet: lead=%s call=%s channel=%s number=%s",
            lead_id, call.id, handle.provider_channel_id, mask_phone(lead.telefonnummer),
        )
        return call.id

    # --- ARI Event-Loop ---------------------------------------------------

    async def run_event_loop(self) -> None:
        """Hauptschleife: verarbeitet ARI-Events, bis die Verbindung endet."""
        async for event in self.provider.events():
            await self._handle_event(event)

    async def _handle_event(self, event: dict) -> None:
        event_type = event.get("type")
        channel = event.get("channel", {})
        channel_id = channel.get("id")

        handlers = {
            "StasisStart": self._on_stasis_start,
            "ChannelStateChange": self._on_state_change,
            "StasisEnd": self._on_stasis_end,
        }
        handler = handlers.get(event_type)
        if handler and channel_id:
            await handler(channel_id, event)

    async def _on_stasis_start(self, channel_id: str, event: dict) -> None:
        info = self._active_channels.get(channel_id)
        if info is None:
            return  # unbekannter/eingehender Kanal - fuer Phase 13 (Inbound) vorgesehen

        await self.answer_call(channel_id)
        await self.call_service.mark_answered(info["call_id"])

        dario: Dario = await self.dario_factory(info["lead_id"], info["call_id"])
        info["dario"] = dario

        opening = dario.opening_line()
        await self._say(channel_id, opening)
        await self._conversation_loop(channel_id, dario)

    async def _on_state_change(self, channel_id: str, event: dict) -> None:
        state = event.get("channel", {}).get("state")
        info = self._active_channels.get(channel_id)
        if info is None:
            return
        if state == "Busy":
            await self.handle_busy(info["call_id"])
        elif state == "Ringing":
            logger.debug("Kanal %s klingelt", channel_id)

    async def _on_stasis_end(self, channel_id: str, event: dict) -> None:
        info = self._active_channels.pop(channel_id, None)
        if info is None:
            return
        await self.handle_disconnect(info["call_id"])

    # --- Gespraechsschleife (turn-basiert) -------------------------------

    async def _conversation_loop(self, channel_id: str, dario: Dario) -> None:
        while dario.call_active:
            text = await self.detect_speech(channel_id)
            if not text:
                continue
            outcome = await dario.process_utterance(text)
            if outcome.reply_text:
                await self._say(channel_id, outcome.reply_text)
            if outcome.call_ended:
                await self.end_call(channel_id)
                break

    async def _say(self, channel_id: str, text: str) -> None:
        self.sounds_dir.mkdir(parents=True, exist_ok=True)
        filename = f"dario_{channel_id}_{asyncio.get_event_loop().time():.0f}"
        wav_path = self.sounds_dir / f"{filename}.wav"
        await self.tts.synthesize(text, str(wav_path))
        media_uri = f"sound:dario/{filename}"
        await self.play_audio(channel_id, media_uri)

    # --- Abschnitt 49: geforderte Funktionen -----------------------------

    async def answer_call(self, channel_id: str) -> None:
        await self.provider.answer_call(channel_id)

    async def play_audio(self, channel_id: str, media_uri: str) -> str:
        return await self.provider.play_audio(channel_id, media_uri)

    async def stream_audio(self, channel_id: str, media_target_host: str) -> dict:
        return await self.provider.start_external_media(channel_id, media_target_host)

    async def stop_audio(self, playback_id: str) -> None:
        await self.provider.stop_audio(playback_id)

    async def detect_speech(self, channel_id: str) -> str:
        recording_name = f"turn_{channel_id}_{asyncio.get_event_loop().time():.0f}"
        await self.provider.record_utterance(
            channel_id,
            recording_name,
            max_duration=int(self.settings.wait_timeout),
            max_silence=max(1, self.settings.silence_timeout // 4),
        )
        await asyncio.sleep(0.5)  # Asterisk Zeit geben, Datei zu schreiben
        recording_path = self.recording_dir / f"{recording_name}.wav"
        if not recording_path.exists():
            return ""
        result = await self.stt.transcribe(str(recording_path))
        return result.text

    async def end_call(self, channel_id: str) -> None:
        await self.provider.end_call(channel_id)

    async def handle_disconnect(self, call_id: int) -> None:
        call_repo = CallRepository(self.session)
        call = await call_repo.get(call_id)
        if call and call.status not in (CallStatus.COMPLETED, CallStatus.HANGUP):
            await self.call_service.hangup(call_id, result="UNKNOWN")

    async def handle_busy(self, call_id: int) -> None:
        await self.call_service.mark_busy(call_id)

    async def handle_no_answer(self, call_id: int) -> None:
        await self.call_service.mark_no_answer(call_id)

    async def handle_failed_call(self, call_id: int) -> None:
        await self.call_service.mark_failed(call_id)
