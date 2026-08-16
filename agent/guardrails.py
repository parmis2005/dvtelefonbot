"""Harte, programmatisch erzwungene Regeln (Abschnitt 11 + 57 der Spezifikation).

Diese Regeln stehen NICHT nur im Prompt. Sie werden von der Response-Erzeugung
(agent/responses.py) und der Tool-Ausfuehrung (tools/call_tools.py) tatsaechlich
geprueft, sodass ein Verstoss technisch unmoeglich ist - unabhaengig davon, was
ein LLM "moechte".
"""

from __future__ import annotations

import re

from agent.context import ConversationContext, LeadData

FALLBACK_UNKNOWN = "Das kann unsere Geschaeftsleitung Ihnen persoenlich genauer beantworten."

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}$")
_PHONE_RE = re.compile(r"^\+?\d{6,15}$")


class GuardrailViolation(Exception):
    """Wird geworfen, wenn Code versucht, eine unbelegte Behauptung zu erzeugen."""


# --- Wahrheitsregeln -------------------------------------------------------


def can_claim_online_auftritt_geprueft(lead: LeadData) -> bool:
    return lead.online_auftritt_geprueft is True


def can_claim_entwurf_vorhanden(lead: LeadData) -> bool:
    return lead.entwurf_vorhanden is True


def assert_can_claim_online_auftritt_geprueft(lead: LeadData) -> None:
    if not can_claim_online_auftritt_geprueft(lead):
        raise GuardrailViolation(
            "Online-Auftritt wurde nicht geprueft - Behauptung 'wir haben uns Ihren "
            "Online-Auftritt angesehen' ist nicht zulaessig."
        )


def assert_can_claim_entwurf_vorhanden(lead: LeadData) -> None:
    if not can_claim_entwurf_vorhanden(lead):
        raise GuardrailViolation(
            "Kein Entwurf vorhanden - Behauptung 'wir haben bereits einen Entwurf "
            "vorbereitet' ist nicht zulaessig."
        )


# --- Zwei-Nein-Regel --------------------------------------------------------


def can_offer_design(context: ConversationContext, max_rejections: int) -> bool:
    """Nach dem Erreichen von max_rejections darf KEIN weiteres Angebot mehr erfolgen."""
    if context.rejection_count >= max_rejections:
        return False
    # beim ersten Nein darf hoechstens EINMAL nachgefragt werden
    return not (context.rejection_count == 1 and context.design_offered)


def must_end_acquisition(context: ConversationContext, max_rejections: int) -> bool:
    return context.rejection_count >= max_rejections


# --- Validierung von Kontaktdaten ------------------------------------------


def is_valid_email(email: str | None) -> bool:
    return bool(email) and bool(_EMAIL_RE.match(email.strip()))


def is_valid_phone(phone: str | None) -> bool:
    if not phone:
        return False
    cleaned = re.sub(r"[\s()/-]", "", phone.strip())
    return bool(_PHONE_RE.match(cleaned))


# --- Tool-Guardrails (Abschnitt 57) -----------------------------------------


def guard_send_email(lead: LeadData) -> tuple[bool, str]:
    if not is_valid_email(lead.email):
        return False, "Keine gueltige E-Mail-Adresse vorhanden."
    if not lead.entwurf_link:
        return False, "Kein Entwurf-Link hinterlegt - Versand nicht moeglich."
    return True, "ok"


def guard_send_whatsapp(lead: LeadData, provider_available: bool) -> tuple[bool, str]:
    if not is_valid_phone(lead.telefonnummer):
        return False, "Keine gueltige Telefonnummer vorhanden."
    if not provider_available:
        return False, "WhatsApp-Provider ist nicht konfiguriert - nur Nummer wird gespeichert."
    return True, "ok"


def guard_callback(callback_at: str | None) -> tuple[bool, str]:
    if not callback_at:
        return False, "Kein Rueckrufzeitpunkt angegeben."
    return True, "ok"


def guard_end_call(call_active: bool) -> tuple[bool, str]:
    if not call_active:
        return False, "Kein aktiver Call vorhanden."
    return True, "ok"


def guard_outbound_call(
    do_not_call: bool, phone_valid: bool, cooldown_ok: bool
) -> tuple[bool, str]:
    if do_not_call:
        return False, "Nummer steht auf der Do-Not-Call-Liste."
    if not phone_valid:
        return False, "Telefonnummer ist ungueltig."
    if not cooldown_ok:
        return False, "Cooldown zwischen Anrufen ist noch aktiv."
    return True, "ok"


def confirm_or_fallback(known: bool, statement: str, fallback: str = FALLBACK_UNKNOWN) -> str:
    """Generischer Guard: gib `statement` nur zurueck, wenn `known` True ist."""
    return statement if known else fallback


# --- Audio-Hygiene (Abschnitt 27) -------------------------------------------

_FILLER_PATTERNS = [
    r"\*[^*]*\*",  # *seufzt*, *raeuspert sich*
    r"\([^)]*(seufz|raeusper|atem|stöhn|stoehn)[^)]*\)",
    r"^\s*(hm+|ähm+|äh+|uhm+|hmm+)[.,!]?\s*",
]


def strip_disallowed_audio_artifacts(text: str) -> str:
    """Entfernt Seufzer/Fuelllaute/Regieanweisungen aus (insbesondere LLM-)Text,
    bevor er an die TTS geschickt wird - Dario soll nur bewusst erzeugten Text
    sprechen (Abschnitt 27)."""
    cleaned = text
    for pattern in _FILLER_PATTERNS:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()
