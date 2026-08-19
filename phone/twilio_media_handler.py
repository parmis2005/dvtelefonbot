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
import enum
import json
import tempfile
import time
from pathlib import Path

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

from agent.dario import Dario
from core.logging import get_logger
from phone.twilio_voice import TwilioProvider
from services.call_service import CallService
from services.tts_cache import get_cached_tts
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
MIN_STT_SPEECH_MS = 120  # kurze Antworten wie "ja" duerfen nicht weggefiltert werden


class MediaSessionState(str, enum.Enum):
    INITIALIZING = "INITIALIZING"
    CONNECTED = "CONNECTED"
    SPEAKING = "SPEAKING"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    WAITING = "WAITING"
    ENDING = "ENDING"
    ENDED = "ENDED"
    ERROR = "ERROR"


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
        opening_text: str | None = None,
        audio_debug_dir: str | None = None,
        require_vad_speech_for_stt: bool = True,
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
        self.opening_text = opening_text
        self.audio_debug_dir = Path(audio_debug_dir) if audio_debug_dir else None
        self.require_vad_speech_for_stt = require_vad_speech_for_stt

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
        self._state = MediaSessionState.INITIALIZING
        self._playback_started_at: float | None = None
        self._barge_in_speech_ms = 0
        self._last_speech_active = False
        self._speech_started_at: float | None = None
        self._speech_ended_at: float | None = None
        self._last_stt_finished_at: float | None = None
        self._listen_speech_ms = 0

        # Vom durchgehenden Empfangs-Task befuellt, von _listen_for_utterance
        # konsumiert - entkoppelt Lesen (immer aktiv) von Verarbeiten
        # (nur waehrend der Zuhoer-Phase).
        self._current_utterance: list[np.ndarray] = []
        self._utterance_ready = asyncio.Event()
        self._last_listen_end_reason = "unknown"
        self._receiver_task: asyncio.Task | None = None
        self._tts_warmup_task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    def _set_state(self, state: MediaSessionState) -> None:
        if self._state == state:
            return
        previous = self._state
        self._state = state
        logger.info(
            "[STATE] %s -> %s call_id=%s streamSid=%s callSid=%s",
            previous.value,
            state.value,
            self.call_id,
            self.stream_sid,
            self.call_sid,
        )

    def _log_latency(
        self, metric: str, started_at: float | None, ended_at: float | None = None
    ) -> None:
        if started_at is None:
            return
        end = ended_at if ended_at is not None else time.perf_counter()
        logger.info(
            "[LATENCY] %s=%.0fms call_id=%s",
            metric,
            (end - started_at) * 1000,
            self.call_id,
        )

    # --- Hauptschleife -------------------------------------------------

    async def run(self) -> None:
        try:
            if self.stream_sid is None:
                await self._wait_for_start()
            else:
                await self.call_service.mark_answered(self.call_id)
            logger.info(
                "[CALL] answered call_id=%s streamSid=%s callSid=%s",
                self.call_id,
                self.stream_sid,
                self.call_sid,
            )
            self._set_state(MediaSessionState.CONNECTED)

            self._receiver_task = asyncio.create_task(self._receive_loop())
            self._tts_warmup_task = asyncio.create_task(self._warm_tts_provider())

            opening = self.opening_text or self.dario.opening_line()
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
                            self._set_state(MediaSessionState.ENDING)
                            await self._hangup_real_call()
                            break
                        continue
                    no_response_outcome = await self.dario.handle_no_response()
                    if no_response_outcome is not None:
                        if no_response_outcome.reply_text:
                            await self._speak(no_response_outcome.reply_text)
                        if no_response_outcome.call_ended:
                            self._set_state(MediaSessionState.ENDING)
                            await self._hangup_real_call()
                            break
                    continue
                llm_started_at = time.perf_counter()
                logger.info(
                    "[LLM] response started call_id=%s text_chars=%s",
                    self.call_id,
                    len(text),
                )
                self._set_state(MediaSessionState.THINKING)
                outcome = await self.dario.process_utterance(text)
                llm_finished_at = time.perf_counter()
                logger.info(
                    "[LLM] response finished call_id=%s reply_chars=%s",
                    self.call_id,
                    len(outcome.reply_text or ""),
                )
                self._log_latency(
                    "stt_final_to_llm_first_token",
                    self._last_stt_finished_at,
                    llm_finished_at,
                )
                if outcome.reply_text:
                    await self._speak(
                        outcome.reply_text,
                        llm_started_at=llm_started_at,
                    )
                if outcome.call_ended:
                    self._set_state(MediaSessionState.ENDING)
                    await self._hangup_real_call()
                    break
        except WebSocketDisconnect:
            logger.info("Twilio Media Stream getrennt (Call %s)", self.call_id)
        except Exception:
            self._set_state(MediaSessionState.ERROR)
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
            if self._tts_warmup_task is not None:
                if not self._tts_warmup_task.done():
                    self._tts_warmup_task.cancel()
                try:
                    await self._tts_warmup_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    logger.exception("Fehler beim Beenden des TTS-Warmups (Call %s)", self.call_id)
            await self._on_session_end()
            self._set_state(MediaSessionState.ENDED)

    async def _warm_tts_provider(self) -> None:
        warmup = getattr(self.tts, "warmup", None)
        if not callable(warmup):
            return
        try:
            logger.info("[TTS] warmup started call_id=%s provider=%s", self.call_id, type(self.tts).__name__)
            await warmup()
            logger.info("[TTS] warmup finished call_id=%s provider=%s", self.call_id, type(self.tts).__name__)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("[TTS] warmup failed call_id=%s provider=%s", self.call_id, type(self.tts).__name__)

    async def _wait_for_start(self) -> None:
        while True:
            raw = await self.ws.receive_text()
            msg = json.loads(raw)
            if msg.get("event") == "start":
                self.stream_sid = msg["start"]["streamSid"]
                self.call_sid = msg["start"].get("callSid")
                logger.info(
                    "[WS] start received streamSid=%s callSid=%s",
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
                            self._last_listen_end_reason = "endpoint"
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
            speech_rms = (
                float(np.sqrt(np.mean(frame.astype(np.float64) ** 2))) if len(frame) else 0.0
            )
            is_relevant_speech = is_speech and speech_rms >= 350.0

            if self._listening:
                now = time.perf_counter()
                if is_relevant_speech and not self._last_speech_active:
                    self._speech_started_at = now
                    self._speech_ended_at = None
                    logger.info(
                        "[VAD] speech started call_id=%s streamSid=%s rms=%.0f",
                        self.call_id,
                        self.stream_sid,
                        speech_rms,
                    )
                elif not is_relevant_speech and self._last_speech_active:
                    self._speech_ended_at = now
                    logger.info(
                        "[VAD] speech ended call_id=%s streamSid=%s",
                        self.call_id,
                        self.stream_sid,
                    )
                self._last_speech_active = is_relevant_speech
                if is_relevant_speech:
                    self._listen_speech_ms += VAD_FRAME_MS

            if self._speaking and self._barge_in_enabled:
                playback_ms = (
                    (time.perf_counter() - self._playback_started_at) * 1000
                    if self._playback_started_at is not None
                    else 0.0
                )
                if is_relevant_speech and playback_ms >= 250:
                    self._barge_in_speech_ms += VAD_FRAME_MS
                else:
                    self._barge_in_speech_ms = 0

                if self._barge_in_speech_ms >= 120 and not self._barge_in_event.is_set():
                    logger.info(
                        "[BARGE_IN] detected call_id=%s streamSid=%s speech_ms=%s rms=%.0f playback_ms=%.0f",
                        self.call_id,
                        self.stream_sid,
                        self._barge_in_speech_ms,
                        speech_rms,
                        playback_ms,
                    )
                    self._barge_in_event.set()
            if self._listening and self._endpoint.process_frame(is_relevant_speech):
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
        llm_started_at: float | None = None,
    ) -> None:
        if self._stopped.is_set():
            return
        tts_started_at = time.perf_counter()

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
            self._log_latency("llm_start_to_tts_start", llm_started_at, tts_started_at)
            await self._stream_wav_file(
                wav_path,
                allow_barge_in=allow_barge_in,
                label=label,
                tts_started_at=tts_started_at,
            )
            return

        cached = get_cached_tts(self.tts, text, label=label)
        if cached is not None:
            logger.info(
                "[TTS] generation started call_id=%s label=%s source=cache",
                self.call_id,
                label,
            )
            logger.info(
                "[TTS] generation finished bytes=%s call_id=%s label=%s source=cache",
                cached.bytes,
                self.call_id,
                label,
            )
            self._log_latency("llm_start_to_tts_start", llm_started_at, tts_started_at)
            await self._stream_wav_file(
                str(cached.path),
                allow_barge_in=allow_barge_in,
                label=label,
                tts_started_at=tts_started_at,
            )
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
            self._log_latency("llm_start_to_tts_start", llm_started_at, tts_started_at)
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
            await self._stream_wav_file(
                generated_wav_path,
                allow_barge_in=allow_barge_in,
                label=label,
                tts_started_at=tts_started_at,
            )
        finally:
            Path(generated_wav_path).unlink(missing_ok=True)

    async def _stream_wav_file(
        self,
        wav_path: str,
        allow_barge_in: bool = True,
        label: str = "tts",
        tts_started_at: float | None = None,
    ) -> None:
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
        self._write_audio_debug(mulaw, label=label)

        loop = asyncio.get_event_loop()
        next_send = loop.time()
        frame_seconds = FRAME_MS / 1000
        chunks_sent = 0

        if not allow_barge_in:
            self._barge_in_event.clear()
        self._barge_in_speech_ms = 0
        self._playback_started_at = time.perf_counter()
        self._barge_in_enabled = allow_barge_in
        self._speaking = True
        self._set_state(MediaSessionState.SPEAKING)
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
                if chunks_sent == 1:
                    logger.info(
                        "[TTS] first audio ready call_id=%s label=%s source_wav=%s",
                        self.call_id,
                        label,
                        Path(wav_path).name,
                    )
                    logger.info(
                        "[AUDIO] first chunk sent call_id=%s streamSid=%s label=%s",
                        self.call_id,
                        self.stream_sid,
                        label,
                    )
                    self._log_latency("tts_start_to_first_audio_sent", tts_started_at)
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
            self._barge_in_speech_ms = 0
            self._playback_started_at = None
            logger.info(
                "[AUDIO] chunks sent=%s call_id=%s streamSid=%s",
                chunks_sent,
                self.call_id,
                self.stream_sid,
            )
            logger.info(
                "[AUDIO] playback complete call_id=%s streamSid=%s label=%s",
                self.call_id,
                self.stream_sid,
                label,
            )

    def _write_audio_debug(self, mulaw: np.ndarray, label: str) -> None:
        if self.audio_debug_dir is None:
            return
        try:
            self.audio_debug_dir.mkdir(parents=True, exist_ok=True)
            safe_label = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in label)
            stream_suffix = (self.stream_sid or "nostream")[-8:]
            path = (
                self.audio_debug_dir
                / f"call_{self.call_id}_{stream_suffix}_{safe_label}_twilio_decoded.wav"
            )
            decoded_pcm = mulaw_to_pcm16(mulaw)
            write_wav(str(path), decoded_pcm.tobytes(), sample_rate=TWILIO_SAMPLE_RATE)
            logger.info("[AUDIO] debug wav written call_id=%s path=%s", self.call_id, path)
        except Exception:
            logger.exception("[AUDIO] debug wav failed call_id=%s label=%s", self.call_id, label)

    async def _send_clear(self) -> None:
        await self.ws.send_text(json.dumps({"event": "clear", "streamSid": self.stream_sid}))

    # --- Zuhoeren (aus der vom Empfangs-Task befuellten Warteschlange) ----

    async def _listen_for_utterance(self) -> str:
        self._current_utterance = []
        self._endpoint.reset()
        self._utterance_ready.clear()
        self._last_listen_end_reason = "timeout"
        self._last_speech_active = False
        self._speech_started_at = None
        self._speech_ended_at = None
        self._listen_speech_ms = 0
        self._listening = True
        self._set_state(
            MediaSessionState.WAITING if self.dario.context.wait_mode else MediaSessionState.LISTENING
        )
        logger.info(
            "[LISTEN] started call_id=%s streamSid=%s max_seconds=%.1f",
            self.call_id,
            self.stream_sid,
            self.max_utterance_seconds,
        )
        try:
            try:
                await asyncio.wait_for(
                    self._utterance_ready.wait(), timeout=self.max_utterance_seconds
                )
            except TimeoutError:
                pass
        finally:
            self._listening = False
            if self._last_speech_active:
                self._speech_ended_at = time.perf_counter()
                self._last_speech_active = False
                logger.info(
                    "[VAD] speech ended call_id=%s streamSid=%s",
                    self.call_id,
                    self.stream_sid,
                )

        if self._stopped.is_set() or not self._current_utterance:
            logger.info(
                "[LISTEN] finished call_id=%s streamSid=%s reason=%s frames=%s text=none",
                self.call_id,
                self.stream_sid,
                "stopped" if self._stopped.is_set() else self._last_listen_end_reason,
                len(self._current_utterance),
            )
            return ""

        if self.require_vad_speech_for_stt and self._listen_speech_ms < MIN_STT_SPEECH_MS:
            logger.info(
                "[LISTEN] finished call_id=%s streamSid=%s reason=no_vad_speech frames=%s speech_ms=%s text=none",
                self.call_id,
                self.stream_sid,
                len(self._current_utterance),
                self._listen_speech_ms,
            )
            return ""

        full_pcm_8k = np.concatenate(self._current_utterance)
        pcm_16k = resample_pcm16(full_pcm_8k, TWILIO_SAMPLE_RATE, STT_SAMPLE_RATE)
        duration_seconds = len(full_pcm_8k) / TWILIO_SAMPLE_RATE
        logger.info(
            "[LISTEN] finished call_id=%s streamSid=%s reason=%s frames=%s duration=%.2fs",
            self.call_id,
            self.stream_sid,
            self._last_listen_end_reason,
            len(self._current_utterance),
            duration_seconds,
        )

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name
        try:
            write_wav(wav_path, pcm_16k.tobytes(), sample_rate=STT_SAMPLE_RATE)
            logger.info(
                "[STT] transcription started call_id=%s audio_seconds=%.2f",
                self.call_id,
                duration_seconds,
            )
            result = await self.stt.transcribe(wav_path)
            self._last_stt_finished_at = time.perf_counter()
            logger.info(
                "[STT] transcription finished call_id=%s chars=%s text=%r",
                self.call_id,
                len(result.text),
                result.text[:160],
            )
            self._log_latency(
                "speech_end_to_stt_final",
                self._speech_ended_at,
                self._last_stt_finished_at,
            )
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
            logger.info("[CALL] ending call_id=%s callSid=%s", self.call_id, self.call_sid)
            await asyncio.get_event_loop().run_in_executor(
                None, self.twilio_provider.end_call, self.call_sid
            )
            logger.info("[CALL] ended call_id=%s callSid=%s", self.call_id, self.call_sid)
        except Exception:
            logger.exception("Konnte Twilio-Call %s nicht beenden", self.call_sid)

    async def _on_session_end(self) -> None:
        if self.dario.call_active:
            # Verbindung brach ab, bevor Dario das Gespraech regulaer beendet hat
            await self.dario.persist_partial_call(result="UNKNOWN")
            await self.call_service.hangup(self.call_id, result="UNKNOWN")
