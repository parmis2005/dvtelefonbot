"""Tests fuer services/effective_settings.py und deren Verdrahtung
(Abschnitt 28 "Einstellungen"): Agent-Name/Firma/Standort/Wartezeit/
Stille-Timeout/Cooldown wirken ohne Backend-Neustart auf NEUE Calls."""

from __future__ import annotations

from datetime import datetime

import pytest

from agent.dario import Dario
from agent.state_machine import CallState
from app.bootstrap import build_app_context
from core.config import get_settings
from database.repository import AppSettingRepository, CallRepository
from services.call_service import CallNotAllowedError, CallService
from services.effective_settings import get_effective_settings
from services.transcript_service import write_transcript_file
from tools.call_tools import ToolExecutor


@pytest.mark.asyncio
async def test_get_effective_settings_without_overrides_matches_env(db_session):
    effective = await get_effective_settings(db_session)
    base = get_settings()
    assert effective.agent_name == base.agent_name
    assert effective.wait_timeout == base.wait_timeout


@pytest.mark.asyncio
async def test_get_effective_settings_applies_stored_overrides(db_session):
    repo = AppSettingRepository(db_session)
    await repo.set("agent_name", "Testbot")
    await repo.set("company_name", "Test GmbH")
    await repo.set("wait_timeout_seconds", "5")

    effective = await get_effective_settings(db_session)
    assert effective.agent_name == "Testbot"
    assert effective.company_name == "Test GmbH"
    assert effective.wait_timeout == 5
    # Nicht ueberschriebene Felder bleiben beim .env-Wert.
    assert effective.silence_timeout == get_settings().silence_timeout


@pytest.mark.asyncio
async def test_get_effective_settings_ignores_invalid_int_override(db_session):
    await AppSettingRepository(db_session).set("call_cooldown_seconds", "nicht-numerisch")
    effective = await get_effective_settings(db_session)
    assert effective.call_cooldown == get_settings().call_cooldown


@pytest.mark.asyncio
async def test_build_app_context_uses_overridden_agent_name(db_session):
    await AppSettingRepository(db_session).set("agent_name", "Dashboardbot")
    ctx = await build_app_context(db_session)
    assert ctx.settings.agent_name == "Dashboardbot"
    assert ctx.engine.responses.agent_name == "Dashboardbot"


@pytest.mark.asyncio
async def test_call_cooldown_override_blocks_call(db_session, sample_lead):
    settings = get_settings()
    call_service = CallService(db_session, settings)

    # Ohne Override: normaler (langer) .env-Cooldown - erster Call ist erlaubt.
    call = await call_service.start_call(sample_lead.id)
    await call_service.complete(call.id, result="NOT_INTERESTED")

    # Zweiter Call sofort danach ist normalerweise durch den .env-Cooldown
    # (86400s Standard) blockiert.
    with pytest.raises(CallNotAllowedError):
        await call_service.start_call(sample_lead.id)

    # Dashboard setzt den Cooldown auf 0 -> derselbe Lead darf sofort wieder
    # angerufen werden, OHNE Backend-Neustart.
    await AppSettingRepository(db_session).set("call_cooldown_seconds", "0")
    call2 = await call_service.start_call(sample_lead.id)
    assert call2.id != call.id


@pytest.mark.asyncio
async def test_settings_api_roundtrip_affects_effective_settings(db_session):
    from api.settings_api import SettingsUpdate, get_dashboard_settings, update_dashboard_settings

    updated = await update_dashboard_settings(
        SettingsUpdate(values={"agent_name": "API-Bot", "silence_timeout_seconds": "3"}), db_session
    )
    assert updated.values["agent_name"] == "API-Bot"
    assert updated.values["silence_timeout_seconds"] == "3"

    fetched = await get_dashboard_settings(db_session)
    assert fetched.values["agent_name"] == "API-Bot"

    effective = await get_effective_settings(db_session)
    assert effective.agent_name == "API-Bot"
    assert effective.silence_timeout == 3


async def _build_dario(db_session, sample_lead, business_config, engine) -> Dario:
    tool_executor = ToolExecutor(db_session, None, None, "Digital Vision")
    call_repo = CallRepository(db_session)
    call = await call_repo.create(lead_id=sample_lead.id)
    return await Dario.for_lead(
        db_session, get_settings(), business_config, engine, tool_executor, sample_lead.id, call.id
    )


@pytest.mark.asyncio
async def test_check_wait_timeout_noop_when_not_waiting(db_session, sample_lead):
    from tests.factories import make_business_config, make_engine

    dario = await _build_dario(db_session, sample_lead, make_business_config(), make_engine())
    assert await dario.check_wait_timeout(25) is None


@pytest.mark.asyncio
async def test_no_response_followup_then_ends_call(db_session, sample_lead, tmp_path, monkeypatch):
    from tests.factories import make_business_config, make_engine

    monkeypatch.setattr(
        "agent.dario.write_transcript_file",
        lambda call_id, context: write_transcript_file(call_id, context, transcripts_dir=str(tmp_path)),
    )

    dario = await _build_dario(db_session, sample_lead, make_business_config(), make_engine())
    first = await dario.handle_no_response()

    assert first is not None
    assert first.reply_text == "Hallo, koennen Sie mich hoeren? Es geht nur kurz um Ihren Online-Auftritt."
    assert first.call_ended is False
    assert dario.call_active is True

    second = await dario.handle_no_response()

    assert second is not None
    assert second.call_ended is True
    assert dario.call_active is False
    persisted = await CallRepository(db_session).get(dario.call_id)
    assert persisted.status.value == "COMPLETED"
    assert persisted.result.value == "NO_ANSWER"


@pytest.mark.asyncio
async def test_check_wait_timeout_stays_silent_while_waiting(db_session, sample_lead):
    from tests.factories import make_business_config, make_engine

    dario = await _build_dario(db_session, sample_lead, make_business_config(), make_engine())
    dario.context.wait_mode = True
    dario.context.transition_to(CallState.WAITING)
    dario.context.wait_started_at = datetime.utcnow()

    assert await dario.check_wait_timeout(25) is None
    assert dario.context.still_there_asked is False
    assert dario.call_active is True

    persisted = await CallRepository(db_session).get(dario.call_id)
    assert persisted.status.value == "CREATED"
