"""Test 19 (Abschnitt 60): Call-Status-Uebergaenge."""

from __future__ import annotations

import pytest

from core.config import get_settings
from database.models import CallStatus
from services.call_service import CallService
from tests.factories import make_settings


@pytest.mark.asyncio
async def test_call_lifecycle_transitions(db_session, sample_lead):
    settings = get_settings()
    call_service = CallService(db_session, settings)

    call = await call_service.start_call(sample_lead.id)
    assert call.status == CallStatus.CREATED
    assert call.started_at is not None

    answered = await call_service.mark_answered(call.id)
    assert answered.status == CallStatus.ANSWERED
    assert answered.answered_at is not None

    completed = await call_service.complete(call.id, result="INTERESTED")
    assert completed.status == CallStatus.COMPLETED
    assert completed.ended_at is not None
    assert completed.duration is not None
    assert completed.result == "INTERESTED"


@pytest.mark.asyncio
async def test_busy_and_no_answer_are_recorded(db_session, sample_lead):
    settings = get_settings()
    call_service = CallService(db_session, settings)

    busy_call = await call_service.start_call(sample_lead.id)
    busy_result = await call_service.mark_busy(busy_call.id)
    assert busy_result.status == CallStatus.BUSY


@pytest.mark.asyncio
async def test_active_call_blocks_second_concurrent_call(db_session, sample_lead):
    # Cooldown bewusst auf 0 gesetzt, um den Aktiv-Call-Check isoliert von der
    # (ebenfalls sofort greifenden) Cooldown-Sperre zu pruefen.
    settings = make_settings(call_cooldown=0)
    call_service = CallService(db_session, settings)

    await call_service.start_call(sample_lead.id)
    allowed, reason = await call_service.can_start_call(sample_lead.id)
    assert allowed is False
    assert "aktiven" in reason


@pytest.mark.asyncio
async def test_cooldown_blocks_call_shortly_after_previous_one(db_session, sample_lead):
    settings = get_settings()
    call_service = CallService(db_session, settings)

    call = await call_service.start_call(sample_lead.id)
    await call_service.complete(call.id, result="NOT_INTERESTED")

    allowed, reason = await call_service.can_start_call(sample_lead.id)
    assert allowed is False
    assert "Cooldown" in reason
