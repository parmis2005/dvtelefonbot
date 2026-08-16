"""Zentrale, serverseitig validierte Tool-Ausfuehrung.

Jeder Tool-Aufruf (egal ob vom LLM vorgeschlagen oder direkt von der
Conversation Engine ausgeloest) laeuft durch diese Klasse. Das LLM erhaelt
NIE direkten SQL- oder Provider-Zugriff - nur diese validierten Funktionen.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from agent.guardrails import guard_end_call, guard_send_email, guard_send_whatsapp
from core.logging import get_logger
from database.models import LeadStatus
from database.repository import LeadRepository
from tools.base import EmailProvider, WhatsAppProvider
from tools.callbacks import set_callback as _set_callback
from tools.do_not_call import set_do_not_call as _set_do_not_call
from tools.email import build_design_email_body

logger = get_logger(__name__)


@dataclass
class ToolCallResult:
    tool: str
    success: bool
    detail: str = ""
    data: dict[str, Any] | None = None


class ToolExecutor:
    def __init__(
        self,
        session: AsyncSession,
        email_provider: EmailProvider,
        whatsapp_provider: WhatsAppProvider,
        company_name: str,
    ):
        self.session = session
        self.email_provider = email_provider
        self.whatsapp_provider = whatsapp_provider
        self.company_name = company_name
        self.lead_repo = LeadRepository(session)

    async def save_lead(self, **fields: Any) -> ToolCallResult:
        lead = await self.lead_repo.create(**fields)
        return ToolCallResult("save_lead", True, "Lead angelegt", {"lead_id": lead.id})

    async def update_lead(self, lead_id: int, **fields: Any) -> ToolCallResult:
        lead = await self.lead_repo.update(lead_id, **fields)
        if lead is None:
            return ToolCallResult("update_lead", False, "Lead nicht gefunden")
        return ToolCallResult("update_lead", True, "Lead aktualisiert")

    async def send_email(self, lead_id: int) -> ToolCallResult:
        lead = await self.lead_repo.get(lead_id)
        if lead is None:
            return ToolCallResult("send_email", False, "Lead nicht gefunden")

        allowed, reason = guard_send_email(lead)
        if not allowed:
            return ToolCallResult("send_email", False, reason)

        body = build_design_email_body(self.company_name, lead.ansprechpartner or "", lead.entwurf_link)
        result = await self.email_provider.send(
            to_email=lead.email,
            subject=f"{self.company_name} - Ihr unverbindlicher Webseiten-Entwurf",
            body=body,
        )
        if result.success:
            await self.lead_repo.update(lead_id, status=LeadStatus.DESIGN_SENT)
        return ToolCallResult("send_email", result.success, result.detail)

    async def send_whatsapp(self, lead_id: int) -> ToolCallResult:
        lead = await self.lead_repo.get(lead_id)
        if lead is None:
            return ToolCallResult("send_whatsapp", False, "Lead nicht gefunden")

        allowed, reason = guard_send_whatsapp(lead, self.whatsapp_provider.is_configured())
        if not allowed:
            return ToolCallResult("send_whatsapp", False, reason)

        message = (
            f"Hallo, hier ist {self.company_name}. Wie besprochen der Link zu Ihrem "
            f"unverbindlichen Webseiten-Entwurf: {lead.entwurf_link}"
        )
        result = await self.whatsapp_provider.send(lead.telefonnummer, message)
        if result.success:
            await self.lead_repo.update(lead_id, status=LeadStatus.DESIGN_SENT)
        return ToolCallResult("send_whatsapp", result.success, result.detail)

    async def set_callback(
        self, lead_id: int, callback_note: str, preferred_contact: str | None = None
    ) -> ToolCallResult:
        success, detail = await _set_callback(self.session, lead_id, callback_note, preferred_contact)
        return ToolCallResult("set_callback", success, detail)

    async def set_do_not_call(self, lead_id: int, phone: str, reason: str = "") -> ToolCallResult:
        await _set_do_not_call(self.session, phone, lead_id, reason or "Kunde hat widersprochen")
        return ToolCallResult("set_do_not_call", True, "Nummer gesperrt")

    async def end_call(self, call_active: bool) -> ToolCallResult:
        allowed, reason = guard_end_call(call_active)
        if not allowed:
            return ToolCallResult("end_call", False, reason)
        return ToolCallResult("end_call", True, "Call wird beendet")
