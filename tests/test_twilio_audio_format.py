"""Dedizierte Regressionstests fuer den Twilio-Audio-Ausgabepfad
(G.711 mu-law/8kHz/mono, siehe CLAUDE.md "Twilio Media Streams liefern/
erwarten G.711 mu-law bei 8kHz").

Deckt genau die Kette ab, die bei einem echten Anruf durchlaufen wird:
Chatterbox-WAV (32bit-Float, beliebige Samplerate) -> Resampling auf 8kHz ->
mu-law-Kodierung -> 20ms-Frames -> base64 -> Twilio "media"-WebSocket-
Nachrichten (phone/twilio_media_handler.py::TwilioMediaStreamSession
._stream_wav_file). Nutzt echte Audio-Synthese (Sinuston statt Chatterbox,
da das TTS-Modell fuer die schnelle Test-Suite ungeeignet ist - siehe
tests/test_twilio_media_stream_e2e.py), aber ausschliesslich echten
Produktionscode fuer Resampling/Kodierung/Chunking/Versand.
"""

from __future__ import annotations

import base64
import time

import numpy as np
import pytest
import soundfile as sf

from phone.twilio_media_handler import (
    FRAME_SAMPLES_8K,
    TWILIO_SAMPLE_RATE,
    TwilioMediaStreamSession,
)
from tests.test_twilio_media_stream_e2e import FakeTwilioWebSocket
from voice.codecs import mulaw_to_pcm16, pcm16_to_mulaw, resample_pcm16

# --- reine Codec-Korrektheit (Ground Truth: Pythons eingebautes audioop) ---


def test_mulaw_roundtrip_matches_audioop_reference():
    """audioop.lin2ulaw/ulaw2lin sind die im CPython-Stdlib mitgelieferte
    Referenzimplementierung von G.711 mu-law - unsere eigene, audioop-freie
    Implementierung (voice/codecs.py, noetig da audioop seit Python 3.13
    entfernt ist) muss praktisch identisches Verhalten liefern."""
    audioop = pytest.importorskip("audioop", reason="nur zur Ground-Truth-Verifikation, optional")

    rng = np.random.default_rng(1234)
    pcm = rng.integers(-32768, 32767, size=20000, dtype=np.int16)

    ref_mulaw = np.frombuffer(audioop.lin2ulaw(pcm.tobytes(), 2), dtype=np.uint8)
    ours_mulaw = pcm16_to_mulaw(pcm)

    # Winzige Rundungsunterschiede an Segmentgrenzen (< 1%, jeweils jeweils
    # nur 1 mu-law-Quantisierungsstufe) sind tolerierbar und unhoerbar - eine
    # exakte Bit-Uebereinstimmung ist bei zwei unabhaengigen Implementierungen
    # nicht garantiert, wohl aber eine fast durchgaengige Uebereinstimmung.
    mismatch_ratio = np.mean(ref_mulaw != ours_mulaw)
    assert mismatch_ratio < 0.01, f"{mismatch_ratio:.2%} der mu-law-Bytes weichen ab"
    max_abs_diff = np.max(np.abs(ref_mulaw.astype(int) - ours_mulaw.astype(int)))
    assert max_abs_diff <= 1, "Abweichungen sollten hoechstens 1 Quantisierungsstufe betragen"

    # Dekodierung muss exakt uebereinstimmen (kein Rundungsspielraum mehr).
    ref_pcm = np.frombuffer(audioop.ulaw2lin(ours_mulaw.tobytes(), 2), dtype=np.int16)
    ours_pcm = mulaw_to_pcm16(ours_mulaw)
    assert np.array_equal(ref_pcm, ours_pcm)


def test_mulaw_silence_is_standard_ff_byte():
    """PCM16-Stille (0) muss auf den Standard-G.711-Stille-Byte 0xFF kodiert
    werden - eine falsche Stille-Kodierung wuerde sich als konstantes
    Knacken/Rauschen in jeder Sprechpause bemerkbar machen."""
    silence = np.zeros(100, dtype=np.int16)
    encoded = pcm16_to_mulaw(silence)
    assert np.all(encoded == 0xFF)


def test_mulaw_encode_does_not_wrap_on_full_scale_values():
    """Vollausschlag (+-32767) darf nicht ueberlaufen/umklappen, sondern muss
    sauber in die hoechste mu-law-Segmentstufe geclippt werden."""
    extreme = np.array([32767, -32768, 32766, -32767], dtype=np.int16)
    encoded = pcm16_to_mulaw(extreme)
    decoded = mulaw_to_pcm16(encoded)
    # mu-law ist verlustbehaftet, aber bei Vollausschlag muss das Vorzeichen
    # erhalten bleiben und die Amplitude nahe am Maximum liegen (>90%).
    assert decoded[0] > 29000
    assert decoded[1] < -29000


# --- Resampling-Qualitaet ---------------------------------------------------


def test_resample_24k_to_8k_preserves_low_frequency_tone():
    """Chatterbox erzeugt Audio bei 24kHz (S3GEN_SR) - das Herunterrechnen auf
    Telefonqualitaet (8kHz) darf ein im Basisband liegendes Sprachsignal
    (hier: 300Hz-Testton, im menschlichen Sprachbereich) nicht durch
    Aliasing/schlechte Interpolation verfaellschen."""
    src_rate = 24000
    dst_rate = TWILIO_SAMPLE_RATE
    duration = 0.5
    t = np.arange(int(src_rate * duration)) / src_rate
    tone = (0.5 * np.sin(2 * np.pi * 300 * t) * 32767).astype(np.int16)

    resampled = resample_pcm16(tone, src_rate, dst_rate)

    # Erwartete Laenge (bis auf Rundung durch die Polyphasen-Filterlaenge).
    expected_len = int(len(tone) * dst_rate / src_rate)
    assert abs(len(resampled) - expected_len) <= 2

    # Amplitude/Energie darf nicht kollabieren (kein stummgeschaltetes/
    # gefiltertes Ergebnis) - RMS des 8kHz-Signals muss nahe am Original liegen.
    src_rms = np.sqrt(np.mean(tone.astype(np.float64) ** 2))
    dst_rms = np.sqrt(np.mean(resampled.astype(np.float64) ** 2))
    assert dst_rms > src_rms * 0.9


def test_resample_identity_when_rates_match():
    pcm = np.array([100, -100, 32767, -32768], dtype=np.int16)
    result = resample_pcm16(pcm, 8000, 8000)
    assert np.array_equal(result, pcm)


# --- Vollstaendiger _stream_wav_file-Pfad (echter Produktionscode) --------


def _make_session(ws: FakeTwilioWebSocket, stream_sid: str) -> TwilioMediaStreamSession:
    return TwilioMediaStreamSession(
        websocket=ws,
        dario=None,  # von _stream_wav_file nicht benoetigt
        call_service=None,
        call_id=1,
        stt=None,
        tts=None,
        twilio_provider=None,
        stream_sid=stream_sid,
    )


@pytest.mark.asyncio
async def test_stream_wav_file_produces_valid_twilio_media_messages(tmp_path):
    """Erzeugt eine synthetische 24kHz-Float32-WAV (wie sie torchaudio.save
    fuer Chatterbox-Ausgaben schreibt, siehe voice/tts/chatterbox_tts.py) und
    schickt sie durch den ECHTEN _stream_wav_file()-Code. Prueft Format,
    Chunking und Inhalt jeder einzelnen "media"-Nachricht - keine Annahmen,
    nur Verifikation der tatsaechlich gesendeten Bytes."""
    src_rate = 24000
    duration = 0.5
    t = np.arange(int(src_rate * duration)) / src_rate
    tone_float = (0.5 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)

    wav_path = str(tmp_path / "synthetic_tts_output.wav")
    sf.write(wav_path, tone_float, src_rate, subtype="FLOAT")

    ws = FakeTwilioWebSocket()
    stream_sid = "MZaudiofmt1234567890"
    session = _make_session(ws, stream_sid)

    await session._stream_wav_file(wav_path)

    media_events = [m for m in ws.sent_messages if m.get("event") == "media"]
    assert len(media_events) > 0, "Es wurden keine Audio-Frames gesendet"

    expected_frame_count = int(np.ceil((src_rate * duration) * TWILIO_SAMPLE_RATE / src_rate / FRAME_SAMPLES_8K))
    assert abs(len(media_events) - expected_frame_count) <= 1

    decoded_frames: list[np.ndarray] = []
    for i, msg in enumerate(media_events):
        assert msg["streamSid"] == stream_sid
        assert set(msg.keys()) == {"event", "streamSid", "media"}
        assert set(msg["media"].keys()) == {"payload"}

        payload_b64 = msg["media"]["payload"]
        # Muss gueltiges Base64 sein (Twilio lehnt sonst die Nachricht ab).
        raw = base64.b64decode(payload_b64, validate=True)

        if i < len(media_events) - 1:
            assert len(raw) == FRAME_SAMPLES_8K, f"Frame {i} hat falsche Laenge: {len(raw)} Bytes"
        else:
            assert 0 < len(raw) <= FRAME_SAMPLES_8K

        decoded_frames.append(mulaw_to_pcm16(np.frombuffer(raw, dtype=np.uint8)))

    # Rueckweg: was der Anrufer tatsaechlich haette hoeren muessen, verglichen
    # mit dem direkt (ohne Frame-Splitting/Base64/JSON) berechneten Referenzsignal -
    # zeigt, dass der Versandpfad selbst (Chunking, Base64, JSON) keine
    # zusaetzliche Verzerrung ueber die inhaerente mu-law-Quantisierung hinaus
    # einfuehrt.
    sent_pcm = np.concatenate(decoded_frames)
    pcm16 = np.clip(tone_float.astype(np.float64) * 32767.0, -32768, 32767).astype(np.int16)
    reference_pcm = resample_pcm16(pcm16, src_rate, TWILIO_SAMPLE_RATE)

    n = min(len(sent_pcm), len(reference_pcm))
    err = sent_pcm[:n].astype(np.float64) - reference_pcm[:n].astype(np.float64)
    signal_power = np.mean(reference_pcm[:n].astype(np.float64) ** 2)
    err_power = np.mean(err**2)
    snr_db = 10 * np.log10(signal_power / err_power)
    assert snr_db > 30, f"Unerwartet niedriger SNR im Versandpfad: {snr_db:.1f} dB"


@pytest.mark.asyncio
async def test_stream_wav_file_writes_decoded_twilio_audio_debug_wav(tmp_path):
    src_rate = 24000
    duration = 0.2
    t = np.arange(int(src_rate * duration)) / src_rate
    tone_float = (0.5 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)

    wav_path = str(tmp_path / "synthetic_tts_output.wav")
    sf.write(wav_path, tone_float, src_rate, subtype="FLOAT")

    ws = FakeTwilioWebSocket()
    session = _make_session(ws, "MZdebugaudio123456")
    session.audio_debug_dir = tmp_path / "audio_debug"

    await session._stream_wav_file(wav_path, label="tts")

    debug_files = list(session.audio_debug_dir.glob("call_1_*_tts_twilio_decoded.wav"))
    assert len(debug_files) == 1
    info = sf.info(str(debug_files[0]))
    assert info.samplerate == TWILIO_SAMPLE_RATE
    assert info.channels == 1
    assert info.duration > 0


def test_barge_in_requires_relevant_speech_not_only_vad(monkeypatch):
    ws = FakeTwilioWebSocket()
    session = _make_session(ws, "MZbargethreshold")
    session._speaking = True
    session._barge_in_enabled = True
    session._playback_started_at = time.perf_counter() - 1.0

    monkeypatch.setattr(session._vad, "is_speech", lambda frame, sample_rate=16000: True)

    quiet = np.zeros(FRAME_SAMPLES_8K, dtype=np.int16)
    for _ in range(8):
        session._process_vad_frames(quiet)
    assert not session._barge_in_event.is_set()

    loud = np.full(FRAME_SAMPLES_8K, 12000, dtype=np.int16)
    for _ in range(8):
        session._process_vad_frames(loud)
    assert session._barge_in_event.is_set()


@pytest.mark.asyncio
async def test_stream_wav_file_stops_immediately_on_barge_in(tmp_path):
    """Wenn waehrend des Sendens ein Barge-In erkannt wird, muss die
    restliche Audio-Ausgabe sofort abgebrochen und ein "clear"-Event an
    Twilio geschickt werden (loescht Twilios Wiedergabepuffer) - siehe
    CLAUDE.md "Barge-In war faktisch tot"."""
    src_rate = 8000
    duration = 2.0  # absichtlich lang, damit ein frueher Abbruch messbar ist
    silence = np.zeros(int(src_rate * duration), dtype=np.int16)
    wav_path = str(tmp_path / "long_silence.wav")
    sf.write(wav_path, silence, src_rate, subtype="PCM_16")

    ws = FakeTwilioWebSocket()
    session = _make_session(ws, "MZbargein1234567890")
    session._barge_in_event.set()  # simuliert: VAD hat bereits Sprache erkannt

    await session._stream_wav_file(wav_path)

    media_events = [m for m in ws.sent_messages if m.get("event") == "media"]
    clear_events = [m for m in ws.sent_messages if m.get("event") == "clear"]

    total_frames_if_uninterrupted = len(silence) // FRAME_SAMPLES_8K
    assert len(media_events) < total_frames_if_uninterrupted, (
        "Barge-In haette die Wiedergabe abbrechen muessen, es wurden aber "
        f"{len(media_events)}/{total_frames_if_uninterrupted} Frames gesendet"
    )
    assert len(clear_events) == 1
    assert clear_events[0]["streamSid"] == "MZbargein1234567890"
