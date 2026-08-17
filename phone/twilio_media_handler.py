"""TwilioMediaStreamSession: bruecke zwischen Twilios bidirektionaler
Media-Stream-WebSocket (G.711 mu-law, 8kHz) und Darios bestehender
STT -> Conversation Engine -> TTS Pipeline.

Nutzt ausschliesslich die bereits vorhandene Fassade agent/dario.py::Dario -
die Gespraechslogik selbst wird hier nicht angefasst, nur an einen neuen
Audio-Transport angebunden (genau wie phone/call_controller.py es fuer
Asterisk tut, nur turn-basiert statt Stream-basiert).

Protokoll: https://www.twilio.com/docs/voice/media-streams/websocket-messages
"""

from __future__ import annotations

import asyncio
import base64
import json
import tempfile
from pathlib import Path

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from agent.dario import Dario
from core.logging import get_logger
from phone.twilio_voice import TwilioProvider
from services.call_service import CallService
from voice.audio_stream import write_wav
from voice.codecs import mulaw_to_pcm16, pcm16_to_mulaw, resample_pcm16
from voice.stt.base import SpeechToTextProvider
from voice.tts.base import TextToSpeechProvider
from voice.vad import EndpointConfig, EndpointDetector, VoiceActivityDetector

logger = get_logger(__name__)

TWILIO_SAMPLE_RATE = 8000
STT_SAMPLE_RATE = 16000
FRAME_MS = 20  # Twilio liefert/erwartet 20ms-Frames
FRAME_SAMPLES_8K = TWILIO_SAMPLE_RATE * FRAME_MS // 1000  # 160 Samples = 160 Bytes mu-law
VAD_FRAME_MS = 30  # webrtcvad erlaubt nur 10/20/30ms


class TwilioMediaStreamSession:
    def __init__(
        self,
        websocket: WebSocket,
        dario: Dario,
        call_service: CallService,
        call_id: int,
        stt: SpeechToTextProvider,
        tts: TextToSpeechProvider,
        twilio_provider: TwilioProvider,
        stream_sid: str | None = None,
        twilio_call_sid: str | None = None,
        silence_timeout_ms: int = 900,
        max_utterance_seconds: float = 20.0,
    ):
        self.ws = websocket
        self.dario = dario
        self.call_service = call_service
        self.call_id = call_id
        self.stt = stt
        self.tts = tts
        self.twilio_provider = twilio_provider
        self.silence_timeout_ms = silence_timeout_ms
        self.max_utterance_seconds = max_utterance_seconds

        # Werden ueblicherweise vom Aufrufer schon aus dem "start"-Event
        # herausgelesen uebergeben (siehe api/twilio.py), da dort auch die
        # call_id daraus bestimmt werden muss (Twilio reicht Query-Parameter
        # in der Stream-URL nicht zuverlaessig durch - Fehler 31920).
        self.stream_sid: str | None = stream_sid
        self.call_sid: str | None = twilio_call_sid
        self._inbound_buffer: list[np.ndarray] = []
        self._vad = VoiceActivityDetector(aggressiveness=2)
        self._endpoint = EndpointDetector(EndpointConfig(silence_timeout_ms=silence_timeout_ms))
        self._vad_carry = np.array([], dtype=np.int16)  # Rest-Samples < einem VAD-Frame

        self._speaking = False
        self._playback_task: asyncio.Task | None = None
        self._barge_in_event = asyncio.Event()

    # --- Hauptschleife -------------------------------------------------

    async def run(self) -> None:
        try:
            if self.stream_sid is None:
                await self._wait_for_start()
            else:
                await self.call_service.mark_answered(self.call_id)
            opening = self.dario.opening_line()
            await self._speak(opening)

            while self.dario.call_active:
                text = await self._listen_for_utterance()
                if not text:
                    continue
                outcome = await self.dario.process_utterance(text)
                if outcome.reply_text:
                    await self._speak(outcome.reply_text)
                if outcome.call_ended:
                    await self._hangup_real_call()
                    break
        except WebSocketDisconnect:
            logger.info("Twilio Media Stream getrennt (Call %s)", self.call_id)
        except Exception:
            logger.exception("Fehler in Twilio Media Stream Session (Call %s)", self.call_id)
        finally:
            await self._on_session_end()

    async def _wait_for_start(self) -> None:
        while True:
            raw = await self.ws.receive_text()
            msg = json.loads(raw)
            if msg.get("event") == "start":
                self.stream_sid = msg["start"]["streamSid"]
                self.call_sid = msg["start"].get("callSid")
                logger.info(
                    "Twilio Media Stream gestartet: streamSid=%s callSid=%s",
                    self.stream_sid,
                    self.call_sid,
                )
                await self.call_service.mark_answered(self.call_id)
                return
            if msg.get("event") == "connected":
                continue

    # --- Sprechen (TTS -> mu-law -> WebSocket) ---------------------------

    async def _speak(self, text: str) -> None:
        self._speaking = True
        self._barge_in_event.clear()
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                wav_path = tmp.name
            try:
                await self.tts.synthesize(text, wav_path)
                await self._stream_wav_file(wav_path)
            finally:
                Path(wav_path).unlink(missing_ok=True)
        finally:
            self._speaking = False

    async def _stream_wav_file(self, wav_path: str) -> None:
        import soundfile as sf

        # Bewusst als float32 lesen und selbst nach int16 skalieren: manche
        # TTS-Provider (Chatterbox) schreiben 32bit-Float-WAVs, und
        # sf.read(..., dtype="int16") skaliert dabei NICHT verlaesslich hoch
        # (fuehrte zu quasi lautlosem/verrauschtem Audio auf der Leitung).
        pcm_float, src_rate = sf.read(wav_path, dtype="float32")
        if pcm_float.ndim > 1:
            pcm_float = pcm_float[:, 0]
        pcm = np.clip(pcm_float * 32767.0, -32768, 32767).astype(np.int16)
        pcm_8k = resample_pcm16(pcm, src_rate, TWILIO_SAMPLE_RATE)
        mulaw = pcm16_to_mulaw(pcm_8k)

        for i in range(0, len(mulaw), FRAME_SAMPLES_8K):
            if self._barge_in_event.is_set():
                await self._send_clear()
                break
            chunk = mulaw[i : i + FRAME_SAMPLES_8K].tobytes()
            payload = base64.b64encode(chunk).decode("ascii")
            await self.ws.send_text(
                json.dumps(
                    {
                        "event": "media",
                        "streamSid": self.stream_sid,
                        "media": {"payload": payload},
                    }
                )
            )
            # kurze Pause, damit wir zwischendurch auf Barge-In/Events reagieren
            # koennen, ohne den gesamten Puffer blockierend auf einmal zu senden
            await asyncio.sleep(0)

    async def _send_clear(self) -> None:
        await self.ws.send_text(json.dumps({"event": "clear", "streamSid": self.stream_sid}))

    # --- Zuhoeren (WebSocket -> mu-law -> PCM16 -> STT) -------------------

    async def _listen_for_utterance(self) -> str:
        self._inbound_buffer = []
        self._endpoint.reset()
        loop = asyncio.get_event_loop()
        deadline = loop.time() + self.max_utterance_seconds

        while loop.time() < deadline:
            try:
                raw = await asyncio.wait_for(self.ws.receive_text(), timeout=deadline - loop.time())
            except TimeoutError:
                break
            msg = json.loads(raw)
            event = msg.get("event")

            if event == "media":
                pcm = mulaw_to_pcm16(base64.b64decode(msg["media"]["payload"]))
                self._inbound_buffer.append(pcm)
                if self._process_vad_frames(pcm):
                    break
            elif event == "stop":
                self.dario.call_active = False
                break
            elif event == "mark":
                continue

        if not self._inbound_buffer:
            return ""

        full_pcm_8k = np.concatenate(self._inbound_buffer)
        pcm_16k = resample_pcm16(full_pcm_8k, TWILIO_SAMPLE_RATE, STT_SAMPLE_RATE)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name
        try:
            write_wav(wav_path, pcm_16k.tobytes(), sample_rate=STT_SAMPLE_RATE)
            result = await self.stt.transcribe(wav_path)
            return result.text
        finally:
            Path(wav_path).unlink(missing_ok=True)

    def _process_vad_frames(self, new_pcm_8k: np.ndarray) -> bool:
        """Speist neue 8kHz-Samples framegenau in die VAD/Endpoint-Erkennung
        (die auf 16kHz/30ms-Frames ausgelegt ist) und meldet True, sobald ein
        Sprechende erkannt wurde. Loest ausserdem Barge-In aus, falls Dario
        gerade selbst spricht."""
        pcm_16k = resample_pcm16(new_pcm_8k, TWILIO_SAMPLE_RATE, STT_SAMPLE_RATE)
        combined = np.concatenate([self._vad_carry, pcm_16k])

        frame_len = int(STT_SAMPLE_RATE * VAD_FRAME_MS / 1000)
        n_frames = len(combined) // frame_len
        endpoint_hit = False

        for i in range(n_frames):
            frame = combined[i * frame_len : (i + 1) * frame_len]
            is_speech = self._vad.is_speech(frame.tobytes(), STT_SAMPLE_RATE)
            if is_speech and self._speaking:
                self._barge_in_event.set()
            if self._endpoint.process_frame(is_speech):
                endpoint_hit = True

        self._vad_carry = combined[n_frames * frame_len :]
        return endpoint_hit

    async def _hangup_real_call(self) -> None:
        """Beendet den ECHTEN Telefonanruf ueber die Twilio-API, wenn Dario
        das Gespraech regulaer beendet hat (end_call ist real, Abschnitt 5
        der Projektregeln - kein reines Setzen eines State-Feldes)."""
        if not self.call_sid:
            return
        try:
            await asyncio.get_event_loop().run_in_executor(
                None, self.twilio_provider.end_call, self.call_sid
            )
        except Exception:
            logger.exception("Konnte Twilio-Call %s nicht beenden", self.call_sid)

    async def _on_session_end(self) -> None:
        if self.dario.call_active:
            # Verbindung brach ab, bevor Dario das Gespraech regulaer beendet hat
            await self.call_service.hangup(self.call_id, result="UNKNOWN")
