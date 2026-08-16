"""Regelbasierte Intent-/Entity-Erkennung fuer deutsche Gespraechssprache.

Bewusst NICHT dem LLM ueberlassen: sicherheitskritische Signale (Do-Not-Call,
Ablehnung, Wartesignale, Verabschiedung) muessen deterministisch erkannt
werden, damit die harten Regeln in rules.py/guardrails.py zuverlaessig
greifen - unabhaengig davon, ob/wie ein LLM verfuegbar ist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class Intent(str, Enum):
    DO_NOT_CALL = "DO_NOT_CALL"
    REJECTION = "REJECTION"
    AFFIRMATION = "AFFIRMATION"
    WAIT = "WAIT"
    RESUME_AFTER_WAIT = "RESUME_AFTER_WAIT"
    FAREWELL = "FAREWELL"
    FRIENDLY_WISH = "FRIENDLY_WISH"
    GATEKEEPER_ASK_TOPIC = "GATEKEEPER_ASK_TOPIC"
    PERSON_NOT_AVAILABLE = "PERSON_NOT_AVAILABLE"
    OFFER_TO_PASS_MESSAGE = "OFFER_TO_PASS_MESSAGE"
    NO_TIME = "NO_TIME"
    NO_BUDGET = "NO_BUDGET"
    ALREADY_HAVE_PROVIDER = "ALREADY_HAVE_PROVIDER"
    NO_WEBSITE_NEEDED = "NO_WEBSITE_NEEDED"
    HAS_WEBSITE_SATISFIED = "HAS_WEBSITE_SATISFIED"
    NO_WEBSITE = "NO_WEBSITE"
    ASK_IF_AI = "ASK_IF_AI"
    ASK_WHO_WILL_CALL = "ASK_WHO_WILL_CALL"
    ASK_PRICE = "ASK_PRICE"
    PROVIDE_EMAIL = "PROVIDE_EMAIL"
    PROVIDE_PHONE = "PROVIDE_PHONE"
    CHANNEL_CHOICE_EMAIL = "CHANNEL_CHOICE_EMAIL"
    CHANNEL_CHOICE_WHATSAPP = "CHANNEL_CHOICE_WHATSAPP"
    UNKNOWN = "UNKNOWN"


@dataclass
class NluResult:
    intents: list[Intent] = field(default_factory=list)
    email: str | None = None
    phone: str | None = None
    raw_text: str = ""

    def has(self, intent: Intent) -> bool:
        return intent in self.intents


_DO_NOT_CALL_PATTERNS = [
    r"ruf(en)?\s+sie?\s+mich\s+(bitte\s+)?nicht\s+mehr\s+an\b",
    r"nicht\s+mehr\s+(bei\s+mir\s+)?an(rufen)?\b",
    r"nicht\s+mehr\s+kontaktieren\b",
    r"l(ö|oe)schen\s+sie\s+(meine\s+)?nummer",
    r"keine\s+(weiteren\s+)?anrufe\s+mehr",
    r"bitte\s+nicht\s+mehr\s+kontaktieren",
    r"nehmen\s+sie\s+mich\s+von\s+(ihrer\s+)?liste",
    r"sperren\s+sie\s+(meine\s+)?nummer",
]

_REJECTION_PATTERNS = [
    r"\bkein\s+interesse\b",
    r"\bnein[,.]?\s*danke\b",
    r"\bnicht\s+interessiert\b",
    r"\bwollen\s+wir\s+nicht\b",
    r"\bbrauchen\s+wir\s+nicht\b",
    r"\bnein\b",
]

_AFFIRMATION_PATTERNS = [
    r"^\s*ja\b",
    r"\bgerne\b",
    r"\bja,?\s*bitte\b",
    r"\bklingt\s+gut\b",
    r"\bsehr\s+gerne\b",
    r"\beinverstanden\b",
]

_WAIT_PATTERNS = [
    r"einen\s+moment\b",
    r"moment\s+bitte\b",
    r"\bmoment\b",
    r"warten\s+sie\s+kurz",
    r"eine\s+sekunde\b",
    r"ich\s+schaue\s+kurz\b",
    r"ich\s+suche\s+(meine|kurz)\b",
    r"kurz\s+warten\b",
    r"bleiben\s+sie\s+kurz\s+dran\b",
]

_FAREWELL_PATTERNS = [
    r"auf\s+wieder(sehen|h(ö|oe|o)ren)",
    r"tsch(ü|ue|u)ss",
    r"ciao\b",
    r"macht'?s?\s+gut\b",
]

_FRIENDLY_WISH_PATTERNS = [
    r"sch(ö|oe)nen?\s+tag\b",
    r"sch(ö|oe)nes?\s+wochenende\b",
    r"noch\s+einen\s+sch(ö|oe)nen\b",
]

_GATEKEEPER_TOPIC_PATTERNS = [r"worum\s+geht\s+es", r"worum\s+geht'?s", r"was\s+m(ö|oe)chten\s+sie"]
_PERSON_NOT_AVAILABLE_PATTERNS = [
    r"(ist|sind)\s+(heute\s+)?nicht\s+da\b",
    r"nicht\s+im\s+haus\b",
    r"gerade\s+nicht\s+erreichbar\b",
    r"nicht\s+anwesend\b",
]
_OFFER_MESSAGE_PATTERNS = [r"soll\s+ich\s+(etwas|was)\s+ausrichten", r"etwas\s+ausrichten\b"]
_NO_TIME_PATTERNS = [r"keine\s+zeit\b", r"habe\s+gerade\s+zu\s+tun\b", r"passt\s+gerade\s+nicht\b"]
_NO_BUDGET_PATTERNS = [
    r"kein\s+budget\b",
    r"zu\s+teuer\b",
    r"k(ö|oe)nnen\s+wir\s+uns\s+nicht\s+leisten",
]
_ALREADY_HAVE_PATTERNS = [
    r"haben\s+(schon|bereits)\s+jemand",
    r"haben\s+(schon|bereits)\s+eine[n]?\s+agentur",
    r"arbeiten\s+schon\s+mit\b",
]
_NO_WEBSITE_NEEDED_PATTERNS = [r"brauchen\s+keine\s+webseite", r"keine\s+webseite\s+n(ö|oe)tig"]
_NO_WEBSITE_PATTERNS = [
    r"haben\s+keine\s+webseite\b",
    r"nur\s+(instagram|facebook|social\s+media)\b",
    r"noch\s+keine\s+webseite\b",
]
_HAS_WEBSITE_SATISFIED_PATTERNS = [
    r"\bzufrieden\b",
    r"passt\s+f(ü|u)r\s+uns\b",
    r"brauchen\s+nichts\s+(neues|(ä|ae)ndern)\b",
]
_ASK_IF_AI_PATTERNS = [
    r"sind\s+sie\s+ein[e]?\s+ki\b",
    r"sind\s+sie\s+ein\s+bot\b",
    r"bin\s+ich\s+mit\s+einem\s+computer\b",
    r"ist\s+das\s+ein\s+roboter\b",
    r"sprech(e)?\s+ich\s+mit\s+einer\s+maschine\b",
    r"k(ü|ue)nstliche\s+intelligenz\b",
]
_ASK_WHO_WILL_CALL_PATTERNS = [r"wer\s+meldet\s+sich", r"wer\s+ruft\s+(mich\s+)?an", r"wer\s+kontaktiert\s+mich"]
_ASK_PRICE_PATTERNS = [r"was\s+kostet", r"wie\s+teuer", r"welche\s+preise", r"was\s+kosten\s+sie"]
_CHANNEL_EMAIL_PATTERNS = [r"per\s+e-?mail\b", r"^\s*e-?mail\s*$", r"lieber\s+e-?mail\b"]
_CHANNEL_WHATSAPP_PATTERNS = [r"per\s+whatsapp\b", r"^\s*whatsapp\s*$", r"lieber\s+whatsapp\b"]

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"(\+?\d[\d\s()/-]{6,}\d)")

_SPOKEN_EMAIL_REPLACEMENTS = [
    (r"\s+at\s+", "@"),
    (r"\s+ät\s+", "@"),
    (r"\s+klammeraffe\s+", "@"),
    (r"\s+punkt\s+", "."),
    (r"\s+dot\s+", "."),
    (r"\s+minus\s+", "-"),
    (r"\s+unterstrich\s+", "_"),
    (r"\s+bindestrich\s+", "-"),
]


def normalize_spoken_email(text: str) -> str | None:
    """"info at firma punkt de" -> "info@firma.de"

    Ersetzt nur die gesprochenen Trenner (at/punkt/...) durch Symbole und
    laesst umgebende Woerter unangetastet, damit eine eingebettete E-Mail
    ("also, das waere info at firma punkt de gewesen") korrekt isoliert
    werden kann statt den ganzen Satz zusammenzuziehen.
    """
    candidate = text.strip().lower()
    for pattern, repl in _SPOKEN_EMAIL_REPLACEMENTS:
        candidate = re.sub(pattern, repl, candidate)
    match = _EMAIL_RE.search(candidate)
    return match.group(0) if match else None


def extract_email(text: str) -> str | None:
    direct = _EMAIL_RE.search(text)
    if direct:
        return direct.group(0)
    return normalize_spoken_email(text)


def extract_phone(text: str) -> str | None:
    match = _PHONE_RE.search(text)
    if not match:
        return None
    candidate = re.sub(r"[\s()/-]", "", match.group(1))
    return candidate


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in patterns)


def analyze(text: str) -> NluResult:
    text_norm = text.strip().lower()
    result = NluResult(raw_text=text)

    intent_pattern_map = [
        (Intent.DO_NOT_CALL, _DO_NOT_CALL_PATTERNS),
        (Intent.FAREWELL, _FAREWELL_PATTERNS),
        (Intent.FRIENDLY_WISH, _FRIENDLY_WISH_PATTERNS),
        (Intent.WAIT, _WAIT_PATTERNS),
        (Intent.GATEKEEPER_ASK_TOPIC, _GATEKEEPER_TOPIC_PATTERNS),
        (Intent.PERSON_NOT_AVAILABLE, _PERSON_NOT_AVAILABLE_PATTERNS),
        (Intent.OFFER_TO_PASS_MESSAGE, _OFFER_MESSAGE_PATTERNS),
        (Intent.NO_TIME, _NO_TIME_PATTERNS),
        (Intent.NO_BUDGET, _NO_BUDGET_PATTERNS),
        (Intent.ALREADY_HAVE_PROVIDER, _ALREADY_HAVE_PATTERNS),
        (Intent.NO_WEBSITE_NEEDED, _NO_WEBSITE_NEEDED_PATTERNS),
        (Intent.NO_WEBSITE, _NO_WEBSITE_PATTERNS),
        (Intent.HAS_WEBSITE_SATISFIED, _HAS_WEBSITE_SATISFIED_PATTERNS),
        (Intent.ASK_IF_AI, _ASK_IF_AI_PATTERNS),
        (Intent.ASK_WHO_WILL_CALL, _ASK_WHO_WILL_CALL_PATTERNS),
        (Intent.ASK_PRICE, _ASK_PRICE_PATTERNS),
        (Intent.CHANNEL_CHOICE_EMAIL, _CHANNEL_EMAIL_PATTERNS),
        (Intent.CHANNEL_CHOICE_WHATSAPP, _CHANNEL_WHATSAPP_PATTERNS),
        (Intent.REJECTION, _REJECTION_PATTERNS),
        (Intent.AFFIRMATION, _AFFIRMATION_PATTERNS),
    ]
    for intent, patterns in intent_pattern_map:
        if _matches_any(text_norm, patterns):
            result.intents.append(intent)

    email = extract_email(text)
    if email:
        result.email = email
        result.intents.append(Intent.PROVIDE_EMAIL)

    phone = extract_phone(text)
    if phone and len(phone) >= 7:
        result.phone = phone
        result.intents.append(Intent.PROVIDE_PHONE)

    if not result.intents:
        result.intents.append(Intent.UNKNOWN)

    return result
