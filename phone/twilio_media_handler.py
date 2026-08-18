"""TwilioMediaStreamSession: bruecke zwischen Twilios bidirektionaler
Media-Stream-WebSocket (G.711 mu-law, 8kHz) und Darios bestehender
STT -> Conversation Engine -> TTS Pipeline.

Nutzt ausschliesslich die bereits vorhandene Fassade agent/dario.py::Dario -
die Gespraechslogik selbst wird hier nicht angefasst, nur an einen neuen
Audio-Transport angebunden (genau wie phone/call_controller.py es fuer
Asterisk tut, nur turn-basiert statt Stream-basiert).

Architektur (wichtig fuer Barge-In): ein einzelner, durchgehend laufender
Empfangs-Task liest die WebSocket fuer die GESAMTE Session-Dauer, nicht nur
waehrend wir "zuhoeren". Nur so kann waehrend Darios eigener TTS-Ausgabe
gleichzeitig auf eingehende Anrufer-Sprache geprueft werden. Eine fruehere
Version las eingehende Nachrichten nur innerhalb der Zuhoer-Phase - Barge-In
konnte dadurch faktisch nie ausgeloest werden.

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
        wait_timeout_seconds: int = 25,
        greeting_audio_path: str | None = None,
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
        # Nur relevant, wenn der Kunde explizit um eine Wartepause gebeten
        # hat (ConversationContext.wait_mode) - siehe Dario.check_wait_timeout.
        self.wait_timeout_seconds = wait_timeout_seconds
        self.greeting_audio_path = greeting_audio_path

        # Werden ueblicherweise vom Aufrufer schon aus dem "start"-Event
        # herausgelesen uebergeben (siehe api/twilio.py), da dort auch die
        # call_id daraus bestimmt werden muss (Twilio reicht Query-Parameter
        # in der Stream-URL nicht zuverlaessig durch - Fehler 31920).
        self.stream_sid: str | None = stream_sid
        self.call_sid: str | None = twilio_call_sid

        self._vad = VoiceActivityDetector(aggressiveness=2)
        self._endpoint = EndpointDetector(EndpointConfig(silence_timeout_ms=silence_timeout_ms))
        self._vad_carry = np.array([], dtype=np.int16)  # Rest-Samples < einem VAD-Frame

        self._speaking = False
        self._barge_in_enabled = False
        self._listening = False
        self._barge_in_event = asyncio.Event()

        # Vom durchgehenden Empfangs-Task befuellt, von _listen_for_utterance
        # konsumiert - entkoppelt Lesen (immer aktiv) von Verarbeiten
        # (nur waehrend der Zuhoer-Phase).
        self._current_utterance: list[np.ndarray] = []
        self._utterance_ready = asyncio.Event()
        self._receiver_task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    # --- Hauptschleife -------------------------------------------------

    async def run(self) -> None:
        try:
            if self.stream_sid is None:
                await self._wait_for_start()
            else:
                await self.call_service.mark_answered(self.call_id)

            self._receiver_task = asyncio.create_task(self._receive_loop())

            opening = self.dario.opening_line()
            logger.info(
                "[GREETING] starting call_id=%s streamSid=%s callSid=%s",
                self.call_id,
                self.stream_sid,
                self.call_sid,
            )
            await self._speak(
                opening,
                wav_path=self.greeting_audio_path,
                label="greeting",
                allow_barge_in=False,
            )
            logger.info(
                "[GREETING] finished call_id=%s streamSid=%s stopped=%s",
                self.call_id,
                self.stream_sid,
                self._stopped.is_set(),
            )

            while self.dario.call_active and not self._stopped.is_set():
                text = await self._listen_for_utterance()
                if self._stopped.is_set():
                    break
                if not text:
                    # Stille: nur relevant, falls der Kunde zuvor explizit um
                    # eine Wartepause gebeten hat (siehe Dario.check_wait_timeout) -
                    # ausserhalb des Wait-Mode liefert dies immer None.
                    timeout_outcome = await self.dario.check_wait_timeout(self.wait_timeout_seconds)
                    if timeout_outcome is not None:
                        if timeout_outcome.reply_text:
                            await self._speak(timeout_outcome.reply_text)
                        if timeout_outcome.call_ended:
                            await self._hangup_real_call()
                            break
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
            if self._receiver_task is not None:
                self._receiver_task.cancel()
                try:
                    await self._receiver_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("Fehler beim Beenden des Empfangs-Tasks (Call %s)", self.call_id)
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

    # --- Durchgehender Empfang (laeuft parallel zur gesamten Session) ----

    async def _receive_loop(self) -> None:
        """Liest die WebSocket ununterbrochen, solange die Session laeuft -
        unabhaengig davon, ob Dario gerade spricht oder zuhoert. Nur so kann
        Barge-In waehrend Darios eigener Ausgabe erkannt werden."""
        try:
            while True:
                raw = await self.ws.receive_text()
                msg = json.loads(raw)
                event = msg.get("event")

                if event == "media":
                    pcm_8k = mulaw_to_pcm16(base64.b64decode(msg["media"]["payload"]))
                    endpoint_hit = self._process_vad_frames(pcm_8k)
                    if self._listening:
                        self._current_utterance.append(pcm_8k)
                        if endpoint_hit:
                            self._utterance_ready.set()
                elif event == "stop":
                    self.dario.call_active = False
                    self._stopped.set()
                    self._utterance_ready.set()
                    return
                elif event == "mark":
                    continue
        except WebSocketDisconnect:
            self._stopped.set()
            self._utterance_ready.set()
        except asyncio.CancelledError:
            raise
        except Exception:
            self._stopped.set()
            self._utterance_ready.set()
            logger.exception("Fehler im Twilio-Empfangs-Task (Call %s)", self.call_id)

    def _process_vad_frames(self, new_pcm_8k: np.ndarray) -> bool:
        """Speist neue 8kHz-Samples framegenau in die VAD/Endpoint-Erkennung
        (die auf 16kHz/30ms-Frames ausgelegt ist). Laeuft fuer JEDEN
        eingehenden Frame, unabhaengig vom Zuhoer-Status: so kann Barge-In
        auch waehrend Darios Ausgabe erkannt werden. Die Endpoint-Erkennung
        (Sprechende) zaehlt nur, wenn wir gerade aktiv zuhoeren."""
        pcm_16k = resample_pcm16(new_pcm_8k, TWILIO_SAMPLE_RATE, STT_SAMPLE_RATE)
        combined = np.concatenate([self._vad_carry, pcm_16k])

        frame_len = int(STT_SAMPLE_RATE * VAD_FRAME_MS / 1000)
        n_frames = len(combined) // frame_len
        endpoint_hit = False

        for i in range(n_frames):
            frame = combined[i * frame_len : (i + 1) * frame_len]
            is_speech = self._vad.is_speech(frame.tobytes(), STT_SAMPLE_RATE)
            if is_speech and self._speaking and self._barge_in_enabled:
                self._barge_in_event.set()
            if self._listening and self._endpoint.process_frame(is_speech):
                endpoint_hit = True

        self._vad_carry = combined[n_frames * frame_len :]
        return endpoint_hit

    # --- Sprechen (TTS -> mu-law -> WebSocket) ---------------------------

    async def _speak(
        self,
        text: str,
        wav_path: str | None = None,
        label: str = "tts",
        allow_barge_in: bool = True,
    ) -> None:
        if self._stopped.is_set():
            return

        if wav_path is not None:
            size = Path(wav_path).stat().st_size if Path(wav_path).exists() else 0
            logger.info(
                "[TTS] generation started call_id=%s label=%s source=cache",
                self.call_id,
                label,
            )
            logger.info(
                "[TTS] generation finished bytes=%s call_id=%s label=%s source=cache",
                size,
                self.call_id,
                label,
            )
            await self._stream_wav_file(wav_path, allow_barge_in=allow_barge_in)
            return

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            generated_wav_path = tmp.name
        try:
            logger.info(
                "[TTS] generation started call_id=%s label=%s provider=%s chars=%s",
                self.call_id,
                label,
                type(self.tts).__name__,
                len(text),
            )
            await self.tts.synthesize(text, generated_wav_path)
            size = Path(generated_wav_path).stat().st_size
            logger.info(
                "[TTS] generation finished bytes=%s call_id=%s label=%s",
                size,
                self.call_id,
                label,
            )
            if self._stopped.is_set():
                return
            await self._stream_wav_file(generated_wav_path, allow_barge_in=allow_barge_in)
        finally:
            Path(generated_wav_path).unlink(missing_ok=True)

    async def _stream_wav_file(self, wav_path: str, allow_barge_in: bool = True) -> None:
        import soundfile as sf

        if self.stream_sid is None:
            raise RuntimeError("Kann Audio ohne streamSid nicht an Twilio senden.")

        logger.info(
            "[AUDIO] sending to Twilio call_id=%s streamSid=%s wav_bytes=%s",
            self.call_id,
            self.stream_sid,
            Path(wav_path).stat().st_size if Path(wav_path).exists() else 0,
        )

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

        loop = asyncio.get_event_loop()
        next_send = loop.time()
        frame_seconds = FRAME_MS / 1000
        chunks_sent = 0

        self._barge_in_event.clear()
        self._barge_in_enabled = allow_barge_in
        self._speaking = True
        try:
            for i in range(0, len(mulaw), FRAME_SAMPLES_8K):
                if self._stopped.is_set():
                    break
                if self._barge_in_event.is_set():
                    logger.info(
                        "[AUDIO] barge-in clear call_id=%s streamSid=%s chunks_sent=%s",
                        self.call_id,
                        self.stream_sid,
                        chunks_sent,
                    )
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
                chunks_sent += 1
                # In Echtzeit-Kadenz senden (statt alles auf einmal): nur so
                # bleibt waehrend der Wiedergabe ein tatsaechliches Zeitfenster,
                # in dem Barge-In die restliche, noch nicht gesendete Antwort
                # abbrechen kann, bevor sie beim Anrufer ankommt.
                next_send += frame_seconds
                delay = next_send - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
        finally:
            self._speaking = False
            self._barge_in_enabled = False
            self._barge_in_event.clear()
            logger.info(
                "[AUDIO] chunks sent=%s call_id=%s streamSid=%s",
                chunks_sent,
                self.call_id,
                self.stream_sid,
            )

    async def _send_clear(self) -> None:
        await self.ws.send_text(json.dumps({"event": "clear", "streamSid": self.stream_sid}))

    # --- Zuhoeren (aus der vom Empfangs-Task befuellten Warteschlange) ----

    async def _listen_for_utterance(self) -> str:
        self._current_utterance = []
        self._endpoint.reset()
        self._utterance_ready.clear()
        self._listening = True
        try:
            try:
                await asyncio.wait_for(
                    self._utterance_ready.wait(), timeout=self.max_utterance_seconds
                )
            except TimeoutError:
                pass
        finally:
            self._listening = False

        if self._stopped.is_set() or not self._current_utterance:
            return ""

        full_pcm_8k = np.concatenate(self._current_utterance)
        pcm_16k = resample_pcm16(full_pcm_8k, TWILIO_SAMPLE_RATE, STT_SAMPLE_RATE)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name
        try:
            write_wav(wav_path, pcm_16k.tobytes(), sample_rate=STT_SAMPLE_RATE)
            result = await self.stt.transcribe(wav_path)
            return result.text
        finally:
            Path(wav_path).unlink(missing_ok=True)

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
