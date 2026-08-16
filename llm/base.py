"""Provider-Abstraktion fuer LLMs. Ermoeglicht spaeteren Wechsel/Ergaenzung
auf Cloud-Provider (z.B. Anthropic), ohne die Conversation Engine anzufassen.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMUnavailableError(Exception):
    """Wird geworfen, wenn der konfigurierte LLM-Provider nicht erreichbar ist."""


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 200,
        temperature: float = 0.4,
    ) -> str:
        """Erzeugt eine Antwort aus einer Liste von {role, content} Nachrichten."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Prueft, ob der Provider aktuell erreichbar ist (z.B. Server laeuft)."""
