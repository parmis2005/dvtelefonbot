"""Tests fuer services/campaign_service.py::CampaignManager.

Nutzt einen Fake-TwilioProvider statt des echten Twilio-SDK - es darf in
Tests NIE ein echter, kostenpflichtiger Anruf ausgeloest werden. Simuliert
den Abschluss eines Anrufs manuell (Call-Status setzen), da die eigentliche
Media-Stream-Session (api/twilio.py) hier nicht laeuft.

Pruefungen lesen bewusst ueber eine FRISCHE Session (get_session_factory()),
nicht ueber die lang lebende `db_session`-Fixture: der CampaignManager
arbeitet mit eigenen, kurzlebigen Sessions (wie es echte parallele
API-Requests auch taeten), und SQLAlchemys Identity Map wuerde auf einer
wiederverwendeten Session sonst veraltete, im Speicher gecachte Objekte
liefern statt der von diesen fremden Sessions committeten Aenderungen.
"""

from __future__ import annotations

import asyncio
import json
from typing import ClassVar

import pytest
import pytest_asyncio

import services.campaign_service as campaign_service_module
from core.config import get_settings
from database.database import get_session_factory
from database.models import CallResult, CallStatus, CampaignStatus
from database.repository import CallRepository, CampaignRepository, LeadRepository
from services.campaign_service import CampaignManager


class FakeTwilioProvider:
    calls_made: ClassVar[list[str]] = []

    def __init__(self, account_sid: str, auth_token: str, caller_id: str):
        pass

    def start_outbound_call(self, to_number: str, twiml_webhook_url: str) -> str:
        FakeTwilioProvider.calls_made.append(to_number)
        return f"CAfake{len(FakeTwilioProvider.calls_made)}"


@pytest_asyncio.fixture(autouse=True)
async def _campaign_test_env(db_session, monkeypatch):
    FakeTwilioProvider.calls_made = []
    monkeypatch.setattr(campaign_service_module, "TwilioProvider", FakeTwilioProvider)
    monkeypatch.setattr(campaign_service_module, "POLL_INTERVAL_SECONDS", 0.05)
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tokentest")
    monkeypatch.setenv("TWILIO_CALLER_ID", "+491700000000")
    monkeypatch.setenv("TWILIO_PUBLIC_BASE_URL", "https://example-tunnel.test")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def _make_leads(session, count: int, do_not_call_indices: set[int] | None = None) -> list[int]:
    do_not_call_indices = do_not_call_indices or set()
    repo = LeadRepository(session)
    ids = []
    for i in range(count):
        lead = await repo.create(
            unternehmen=f"Firma {i}",
            telefonnummer=f"+4917000000{i:02d}",
            do_not_call=(i in do_not_call_indices),
        )
        ids.append(lead.id)
    return ids


async def _campaign_calls(campaign_id: int):
    async with get_session_factory()() as session:
        return await CallRepository(session).list_for_campaign(campaign_id)


async def _campaign(campaign_id: int):
    async with get_session_factory()() as session:
        return await CampaignRepository(session).get(campaign_id)


async def _mark_ended(call_id: int, status: CallStatus, result: CallResult) -> None:
    async with get_session_factory()() as session:
        await CallRepository(session).mark_ended(call_id, status, result=result)


async def _wait_until(condition, timeout: float = 3.0) -> None:
    elapsed = 0.0
    step = 0.05
    while elapsed < timeout:
        if await condition():
            return
        await asyncio.sleep(step)
        elapsed += step
    raise AssertionError("Bedingung nicht innerhalb des Timeouts erfuellt")


async def _len_eq(coro, expected: int) -> bool:
    result = await coro
    return len(result) == expected


@pytest.mark.asyncio
async def test_campaign_launches_up_to_max_concurrent(db_session):
    lead_ids = await _make_leads(db_session, 3)
    campaign = await CampaignRepository(db_session).create(
        name="Testkampagne", lead_ids_json=json.dumps(lead_ids), max_concurrent=2
    )
    manager = CampaignManager()
    await manager.start(campaign.id)

    await _wait_until(lambda: _len_eq(_campaign_calls(campaign.id), 2))
    calls = await _campaign_calls(campaign.id)
    assert all(c.status == CallStatus.CREATED for c in calls)
    assert len(FakeTwilioProvider.calls_made) == 2

    await manager.stop(campaign.id)


@pytest.mark.asyncio
async def test_campaign_frees_slot_when_call_ends(db_session):
    lead_ids = await _make_leads(db_session, 3)
    campaign = await CampaignRepository(db_session).create(
        name="Testkampagne", lead_ids_json=json.dumps(lead_ids), max_concurrent=2
    )
    manager = CampaignManager()
    await manager.start(campaign.id)

    await _wait_until(lambda: _len_eq(_campaign_calls(campaign.id), 2))
    calls = await _campaign_calls(campaign.id)
    await _mark_ended(calls[0].id, CallStatus.COMPLETED, CallResult.NOT_INTERESTED)

    await _wait_until(lambda: _len_eq(_campaign_calls(campaign.id), 3))
    await manager.stop(campaign.id)


@pytest.mark.asyncio
async def test_campaign_completes_when_all_done(db_session):
    lead_ids = await _make_leads(db_session, 2)
    campaign = await CampaignRepository(db_session).create(
        name="Testkampagne", lead_ids_json=json.dumps(lead_ids), max_concurrent=5
    )
    manager = CampaignManager()
    await manager.start(campaign.id)

    await _wait_until(lambda: _len_eq(_campaign_calls(campaign.id), 2))
    calls = await _campaign_calls(campaign.id)
    for call in calls:
        await _mark_ended(call.id, CallStatus.COMPLETED, CallResult.NOT_INTERESTED)

    async def campaign_completed() -> bool:
        c = await _campaign(campaign.id)
        return c.status == CampaignStatus.COMPLETED

    await _wait_until(campaign_completed)


@pytest.mark.asyncio
async def test_campaign_skips_do_not_call_leads(db_session):
    lead_ids = await _make_leads(db_session, 2, do_not_call_indices={0})
    campaign = await CampaignRepository(db_session).create(
        name="Testkampagne", lead_ids_json=json.dumps(lead_ids), max_concurrent=5
    )
    manager = CampaignManager()
    await manager.start(campaign.id)

    await _wait_until(lambda: _len_eq(_campaign_calls(campaign.id), 2))
    calls = await _campaign_calls(campaign.id)
    skipped = [c for c in calls if c.lead_id == lead_ids[0]]
    assert len(skipped) == 1
    assert skipped[0].result == CallResult.DO_NOT_CALL
    assert skipped[0].status == CallStatus.FAILED
    # Der gesperrte Lead darf NIE tatsaechlich angerufen worden sein.
    assert len(FakeTwilioProvider.calls_made) == 1

    await manager.stop(campaign.id)


@pytest.mark.asyncio
async def test_campaign_pause_stops_new_calls_but_keeps_active(db_session):
    lead_ids = await _make_leads(db_session, 3)
    campaign = await CampaignRepository(db_session).create(
        name="Testkampagne", lead_ids_json=json.dumps(lead_ids), max_concurrent=1
    )
    manager = CampaignManager()
    await manager.start(campaign.id)

    await _wait_until(lambda: _len_eq(_campaign_calls(campaign.id), 1))
    await manager.pause(campaign.id)
    await asyncio.sleep(0.3)  # mehrere Poll-Ticks abwarten

    calls = await _campaign_calls(campaign.id)
    assert len(calls) == 1, "Pause haette keinen neuen Anruf starten duerfen"
    assert calls[0].status == CallStatus.CREATED, "aktiver Anruf darf durch Pause nicht beendet werden"

    await manager.resume(campaign.id)

    async def campaign_running() -> bool:
        c = await _campaign(campaign.id)
        return c.status == CampaignStatus.RUNNING

    await _wait_until(campaign_running)
    await manager.stop(campaign.id)


@pytest.mark.asyncio
async def test_campaign_stop_is_permanent(db_session):
    lead_ids = await _make_leads(db_session, 1)
    campaign = await CampaignRepository(db_session).create(
        name="Testkampagne", lead_ids_json=json.dumps(lead_ids), max_concurrent=1
    )
    manager = CampaignManager()
    await manager.stop(campaign.id)

    with pytest.raises(ValueError):
        await manager.start(campaign.id)


@pytest.mark.asyncio
async def test_resume_after_restart_pauses_orphaned_running_campaigns(db_session):
    lead_ids = await _make_leads(db_session, 1)
    campaign = await CampaignRepository(db_session).create(
        name="Testkampagne", lead_ids_json=json.dumps(lead_ids), max_concurrent=1
    )
    await CampaignRepository(db_session).update(campaign.id, status=CampaignStatus.RUNNING)

    fresh_manager = CampaignManager()  # simuliert einen neuen Prozess (kein Task bekannt)
    await fresh_manager.resume_after_restart()

    reloaded = await _campaign(campaign.id)
    assert reloaded.status == CampaignStatus.PAUSED
