"""Mikrofon-Aufnahme und Lautsprecher-Wiedergabe fuer den lokalen Voice-Test
(app/local_voice_test.py). Nutzt sounddevice (PortAudio) + WAV-Dateien.

Fuer den Telefonie-Pfad wird stattdessen Audio direkt von/zu Asterisk (ARI
externalMedia / RTP) gestreamt - siehe phone/asterisk.py.
"""

from __future__ import annotations

import wave

SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16bit


def write_wav(path: str, pcm_bytes: bytes, sample_rate: int = SAMPLE_RATE) -> None:
    with wave.open(path, "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(SAMPLE_WIDTH)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_bytes)


def read_wav(path: str) -> tuple[bytes, int]:
    with wave.open(path, "rb") as wf:
        return wf.readframes(wf.getnframes()), wf.getframerate()


async def record_until_silence(
    max_seconds: float = 15.0,
    silence_timeout_ms: int = 800,
) -> str:
    """Nimmt vom Standard-Mikrofon auf, bis Stille erkannt wird, und gibt den
    Pfad einer temporaeren WAV-Datei zurueck. Erfordert `sounddevice` (optional
    dependency, siehe pyproject.toml [voice])."""
    import asyncio
    import tempfile

    import numpy as np
    import sounddevice as sd

    from voice.vad import FRAME_MS, EndpointConfig, EndpointDetector, VoiceActivityDetector

    vad = VoiceActivityDetector(aggressiveness=2)
    endpoint = EndpointDetector(EndpointConfig(silence_timeout_ms=silence_timeout_ms))

    frame_samples = int(SAMPLE_RATE * FRAME_MS / 1000)
    frames: list[bytes] = []
    loop = asyncio.get_event_loop()
    done = asyncio.Event()

    def callback(indata, frame_count, time_info, status):
        pcm = (indata[:, 0] * 32767).astype(np.int16).tobytes()
        frames.append(pcm)
        is_speech = vad.is_speech(pcm, SAMPLE_RATE)
        if endpoint.process_frame(is_speech):
            loop.call_soon_threadsafe(done.set)

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=CHANNELS,
        blocksize=frame_samples,
        dtype="float32",
        callback=callback,
    ):
        try:
            await asyncio.wait_for(done.wait(), timeout=max_seconds)
        except TimeoutError:
            pass

    tmp_path = tempfile.mktemp(suffix=".wav")
    write_wav(tmp_path, b"".join(frames))
    return tmp_path


def play_wav(path: str) -> None:
    """Spielt eine WAV-Datei ueber den Standard-Lautsprecher ab (blockierend)."""
    import sounddevice as sd
    import soundfile as sf

    data, sample_rate = sf.read(path, dtype="float32")
    sd.play(data, sample_rate)
    sd.wait()
