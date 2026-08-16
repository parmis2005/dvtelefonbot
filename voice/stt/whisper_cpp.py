"""LocalWhisperProvider: ruft das whisper.cpp CLI-Binary auf (echter Subprocess-
Aufruf, kein Mock). Erwartet ein Binary wie `whisper-cli` (frueher `main`) aus
https://github.com/ggerganov/whisper.cpp sowie ein ggml-Modell.

Installation siehe scripts/setup_mac.sh / README.md.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path

from core.logging import get_logger
from voice.stt.base import SpeechToTextProvider, TranscriptionResult

logger = get_logger(__name__)


class WhisperBinaryNotFoundError(Exception):
    pass


class LocalWhisperProvider(SpeechToTextProvider):
    def __init__(self, binary: str, model_path: str, language: str = "de"):
        self.binary = binary
        self.model_path = model_path
        self.language = language

    async def is_available(self) -> bool:
        return shutil.which(self.binary) is not None and Path(self.model_path).exists()

    async def transcribe(self, audio_path: str) -> TranscriptionResult:
        if shutil.which(self.binary) is None:
            raise WhisperBinaryNotFoundError(
                f"whisper.cpp Binary '{self.binary}' nicht im PATH gefunden. "
                f"Siehe scripts/setup_mac.sh."
            )
        if not Path(self.model_path).exists():
            raise WhisperBinaryNotFoundError(f"Whisper-Modell nicht gefunden: {self.model_path}")

        with tempfile.TemporaryDirectory() as tmp_dir:
            out_prefix = str(Path(tmp_dir) / "out")
            cmd = [
                self.binary,
                "-m", self.model_path,
                "-f", audio_path,
                "-l", self.language,
                "-oj",  # JSON-Output
                "-of", out_prefix,
                "-nt",  # keine Timestamps im Text
            ]
            logger.debug("whisper.cpp Aufruf: %s", " ".join(cmd))
            proc = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                raise RuntimeError(f"whisper.cpp fehlgeschlagen: {stderr.decode(errors='ignore')}")

            json_path = Path(f"{out_prefix}.json")
            if json_path.exists():
                data = json.loads(json_path.read_text(encoding="utf-8"))
                text = "".join(seg.get("text", "") for seg in data.get("transcription", []))
                return TranscriptionResult(text=text.strip(), language=self.language)

            # Fallback: Text aus stdout extrahieren
            return TranscriptionResult(text=stdout.decode(errors="ignore").strip(), language=self.language)
