"""LocalTTSProvider: ruft das Piper CLI-Binary auf (echter Subprocess-Aufruf).

Piper (https://github.com/rhasspy/piper) liefert natuerliche, lokale deutsche
Stimmen mit niedriger Latenz. Empfohlene maennliche Stimme: de_DE-thorsten-*.
Provider-Struktur erlaubt spaeter z.B. ElevenLabs als optionale Cloud-Stimme.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from agent.guardrails import strip_disallowed_audio_artifacts
from core.logging import get_logger
from voice.tts.base import TextToSpeechProvider

logger = get_logger(__name__)


class PiperBinaryNotFoundError(Exception):
    pass


class LocalTTSProvider(TextToSpeechProvider):
    def __init__(self, binary: str, model_path: str, speaker: str | None = None):
        self.binary = binary
        self.model_path = model_path
        self.speaker = speaker

    async def is_available(self) -> bool:
        return shutil.which(self.binary) is not None and Path(self.model_path).exists()

    async def synthesize(self, text: str, output_path: str) -> str:
        if shutil.which(self.binary) is None:
            raise PiperBinaryNotFoundError(
                f"Piper Binary '{self.binary}' nicht im PATH gefunden. Siehe scripts/setup_mac.sh."
            )
        if not Path(self.model_path).exists():
            raise PiperBinaryNotFoundError(f"Piper-Modell nicht gefunden: {self.model_path}")

        clean_text = strip_disallowed_audio_artifacts(text)
        if not clean_text:
            raise ValueError("Kein Text zum Sprechen nach Bereinigung uebrig.")

        cmd = [self.binary, "-m", self.model_path, "-f", output_path]
        if self.speaker:
            cmd += ["--speaker", self.speaker]

        logger.debug("piper Aufruf: %s", " ".join(cmd))
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate(input=clean_text.encode("utf-8"))
        if proc.returncode != 0:
            raise RuntimeError(f"piper fehlgeschlagen: {stderr.decode(errors='ignore')}")
        return output_path
