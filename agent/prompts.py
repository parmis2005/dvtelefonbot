"""Baut den LLM-Prompt-Kontext aus Systemprompt + Lead-Daten + Gespraechsverlauf.

Nur fuer die offenen, nicht sicherheitskritischen Gespraechsteile genutzt
(Discovery-Smalltalk, freie Rueckfragen). Alle sicherheitskritischen Aussagen
kommen aus agent/responses.py, nicht vom LLM.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from agent.context import ConversationContext

BASE_DIR = Path(__file__).resolve().parent.parent
SYSTEM_PROMPT_PATH = BASE_DIR / "prompts" / "dario_system_prompt.md"

MAX_HISTORY_TURNS = 8  # Prompt klein halten -> niedrigere Latenz


@lru_cache
def load_system_prompt() -> str:
    if not SYSTEM_PROMPT_PATH.exists():
        return "Du bist Dario, die digitale Assistenz von Digital Vision."
    return SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")


def build_lead_summary(context: ConversationContext) -> str:
    lead = context.lead
    lines = [f"Gespraechszustand: {context.state.value}"]
    if lead.has("unternehmen"):
        lines.append(f"Unternehmen: {lead.unternehmen}")
    if lead.has("ansprechpartner"):
        lines.append(f"Ansprechpartner: {lead.ansprechpartner}")
    if lead.has("branche"):
        lines.append(f"Branche: {lead.branche}")
    lines.append(f"Online-Auftritt geprueft: {'ja' if lead.online_auftritt_geprueft else 'nein'}")
    lines.append(f"Entwurf vorhanden: {'ja' if lead.entwurf_vorhanden else 'nein'}")
    lines.append(f"Anzahl eindeutiger Ablehnungen: {context.rejection_count}")
    return "\n".join(lines)


def build_messages(context: ConversationContext, user_utterance: str) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": load_system_prompt()}]
    messages.append({"role": "system", "content": build_lead_summary(context)})

    recent = context.history[-MAX_HISTORY_TURNS:]
    for turn in recent:
        role = "assistant" if turn.speaker == "dario" else "user"
        messages.append({"role": role, "content": turn.text})

    messages.append({"role": "user", "content": user_utterance})
    return messages
