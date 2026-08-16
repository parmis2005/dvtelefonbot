"""Conversation Context: der vollstaendige, strukturierte Zustand eines Anrufs.

Enthaelt sowohl die Lead-Variablen (Abschnitt 10 der Spezifikation) als auch
den Gespraechs-Fortschritt (State Machine, Ablehnungen, Wait Mode, etc).
Nichts davon wird "erraten" - es wird explizit gesetzt und vom Code geprueft.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from agent.state_machine import CallState, transition


@dataclass
class Turn:
    speaker: str  # "dario" | "kunde"
    text: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class LeadData:
    """Entspricht 1:1 den Lead-Variablen aus der Spezifikation (Abschnitt 10).

    Leere Felder duerfen NIEMALS laut vorgelesen werden - das wird von
    agent/guardrails.py erzwungen, nicht nur durch den Prompt.
    """

    unternehmen: str = ""
    ansprechpartner: str = ""
    branche: str = ""
    website_url: str = ""
    online_auftritt_geprueft: bool = False
    entwurf_vorhanden: bool = False
    entwurf_link: str = ""
    notizen: str = ""
    telefonnummer: str = ""
    email: str = ""

    def has(self, field_name: str) -> bool:
        value = getattr(self, field_name, "")
        if isinstance(value, bool):
            return value
        return bool(value and value.strip())


@dataclass
class ConversationContext:
    lead: LeadData = field(default_factory=LeadData)

    state: CallState = CallState.INITIAL
    previous_state: CallState | None = None
    state_before_wait: CallState | None = None

    rejection_count: int = 0
    design_offered: bool = False
    contact_confirmed: bool = False
    design_sent: bool = False
    callback_requested_at: str | None = None
    do_not_call_triggered: bool = False
    call_result: str | None = None

    wait_mode: bool = False
    wait_started_at: datetime | None = None
    still_there_asked: bool = False

    preferred_contact: str | None = None  # "EMAIL" | "WHATSAPP"
    contact_value_pending: str | None = None  # noch nicht bestaetigter Wert

    history: list[Turn] = field(default_factory=list)
    collected_notes: list[str] = field(default_factory=list)

    def add_turn(self, speaker: str, text: str) -> None:
        self.history.append(Turn(speaker=speaker, text=text))

    def transition_to(self, target: CallState) -> None:
        if target == CallState.WAITING and self.state != CallState.WAITING:
            self.state_before_wait = self.state
        new_state = transition(self.state, target)
        self.previous_state = self.state
        self.state = new_state

    def resume_from_wait(self) -> None:
        if self.state == CallState.WAITING and self.state_before_wait is not None:
            self.previous_state = self.state
            self.state = self.state_before_wait
            self.state_before_wait = None
        self.wait_mode = False
        self.wait_started_at = None
        self.still_there_asked = False

    def register_rejection(self) -> int:
        self.rejection_count += 1
        return self.rejection_count

    def transcript_text(self) -> str:
        lines = []
        for turn in self.history:
            label = "Dario" if turn.speaker == "dario" else "Kunde"
            lines.append(f"{label}: {turn.text}")
        return "\n".join(lines)
