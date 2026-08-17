"""Lokaler Audio-Kontrolltest fuer den Twilio-Sprachausgabepfad.

Erzeugt die Begruessung mit der echten, aktuell aktiven Chatterbox-Stimme
und durchlaeuft exakt denselben Code, den phone/twilio_media_handler.py
fuer einen echten Anruf verwendet (_stream_wav_file-Logik), um zu
verifizieren, dass das Audio nach der Telefonformat-Konvertierung
(8kHz mu-law) weiterhin verstaendlich ist.

Speichert:
  1_original_tts.wav        - rohes Chatterbox-Ergebnis (Modell-Samplerate)
  2_twilio_mulaw_8k.raw     - exakt die Bytes, die als Twilio "media"-Payloads
                               gesendet wuerden (G.711 mu-law, 8kHz, mono)
  3_roundtrip_check_8k.wav  - mu-law wieder nach PCM16 dekodiert, hoerbar
                               als WAV (zeigt, was beim Anrufer ankommt)
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from voice.codecs import mulaw_to_pcm16, pcm16_to_mulaw, resample_pcm16
from voice.tts.chatterbox_tts import ChatterboxTTSProvider

OUT_DIR = Path(__file__).resolve().parent
TEXT = (
    "Guten Tag! Hier ist Dario der digitale Assistent von Digital Vision aus "
    "Mönchengladbach. Haben Sie.. gerade einen Moment Zeit???"
)
TWILIO_SAMPLE_RATE = 8000


def analyze(label: str, pcm: np.ndarray, rate: int) -> None:
    pcm_f = pcm.astype(np.float64)
    peak = np.max(np.abs(pcm_f)) if len(pcm_f) else 0.0
    rms = np.sqrt(np.mean(pcm_f**2)) if len(pcm_f) else 0.0
    clipped = int(np.sum(np.abs(pcm) >= 32767))
    dur = len(pcm) / rate if rate else 0.0
    print(
        f"[{label}] rate={rate}Hz samples={len(pcm)} dur={dur:.2f}s "
        f"peak={peak:.0f} rms={rms:.1f} clipped_samples={clipped}"
    )


async def main() -> None:
    print("Text:", TEXT)
    provider = ChatterboxTTSProvider(
        language="de",
        exaggeration=0.22,
        cfg_weight=0.35,
        temperature=0.55,
        device="cpu",
        max_attempts=3,
        reference_audio_path=str(
            Path(__file__).resolve().parent.parent
            / "models/voice_reference/dario_reference.wav"
        ),
    )

    t0 = time.time()
    original_path = str(OUT_DIR / "1_original_tts.wav")
    await provider.synthesize(TEXT, original_path)
    print(f"TTS-Generierung dauerte {time.time() - t0:.1f}s -> {original_path}")

    # --- Exakt dieselbe Logik wie TwilioMediaStreamSession._stream_wav_file ---
    pcm_float, src_rate = sf.read(original_path, dtype="float32")
    if pcm_float.ndim > 1:
        pcm_float = pcm_float[:, 0]
    pcm = np.clip(pcm_float * 32767.0, -32768, 32767).astype(np.int16)
    analyze("1 original (PCM16, Modell-Rate)", pcm, src_rate)

    # Warnen, falls das Modell tatsaechlich Samples ausserhalb [-1, 1] liefert
    raw_peak = float(np.max(np.abs(pcm_float))) if len(pcm_float) else 0.0
    if raw_peak > 1.0:
        n_over = int(np.sum(np.abs(pcm_float) > 1.0))
        print(
            f"WARNUNG: {n_over} Samples liegen ueber Vollausschlag (peak={raw_peak:.3f}) "
            "-> werden beim Skalieren *32767 hart geclippt (Verzerrung/Knacken moeglich)."
        )

    pcm_8k = resample_pcm16(pcm, src_rate, TWILIO_SAMPLE_RATE)
    analyze("2 resampled auf 8kHz", pcm_8k, TWILIO_SAMPLE_RATE)

    mulaw = pcm16_to_mulaw(pcm_8k)
    mulaw_path = OUT_DIR / "2_twilio_mulaw_8k.raw"
    mulaw_path.write_bytes(mulaw.tobytes())
    print(f"mu-law Rohbytes gespeichert -> {mulaw_path} ({len(mulaw)} bytes = "
          f"{len(mulaw) / TWILIO_SAMPLE_RATE:.2f}s bei 8kHz/8bit)")

    # Frame-Groessen-Check wie im echten Sende-Loop (FRAME_SAMPLES_8K = 160)
    frame_samples = TWILIO_SAMPLE_RATE * 20 // 1000
    n_full_frames = len(mulaw) // frame_samples
    remainder = len(mulaw) % frame_samples
    print(
        f"Frame-Check: {n_full_frames} volle 20ms-Frames (160 Byte), "
        f"Rest={remainder} Byte im letzten Frame"
    )

    # --- Rueckweg: was der Anrufer tatsaechlich hoert ---
    decoded_pcm16_8k = mulaw_to_pcm16(mulaw)
    analyze("3 roundtrip decoded (PCM16, 8kHz)", decoded_pcm16_8k, TWILIO_SAMPLE_RATE)

    roundtrip_path = OUT_DIR / "3_roundtrip_check_8k.wav"
    sf.write(str(roundtrip_path), decoded_pcm16_8k, TWILIO_SAMPLE_RATE, subtype="PCM_16")
    print(f"Hoerbare Kontrollversion gespeichert -> {roundtrip_path}")

    # SNR zwischen Original (auf 8kHz resampled) und roundtrip-dekodiertem Signal
    err = decoded_pcm16_8k.astype(np.float64) - pcm_8k.astype(np.float64)
    signal_power = np.mean(pcm_8k.astype(np.float64) ** 2)
    err_power = np.mean(err**2)
    if err_power > 0 and signal_power > 0:
        snr_db = 10 * np.log10(signal_power / err_power)
        print(f"mu-law Roundtrip-SNR: {snr_db:.1f} dB (typisch fuer G.711: ~35-38 dB)")
    else:
        print("SNR-Berechnung uebersprungen (Stille?)")

    print("\nFERTIG. Bitte 1_original_tts.wav und 3_roundtrip_check_8k.wav manuell anhoeren.")


if __name__ == "__main__":
    asyncio.run(main())
