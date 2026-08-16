"""Provider-Abstraktion fuer Speech-to-Text."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TranscriptionResult:
    text: str
    language: str = "de"
    confidence: float | None = None


class SpeechToTextProvider(ABC):
    @abstractmethod
    async def transcribe(self, audio_path: str) -> TranscriptionResult:
        """Transkribiert eine WAV-Datei (16kHz, mono, PCM16) zu Text."""

    @abstractmethod
    async def is_available(self) -> bool: ...
