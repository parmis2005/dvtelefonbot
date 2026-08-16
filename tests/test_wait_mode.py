"""Test 8 (Abschnitt 60): Wait Mode - kein Text waehrend des Wartens,
kein Fuellaut, korrekte Fortsetzung nach dem Warten."""

from __future__ import annotations

import pytest

from agent.state_machine import CallState
from tests.factories import make_context, make_engine


@pytest.mark.asyncio
async def test_wait_phrase_triggers_wait_mode_with_fixed_ack():
    engine = make_engine()
    ctx = make_context()

    result = await engine.handle_utterance(ctx, "Einen Moment bitte.")

    assert ctx.wait_mode is True
    assert result.reply_text in ("Kein Problem. Ich warte.", "Natuerlich, kein Problem. Ich warte.")
    assert ctx.state == CallState.WAITING


@pytest.mark.asyncio
async def test_no_output_while_still_waiting():
    engine = make_engine()
    ctx = make_context()
    await engine.handle_utterance(ctx, "Moment, ich schaue kurz.")

    # Kunde sagt waehrend des Wartens erneut "Moment" -> weiterhin Wait Mode,
    # kein neuer Fuelltext.
    result = await engine.handle_utterance(ctx, "Moment.")
    assert ctx.wait_mode is True
    assert result.reply_text == ""


@pytest.mark.asyncio
async def test_customer_speaking_resumes_from_wait():
    engine = make_engine()
    ctx = make_context(state=CallState.DISCOVERY)
    await engine.handle_utterance(ctx, "Einen Moment bitte.")
    assert ctx.wait_mode is True

    await engine.handle_utterance(ctx, "So, jetzt bin ich wieder da.")

    assert ctx.wait_mode is False
    assert ctx.state != CallState.WAITING
