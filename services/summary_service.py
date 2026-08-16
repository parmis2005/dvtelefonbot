"""Erzeugt die strukturierte Gespraechszusammenfassung nach Abschnitt 42.

Rein deterministisch aus dem strukturierten ConversationContext erzeugt -
kein Chain-of-Thought, keine erfundenen Inhalte.
"""

from __future__ import annotations

from agent.context import ConversationContext
from agent.state_machine import CallState

_RESULT_LABELS = {
    "INTERESTED": "Interessiert",
    "NOT_INTERESTED": "Kein Interesse",
    "DESIGN_SENT": "Entwurf versendet",
    "CALLBACK_REQUESTED": "Rueckruf gewuenscht",
    "DO_NOT_CALL": "Keine weiteren Anrufe (Do-Not-Call)",
    "GATEKEEPER_ONLY": "Nur mit Empfang/Assistenz gesprochen",
    "NO_ANSWER": "Nicht erreicht",
    None: "Unklar",
}


def _infer_result(context: ConversationContext) -> str:
    if context.do_not_call_triggered:
        return "DO_NOT_CALL"
    if context.design_sent:
        return "DESIGN_SENT"
    if context.callback_requested_at or context.state == CallState.CALLBACK_REQUEST:
        return "CALLBACK_REQUESTED"
    if context.state == CallState.REJECTED or context.rejection_count >= 2:
        return "NOT_INTERESTED"
    if context.contact_confirmed or context.state == CallState.SUCCESS:
        return "INTERESTED"
    if context.state in (CallState.GATEKEEPER, CallState.CALLBACK_REQUEST):
        return "GATEKEEPER_ONLY"
    return context.call_result


def build_summary(context: ConversationContext) -> str:
    lead = context.lead
    result_key = context.call_result or _infer_result(context)
    result_label = _RESULT_LABELS.get(result_key, result_key or "Unklar")

    lines = [
        "Unternehmen:",
        lead.unternehmen or "-",
        "",
        "Ansprechpartner:",
        lead.ansprechpartner or "-",
        "",
        "Ergebnis:",
        result_label,
        "",
        "Entwurf:",
        ("Versendet" if context.design_sent else "Angeboten" if context.design_offered else "Nicht angeboten"),
        "",
        "Kontaktweg:",
        context.preferred_contact or "-",
        "",
        "Rueckruf:",
        context.callback_requested_at or "-",
        "",
        "Wuensche:",
    ]
    if context.collected_notes:
        lines.extend(f"- {note}" for note in context.collected_notes)
    else:
        lines.append("- keine erfasst")

    lines.extend(
        [
            "",
            "Naechster Schritt:",
            "Geschaeftsleitung kontaktieren" if result_key in ("INTERESTED", "DESIGN_SENT", "CALLBACK_REQUESTED") else "Keine weitere Aktion",
        ]
    )
    return "\n".join(lines)
