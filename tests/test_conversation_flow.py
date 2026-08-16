"""Tests 10-16 (Abschnitt 60): Gatekeeper, Einwaende, Wuensche, Verabschiedung."""

from __future__ import annotations

import pytest

from agent.state_machine import CallState
from tests.factories import make_context, make_engine

# --- Test 10: Gatekeeper ---------------------------------------------------


@pytest.mark.asyncio
async def test_gatekeeper_topic_question_with_design():
    engine = make_engine()
    ctx = make_context(state=CallState.INTRODUCTION, entwurf_vorhanden=True)

    result = await engine.handle_utterance(ctx, "Worum geht es denn genau?")

    assert "Entwurf" in result.reply_text
    assert ctx.state == CallState.GATEKEEPER


@pytest.mark.asyncio
async def test_gatekeeper_topic_question_without_design():
    engine = make_engine()
    ctx = make_context(state=CallState.INTRODUCTION, entwurf_vorhanden=False)

    result = await engine.handle_utterance(ctx, "Worum geht es denn genau?")

    assert "bereits einen unverbindlichen Webseiten-Entwurf" not in result.reply_text
    assert "konkreten Vorschlag" in result.reply_text


# --- Test 11: kein Interesse -----------------------------------------------


@pytest.mark.asyncio
async def test_no_interest_first_time_offers_design_once():
    engine = make_engine()
    ctx = make_context()

    result = await engine.handle_utterance(ctx, "Wir haben kein Interesse.")

    assert result.should_end_call is False
    assert ctx.rejection_count == 1


# --- Test 12: keine Zeit ----------------------------------------------------


@pytest.mark.asyncio
async def test_no_time_asks_exactly_one_question():
    engine = make_engine()
    ctx = make_context()

    result = await engine.handle_utterance(ctx, "Ich habe gerade keine Zeit.")

    assert result.reply_text.count("?") == 1
    assert ctx.state == CallState.OBJECTION


# --- Test 13: kein Budget ----------------------------------------------------


@pytest.mark.asyncio
async def test_no_budget_offers_flexible_payment():
    engine = make_engine()
    ctx = make_context()

    result = await engine.handle_utterance(ctx, "Wir haben leider kein Budget dafuer.")

    assert "flexible Zahlungsmodelle" in result.reply_text
    # keine erfundenen Preise/Rabatte
    assert "%" not in result.reply_text


# --- Test 14: freundliche Wuensche -----------------------------------------


@pytest.mark.asyncio
async def test_friendly_wish_gets_matching_reply():
    engine = make_engine()
    ctx = make_context()

    result = await engine.handle_utterance(ctx, "Schoenen Tag noch!")

    assert "wuensche ich Ihnen auch" in result.reply_text


@pytest.mark.asyncio
async def test_plain_thanks_does_not_trigger_friendly_wish_reply():
    engine = make_engine()
    ctx = make_context()

    result = await engine.handle_utterance(ctx, "Danke.")

    assert "wuensche ich Ihnen auch" not in result.reply_text


# --- Test 15+16: Verabschiedung ohne Schleife ------------------------------


@pytest.mark.asyncio
async def test_farewell_ends_call_immediately():
    engine = make_engine()
    ctx = make_context()

    result = await engine.handle_utterance(ctx, "Vielen Dank. Tschuess.")

    assert result.should_end_call is True
    assert result.reply_text == "Vielen Dank. Auf Wiederhoeren."
    assert ctx.state == CallState.GOODBYE


@pytest.mark.asyncio
async def test_no_farewell_loop_second_farewell_not_processed_by_dario():
    """Nach dem end_call-Signal darf die Fassade (agent/dario.py) keine
    weiteren Antworten mehr generieren - das wird hier auf Engine-Ebene
    sichergestellt: das Ergebnis signalisiert klar `should_end_call`, sodass
    der Aufrufer (chat_test/call_controller) die Schleife beendet."""
    engine = make_engine()
    ctx = make_context()

    result = await engine.handle_utterance(ctx, "Auf Wiederhoeren.")

    assert result.should_end_call is True
    # keine zweite Verabschiedung/Wiederholung im selben Text
    assert result.reply_text.count("Wiederhoeren") == 1
