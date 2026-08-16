"""Grundlegende State-Machine-Tests: keine unerlaubten Uebergaenge."""

from __future__ import annotations

from agent.state_machine import CallState, can_transition


def test_cannot_jump_from_initial_to_success():
    assert can_transition(CallState.INITIAL, CallState.SUCCESS) is False


def test_can_always_reach_do_not_call():
    for state in CallState:
        if state == CallState.ENDED:
            continue
        assert can_transition(state, CallState.DO_NOT_CALL) is True


def test_ended_is_truly_terminal():
    for state in CallState:
        assert can_transition(CallState.ENDED, state) is (state == CallState.ENDED)


def test_do_not_call_can_reach_goodbye_and_ended():
    assert can_transition(CallState.DO_NOT_CALL, CallState.GOODBYE) is True
    assert can_transition(CallState.GOODBYE, CallState.ENDED) is True


def test_self_transition_always_allowed():
    assert can_transition(CallState.DISCOVERY, CallState.DISCOVERY) is True
