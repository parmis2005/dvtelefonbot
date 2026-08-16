"""Barge-In: bricht die laufende TTS-Wiedergabe ab, sobald der Gespraechspartner
zu sprechen beginnt (Abschnitt 28).

Ablauf:
1. Voice Activity erkennen (waehrend Dario spricht)
2. TTS-Ausgabe sofort abbrechen (Playback-Task canceln)
3. Audio-Queue leeren
4. Kunde ausreden lassen (EndpointDetector nutzen)
5. STT abschliessen
6. Gespraechskontext aktualisieren (geschieht im Aufrufer via ConversationEngine)
"""

from __future__ import annotations

import asyncio

from core.logging import get_logger
from voice.vad import EndpointDetector, VoiceActivityDetector

logger = get_logger(__name__)


class BargeInController:
    def __init__(self, vad: VoiceActivityDetector, endpoint: EndpointDetector | None = None):
        self.vad = vad
        self.endpoint = endpoint or EndpointDetector()
        self._playback_task: asyncio.Task | None = None
        self._audio_queue: asyncio.Queue | None = None
        self.is_speaking_dario = False

    def attach_playback(self, task: asyncio.Task, queue: asyncio.Queue) -> None:
        self._playback_task = task
        self._audio_queue = queue
        self.is_speaking_dario = True

    async def on_incoming_frame(self, frame: bytes, sample_rate: int = 16000) -> bool:
        """Wird pro Audio-Frame vom Mikrofon/Telefonkanal aufgerufen.

        Gibt True zurueck, wenn ein Barge-In ausgeloest wurde (Dario wurde
        unterbrochen und sollte sofort verstummen).
        """
        speech = self.vad.is_speech(frame, sample_rate)

        if self.is_speaking_dario and speech:
            await self._abort_playback()
            return True

        self.endpoint.process_frame(speech)
        return False

    async def _abort_playback(self) -> None:
        logger.info("Barge-In erkannt - breche TTS-Wiedergabe ab")
        if self._playback_task is not None and not self._playback_task.done():
            self._playback_task.cancel()
        if self._audio_queue is not None:
            while not self._audio_queue.empty():
                try:
                    self._audio_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        self.is_speaking_dario = False

    def mark_playback_finished(self) -> None:
        self.is_speaking_dario = False
