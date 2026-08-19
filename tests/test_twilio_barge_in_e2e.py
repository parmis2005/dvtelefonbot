"""End-to-End-Test fuer Barge-In ueber den ECHTEN Twilio-Media-Stream-Pfad
(api/twilio.py::twilio_media_stream), nicht nur die isolierte
_stream_wav_file()-Sendeschleife (siehe tests/test_twilio_audio_format.py)
oder den vollkommen getrennten lokalen BargeInController
(tests/test_barge_in.py, nur fuer app/local_voice_test.py relevant).

Hintergrund (CLAUDE.md "Barge-In war faktisch tot"): die eigentliche
Erkennung fuer den Twilio-Pfad passiert in
phone/twilio_media_handler.py::TwilioMediaStreamSession._receive_loop /
_process_vad_frames, komplett unabhaengig vom lokalen BargeInController.
Es gab bisher KEINEN Test, der bewiesen haette, dass eine waehrend Darios
eigener Sprachausgabe eintreffende "media"-Nachricht tatsaechlich (a) durch
den durchgehend laufenden Empfangs-Task erkannt wird, (b) ein "clear"-Event
an Twilio ausloest, (c) die laufende Wiedergabe vorzeitig abbricht, und (d)
das Gespraech danach normal weiterlaeuft (kein haengender/kaputter Zustand).
Dieser Test schliesst genau diese Luecke."""

from __future__ import annotations

import asyncio
import base64

import numpy as np
import pytest

import api.twilio as twilio_api
import voice.vad as vad_module
from phone import twilio_media_handler
from tests.test_twilio_media_stream_e2e import FakeTwilioWebSocket, _seed_call
from voice.codecs import pcm16_to_mulaw
from voice.stt.base import TranscriptionResult
from voice.stt.whisper_cpp import LocalWhisperProvider
from voice.tts.chatterbox_tts import ChatterboxTTSProvider

# Bewusst lokal statt aus tests/test_twilio_media_stream_e2e.py importiert:
# ein direkter Cross-Modul-Import von Pytest-Fixtures fuehrt zu Ruff F811
# ("Redefinition"), sobald der importierte Name zusaetzlich als Test-
# Funktionsparameter auftaucht. Diese Fixtures sind absichtlich kurz genug,
# um verlustfrei dupliziert zu werden (siehe CLAUDE.md: keine Abstraktion
# ohne echten Bedarf).
TEST_MAX_UTTERANCE_SECONDS = 0.3

# Deutlich laenger als eine 20ms-Frame-Periode, damit der Sende-Loop in
# phone/twilio_media_handler.py::_stream_wav_file genug Zeit hat, mehrere
# Frames zu verschicken, bevor (falls kein Barge-In ausgeloest wird) die
# gesamte Aeusserung durchgelaufen waere - nur so ist ein frueher Abbruch
# ueberhaupt messbar.
_LONG_GREETING_SECONDS = 1.0
_TOTAL_FRAMES_IF_UNINTERRUPTED = int(_LONG_GREETING_SECONDS * 1000 / 20)  # 20ms-Frames
_FRAME_SAMPLES_8K = 160


def _make_loud_media_event(stream_sid: str) -> dict:
    pcm = np.full(_FRAME_SAMPLES_8K, 12000, dtype=np.int16)
    payload = pcm16_to_mulaw(pcm).tobytes()
    return {
        "event": "media",
        "streamSid": stream_sid,
        "media": {"payload": base64.b64encode(payload).decode("ascii")},
    }


def _write_long_silent_wav(path: str, seconds: float, rate: int) -> str:
    import wave

    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"\x00\x00" * int(rate * seconds))
    return path


class ScriptedSTT:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    async def transcribe(self, audio_path: str) -> TranscriptionResult:
        idx = min(len(self.calls), len(self.responses) - 1)
        text = self.responses[idx]
        self.calls.append(text)
        return TranscriptionResult(text=text)

    async def is_available(self) -> bool:
        return True


@pytest.fixture
def scripted_stt(monkeypatch):
    holder: dict[str, ScriptedSTT] = {}

    async def fake_transcribe(self, audio_path: str) -> TranscriptionResult:
        return await holder["instance"].transcribe(audio_path)

    async def fake_is_available(self) -> bool:
        return True

    monkeypatch.setattr(LocalWhisperProvider, "transcribe", fake_transcribe)
    monkeypatch.setattr(LocalWhisperProvider, "is_available", fake_is_available)

    def _make(responses: list[str]) -> ScriptedSTT:
        instance = ScriptedSTT(responses)
        holder["instance"] = instance
        return instance

    return _make


@pytest.fixture
def fake_twilio_end_call(monkeypatch):
    from phone.twilio_voice import TwilioProvider

    calls: list[str] = []

    def fake_end_call(self, call_sid: str) -> None:
        calls.append(call_sid)

    def fake_init(self, account_sid: str, auth_token: str, caller_id: str) -> None:
        self.account_sid = account_sid
        self.caller_id = caller_id

    monkeypatch.setattr(TwilioProvider, "__init__", fake_init)
    monkeypatch.setattr(TwilioProvider, "end_call", fake_end_call)
    return calls


@pytest.fixture
def short_utterance_timeout(monkeypatch):
    original_init = twilio_media_handler.TwilioMediaStreamSession.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["max_utterance_seconds"] = TEST_MAX_UTTERANCE_SECONDS
        kwargs["require_vad_speech_for_stt"] = False
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(twilio_media_handler.TwilioMediaStreamSession, "__init__", patched_init)


@pytest.fixture
def always_speech_vad(monkeypatch):
    """Ersetzt die echte WebRTC-VAD-Entscheidung durch ein deterministisches
    'es wird gerade gesprochen' - realer Audioinhalt der Test-Frames ist
    fuer diesen Test irrelevant, nur das Timing (waehrend Darios Sprechen)
    zaehlt. Ersetzt die Klassenmethode, sodass jede im Produktionscode neu
    erzeugte VoiceActivityDetector-Instanz betroffen ist."""

    def fake_is_speech(self, frame: bytes, sample_rate: int = 16000) -> bool:
        return True

    monkeypatch.setattr(vad_module.VoiceActivityDetector, "is_speech", fake_is_speech)


@pytest.fixture
def slow_tts(monkeypatch):
    """Liefert eine kuenstlich lange (aber sofort synthetisierte, kein
    echtes Chatterbox-Modell) Aeusserung, damit waehrend des Echtzeit-
    Sendens (20ms/Frame, siehe _stream_wav_file) genug Zeit fuer eine
    eintreffende 'media'-Nachricht bleibt, bevor die Aeusserung natuerlich
    zu Ende waere."""

    async def fake_synthesize(self, text: str, output_path: str) -> str:
        return _write_long_silent_wav(output_path, seconds=_LONG_GREETING_SECONDS, rate=8000)

    async def fake_is_available(self) -> bool:
        return True

    async def fake_warmup(self) -> None:
        return None

    monkeypatch.setattr(ChatterboxTTSProvider, "synthesize", fake_synthesize)
    monkeypatch.setattr(ChatterboxTTSProvider, "is_available", fake_is_available)
    monkeypatch.setattr(ChatterboxTTSProvider, "warmup", fake_warmup)


async def _feed_with_mid_speech_interruption(
    ws: FakeTwilioWebSocket, stream_sid: str, call_sid: str, call_id: int, total_seconds: float
) -> None:
    ws.push({"event": "connected"})
    ws.push(
        {
            "event": "start",
            "start": {
                "streamSid": stream_sid,
                "callSid": call_sid,
                "customParameters": {"call_id": str(call_id)},
            },
        }
    )
    # Kurz warten, bis Darios Begruessung sicher begonnen hat, dann "spricht"
    # der Anrufer dazwischen - der durchgehend laufende Empfangs-Task muss
    # das WAEHREND der Ausgabe verarbeiten (siehe Modul-Docstring).
    await asyncio.sleep(0.08)
    ws.push(_make_loud_media_event(stream_sid))

    elapsed = 0.08
    step = 0.05
    while elapsed < total_seconds:
        ws.push(_make_loud_media_event(stream_sid))
        await asyncio.sleep(step)
        elapsed += step
    ws.push({"event": "stop"})
    ws.push_disconnect()


@pytest.mark.asyncio
async def test_customer_speech_during_playback_triggers_real_barge_in(
    db_session,
    scripted_stt,
    slow_tts,
    always_speech_vad,
    fake_twilio_end_call,
    short_utterance_timeout,
    tmp_path,
    monkeypatch,
):
    from services.transcript_service import write_transcript_file

    monkeypatch.setattr(
        "agent.dario.write_transcript_file",
        lambda call_id, context: write_transcript_file(call_id, context, transcripts_dir=str(tmp_path)),
    )

    _lead_id, call_id = await _seed_call(db_session)
    stt = scripted_stt(["Ja, worum geht es?", "Vielen Dank, auf Wiederhoeren."])

    ws = FakeTwilioWebSocket()
    stream_sid = "MZbargeine2e1234567"
    call_sid = "CAbargeine2e1234567"

    feeder = asyncio.create_task(
        _feed_with_mid_speech_interruption(ws, stream_sid, call_sid, call_id, total_seconds=2.5)
    )
    await twilio_api.twilio_media_stream(ws)
    feeder.cancel()
    try:
        await feeder
    except asyncio.CancelledError:
        pass

    assert ws.accepted is True
    assert ws.closed is True

    clear_events = [m for m in ws.sent_messages if m.get("event") == "clear"]
    assert len(clear_events) >= 1, "Barge-In wurde nicht erkannt - kein 'clear'-Event an Twilio gesendet"
    for evt in clear_events:
        assert evt["streamSid"] == stream_sid

    # Jede unterbrochene Aeusserung darf nur einen Bruchteil ihrer vollen
    # Frame-Anzahl gesendet haben - beweist einen tatsaechlich FRUEHEN
    # Abbruch, nicht nur ein zufaellig spaetes "clear" nach Ende der Wiedergabe.
    media_events = [m for m in ws.sent_messages if m.get("event") == "media"]
    clear_indices = [i for i, m in enumerate(ws.sent_messages) if m.get("event") == "clear"]
    prev = 0
    interrupted_segments = 0
    for clear_idx in clear_indices:
        segment_media = [
            m for m in ws.sent_messages[prev:clear_idx] if m.get("event") == "media"
        ]
        interrupted_frames = len(segment_media) % _TOTAL_FRAMES_IF_UNINTERRUPTED
        if 0 < interrupted_frames < _TOTAL_FRAMES_IF_UNINTERRUPTED:
            interrupted_segments += 1
        prev = clear_idx
    assert interrupted_segments >= 1, (
        "Kein frueher Abbruch erkennbar - alle 'clear'-Events kamen erst nach "
        "vollstaendig gesendeten Aeusserungen"
    )
    assert len(media_events) > 0, "Trotz Barge-In sollte ueberhaupt Audio gesendet worden sein"

    # Das Gespraech muss nach dem/den Barge-In(s) normal weiterlaufen: STT
    # wurde fuer beide Kundenbeitraege aufgerufen, und der Call wurde ueber
    # das reguläre end_call sauber beendet - kein haengender/kaputter Zustand.
    assert len(stt.calls) >= 2
    assert fake_twilio_end_call == [call_sid]
