"""Tests fuer api/calls.py: Anrufhistorie-Filterung und Transkript-Abruf
(Abschnitt 15-16 - bisher ohne dedizierte Testabdeckung)."""

from __future__ import annotations

import asyncio
import json
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

import api.calls as calls_module
import app.main as app_main
from core.config import get_settings
from database.database import get_session_factory, reset_engine_for_tests
from database.models import CallResult, CallStatus
from database.repository import CallRepository, LeadRepository


class FakeTwilioProvider:
    calls_made: ClassVar[list[tuple[str, str]]] = []

    def __init__(self, account_sid: str, auth_token: str, caller_id: str):
        pass

    def start_outbound_call(self, to_number: str, twiml_webhook_url: str) -> str:
        FakeTwilioProvider.calls_made.append((to_number, twiml_webhook_url))
        return f"CAfake{len(FakeTwilioProvider.calls_made)}"


async def _fake_webhook_reachable(base_url: str) -> tuple[bool, str]:
    return True, "erreichbar (Test)"


@pytest.fixture
def client(tmp_path, monkeypatch):
    FakeTwilioProvider.calls_made = []
    db_path = tmp_path / "test_calls.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-passwort-123")
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC" + "test1234" * 4)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tokentest")
    monkeypatch.setenv("TWILIO_CALLER_ID", "+491700000000")
    monkeypatch.setenv("TWILIO_PUBLIC_BASE_URL", "https://example-tunnel.test")
    monkeypatch.setattr(calls_module, "TwilioProvider", FakeTwilioProvider)
    monkeypatch.setattr(calls_module, "check_webhook_reachable", _fake_webhook_reachable)
    get_settings.cache_clear()

    asyncio.run(reset_engine_for_tests())

    with TestClient(app_main.app) as test_client:
        test_client.post(
            "/api/auth/login", json={"username": "admin", "password": "test-passwort-123"}
        )
        yield test_client

    asyncio.run(reset_engine_for_tests())
    get_settings.cache_clear()


async def _seed_call_with_transcript(lead_phone: str) -> tuple[int, int]:
    async with get_session_factory()() as session:
        lead = await LeadRepository(session).create(unternehmen="Testfirma", telefonnummer=lead_phone)
        call_repo = CallRepository(session)
        call = await call_repo.create(lead_id=lead.id, status=CallStatus.ANSWERED)
        transcript = json.dumps(
            [
                {"speaker": "dario", "text": "Guten Tag, hier ist Dario.", "timestamp": "2026-01-01T10:00:00"},
                {"speaker": "kunde", "text": "Kein Interesse, danke.", "timestamp": "2026-01-01T10:00:05"},
            ]
        )
        await call_repo.update(call.id, transcript=transcript, summary="Ergebnis:\nKein Interesse")
        await call_repo.mark_ended(call.id, CallStatus.COMPLETED, result=CallResult.NOT_INTERESTED)
        return lead.id, call.id


def test_call_history_lists_all_calls(client):
    _lead_id, call_id = asyncio.run(_seed_call_with_transcript("+491701111111"))

    response = client.get("/api/calls")
    assert response.status_code == 200
    calls = response.json()
    assert any(c["id"] == call_id for c in calls)


def test_call_history_filters_by_lead_id(client):
    lead_a, call_a = asyncio.run(_seed_call_with_transcript("+491702222222"))
    _lead_b, call_b = asyncio.run(_seed_call_with_transcript("+491703333333"))

    response = client.get(f"/api/calls?lead_id={lead_a}")
    assert response.status_code == 200
    calls = response.json()
    assert {c["id"] for c in calls} == {call_a}
    assert call_b not in {c["id"] for c in calls}


def test_call_history_active_only_filter_excludes_completed(client):
    asyncio.run(_seed_call_with_transcript("+491704444444"))

    response = client.get("/api/calls?active_only=true")
    assert response.status_code == 200
    assert response.json() == []


def test_call_detail_includes_transcript_and_result(client):
    _lead_id, call_id = asyncio.run(_seed_call_with_transcript("+491705555555"))

    response = client.get(f"/api/calls/{call_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "NOT_INTERESTED"
    assert body["status"] == "COMPLETED"

    turns = json.loads(body["transcript"])
    assert len(turns) == 2
    assert turns[0]["speaker"] == "dario"
    assert "Kein Interesse" in body["summary"]


def test_call_detail_404_for_unknown_call(client):
    response = client.get("/api/calls/999999")
    assert response.status_code == 404


def _create_lead(client, phone: str) -> int:
    response = client.post("/api/leads", json={"unternehmen": "Testfirma", "telefonnummer": phone})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_twilio_call_launches_real_call(client):
    lead_id = _create_lead(client, "+491706666666")

    response = client.post("/api/calls/twilio", json={"lead_id": lead_id})
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["twilio_call_sid"] == "CAfake1"
    assert len(FakeTwilioProvider.calls_made) == 1
    assert FakeTwilioProvider.calls_made[0][0] == "+491706666666"


def test_twilio_call_blocked_when_webhook_unreachable(client, monkeypatch):
    """Regression fuer den gemeldeten Vorfall (Twilio-Fehler 11200 'Got HTTP
    502 response') - siehe tests/test_telephony_api.py fuer das Aequivalent
    beim dedizierten Testanruf-Endpunkt."""

    async def fake_unreachable(base_url: str) -> tuple[bool, str]:
        return False, "Got HTTP 502 response"

    monkeypatch.setattr(calls_module, "check_webhook_reachable", fake_unreachable)

    lead_id = _create_lead(client, "+491706666667")
    response = client.post("/api/calls/twilio", json={"lead_id": lead_id})
    assert response.status_code == 502
    assert len(FakeTwilioProvider.calls_made) == 0
