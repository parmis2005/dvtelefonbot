"""LLMProvider-Implementierung fuer ein lokal laufendes llama.cpp.

Erwartet einen `llama-server` (Teil von llama.cpp) im OpenAI-kompatiblen
Modus, gestartet z.B. mit:

    llama-server -m ./models/llm/model.gguf --port 8080

Kein Mock: es wird ein echter HTTP-Request an /v1/chat/completions gestellt.
Ist der Server nicht erreichbar, wird LLMUnavailableError geworfen - die
Conversation Engine faellt dann kontrolliert auf Template-Antworten zurueck.
"""

from __future__ import annotations

import httpx

from core.logging import get_logger
from llm.base import LLMProvider, LLMUnavailableError

logger = get_logger(__name__)


class LocalLlamaProvider(LLMProvider):
    def __init__(self, server_url: str, model_name: str = "local-model", timeout: int = 30):
        self.server_url = server_url.rstrip("/")
        self.model_name = model_name
        self.timeout = timeout

    async def generate(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 200,
        temperature: float = 0.4,
    ) -> str:
        payload = {
            "model": self.model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.server_url}/v1/chat/completions", json=payload
                )
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()
        except (httpx.HTTPError, KeyError, IndexError) as exc:
            logger.warning("LocalLlamaProvider nicht erreichbar: %s", exc)
            raise LLMUnavailableError(str(exc)) from exc

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                response = await client.get(f"{self.server_url}/health")
                return response.status_code == 200
        except httpx.HTTPError:
            return False
