"""Simulierter End-to-End-Test des ECHTEN Twilio-Media-Stream-Pfads
(api/twilio.py::twilio_media_stream + phone/twilio_media_handler.py::
TwilioMediaStreamSession) - OHNE echten Twilio-Anruf, echte Sprachsynthese
oder echte Spracherkennung.

Nur STT/TTS/TwilioProvider werden an der Provider-Grenze gemockt (Chatterbox
braucht ~2GB Modell + 25-30s/Aeusserung, whisper.cpp ein echtes Binary/
Modell - beides fuer die schnelle Test-Suite ungeeignet und hier nicht das,
was getestet werden soll). ALLES andere laeuft echt: Dario-Fassade,
ConversationEngine, State Machine, Guardrails, Datenbank,
app/bootstrap.py::build_app_context (inkl. Dashboard-Settings-Ueberlagerung,
siehe services/effective_settings.py), das komplette Twilio-Protokoll
(connected/start/media/stop-Events, customParameters, WebSocket-Close).

Hintergrund: ein echter Testanruf schlug mit Twilio-Fehler 11200 fehl
("Got HTTP 502 response" von ngrok) - das Backend war zum Anrufzeitpunkt
schlicht nicht erreichbar (kein Code-Fehler, siehe CLAUDE.md). Dieser Test
verifiziert den Code-Pfad selbst, unabhaengig von Infrastruktur-
Verfuegbarkeit, und haette echte Regressionen in build_app_context/
TwilioMediaStreamSession (z.B. aus der Einstellungen-Verdrahtung) erkannt.
"""

from __future__ import annotations

import asyncio
import base64
import json
import wave

import pytest
from fastapi import WebSocketDisconnect

import api.twilio as twilio_api
from database.repository import CallRepository, LeadRepository
from phone import twilio_media_handler
from phone.twilio_voice import TwilioProvider
from services.transcript_service import write_transcript_file
from tools.base import SendResult
from tools.email import SMTPEmailProvider
from voice.stt.base import TranscriptionResult
from voice.stt.whisper_cpp import LocalWhisperProvider
from voice.tts.chatterbox_tts import ChatterboxTTSProvider

# api/twilio.py laesst TwilioMediaStreamSession's max_utterance_seconds auf
# dem hartcodierten Default (20s, unabhaengig von .env) - fuer die Test-Suite
# viel zu lang, um auf dieses Timeout zu warten. In echten Gespraechen loest
# meist webrtcvads Endpoint-Erkennung viel frueher aus (siehe voice/vad.py);
# hier werden bewusst nur Stille-Frames simuliert (keine echte Sprache), das
# Listen-Ende kommt also ausschliesslich ueber dieses Timeout zustande - fuer
# den Test daher verkuerzt, um denselben Codepfad schnell zu durchlaufen.
TEST_MAX_UTTERANCE_SECONDS = 0.3

FRAME_SAMPLES_8K = 160  # phone/twilio_media_handler.py::FRAME_SAMPLES_8K
SILENCE_MULAW_BYTE = 0xFF  # G.711 mu-law Stille


def _make_media_event(stream_sid: str) -> dict:
    payload = bytes([SILENCE_MULAW_BYTE]) * FRAME_SAMPLES_8K
    return {
        "event": "media",
        "streamSid": stream_sid,
        "media": {"payload": base64.b64encode(payload).decode("ascii")},
    }


class FakeTwilioWebSocket:
    """Duck-typed Ersatz fuer Starlette/FastAPI WebSocket - dieselbe Schnitt-
    stelle (accept/receive_text/send_text/close), die api/twilio.py und
    phone/twilio_media_handler.py tatsaechlich verwenden."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self.sent_messages: list[dict] = []
        self.accepted = False
        self.closed = False
        self.close_code: int | None = None
        self.query_params: dict[str, str] = {}

    async def accept(self) -> None:
        self.accepted = True

    async def receive_text(self) -> str:
        msg = await self._queue.get()
        if msg is None:
            raise WebSocketDisconnect()
        return msg

    async def send_text(self, data: str) -> None:
        self.sent_messages.append(json.loads(data))

    async def close(self, code: int | None = None) -> None:
        self.closed = True
        self.close_code = code

    def push(self, event: dict) -> None:
        self._queue.put_nowait(json.dumps(event))

    def push_disconnect(self) -> None:
        self._queue.put_nowait(None)


async def _feed_conversation(
    ws: FakeTwilioWebSocket, stream_sid: str, call_sid: str, call_id: int, total_seconds: float
) -> None:
    """Schickt durchgehend einen kleinen 'Rauschteppich' aus Stille-Frames,
    statt Bursts exakt auf das interne Listen-Timeout der Session zu timen
    (dessen genauer Start/Ende von aussen nicht beobachtbar ist). Da die
    gemockte STT (ScriptedSTT) unabhaengig vom tatsaechlichen Audioinhalt bei
    JEDEM Aufruf einfach die naechste vorgegebene Antwort liefert, reicht es,
    dass IRGENDWELCHE Frames waehrend jedes Zuhoer-Fensters eintreffen -
    welche genau, ist unerheblich."""
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
    elapsed = 0.0
    step = 0.05
    while elapsed < total_seconds:
        ws.push(_make_media_event(stream_sid))
        await asyncio.sleep(step)
        elapsed += step
    ws.push({"event": "stop"})
    ws.push_disconnect()


async def _feed_media_only_during_greeting_generation(
    ws: FakeTwilioWebSocket, stream_sid: str, call_sid: str, call_id: int
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
    for _ in range(5):
        ws.push(_make_media_event(stream_sid))
        await asyncio.sleep(0.02)
    await asyncio.sleep(0.5)
    ws.push({"event": "stop"})
    ws.push_disconnect()


async def _feed_media_during_greeting_playback(
    ws: FakeTwilioWebSocket, stream_sid: str, call_sid: str, call_id: int
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
    await asyncio.sleep(0.05)
    for _ in range(8):
        ws.push(_make_media_event(stream_sid))
        await asyncio.sleep(0.03)
    await asyncio.sleep(1.1)
    ws.push({"event": "stop"})
    ws.push_disconnect()


def _write_minimal_wav(path: str) -> str:
    return _write_wav_frames(path, 200)  # ~9ms - haelt den Testlauf schnell


def _write_wav_frames(path: str, frames: int) -> str:
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(22050)
        f.writeframes(b"\x00\x00" * frames)
    return path


class ScriptedSTT:
    """Liefert nacheinander vorgegebene 'Kunde sagt X'-Texte, unabhaengig
    vom tatsaechlichen (stillen) Audioinhalt - die STT-Genauigkeit selbst
    ist nicht Gegenstand dieses Tests (siehe README 'Voice-Test starten')."""

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
def scripted_stt(monkeypatch) -> ScriptedSTT:
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

    return _make  # type: ignore[return-value]


@pytest.fixture
def fast_tts(monkeypatch, tmp_path):
    async def fake_synthesize(self, text: str, output_path: str) -> str:
        return _write_minimal_wav(output_path)

    async def fake_is_available(self) -> bool:
        return True

    async def fake_warmup(self) -> None:
        return None

    monkeypatch.setattr(ChatterboxTTSProvider, "synthesize", fake_synthesize)
    monkeypatch.setattr(ChatterboxTTSProvider, "is_available", fake_is_available)
    monkeypatch.setattr(ChatterboxTTSProvider, "warmup", fake_warmup)


@pytest.fixture
def fake_twilio_end_call(monkeypatch):
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
    """Erzwingt ein kurzes max_utterance_seconds (siehe Modulkommentar oben),
    unabhaengig davon, was api/twilio.py beim Konstruieren von
    TwilioMediaStreamSession uebergibt."""
    original_init = twilio_media_handler.TwilioMediaStreamSession.__init__

    def patched_init(self, *args, **kwargs):
        kwargs["max_utterance_seconds"] = TEST_MAX_UTTERANCE_SECONDS
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(twilio_media_handler.TwilioMediaStreamSession, "__init__", patched_init)


@pytest.mark.asyncio
async def test_twilio_session_uses_fast_turn_endpoint(
    db_session, scripted_stt, fake_twilio_end_call, monkeypatch
):
    captured: dict[str, float] = {}
    original_init = twilio_media_handler.TwilioMediaStreamSession.__init__

    def patched_init(self, *args, **kwargs):
        captured["silence_timeout_ms"] = kwargs["silence_timeout_ms"]
        captured["max_utterance_seconds"] = kwargs["max_utterance_seconds"]
        kwargs["max_utterance_seconds"] = TEST_MAX_UTTERANCE_SECONDS
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(twilio_media_handler.TwilioMediaStreamSession, "__init__", patched_init)
    monkeypatch.setattr(
        ChatterboxTTSProvider,
        "synthesize",
        lambda self, text, output_path: _async_return(_write_minimal_wav(output_path)),
    )
    monkeypatch.setattr(ChatterboxTTSProvider, "is_available", lambda self: _true())
    monkeypatch.setattr(ChatterboxTTSProvider, "warmup", lambda self: _async_return(None))

    _lead_id, call_id = await _seed_call(db_session)
    scripted_stt(["Ja, kein Problem.", "Vielen Dank, auf Wiederhoeren."])

    ws = FakeTwilioWebSocket()
    feeder = asyncio.create_task(
        _feed_conversation(ws, "MZfastturn", "CAfastturn", call_id, total_seconds=1.2)
    )
    await twilio_api.twilio_media_stream(ws)
    feeder.cancel()
    try:
        await feeder
    except asyncio.CancelledError:
        pass

    assert captured["silence_timeout_ms"] == 900
    assert captured["max_utterance_seconds"] <= 5.0


async def _seed_call(db_session) -> tuple[int, int]:
    lead = await LeadRepository(db_session).create(
        unternehmen="Beauty Studio Beispiel",
        ansprechpartner="Frau Mueller",
        telefonnummer="+491701234567",
        online_auftritt_geprueft=True,
        entwurf_vorhanden=True,
        entwurf_link="https://beispiel.de/entwurf",
    )
    call = await CallRepository(db_session).create(lead_id=lead.id)
    return lead.id, call.id


@pytest.mark.asyncio
async def test_full_call_greeting_turn_and_natural_farewell(
    db_session,
    scripted_stt,
    fast_tts,
    fake_twilio_end_call,
    short_utterance_timeout,
    tmp_path,
    monkeypatch,
):
    """Kompletter simulierter Ablauf: connected -> start -> Begruessung (TTS)
    -> ein echter Gespraechsbeitrag -> Verabschiedung -> echtes end_call ->
    sauberes WebSocket-Close -> Transkript/Zusammenfassung/Call-Status in
    der DB - der komplette Pfad aus CLAUDE.md Abschnitt 4 (Architektur)."""
    # _finalize_call() schreibt regulaer eine echte Transkript-Datei - fuer
    # den Test in tmp_path statt in das echte transcripts/-Verzeichnis
    # umleiten (siehe tests/test_effective_settings.py fuer denselben Grund).
    monkeypatch.setattr(
        "agent.dario.write_transcript_file",
        lambda call_id, context: write_transcript_file(call_id, context, transcripts_dir=str(tmp_path)),
    )

    _lead_id, call_id = await _seed_call(db_session)
    stt = scripted_stt(["Ja, kein Problem.", "Vielen Dank. Tschuess."])

    ws = FakeTwilioWebSocket()
    stream_sid = "MZtest1234567890"
    call_sid = "CAtest1234567890"

    feeder = asyncio.create_task(_feed_conversation(ws, stream_sid, call_sid, call_id, total_seconds=2.0))
    await twilio_api.twilio_media_stream(ws)
    # Die Session kann (z.B. durch die Verabschiedung) frueher enden, als
    # der Feeder-Task laeuft - dann muss nicht weiter auf ihn gewartet werden.
    feeder.cancel()
    try:
        await feeder
    except asyncio.CancelledError:
        pass

    assert ws.accepted is True
    assert ws.closed is True

    # Mindestens die Begruessung + eine Antwort wurden als Audio-Frames
    # gesendet (media-Events) - kein stiller/abgebrochener Call.
    media_events = [m for m in ws.sent_messages if m.get("event") == "media"]
    assert len(media_events) > 0, "Dario hat keine Audio-Frames gesendet"

    # Kein Barge-In-"clear"-Event: die reinen Stille-Frames aus _feed_conversation
    # duerfen die echte webrtcvad NICHT faelschlich als Sprache waehrend Darios
    # eigener Ausgabe erkennen (siehe CLAUDE.md "Barge-In war faktisch tot").
    assert not any(m.get("event") == "clear" for m in ws.sent_messages)

    # STT wurde tatsaechlich fuer beide Gespraechsbeitraege aufgerufen.
    assert len(stt.calls) >= 2

    # end_call ist real: TwilioProvider.end_call wurde mit der echten
    # Call-SID aufgerufen (Sicherheitsregel 5, CLAUDE.md) - kein reines
    # Setzen eines State-Feldes.
    assert fake_twilio_end_call == [call_sid]

    call = await CallRepository(db_session).get(call_id)
    assert call.status.value == "COMPLETED"
    assert call.twilio_call_sid is None or call.transcript is not None
    assert call.transcript is not None
    turns = json.loads(call.transcript)
    assert any(t["speaker"] == "dario" for t in turns)
    assert any(t["speaker"] == "kunde" for t in turns)
    assert call.summary is not None


@pytest.mark.asyncio
async def test_customer_audio_during_tts_generation_does_not_cancel_greeting(
    db_session,
    scripted_stt,
    fake_twilio_end_call,
    short_utterance_timeout,
    monkeypatch,
):
    """Regression fuer echte stille Calls: `_speaking` darf erst waehrend
    tatsaechlichem WebSocket-Playback aktiv sein. Wenn schon die Chatterbox-
    Generierung als "Sprechen" zaehlt, triggert ein fruehes "Hallo?" des
    Kunden Barge-In, bevor Dario ueberhaupt Audio gesendet hat."""

    async def delayed_synthesize(self, text: str, output_path: str) -> str:
        await asyncio.sleep(0.2)
        return _write_minimal_wav(output_path)

    monkeypatch.setattr(ChatterboxTTSProvider, "synthesize", delayed_synthesize)
    monkeypatch.setattr(ChatterboxTTSProvider, "is_available", lambda self: _true())
    monkeypatch.setattr(ChatterboxTTSProvider, "warmup", lambda self: _async_return(None))
    monkeypatch.setattr(
        twilio_media_handler.VoiceActivityDetector,
        "is_speech",
        lambda self, frame, sample_rate: True,
    )

    _lead_id, call_id = await _seed_call(db_session)
    scripted_stt([""])

    ws = FakeTwilioWebSocket()
    stream_sid = "MZspeechduringgeneration"
    call_sid = "CAspeechduringgeneration"

    feeder = asyncio.create_task(
        _feed_media_only_during_greeting_generation(ws, stream_sid, call_sid, call_id)
    )
    await twilio_api.twilio_media_stream(ws)
    feeder.cancel()
    try:
        await feeder
    except asyncio.CancelledError:
        pass

    media_events = [m for m in ws.sent_messages if m.get("event") == "media"]
    assert media_events, "Fruehe Kundengeraeusche duerfen die Begruessung nicht vorab abbrechen"
    assert not any(m.get("event") == "clear" for m in ws.sent_messages)


@pytest.mark.asyncio
async def test_customer_audio_during_greeting_playback_does_not_barge_in(
    db_session,
    scripted_stt,
    fake_twilio_end_call,
    short_utterance_timeout,
    monkeypatch,
):
    """Regression fuer den echten Call CAb0dda...: Die Begruessung wurde aus
    dem Cache gestartet, aber nach nur einem Twilio-Media-Chunk abgebrochen,
    weil eingehende Leitungsaudio/VAD sofort Barge-In ausloeste. Die erste
    Begruessung muss vollstaendig rausgehen; Barge-In ist erst fuer spaetere
    Antworten aktiv."""

    async def long_synthesize(self, text: str, output_path: str) -> str:
        return _write_wav_frames(output_path, 22050)  # ~1s

    monkeypatch.setattr(ChatterboxTTSProvider, "synthesize", long_synthesize)
    monkeypatch.setattr(ChatterboxTTSProvider, "is_available", lambda self: _true())
    monkeypatch.setattr(ChatterboxTTSProvider, "warmup", lambda self: _async_return(None))
    monkeypatch.setattr(
        twilio_media_handler.VoiceActivityDetector,
        "is_speech",
        lambda self, frame, sample_rate: True,
    )

    _lead_id, call_id = await _seed_call(db_session)
    scripted_stt([""])

    ws = FakeTwilioWebSocket()
    stream_sid = "MZspeechduringgreeting"
    call_sid = "CAspeechduringgreeting"

    feeder = asyncio.create_task(
        _feed_media_during_greeting_playback(ws, stream_sid, call_sid, call_id)
    )
    await twilio_api.twilio_media_stream(ws)
    feeder.cancel()
    try:
        await feeder
    except asyncio.CancelledError:
        pass

    media_events = [m for m in ws.sent_messages if m.get("event") == "media"]
    assert len(media_events) > 10, "Begruessung wurde direkt nach dem Start abgebrochen"
    assert not any(m.get("event") == "clear" for m in ws.sent_messages)


@pytest.mark.asyncio
async def test_full_call_website_objection_email_draft_request_and_farewell(
    db_session,
    scripted_stt,
    fast_tts,
    fake_twilio_end_call,
    short_utterance_timeout,
    tmp_path,
    monkeypatch,
):
    """Realistischer Mehrfach-Turn-Ablauf ueber den echten Twilio-Media-
    Stream-Pfad: Kunde hat schon eine Webseite und ist damit zufrieden
    (Intent.HAS_WEBSITE_SATISFIED, agent/nlu.py::_HAS_WEBSITE_SATISFIED_PATTERNS)
    -> Dario bietet den vorbereiteten Entwurf als Vergleich an
    (CallState.DESIGN_OFFER, agent/conversation.py Zeile ~189-197) -> Kunde
    moechte den Entwurf per E-Mail (Intent.CHANNEL_CHOICE_EMAIL,
    _CHANNEL_EMAIL_PATTERNS) -> Kunde nennt seine E-Mail-Adresse
    (Intent.PROVIDE_EMAIL ueber agent/nlu.py::extract_email) -> Dario
    wiederholt sie zur Kontrolle -> Kunde bestaetigt (Intent.AFFIRMATION im
    Zustand CONTACT_CAPTURE mit gesetztem contact_value_pending, Zeile
    ~229-244) -> Kunde verabschiedet sich (Intent.FAREWELL,
    _FAREWELL_PATTERNS: "auf Wiederhoeren").

    Hinweis (siehe finaler Bericht): agent/conversation.py transitioniert
    beim Bestaetigen des Kontaktwerts NIE nach CallState.SUCCESS - dieser
    Zustand ist in agent/state_machine.py als erlaubtes Ziel und in
    agent/responses.py::success_closing() als Formulierung vorbereitet, wird
    aber von keiner Stelle im Code tatsaechlich angesteuert (verifiziert per
    Grep ueber alle transition_to()-Aufrufe in agent/conversation.py/dario.py).
    Der tatsaechliche "Erfolg" dieses Ablaufs ist daher ausschliesslich ueber
    das nach aussen sichtbare Ergebnis pruefbar (Transkript/Zusammenfassung/
    Call-Status), nicht ueber den internen State - genau das prueft dieser
    Test, statt einen nie erreichbaren Zustand vorauszusetzen.
    """
    monkeypatch.setattr(
        "agent.dario.write_transcript_file",
        lambda call_id, context: write_transcript_file(call_id, context, transcripts_dir=str(tmp_path)),
    )

    # SMTPEmailProvider an der Provider-Grenze mocken (wie STT/TTS/Twilio
    # oben): ein lokal vorhandenes echtes .env mit echten SMTP-Zugangsdaten
    # darf durch diesen Test NIEMALS eine tatsaechliche E-Mail verschicken -
    # gleichzeitig soll verifiziert werden, DASS ToolExecutor.send_email
    # (tools/call_tools.py) tatsaechlich mit der vom Kunden genannten
    # Adresse aufgerufen wird (Sicherheitsregel 4, CLAUDE.md).
    sent_emails: list[dict] = []

    async def fake_send(self, to_email: str, subject: str, body: str) -> SendResult:
        sent_emails.append({"to_email": to_email, "subject": subject, "body": body})
        return SendResult(success=True, detail="gesendet (Test)")

    monkeypatch.setattr(SMTPEmailProvider, "send", fake_send)

    _lead_id, call_id = await _seed_call(db_session)
    customer_turns = [
        "Wir haben schon eine Webseite und sind eigentlich ganz zufrieden damit.",
        "Ja, schicken Sie mir das gerne per E-Mail.",
        "Meine E-Mail-Adresse ist test@example.de.",
        "Ja, das passt so.",
        "Vielen Dank, auf Wiederhoeren.",
    ]
    stt = scripted_stt(customer_turns)

    ws = FakeTwilioWebSocket()
    stream_sid = "MZtest2multi0001"
    call_sid = "CAtest2multi0001"

    feeder = asyncio.create_task(_feed_conversation(ws, stream_sid, call_sid, call_id, total_seconds=6.0))
    await twilio_api.twilio_media_stream(ws)
    feeder.cancel()
    try:
        await feeder
    except asyncio.CancelledError:
        pass

    assert ws.accepted is True
    assert ws.closed is True

    # STT wurde fuer jeden der fuenf Gespraechsbeitraege aufgerufen.
    assert len(stt.calls) >= len(customer_turns)

    # end_call ist real (Sicherheitsregel 5): TwilioProvider.end_call wurde
    # mit der echten Call-SID aufgerufen, nachdem sich der Kunde verabschiedet
    # hat - kein reines Setzen eines State-Feldes.
    assert fake_twilio_end_call == [call_sid]

    # send_email wurde tatsaechlich mit der vom Kunden diktierten Adresse
    # aufgerufen (nicht nur der Kontaktwunsch entgegengenommen).
    assert len(sent_emails) == 1
    assert sent_emails[0]["to_email"] == "test@example.de"

    call = await CallRepository(db_session).get(call_id)
    assert call.status.value == "COMPLETED"

    assert call.transcript is not None
    turns = json.loads(call.transcript)
    kunde_texts = [t["text"] for t in turns if t["speaker"] == "kunde"]
    for expected in customer_turns:
        assert expected in kunde_texts

    # Dario hat die E-Mail-Adresse zur Kontrolle wiederholt - der
    # Gespraechsbeitrag direkt nach der Nennung der Adresse enthaelt sie.
    email_turn_idx = next(
        i for i, t in enumerate(turns) if t["speaker"] == "kunde" and "test@example.de" in t["text"]
    )
    dario_reply_after_email = turns[email_turn_idx + 1]
    assert dario_reply_after_email["speaker"] == "dario"
    assert "test@example.de" in dario_reply_after_email["text"]

    assert call.summary is not None
    assert "Entwurf versendet" in call.summary


@pytest.mark.asyncio
async def test_technical_error_during_call_does_not_crash_server(
    db_session, scripted_stt, fake_twilio_end_call, short_utterance_timeout, monkeypatch, tmp_path
):
    """Abschnitt 25/27 (Production-Quality, 'Technischer Fehler'-Test): ein
    Fehler in EINEM Anruf (hier: TTS schlaegt bei der Begruessung fehl) darf
    weder den ASGI-Server noch andere gleichzeitige Anrufe zum Absturz
    bringen - phone/twilio_media_handler.py::run() faengt Exceptions bereits
    breit ab und schliesst die Session sauber. Dieser Test verifiziert genau
    das end-to-end, statt es nur am Code abzulesen."""
    monkeypatch.setattr(
        "agent.dario.write_transcript_file",
        lambda call_id, context: write_transcript_file(call_id, context, transcripts_dir=str(tmp_path)),
    )

    async def failing_synthesize(self, text: str, output_path: str) -> str:
        raise RuntimeError("Simulierter TTS-Absturz (z.B. Modell-Ladefehler)")

    monkeypatch.setattr(ChatterboxTTSProvider, "synthesize", failing_synthesize)
    monkeypatch.setattr(ChatterboxTTSProvider, "is_available", lambda self: _true())
    monkeypatch.setattr(ChatterboxTTSProvider, "warmup", lambda self: _async_return(None))

    _lead_id, call_id = await _seed_call(db_session)
    scripted_stt(["Ja, kein Problem."])

    ws = FakeTwilioWebSocket()
    feeder = asyncio.create_task(
        _feed_conversation(ws, "MZerr", "CAerr", call_id, total_seconds=1.0)
    )

    # Der zentrale Punkt: kein Absturz, keine unbehandelte Exception dringt
    # aus twilio_media_stream() nach aussen - der Server bleibt fuer andere
    # Anrufe funktionsfaehig.
    await twilio_api.twilio_media_stream(ws)

    feeder.cancel()
    try:
        await feeder
    except asyncio.CancelledError:
        pass

    # Der Call wurde trotz des Fehlers sauber als beendet markiert, statt
    # unbegrenzt in einem "ANSWERED"-Zustand haengen zu bleiben.
    call = await CallRepository(db_session).get(call_id)
    assert call.status.value in ("HANGUP", "COMPLETED", "FAILED")


async def _true() -> bool:
    return True


async def _async_return(value):
    return value


@pytest.mark.asyncio
async def test_unknown_call_id_closes_connection_without_crash(db_session):
    ws = FakeTwilioWebSocket()
    ws.push({"event": "connected"})
    ws.push(
        {
            "event": "start",
            "start": {
                "streamSid": "MZunknown",
                "callSid": "CAunknown",
                "customParameters": {"call_id": "999999"},
            },
        }
    )
    ws.push_disconnect()

    await twilio_api.twilio_media_stream(ws)

    assert ws.close_code == 4404


@pytest.mark.asyncio
async def test_disconnect_before_start_event_does_not_crash():
    ws = FakeTwilioWebSocket()
    ws.push_disconnect()

    # Darf keine Exception werfen - der Server muss bei einem sofortigen
    # Verbindungsabbruch stabil bleiben (Abschnitt 25 "Production-Quality":
    # kein Absturz durch ungefangene Exceptions).
    await twilio_api.twilio_media_stream(ws)
