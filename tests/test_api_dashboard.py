"""End-to-End-Tests fuer die neuen Dashboard-API-Router (Login, Kontakte,
Kampagnen, Prompt-Versionen, CSV-Import) gegen die echte FastAPI-App.

Nutzt einen Fake-TwilioProvider - es darf hier NIE ein echter,
kostenpflichtiger Anruf ausgeloest werden.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
import services.campaign_service as campaign_service_module
from core.config import get_settings
from database.database import get_session_factory, reset_engine_for_tests
from database.repository import CallRepository, CampaignRepository


class FakeTwilioProvider:
    calls_made: ClassVar[list[str]] = []

    def __init__(self, account_sid: str, auth_token: str, caller_id: str):
        pass

    def start_outbound_call(self, to_number: str, twiml_webhook_url: str) -> str:
        FakeTwilioProvider.calls_made.append(to_number)
        return f"CAfake{len(FakeTwilioProvider.calls_made)}"


async def _fake_webhook_reachable(settings) -> bool:
    return True


@pytest.fixture
def client(tmp_path, monkeypatch):
    FakeTwilioProvider.calls_made = []
    db_path = tmp_path / "test_dashboard.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-passwort-123")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tokentest")
    monkeypatch.setenv("TWILIO_CALLER_ID", "+491700000000")
    monkeypatch.setenv("TWILIO_PUBLIC_BASE_URL", "https://example-tunnel.test")
    monkeypatch.setattr(campaign_service_module, "TwilioProvider", FakeTwilioProvider)
    monkeypatch.setattr(campaign_service_module, "POLL_INTERVAL_SECONDS", 0.05)
    # Simuliert einen erreichbaren Tunnel - siehe tests/test_campaign_manager.py
    # fuer den Hintergrund (services/telephony_diagnostics.py).
    monkeypatch.setattr(
        campaign_service_module.CampaignManager, "_webhook_reachable", staticmethod(_fake_webhook_reachable)
    )
    get_settings.cache_clear()

    asyncio.run(reset_engine_for_tests())

    with TestClient(app_main.app) as test_client:
        yield test_client

    asyncio.run(reset_engine_for_tests())
    get_settings.cache_clear()


def _login(client: TestClient) -> None:
    response = client.post(
        "/api/auth/login", json={"username": "admin", "password": "test-passwort-123"}
    )
    assert response.status_code == 200


def _create_lead(client: TestClient, phone: str, do_not_call: bool = False) -> int:
    response = client.post(
        "/api/leads",
        json={"unternehmen": "Testfirma", "telefonnummer": phone},
    )
    assert response.status_code == 201, response.text
    lead_id = response.json()["id"]
    if do_not_call:
        response = client.post("/api/do-not-call", json={"telefonnummer": phone, "reason": "Test"})
        assert response.status_code == 201
    return lead_id


async def _wait_until(condition, timeout: float = 3.0) -> None:
    elapsed = 0.0
    step = 0.05
    while elapsed < timeout:
        if await condition():
            return
        await asyncio.sleep(step)
        elapsed += step
    raise AssertionError("Bedingung nicht innerhalb des Timeouts erfuellt")


def test_dashboard_routes_require_login(client):
    assert client.get("/api/campaigns").status_code == 401
    assert client.get("/api/leads").status_code == 401
    assert client.get("/api/prompt-versions").status_code == 401
    assert client.get("/api/voices").status_code == 401
    assert client.get("/api/do-not-call").status_code == 401
    assert client.get("/api/settings").status_code == 401


def test_campaign_create_start_launches_real_calls(client):
    _login(client)
    lead_a = _create_lead(client, "+491701111111")
    lead_b = _create_lead(client, "+491702222222")

    create = client.post(
        "/api/campaigns",
        json={"name": "Testkampagne", "lead_ids": [lead_a, lead_b], "max_concurrent": 2},
    )
    assert create.status_code == 201, create.text
    campaign_id = create.json()["id"]

    start = client.post(f"/api/campaigns/{campaign_id}/start")
    assert start.status_code == 200

    async def two_calls_started():
        async with get_session_factory()() as session:
            calls = await CallRepository(session).list_for_campaign(campaign_id)
            return len(calls) == 2

    asyncio.run(_wait_until(two_calls_started))
    assert len(FakeTwilioProvider.calls_made) == 2

    stop = client.post(f"/api/campaigns/{campaign_id}/stop")
    assert stop.status_code == 200
    assert stop.json()["status"] == "STOPPED"


def test_do_not_call_via_api_blocks_campaign_call(client):
    _login(client)
    blocked_lead = _create_lead(client, "+491703333333", do_not_call=True)

    create = client.post(
        "/api/campaigns",
        json={"name": "DNC-Test", "lead_ids": [blocked_lead], "max_concurrent": 1},
    )
    campaign_id = create.json()["id"]
    client.post(f"/api/campaigns/{campaign_id}/start")

    async def campaign_processed_the_only_lead():
        async with get_session_factory()() as session:
            calls = await CallRepository(session).list_for_campaign(campaign_id)
            return len(calls) == 1

    asyncio.run(_wait_until(campaign_processed_the_only_lead))
    assert len(FakeTwilioProvider.calls_made) == 0, "Gesperrte Nummer darf nie angerufen werden"

    async def campaign_completed():
        async with get_session_factory()() as session:
            c = await CampaignRepository(session).get(campaign_id)
            return c.status.value == "COMPLETED"

    asyncio.run(_wait_until(campaign_completed))


def test_prompt_version_create_and_activate_flow(client):
    _login(client)

    initial = client.get("/api/prompt-versions")
    assert initial.status_code == 200
    assert len(initial.json()) == 1  # aus Datei geseedet

    created = client.post(
        "/api/prompt-versions", json={"content": "Neuer Testprompt", "label": "Testversion"}
    )
    assert created.status_code == 201
    new_version = created.json()
    assert new_version["is_active"] is True
    assert new_version["version_number"] == 2

    active = client.get("/api/prompt-versions/active")
    assert active.json()["content"] == "Neuer Testprompt"

    versions = client.get("/api/prompt-versions").json()
    old_version_id = next(v["id"] for v in versions if v["version_number"] == 1)
    restored = client.post(f"/api/prompt-versions/{old_version_id}/activate")
    assert restored.status_code == 200
    assert restored.json()["is_active"] is True

    active_again = client.get("/api/prompt-versions/active")
    assert active_again.json()["id"] == old_version_id


def test_csv_import_preview_and_confirm(client):
    _login(client)
    csv_content = (
        b"Firma;Telefon;Ansprechpartner\n"
        b"Beispiel GmbH;+491704444444;Frau Test\n"
        b"Ungueltig AG;keine-nummer;Herr Fehler\n"
    )

    preview = client.post(
        "/api/leads/import/preview",
        files={"file": ("kontakte.csv", csv_content, "text/csv")},
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["total"] == 2
    assert body["valid_count"] == 1
    assert body["invalid_count"] == 1
    assert body["columns_detected"]["unternehmen"] == "Firma"
    assert body["columns_detected"]["telefonnummer"] == "Telefon"

    valid_rows = [row["data"] for row in body["rows"] if row["valid"]]
    confirm = client.post("/api/leads/import/confirm", json=valid_rows)
    assert confirm.status_code == 200
    assert confirm.json()["created_count"] == 1

    leads = client.get("/api/leads").json()
    assert any(lead_row["unternehmen"] == "Beispiel GmbH" for lead_row in leads)
