"""Tests 10-16 (Abschnitt 60): Gatekeeper, Einwaende, Wuensche, Verabschiedung."""

from __future__ import annotations

import pytest

from agent.state_machine import CallState
from tests.factories import make_context, make_engine

# --- Feste Begruessung (verbindliche Gespraechsvorlage) --------------------


@pytest.mark.asyncio
async def test_opening_line_matches_mandated_greeting():
    """Die woertlich vorgegebene Begruessung ist deterministisch (kein LLM) -
    Dario fragt zuerst nach einem Moment Zeit, statt sofort nach der
    richtigen Ansprechperson fuer das jeweilige Unternehmen zu fragen (das
    passiert separat ueber die Gatekeeper-Logik, siehe Tests 10)."""
    engine = make_engine()
    ctx = make_context(state=CallState.INITIAL)

    opening = engine.opening_line(ctx)

    assert opening == (
        "Guten Tag! Hier ist Dario der digitale Assistent von Digital Vision aus "
        "Mönchengladbach. Haben Sie gerade einen Moment Zeit???"
    )


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


@pytest.mark.asyncio
async def test_farewell_after_confirmed_contact_uses_success_closing():
    """Regression: CallState.SUCCESS und agent/responses.py::success_closing()
    (Abschnitt 71 - erklaert die naechsten Schritte statt nur generisch
    'Auf Wiederhoeren' zu sagen) waren zuvor unerreichbarer Code - die
    Kontaktbestaetigung (Intent.AFFIRMATION bei ausstehendem Kontaktwert,
    siehe agent/conversation.py) setzte zwar `contact_confirmed`, aber keine
    nachfolgende Verabschiedung nutzte das jemals aus."""
    engine = make_engine()
    ctx = make_context(state=CallState.CONTACT_CAPTURE)
    ctx.contact_value_pending = "kunde@beispiel.de"
    ctx.preferred_contact = "EMAIL"

    confirm_result = await engine.handle_utterance(ctx, "Ja, das passt so.")
    assert ctx.contact_confirmed is True
    assert confirm_result.ready_to_send_email is True

    ctx.design_sent = True  # simuliert: tools.send_email lieferte success=True
    farewell_result = await engine.handle_utterance(ctx, "Vielen Dank, auf Wiederhoeren.")

    assert farewell_result.should_end_call is True
    assert farewell_result.reply_text == engine.responses.success_closing(True)
    assert farewell_result.reply_text != "Vielen Dank. Auf Wiederhoeren."
    assert ctx.state == CallState.GOODBYE
    assert ctx.previous_state == CallState.SUCCESS


@pytest.mark.asyncio
async def test_farewell_without_confirmed_contact_still_uses_generic_reply():
    """Gegenprobe: ohne bestaetigten Kontakt bleibt die bisherige, generische
    Verabschiedung unveraendert - success_closing() ist nur fuer den
    tatsaechlichen Erfolgsfall gedacht."""
    engine = make_engine()
    ctx = make_context()

    result = await engine.handle_utterance(ctx, "Vielen Dank, auf Wiederhoeren.")

    assert result.reply_text == "Vielen Dank. Auf Wiederhoeren."
    assert ctx.state == CallState.GOODBYE
