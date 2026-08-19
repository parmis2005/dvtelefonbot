"""Conversation Engine: verbindet NLU, State Machine, Business Rules,
Response-Templates und (optional) das LLM zu einer einzigen Turn-Verarbeitung.

Diese Engine wird identisch von chat_test.py, local_voice_test.py und dem
spaeteren Telefonie-Pfad genutzt - es gibt keine separate vereinfachte Logik.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from agent.context import ConversationContext
from agent.guardrails import (
    can_claim_entwurf_vorhanden,
    can_offer_design,
    is_valid_email,
    is_valid_phone,
    must_end_acquisition,
)
from agent.nlu import Intent, NluResult, analyze
from agent.responses import ResponseBank
from agent.rules import RuleDecision
from agent.rules import apply as apply_rules
from agent.state_machine import CallState
from core.config import BusinessConfig, Settings
from core.logging import get_logger
from llm.base import LLMProvider, LLMUnavailableError

logger = get_logger(__name__)


@dataclass
class EngineResult:
    reply_text: str
    should_end_call: bool = False
    should_trigger_do_not_call: bool = False
    ready_to_send_email: bool = False
    ready_to_send_whatsapp: bool = False
    pending_actions: list[str] = field(default_factory=list)
    lead_updates: dict = field(default_factory=dict)


class ConversationEngine:
    def __init__(
        self,
        settings: Settings,
        business_config: BusinessConfig,
        llm_provider: LLMProvider | None = None,
    ):
        self.settings = settings
        self.business_config = business_config
        self.llm_provider = llm_provider
        self.responses = ResponseBank(
            agent_name=settings.agent_name,
            company_name=settings.company_name,
            company_location=settings.company_location,
            biz=business_config,
        )
        self.max_rejections = settings.max_rejections

    def opening_line(self, context: ConversationContext) -> str:
        context.transition_to(CallState.INTRODUCTION)
        text = self.responses.greeting(context.lead)
        context.add_turn("dario", text)
        return text

    async def handle_utterance(self, context: ConversationContext, user_text: str) -> EngineResult:
        context.add_turn("kunde", user_text)
        nlu = analyze(user_text)

        decision = apply_rules(context, nlu, self.max_rejections)

        result = await self._build_reply(context, nlu, decision)
        context.add_turn("dario", result.reply_text)
        return result

    async def _build_reply(
        self, context: ConversationContext, nlu: NluResult, decision: RuleDecision
    ) -> EngineResult:
        r = self.responses

        # Do-Not-Call hat absolute Prioritaet
        if decision.trigger_do_not_call:
            context.transition_to(CallState.DO_NOT_CALL)
            context.transition_to(CallState.GOODBYE)
            return EngineResult(
                reply_text=r.do_not_call_ack(),
                should_end_call=True,
                should_trigger_do_not_call=True,
            )

        # Wait Mode: waehrend des Wartens keinen neuen Text erzeugen
        if nlu.has(Intent.WAIT) and not context.wait_mode:
            context.wait_mode = True
            import datetime as _dt

            context.wait_started_at = _dt.datetime.utcnow()
            context.transition_to(CallState.WAITING)
            return EngineResult(reply_text=r.wait_ack())
        if context.wait_mode and decision.note == "resume_from_wait":
            # Kunde spricht wieder - normal weiterverarbeiten (fall-through unten)
            pass
        elif context.state == CallState.WAITING:
            # weiterhin am Warten, nichts sagen
            return EngineResult(reply_text="")

        # Verabschiedung - keine Schleife
        if decision.ask_farewell_reply:
            if context.contact_confirmed:
                # Erfolgreicher Abschluss (Abschnitt 71, agent/responses.py::
                # success_closing) statt der generischen Verabschiedung -
                # der Zustandsuebergang ueber SUCCESS wird nur versucht, wenn
                # er von hier aus erlaubt ist (siehe agent/state_machine.py);
                # GOODBYE selbst ist von jedem Nicht-Terminalzustand aus
                # immer erlaubt, der Text haengt aber allein an
                # contact_confirmed, nicht am erreichten Zustand.
                if context.state in (CallState.CONTACT_CAPTURE, CallState.CALLBACK_REQUEST):
                    context.transition_to(CallState.SUCCESS)
                context.transition_to(CallState.GOODBYE)
                reply = r.success_closing(context.design_sent)
            else:
                context.transition_to(CallState.GOODBYE)
                reply = r.farewell_reply()
            return EngineResult(reply_text=reply, should_end_call=True)

        if nlu.has(Intent.FRIENDLY_WISH):
            return EngineResult(reply_text=r.friendly_wish_reply())

        if nlu.has(Intent.ASK_IF_AI):
            return EngineResult(reply_text=r.identity_disclosure())

        if nlu.has(Intent.ASK_WHO_WILL_CALL):
            return EngineResult(reply_text=r.who_will_contact())

        if nlu.has(Intent.ASK_PRICE):
            return EngineResult(reply_text=r.pricing_website())

        # Ablehnung / Zwei-Nein-Regel
        if nlu.has(Intent.REJECTION):
            context.transition_to(decision.next_state)
            if must_end_acquisition(context, self.max_rejections):
                context.call_result = context.call_result or "NOT_INTERESTED"
                context.transition_to(CallState.GOODBYE)
                return EngineResult(reply_text=r.polite_end_after_rejection(), should_end_call=True)
            text = r.first_rejection_ack()
            offer = None
            if decision.offer_design_now and can_offer_design(context, self.max_rejections):
                offer = r.offer_design_despite_rejection(context.lead)
                if offer:
                    context.design_offered = True
                    context.transition_to(CallState.DESIGN_OFFER)
            reply = f"{text} {offer}".strip() if offer else text
            return EngineResult(reply_text=reply)

        # Gatekeeper
        if nlu.has(Intent.GATEKEEPER_ASK_TOPIC):
            if context.state == CallState.INTRODUCTION:
                context.transition_to(CallState.DISCOVERY)
                if can_claim_entwurf_vorhanden(context.lead):
                    context.design_offered = True
                    context.transition_to(CallState.DESIGN_OFFER)
                else:
                    context.transition_to(CallState.PITCH)
                return EngineResult(reply_text=r.topic_explanation_after_opening(context.lead))
            context.transition_to(CallState.GATEKEEPER)
            return EngineResult(reply_text=r.gatekeeper_explain_topic(context.lead))

        if nlu.has(Intent.PERSON_NOT_AVAILABLE):
            context.transition_to(CallState.CALLBACK_REQUEST)
            return EngineResult(reply_text=r.person_not_available())

        if nlu.has(Intent.OFFER_TO_PASS_MESSAGE):
            context.transition_to(CallState.CALLBACK_REQUEST)
            return EngineResult(
                reply_text=f"{r.message_relay(context.lead)} {r.thanks_for_help()}"
            )

        # Einwaende
        if nlu.has(Intent.NO_TIME):
            context.transition_to(CallState.OBJECTION)
            return EngineResult(reply_text=f"{r.no_time_ack()} {r.ask_callback_time()}")

        if nlu.has(Intent.NO_BUDGET):
            context.transition_to(CallState.OBJECTION)
            return EngineResult(reply_text=r.no_budget_response())

        if nlu.has(Intent.ALREADY_HAVE_PROVIDER):
            context.transition_to(CallState.OBJECTION)
            text = r.already_have_provider_ack()
            offer = r.offer_design_as_comparison(context.lead)
            if offer and can_offer_design(context, self.max_rejections):
                context.design_offered = True
                context.transition_to(CallState.DESIGN_OFFER)
                text = f"{text} {offer}"
            return EngineResult(reply_text=text)

        if nlu.has(Intent.NO_WEBSITE_NEEDED):
            context.transition_to(CallState.OBJECTION)
            return EngineResult(reply_text=r.ask_social_media_or_alternative())

        if nlu.has(Intent.NO_WEBSITE):
            context.transition_to(CallState.DISCOVERY)
            text = r.no_website_pitch()
            offer = r.offer_design_no_website(context.lead)
            if offer and can_offer_design(context, self.max_rejections):
                context.design_offered = True
                context.transition_to(CallState.DESIGN_OFFER)
                text = f"{text} {offer}"
            return EngineResult(reply_text=text)

        if nlu.has(Intent.HAS_WEBSITE):
            context.transition_to(CallState.DISCOVERY)
            text = r.existing_website_note()
            offer = r.offer_design_existing_website(context.lead)
            if offer and can_offer_design(context, self.max_rejections):
                context.design_offered = True
                context.transition_to(CallState.DESIGN_OFFER)
                text = f"{text} {offer}"
            else:
                text = f"{text} {r.ask_current_website_satisfaction()}"
            return EngineResult(reply_text=text)

        if nlu.has(Intent.HAS_WEBSITE_SATISFIED):
            context.transition_to(CallState.OBJECTION)
            text = r.customer_satisfied_ack()
            offer = r.offer_design_as_comparison(context.lead)
            if offer and can_offer_design(context, self.max_rejections):
                context.design_offered = True
                context.transition_to(CallState.DESIGN_OFFER)
                text = f"{text} {offer}"
            return EngineResult(reply_text=text)

        # Kontaktweg-Wahl (Antwort auf "E-Mail oder WhatsApp?")
        if nlu.has(Intent.CHANNEL_CHOICE_EMAIL):
            context.preferred_contact = "EMAIL"
            context.transition_to(CallState.CONTACT_CAPTURE)
            if context.lead.has("email"):
                return EngineResult(reply_text=r.confirm_email_repeat(context.lead.email))
            return EngineResult(reply_text="Wie lautet Ihre E-Mail-Adresse?")

        if nlu.has(Intent.CHANNEL_CHOICE_WHATSAPP):
            context.preferred_contact = "WHATSAPP"
            context.transition_to(CallState.CONTACT_CAPTURE)
            if context.lead.has("telefonnummer"):
                return EngineResult(reply_text=r.confirm_phone_repeat(context.lead.telefonnummer))
            return EngineResult(reply_text="Unter welcher Nummer sind Sie auf WhatsApp erreichbar?")

        # Kontaktdaten
        if nlu.email:
            context.transition_to(CallState.CONTACT_CAPTURE)
            if is_valid_email(nlu.email):
                context.contact_value_pending = nlu.email
                context.preferred_contact = "EMAIL"
                return EngineResult(reply_text=r.confirm_email_repeat(nlu.email))
        if nlu.phone:
            context.transition_to(CallState.CONTACT_CAPTURE)
            if is_valid_phone(nlu.phone):
                context.contact_value_pending = nlu.phone
                context.preferred_contact = context.preferred_contact or "WHATSAPP"
                return EngineResult(reply_text=r.confirm_phone_repeat(nlu.phone))

        # Bestaetigung eines zuvor genannten Kontaktwerts
        if nlu.has(Intent.AFFIRMATION) and context.state == CallState.CONTACT_CAPTURE and context.contact_value_pending:
            context.contact_confirmed = True
            lead_updates: dict = {}
            if context.preferred_contact == "EMAIL":
                context.lead.email = context.contact_value_pending
                lead_updates["email"] = context.contact_value_pending
            elif context.preferred_contact == "WHATSAPP":
                context.lead.telefonnummer = context.contact_value_pending
                lead_updates["telefonnummer"] = context.contact_value_pending
            context.contact_value_pending = None
            return EngineResult(
                reply_text=r.handoff_note(),
                ready_to_send_email=context.preferred_contact == "EMAIL",
                ready_to_send_whatsapp=context.preferred_contact == "WHATSAPP",
                lead_updates=lead_updates,
            )

        # Zustimmung im richtigen Zustand -> Kontaktweg erfragen
        if nlu.has(Intent.AFFIRMATION):
            if context.state == CallState.DESIGN_OFFER:
                context.transition_to(CallState.CONTACT_CAPTURE)
                return EngineResult(reply_text=r.ask_contact_channel_for_design())
            if context.state == CallState.GATEKEEPER:
                context.transition_to(CallState.DISCOVERY)
                return EngineResult(
                    reply_text=f"{r.website_check_intro(context.lead)} {r.ask_current_website_satisfaction()}"
                )
            if context.state in (CallState.PITCH, CallState.DISCOVERY):
                context.transition_to(CallState.DESIGN_OFFER)
                context.design_offered = True
                text = r.offer_design_no_website(context.lead) or r.offer_design_as_comparison(
                    context.lead
                )
                return EngineResult(reply_text=text or r.ask_current_website_satisfaction())

        # Erste inhaltliche Aussage der zustaendigen Person -> Discovery starten
        if context.state in (CallState.INTRODUCTION, CallState.DECISION_MAKER):
            context.transition_to(CallState.DISCOVERY)
            intro = r.website_check_intro(context.lead)
            question = r.ask_current_website_satisfaction()
            return EngineResult(reply_text=f"{intro} {question}")

        # Kein spezifisches Muster erkannt: LLM fuer freie Formulierung nutzen,
        # sonst kontrollierter Fallback.
        return await self._llm_or_fallback(context, decision)

    async def _llm_or_fallback(
        self, context: ConversationContext, decision: RuleDecision
    ) -> EngineResult:
        from agent.guardrails import FALLBACK_UNKNOWN
        from agent.prompts import build_messages

        if self.llm_provider is not None:
            try:
                from agent.guardrails import strip_disallowed_audio_artifacts

                messages = build_messages(context, context.history[-1].text if context.history else "")
                timeout = min(float(self.settings.llama_timeout), 2.5)
                text = await asyncio.wait_for(
                    self.llm_provider.generate(messages, max_tokens=80, temperature=0.35),
                    timeout=timeout,
                )
                text = self._compact_voice_reply(strip_disallowed_audio_artifacts(text))
                if text:
                    return EngineResult(reply_text=text)
            except (LLMUnavailableError, TimeoutError):
                logger.info("LLM nicht verfuegbar, nutze Template-Fallback")

        return EngineResult(reply_text=self._contextual_fallback(context) or FALLBACK_UNKNOWN)

    def _contextual_fallback(self, context: ConversationContext) -> str:
        r = self.responses
        if context.state in (CallState.INTRODUCTION, CallState.PITCH):
            return r.topic_explanation_after_opening(context.lead)
        if context.state == CallState.DESIGN_OFFER:
            return r.ask_contact_channel_for_design()
        if context.state == CallState.CONTACT_CAPTURE:
            return r.contact_capture_help()
        if context.state == CallState.DISCOVERY:
            return r.contextual_unknown(context.lead)
        if context.state == CallState.CALLBACK_REQUEST:
            return r.ask_callback_time()
        return ""

    @staticmethod
    def _compact_voice_reply(text: str, max_chars: int = 260) -> str:
        """Keep live voice replies short enough that local TTS does not stall."""
        cleaned = re.sub(r"\s+", " ", text).strip()
        if len(cleaned) <= max_chars:
            return cleaned
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        kept: list[str] = []
        total = 0
        for sentence in sentences:
            if not sentence:
                continue
            next_total = total + len(sentence) + (1 if kept else 0)
            if kept and next_total > max_chars:
                break
            kept.append(sentence)
            total = next_total
            if len(kept) >= 2:
                break
        return " ".join(kept).strip() or cleaned[:max_chars].rsplit(" ", 1)[0].strip()
