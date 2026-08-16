"""Geschaeftsregeln: entscheidet auf Basis von erkannten Intents + Kontext,
wie sich der Gespraechs-Zustand aendert. Trifft KEINE Sprachentscheidungen
(das macht agent/responses.py) - nur Zustands-/Flag-Entscheidungen.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.context import ConversationContext
from agent.nlu import Intent, NluResult
from agent.state_machine import CallState


@dataclass
class RuleDecision:
    next_state: CallState
    trigger_do_not_call: bool = False
    trigger_end_call: bool = False
    offer_design_now: bool = False
    ask_farewell_reply: bool = False
    note: str | None = None


def apply(
    context: ConversationContext,
    nlu: NluResult,
    max_rejections: int,
) -> RuleDecision:
    # 1. Do-Not-Call hat IMMER absolute Prioritaet - keine Ausnahme.
    if nlu.has(Intent.DO_NOT_CALL):
        context.do_not_call_triggered = True
        context.call_result = "DO_NOT_CALL"
        return RuleDecision(
            next_state=CallState.DO_NOT_CALL, trigger_do_not_call=True, trigger_end_call=False
        )

    # 2. Wait Mode: waehrend des Wartens wird sonst nichts verarbeitet.
    if context.wait_mode:
        if nlu.has(Intent.WAIT):
            return RuleDecision(next_state=CallState.WAITING)
        # jede andere Aeusserung beendet den Wait Mode (Kunde spricht wieder)
        context.resume_from_wait()
        return RuleDecision(next_state=context.state, note="resume_from_wait")

    if nlu.has(Intent.WAIT):
        return RuleDecision(next_state=CallState.WAITING)

    # 3. Verabschiedung - keine Schleifen, sofort end_call nach Erwiderung.
    if nlu.has(Intent.FAREWELL):
        return RuleDecision(
            next_state=CallState.GOODBYE, trigger_end_call=True, ask_farewell_reply=True
        )

    # 4. Ablehnung / Zwei-Nein-Regel
    if nlu.has(Intent.REJECTION):
        count = context.register_rejection()
        if count >= max_rejections:
            context.call_result = context.call_result or "NOT_INTERESTED"
            return RuleDecision(next_state=CallState.REJECTED, trigger_end_call=False)
        # erstes Nein: hoechstens einmal Entwurf anbieten (falls noch nicht geschehen)
        offer_now = not context.design_offered
        return RuleDecision(next_state=CallState.OBJECTION, offer_design_now=offer_now)

    # 5. Gatekeeper-Signale
    if nlu.has(Intent.PERSON_NOT_AVAILABLE):
        return RuleDecision(next_state=CallState.CALLBACK_REQUEST)
    if nlu.has(Intent.OFFER_TO_PASS_MESSAGE):
        return RuleDecision(next_state=CallState.CALLBACK_REQUEST)
    if nlu.has(Intent.GATEKEEPER_ASK_TOPIC):
        return RuleDecision(next_state=CallState.GATEKEEPER)

    # 6. Einwaende
    if nlu.has(Intent.NO_TIME) or nlu.has(Intent.NO_BUDGET) or nlu.has(
        Intent.ALREADY_HAVE_PROVIDER
    ) or nlu.has(Intent.HAS_WEBSITE_SATISFIED) or nlu.has(Intent.NO_WEBSITE_NEEDED):
        return RuleDecision(next_state=CallState.OBJECTION)

    # 7. Discovery-Signale
    if nlu.has(Intent.NO_WEBSITE):
        return RuleDecision(next_state=CallState.DISCOVERY)

    # 8. Kontaktdaten geliefert
    if nlu.has(Intent.PROVIDE_EMAIL) or nlu.has(Intent.PROVIDE_PHONE):
        return RuleDecision(next_state=CallState.CONTACT_CAPTURE)

    # 9. Zustimmung -> je nach aktuellem Zustand weiter
    if nlu.has(Intent.AFFIRMATION):
        if context.state in (CallState.DESIGN_OFFER,):
            return RuleDecision(next_state=CallState.CONTACT_CAPTURE)
        if context.state in (CallState.PITCH, CallState.DISCOVERY):
            return RuleDecision(next_state=CallState.DESIGN_OFFER)

    # Standard: im aktuellen Zustand bleiben (LLM/Template generiert freie Antwort)
    return RuleDecision(next_state=context.state)
