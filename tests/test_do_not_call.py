"""Tests 3+20 (Abschnitt 60): Do-Not-Call verhindert Calls und ist persistent."""

from __future__ import annotations

import pytest

from core.config import get_settings
from database.repository import DoNotCallRepository, LeadRepository
from services.call_service import CallService
from tools.do_not_call import is_do_not_call, set_do_not_call


@pytest.mark.asyncio
async def test_do_not_call_blocks_future_outbound_calls(db_session, sample_lead):
    settings = get_settings()
    call_service = CallService(db_session, settings)

    allowed_before, _ = await call_service.can_start_call(sample_lead.id)
    assert allowed_before is True

    await set_do_not_call(db_session, sample_lead.telefonnummer, sample_lead.id)

    allowed_after, reason = await call_service.can_start_call(sample_lead.id)
    assert allowed_after is False
    assert "Do-Not-Call" in reason


@pytest.mark.asyncio
async def test_do_not_call_persists_independent_of_lead_flag(db_session, sample_lead):
    """Test 20: die Sperre lebt in einer eigenen, dauerhaften Tabelle -
    nicht nur als Flag auf einem einzelnen Lead-Datensatz."""
    await set_do_not_call(db_session, sample_lead.telefonnummer, sample_lead.id)

    dnc_repo = DoNotCallRepository(db_session)
    assert await dnc_repo.is_blocked(sample_lead.telefonnummer) is True
    assert await is_do_not_call(db_session, sample_lead.telefonnummer) is True

    # auch ein komplett neuer Lead mit derselben Nummer ist gesperrt
    lead_repo = LeadRepository(db_session)
    new_lead = await lead_repo.create(
        unternehmen="Andere Firma unter gleicher Nummer",
        telefonnummer=sample_lead.telefonnummer,
    )
    assert new_lead.do_not_call is False  # Flag selbst nicht automatisch gesetzt...
    settings = get_settings()
    call_service = CallService(db_session, settings)
    allowed, _reason = await call_service.can_start_call(new_lead.id)
    assert allowed is False  # ...aber die nummernbasierte Sperre greift trotzdem
