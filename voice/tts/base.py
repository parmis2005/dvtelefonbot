"""Provider-Abstraktion fuer Text-to-Speech."""

from __future__ import annotations

from abc import ABC, abstractmethod


class TextToSpeechProvider(ABC):
    @abstractmethod
    async def synthesize(self, text: str, output_path: str) -> str:
        """Erzeugt eine WAV-Datei aus Text und gibt den Pfad zurueck."""

    @abstractmethod
    async def is_available(self) -> bool: ...
