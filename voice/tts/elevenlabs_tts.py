"""ElevenLabs TTS Provider.

Nutzt die offizielle HTTP Text-to-Speech Streaming API. Im Telefonpfad wird
das Ergebnis als PCM/WAV gespeichert und danach wie jede andere TTS-Ausgabe
ueber Twilio gestreamt. Damit bleiben bestehende Kontakte, Prompts,
Geschaechsdokumentation und Barge-In-Logik erhalten, waehrend die Stimme von
ElevenLabs kommt.
"""

from __future__ import annotations

import re
import wave
from pathlib import Path

import httpx
import numpy as np

from agent.guardrails import strip_disallowed_audio_artifacts
from voice.tts.base import TextToSpeechProvider


class ElevenLabsConfigError(Exception):
    pass


def _clean_text(text: str) -> str:
    text = strip_disallowed_audio_artifacts(text)
    text = re.sub(r"([!?.,])\1+", r"\1", text)
    return re.sub(r"\s+", " ", text).strip()


def _sample_rate_from_output_format(output_format: str) -> int:
    match = re.search(r"_(\d{4,5})(?:_|$)", output_format)
    if match:
        return int(match.group(1))
    return 16000


def _write_pcm_wav(path: str, pcm_bytes: bytes, sample_rate: int) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    # 16-bit PCM erwartet gerade Byte-Anzahl. Defensive Kuerzung verhindert
    # kaputte WAVs, falls ein Stream einmal unvollstaendig endet.
    if len(pcm_bytes) % 2:
        pcm_bytes = pcm_bytes[:-1]
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_bytes)


class ElevenLabsTTSProvider(TextToSpeechProvider):
    def __init__(
        self,
        api_key: str,
        voice_id: str,
        model_id: str = "eleven_turbo_v2_5",
        output_format: str = "pcm_16000",
        stability: float = 0.45,
        similarity_boost: float = 0.85,
        style: float = 0.15,
        use_speaker_boost: bool = True,
        timeout_seconds: float = 30.0,
    ):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model_id = model_id
        self.output_format = output_format
        self.stability = stability
        self.similarity_boost = similarity_boost
        self.style = style
        self.use_speaker_boost = use_speaker_boost
        self.timeout_seconds = timeout_seconds

    async def is_available(self) -> bool:
        return bool(self.api_key and self.voice_id)

    async def synthesize(self, text: str, output_path: str) -> str:
        if not await self.is_available():
            raise ElevenLabsConfigError(
                "ELEVENLABS_API_KEY und ELEVENLABS_VOICE_ID muessen gesetzt sein."
            )

        clean_text = _clean_text(text)
        if not clean_text:
            raise ValueError("Kein Text zum Sprechen nach Bereinigung uebrig.")

        url = (
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream"
            f"?output_format={self.output_format}"
        )
        payload = {
            "text": clean_text,
            "model_id": self.model_id,
            "voice_settings": {
                "stability": self.stability,
                "similarity_boost": self.similarity_boost,
                "style": self.style,
                "use_speaker_boost": self.use_speaker_boost,
            },
        }
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/octet-stream",
        }

        chunks: list[bytes] = []
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            async with client.stream("POST", url, json=payload, headers=headers) as response:
                if response.status_code >= 400:
                    detail = await response.aread()
                    raise RuntimeError(
                        "ElevenLabs TTS fehlgeschlagen "
                        f"({response.status_code}): {detail.decode(errors='ignore')[:500]}"
                    )
                async for chunk in response.aiter_bytes():
                    if chunk:
                        chunks.append(chunk)

        audio = b"".join(chunks)
        if not audio:
            raise RuntimeError("ElevenLabs lieferte keine Audiodaten.")

        # Fuer den Telefonpfad verwenden wir PCM-Output. Falls spaeter ein
        # anderes Format konfiguriert wird, bewusst klar fehlschlagen statt
        # still eine falsche Dateiendung/WAV-Struktur zu erzeugen.
        if not self.output_format.startswith("pcm_"):
            raise RuntimeError(
                "ELEVENLABS_OUTPUT_FORMAT muss fuer diesen Provider mit 'pcm_' beginnen."
            )

        pcm = np.frombuffer(audio, dtype=np.int16)
        if pcm.size == 0 or float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2))) < 20:
            raise RuntimeError("ElevenLabs-Audio wirkt leer oder praktisch still.")

        _write_pcm_wav(output_path, audio, _sample_rate_from_output_format(self.output_format))
        return output_path
