"""WhatsAppProvider: echte API-Anbindung (z.B. Meta Cloud API), aber mit
sauberem, technisch ehrlichem Fallback-Verhalten, wenn keine API konfiguriert
ist. In diesem Fall wird NUR die Nummer gespeichert - Dario darf laut
agent/guardrails.py dann keinen erfolgreichen Versand behaupten.
"""

from __future__ import annotations

import httpx

from core.logging import get_logger
from tools.base import SendResult, WhatsAppProvider

logger = get_logger(__name__)


class UnconfiguredWhatsAppProvider(WhatsAppProvider):
    """Aktiv, solange keine echten WhatsApp-Zugangsdaten hinterlegt sind."""

    def is_configured(self) -> bool:
        return False

    async def send(self, to_phone: str, message: str) -> SendResult:
        logger.info("WhatsApp-Provider nicht konfiguriert - Nummer wird nur gespeichert.")
        return SendResult(success=False, detail="WhatsApp-Provider nicht konfiguriert")


class MetaCloudApiWhatsAppProvider(WhatsAppProvider):
    """Echte Anbindung an die WhatsApp Cloud API von Meta."""

    def __init__(self, api_url: str, api_token: str, phone_number_id: str):
        self.api_url = api_url.rstrip("/")
        self.api_token = api_token
        self.phone_number_id = phone_number_id

    def is_configured(self) -> bool:
        return bool(self.api_url and self.api_token and self.phone_number_id)

    async def send(self, to_phone: str, message: str) -> SendResult:
        if not self.is_configured():
            return SendResult(success=False, detail="WhatsApp Cloud API nicht konfiguriert")

        url = f"{self.api_url}/{self.phone_number_id}/messages"
        headers = {"Authorization": f"Bearer {self.api_token}"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to_phone,
            "type": "text",
            "text": {"body": message},
        }
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                logger.info("WhatsApp-Nachricht erfolgreich gesendet")
                return SendResult(success=True, detail="gesendet")
        except httpx.HTTPError as exc:
            logger.error("WhatsApp-Versand fehlgeschlagen: %s", exc)
            return SendResult(success=False, detail=str(exc))


def build_provider(
    api_url: str, api_token: str, phone_number_id: str
) -> WhatsAppProvider:
    if api_url and api_token and phone_number_id:
        return MetaCloudApiWhatsAppProvider(api_url, api_token, phone_number_id)
    return UnconfiguredWhatsAppProvider()
