"""Dario: Fassade, die Conversation Engine, Tools und Persistenz verbindet.

Wird identisch von app/chat_test.py, app/local_voice_test.py und dem
Telefonie-Pfad (phone/call_controller.py) genutzt - keine Duplikation der
Gespraechslogik.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from agent.context import ConversationContext, LeadData
from agent.conversation import ConversationEngine, EngineResult
from core.config import BusinessConfig, Settings
from core.logging import get_logger
from database.models import Lead
from database.repository import LeadRepository, PromptVersionRepository
from services.call_service import CallService
from services.summary_service import build_summary
from services.transcript_service import persist_transcript, write_transcript_file
from tools.call_tools import ToolExecutor

logger = get_logger(__name__)


@dataclass
class TurnOutcome:
    reply_text: str
    call_ended: bool = False
    do_not_call: bool = False
    tool_results: list[str] | None = None


def lead_to_context_data(lead: Lead) -> LeadData:
    return LeadData(
        unternehmen=lead.unternehmen or "",
        ansprechpartner=lead.ansprechpartner or "",
        branche=lead.branche or "",
        website_url=lead.website_url or "",
        online_auftritt_geprueft=bool(lead.online_auftritt_geprueft),
        entwurf_vorhanden=bool(lead.entwurf_vorhanden),
        entwurf_link=lead.entwurf_link or "",
        notizen=lead.notizen or "",
        telefonnummer=lead.telefonnummer or "",
        email=lead.email or "",
    )


class Dario:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        business_config: BusinessConfig,
        engine: ConversationEngine,
        tool_executor: ToolExecutor,
        lead_id: int,
        call_id: int | None = None,
    ):
        self.session = session
        self.settings = settings
        self.business_config = business_config
        self.engine = engine
        self.tools = tool_executor
        self.lead_id = lead_id
        self.call_id = call_id
        self.call_service = CallService(session, settings)
        self.context = ConversationContext()
        self.call_active = True

    @classmethod
    async def for_lead(
        cls,
        session: AsyncSession,
        settings: Settings,
        business_config: BusinessConfig,
        engine: ConversationEngine,
        tool_executor: ToolExecutor,
        lead_id: int,
        call_id: int | None = None,
    ) -> Dario:
        lead_repo = LeadRepository(session)
        lead = await lead_repo.get(lead_id)
        if lead is None:
            raise ValueError(f"Lead {lead_id} nicht gefunden")
        instance = cls(session, settings, business_config, engine, tool_executor, lead_id, call_id)
        instance.context.lead = lead_to_context_data(lead)

        # Aktive Prompt-Version einmalig bei Call-Start festlegen (siehe
        # agent/context.py::ConversationContext.system_prompt) - laufende
        # Gespraeche wechseln danach nicht mehr die Version.
        active_prompt = await PromptVersionRepository(session).get_active()
        if active_prompt is not None:
            instance.context.system_prompt = active_prompt.content

        return instance

    def opening_line(self) -> str:
        return self.engine.opening_line(self.context)

    async def process_utterance(self, user_text: str) -> TurnOutcome:
        if not self.call_active:
            return TurnOutcome(reply_text="", call_ended=True)

        result: EngineResult = await self.engine.handle_utterance(self.context, user_text)
        tool_notes: list[str] = []

        if result.lead_updates:
            await self.tools.update_lead(self.lead_id, **result.lead_updates)

        if result.ready_to_send_email:
            tool_result = await self.tools.send_email(self.lead_id)
            tool_notes.append(f"send_email: {tool_result.detail}")
            if tool_result.success:
                self.context.design_sent = True

        if result.ready_to_send_whatsapp:
            tool_result = await self.tools.send_whatsapp(self.lead_id)
            tool_notes.append(f"send_whatsapp: {tool_result.detail}")
            if tool_result.success:
                self.context.design_sent = True

        if result.should_trigger_do_not_call:
            tool_result = await self.tools.set_do_not_call(
                self.lead_id, self.context.lead.telefonnummer
            )
            tool_notes.append(f"set_do_not_call: {tool_result.detail}")

        if result.should_end_call:
            await self._finalize_call()
            self.call_active = False

        return TurnOutcome(
            reply_text=result.reply_text,
            call_ended=result.should_end_call,
            do_not_call=result.should_trigger_do_not_call,
            tool_results=tool_notes,
        )

    async def _finalize_call(self) -> None:
        summary = build_summary(self.context)
        self.context.call_result = self.context.call_result or "UNKNOWN"

        if self.call_id is not None:
            await persist_transcript(self.session, self.call_id, self.context)
            await self.call_service.complete(self.call_id, result=self.context.call_result)
            from database.repository import CallRepository

            await CallRepository(self.session).update(self.call_id, summary=summary)

        write_transcript_file(self.call_id or 0, self.context)
        logger.info("Call beendet, Ergebnis: %s", self.context.call_result)
