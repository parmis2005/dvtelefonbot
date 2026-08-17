"""Tests fuer api/calls.py: Anrufhistorie-Filterung und Transkript-Abruf
(Abschnitt 15-16 - bisher ohne dedizierte Testabdeckung)."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from core.config import get_settings
from database.database import get_session_factory, reset_engine_for_tests
from database.models import CallResult, CallStatus
from database.repository import CallRepository, LeadRepository


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_calls.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-passwort-123")
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
