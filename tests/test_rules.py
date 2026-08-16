"""Tests 1+2 (Abschnitt 60): Zwei-Nein-Regel."""

from __future__ import annotations

import pytest

from agent.state_machine import CallState
from tests.factories import make_context, make_engine


@pytest.mark.asyncio
async def test_first_rejection_offers_design_once():
    engine = make_engine()
    ctx = make_context()

    result = await engine.handle_utterance(ctx, "Kein Interesse.")

    assert ctx.rejection_count == 1
    assert ctx.design_offered is True
    assert "zusenden" in result.reply_text or "Darf ich" in result.reply_text
    assert ctx.state != CallState.ENDED


@pytest.mark.asyncio
async def test_second_rejection_ends_acquisition_without_further_pitch():
    engine = make_engine()
    ctx = make_context()

    await engine.handle_utterance(ctx, "Kein Interesse.")
    result = await engine.handle_utterance(ctx, "Nein, wirklich nicht.")

    assert ctx.rejection_count >= 2
    assert result.should_end_call is True
    assert "zusenden" not in result.reply_text
    assert result.reply_text == "Alles klar, gar kein Problem. Vielen Dank fuer Ihre Zeit."


@pytest.mark.asyncio
async def test_rejection_without_design_never_claims_one():
    engine = make_engine()
    ctx = make_context(entwurf_vorhanden=False)

    result = await engine.handle_utterance(ctx, "Kein Interesse.")

    assert "bereits einen unverbindlichen Entwurf vorbereitet" not in result.reply_text
    assert ctx.design_offered is False
