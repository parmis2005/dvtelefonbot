"""Tests fuer api/telephony.py (Verbindungsstatus + Testanruf, Abschnitt 24-26).

Nutzt einen Fake-TwilioProvider - es darf hier NIE ein echter,
kostenpflichtiger Anruf ausgeloest werden.
"""

from __future__ import annotations

import asyncio
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

import api.telephony as telephony_module
import app.main as app_main
from core.config import get_settings
from database.database import get_session_factory, reset_engine_for_tests
from database.repository import CallRepository, DoNotCallRepository


class FakeTwilioProvider:
    calls_made: ClassVar[list[tuple[str, str]]] = []
    verify_result: ClassVar[tuple[bool, str]] = (True, "Account-Status: active")

    def __init__(self, account_sid: str, auth_token: str, caller_id: str):
        pass

    def verify_credentials(self) -> tuple[bool, str]:
        return FakeTwilioProvider.verify_result

    def start_outbound_call(self, to_number: str, twiml_webhook_url: str) -> str:
        FakeTwilioProvider.calls_made.append((to_number, twiml_webhook_url))
        return f"CAfake{len(FakeTwilioProvider.calls_made)}"


async def _fake_webhook_reachable(base_url: str) -> tuple[bool, str]:
    return True, "erreichbar (Test)"


@pytest.fixture
def client(tmp_path, monkeypatch):
    FakeTwilioProvider.calls_made = []
    FakeTwilioProvider.verify_result = (True, "Account-Status: active")

    db_path = tmp_path / "test_telephony.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-passwort-123")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC" + "test1234" * 4)  # realistische SID-Laenge
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tokentest")
    monkeypatch.setenv("TWILIO_CALLER_ID", "+491700000000")
    monkeypatch.setenv("TWILIO_PUBLIC_BASE_URL", "https://example-tunnel.test")
    monkeypatch.setattr(telephony_module, "TwilioProvider", FakeTwilioProvider)
    # Default: Tunnel gilt als erreichbar (die echte Pruefung wuerde gegen
    # die Fake-URL oben sonst 5s in einen DNS-Fehler laufen) - dedizierte
    # Tests unten ueberschreiben dies gezielt, um die neue Sicherheitspruefung
    # selbst zu verifizieren (siehe services/telephony_diagnostics.py).
    monkeypatch.setattr(telephony_module, "check_webhook_reachable", _fake_webhook_reachable)
    get_settings.cache_clear()

    asyncio.run(reset_engine_for_tests())

    with TestClient(app_main.app) as test_client:
        test_client.post(
            "/api/auth/login", json={"username": "admin", "password": "test-passwort-123"}
        )
        yield test_client

    asyncio.run(reset_engine_for_tests())
    get_settings.cache_clear()


def test_status_reports_connected_with_masked_sid(client):
    response = client.get("/api/telephony/status")
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["connected"] is True
    assert body["caller_id"] == "+491700000000"
    assert body["account_sid_masked"] == "ACte...1234"
    assert body["account_sid_masked"] != "AC" + "test1234" * 4


def test_status_reports_not_connected_on_bad_credentials(client):
    FakeTwilioProvider.verify_result = (False, "Authentication Error")
    response = client.get("/api/telephony/status")
    assert response.json()["connected"] is False


def test_status_without_configured_credentials(client, monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")
    get_settings.cache_clear()
    response = client.get("/api/telephony/status")
    body = response.json()
    assert body["configured"] is False
    assert body["connected"] is False


def test_trigger_test_call_creates_lead_and_launches_real_call(client):
    response = client.post("/api/telephony/test-call", json={"to_number": "+491709999999"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["twilio_call_sid"] == "CAfake1"
    assert len(FakeTwilioProvider.calls_made) == 1
    assert FakeTwilioProvider.calls_made[0][0] == "+491709999999"

    async def fetch_call():
        async with get_session_factory()() as session:
            return await CallRepository(session).get(body["call_id"])

    call = asyncio.run(fetch_call())
    assert call is not None
    assert call.twilio_call_sid == "CAfake1"


def test_trigger_test_call_blocked_by_do_not_call(client):
    async def block_number():
        async with get_session_factory()() as session:
            await DoNotCallRepository(session).add("+491708888888", "Test-Sperre")

    asyncio.run(block_number())

    response = client.post("/api/telephony/test-call", json={"to_number": "+491708888888"})
    assert response.status_code == 409
    assert len(FakeTwilioProvider.calls_made) == 0


def test_status_reports_unreachable_webhook_url(client, monkeypatch):
    """Direkte Regression fuer den Vorfall: ein echter Testanruf schlug mit
    Twilio-Fehler 11200 ('Got HTTP 502 response') fehl, weil
    TWILIO_PUBLIC_BASE_URL zum Anrufzeitpunkt nicht erreichbar war - das
    Dashboard zeigte das vorher nicht an (nur "konfiguriert", nicht ob
    tatsaechlich erreichbar)."""

    async def fake_unreachable(base_url: str) -> tuple[bool, str]:
        return False, "Got HTTP 502 response"

    monkeypatch.setattr(telephony_module, "check_webhook_reachable", fake_unreachable)

    response = client.get("/api/telephony/status")
    body = response.json()
    assert body["public_base_url_configured"] is True
    assert body["public_base_url_reachable"] is False
    assert "502" in body["public_base_url_detail"]


def test_trigger_test_call_blocked_when_webhook_unreachable(client, monkeypatch):
    """Verhindert genau den gemeldeten Vorfall: kein Anruf wird ausgeloest,
    wenn der Tunnel/das Backend zum Zeitpunkt des Testanrufs nicht
    erreichbar ist - vorher liess Twilio in diesem Fall das Zieltelefon
    klingeln, spielte danach aber eine Fehleransage ab."""

    async def fake_unreachable(base_url: str) -> tuple[bool, str]:
        return False, "Got HTTP 502 response"

    monkeypatch.setattr(telephony_module, "check_webhook_reachable", fake_unreachable)

    response = client.post("/api/telephony/test-call", json={"to_number": "+491707777777"})
    assert response.status_code == 502
    assert len(FakeTwilioProvider.calls_made) == 0
