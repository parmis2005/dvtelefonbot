"""Verifiziert den KOMPLETTEN Kundensprache-Rueckweg mit echter Sprache und
echtem whisper.cpp (kein Mock) - genau die Kette aus CLAUDE.md Abschnitt
"Sprache vom Kunden": Kunde spricht -> Twilio (mu-law/8kHz) -> Media Stream
-> Decoder -> STT -> deutscher Text.

Da in dieser Umgebung kein Mikrofon/keine echte Anrufer-Aufnahme verfuegbar
ist, wird eine realistische deutsche Aeusserung mit der echten (lokalen)
Chatterbox-TTS synthetisiert und exakt durch denselben Code geschickt, den
phone/twilio_media_handler.py fuer eingehende Anrufer-Audiodaten nutzt:

  TTS-WAV (beliebige Samplerate)
    -> Resampling auf 8kHz PCM16 (simuliert die Telefonbandbreite)
    -> mu-law-Kodierung (simuliert Twilios tatsaechliche Leitungskodierung)
    -> mu-law-Dekodierung (voice/codecs.py::mulaw_to_pcm16, wie
       TwilioMediaStreamSession._receive_loop es fuer jeden eingehenden
       Frame tut)
    -> Resampling auf 16kHz (wie TwilioMediaStreamSession
       ._listen_for_utterance es vor der STT-Uebergabe tut)
    -> echtes whisper.cpp (voice/stt/whisper_cpp.py::LocalWhisperProvider,
       derselbe Provider-Code wie im echten Anruf)

Kein Teil dieser Kette ist gemockt ausser der Quelle des Sprachsignals
selbst (synthetische statt menschliche Stimme) - Codec, Resampling und STT
sind exakt der Produktionscode.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice.audio_stream import write_wav
from voice.codecs import mulaw_to_pcm16, pcm16_to_mulaw, resample_pcm16
from voice.stt.whisper_cpp import LocalWhisperProvider
from voice.tts.chatterbox_tts import ChatterboxTTSProvider

OUT_DIR = Path(__file__).resolve().parent
TWILIO_SAMPLE_RATE = 8000
STT_SAMPLE_RATE = 16000

# Exakt die vom Auftrag geforderten Mindest-Testsaetze ("Sprache vom Kunden").
TEST_PHRASES = [
    "Ja, worum geht es?",
    "Ich habe schon eine Webseite.",
    "Kein Interesse.",
    "Einen Moment bitte.",
    "Schicken Sie mir den Entwurf per E-Mail.",
]


async def main() -> None:
    tts = ChatterboxTTSProvider(
        language="de",
        exaggeration=0.22,
        cfg_weight=0.35,
        temperature=0.55,
        device="cpu",
        max_attempts=3,
        reference_audio_path=str(
            Path(__file__).resolve().parent.parent / "models/voice_reference/dario_reference.wav"
        ),
    )
    stt = LocalWhisperProvider(binary="whisper-cli", model_path="./models/whisper/ggml-medium.bin", language="de")

    results = []
    for i, phrase in enumerate(TEST_PHRASES, start=1):
        print(f"\n=== [{i}/{len(TEST_PHRASES)}] Quelltext: {phrase!r} ===")
        raw_tts_path = str(OUT_DIR / f"customer_{i}_raw_tts.wav")
        t0 = time.time()
        await tts.synthesize(phrase, raw_tts_path)
        print(f"  TTS-Synthese: {time.time() - t0:.1f}s")

        pcm_float, src_rate = sf.read(raw_tts_path, dtype="float32")
        if pcm_float.ndim > 1:
            pcm_float = pcm_float[:, 0]
        pcm = np.clip(pcm_float * 32767.0, -32768, 32767).astype(np.int16)

        # --- Simuliert die Telefonleitung (genau wie der Sendepfad) ---
        pcm_8k = resample_pcm16(pcm, src_rate, TWILIO_SAMPLE_RATE)
        mulaw = pcm16_to_mulaw(pcm_8k)

        # --- Genau der Empfangspfad aus TwilioMediaStreamSession ---
        decoded_pcm_8k = mulaw_to_pcm16(mulaw)
        pcm_16k = resample_pcm16(decoded_pcm_8k, TWILIO_SAMPLE_RATE, STT_SAMPLE_RATE)

        stt_input_path = str(OUT_DIR / f"customer_{i}_telephony_quality_16k.wav")
        write_wav(stt_input_path, pcm_16k.tobytes(), sample_rate=STT_SAMPLE_RATE)

        t0 = time.time()
        result = await stt.transcribe(stt_input_path)
        stt_duration = time.time() - t0
        print(f"  whisper.cpp ({stt_duration:.1f}s) erkannte: {result.text!r}")

        results.append((phrase, result.text))

    print("\n" + "=" * 70)
    print("ZUSAMMENFASSUNG (Original -> ueber Telefonqualitaet erkannt):")
    all_ok = True
    for original, recognized in results:
        ok = bool(recognized.strip())
        all_ok = all_ok and ok
        marker = "OK" if ok else "LEER/FEHLGESCHLAGEN"
        print(f"  [{marker}] {original!r} -> {recognized!r}")
    print("=" * 70)
    if not all_ok:
        print("WARNUNG: mindestens eine Erkennung lieferte keinen Text.")


if __name__ == "__main__":
    asyncio.run(main())
