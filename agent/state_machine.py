"""Conversation State Machine.

WICHTIG: Das LLM darf NIEMALS allein bestimmen, in welchem Zustand sich
ein Gespraech befindet. Zustandsuebergaenge laufen ausschliesslich ueber
diese Klasse, gesteuert durch erkannte Intents (agent/nlu.py).
"""

from __future__ import annotations

import enum


class CallState(str, enum.Enum):
    INITIAL = "INITIAL"
    INTRODUCTION = "INTRODUCTION"
    GATEKEEPER = "GATEKEEPER"
    DECISION_MAKER = "DECISION_MAKER"
    DISCOVERY = "DISCOVERY"
    PITCH = "PITCH"
    DESIGN_OFFER = "DESIGN_OFFER"
    CONTACT_CAPTURE = "CONTACT_CAPTURE"
    OBJECTION = "OBJECTION"
    CALLBACK_REQUEST = "CALLBACK_REQUEST"
    WAITING = "WAITING"
    SUCCESS = "SUCCESS"
    REJECTED = "REJECTED"
    DO_NOT_CALL = "DO_NOT_CALL"
    GOODBYE = "GOODBYE"
    ENDED = "ENDED"


# Zustand, aus dem es keinen Ausgang mehr gibt. DO_NOT_CALL ist bewusst NICHT
# terminal in diesem Sinn - er muss noch GOODBYE/ENDED erreichen koennen,
# darf aber (siehe _ALLOWED_TRANSITIONS) nie in ein aktives Verkaufsstadium
# zurueckfallen.
TERMINAL_STATES = {CallState.ENDED}

# Erlaubte Uebergaenge. Jeder Zustand darf zusaetzlich IMMER in DO_NOT_CALL,
# GOODBYE oder ENDED wechseln (sicherheitskritische Ausstiege), das wird
# separat in `can_transition` behandelt statt hier dupliziert zu werden.
_ALLOWED_TRANSITIONS: dict[CallState, set[CallState]] = {
    CallState.INITIAL: {CallState.INTRODUCTION},
    CallState.INTRODUCTION: {
        CallState.GATEKEEPER,
        CallState.DECISION_MAKER,
        CallState.DISCOVERY,
        CallState.OBJECTION,
    },
    CallState.GATEKEEPER: {
        CallState.DECISION_MAKER,
        CallState.CALLBACK_REQUEST,
        CallState.OBJECTION,
        CallState.WAITING,
    },
    CallState.DECISION_MAKER: {CallState.DISCOVERY, CallState.OBJECTION, CallState.WAITING},
    CallState.DISCOVERY: {
        CallState.PITCH,
        CallState.DESIGN_OFFER,
        CallState.OBJECTION,
        CallState.WAITING,
    },
    CallState.PITCH: {CallState.DESIGN_OFFER, CallState.OBJECTION, CallState.WAITING},
    CallState.DESIGN_OFFER: {
        CallState.CONTACT_CAPTURE,
        CallState.OBJECTION,
        CallState.REJECTED,
        CallState.WAITING,
    },
    CallState.CONTACT_CAPTURE: {CallState.SUCCESS, CallState.OBJECTION, CallState.WAITING},
    CallState.OBJECTION: {
        CallState.DESIGN_OFFER,
        CallState.PITCH,
        CallState.REJECTED,
        CallState.CALLBACK_REQUEST,
        CallState.DISCOVERY,
        CallState.WAITING,
    },
    CallState.CALLBACK_REQUEST: {CallState.SUCCESS, CallState.WAITING},
    CallState.WAITING: set(),  # kehrt zum vorherigen Zustand zurueck, siehe context.py
    CallState.SUCCESS: {CallState.GOODBYE},
    CallState.REJECTED: {CallState.GOODBYE},
    CallState.DO_NOT_CALL: {CallState.GOODBYE},
    CallState.GOODBYE: {CallState.ENDED},
    CallState.ENDED: set(),
}

# Sicherheitskritische Ausstiege sind aus JEDEM (nicht-terminalen) Zustand erlaubt.
_ALWAYS_ALLOWED_TARGETS = {CallState.DO_NOT_CALL, CallState.GOODBYE, CallState.WAITING}


def can_transition(current: CallState, target: CallState) -> bool:
    if target == current:
        return True  # Verweilen im aktuellen Zustand ist immer erlaubt
    if current in TERMINAL_STATES:
        return False  # terminal Zustaende sind final
    if target in _ALWAYS_ALLOWED_TARGETS:
        return True
    return target in _ALLOWED_TRANSITIONS.get(current, set())


class InvalidTransitionError(Exception):
    pass


def transition(current: CallState, target: CallState) -> CallState:
    if not can_transition(current, target):
        raise InvalidTransitionError(f"Uebergang {current} -> {target} ist nicht erlaubt")
    return target
