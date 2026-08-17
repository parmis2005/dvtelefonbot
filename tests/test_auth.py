"""Tests fuer core/auth.py + api/auth.py (Login/Logout/Session, Abschnitt 41).

Nutzt eine echte (temporaere SQLite-)Datenbank statt eines Mocks, da Sessions
seit der Umstellung auf database/models.py::DashboardSession persistiert
werden (bewusst nicht mehr nur in-memory - siehe core/auth.py Docstring:
ein Backend-Neustart/-Reload darf eine gueltige Session nicht mehr
kommentarlos invalidieren)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.auth import router as auth_router
from core.auth import require_auth
from core.config import get_settings
from database.database import init_db, reset_engine_for_tests


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-passwort-123")
    db_path = tmp_path / "test_auth.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    asyncio.run(reset_engine_for_tests())
    asyncio.run(init_db())

    app = FastAPI()
    app.include_router(auth_router)

    @app.get("/api/protected")
    async def protected(_: None = Depends(require_auth)) -> dict:
        return {"ok": True}

    with TestClient(app) as test_client:
        yield test_client

    asyncio.run(reset_engine_for_tests())
    get_settings.cache_clear()


def test_protected_route_without_login_returns_401(client):
    response = client.get("/api/protected")
    assert response.status_code == 401


def test_wrong_credentials_rejected(client):
    response = client.post("/api/auth/login", json={"username": "admin", "password": "falsch"})
    assert response.status_code == 401


def test_login_then_protected_route_succeeds(client):
    login = client.post(
        "/api/auth/login", json={"username": "admin", "password": "test-passwort-123"}
    )
    assert login.status_code == 200
    assert "dario_dashboard_session" in login.cookies

    protected = client.get("/api/protected")
    assert protected.status_code == 200
    assert protected.json() == {"ok": True}


def test_me_reflects_session_state(client):
    assert client.get("/api/auth/me").json() == {"authenticated": False}

    client.post("/api/auth/login", json={"username": "admin", "password": "test-passwort-123"})
    assert client.get("/api/auth/me").json() == {"authenticated": True}


def test_logout_invalidates_session(client):
    client.post("/api/auth/login", json={"username": "admin", "password": "test-passwort-123"})
    assert client.get("/api/protected").status_code == 200

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200

    assert client.get("/api/protected").status_code == 401


def test_multiple_consecutive_requests_all_succeed_with_same_session(client):
    """Test 4 (Abschnitt 60/61): eine einmal angemeldete Session muss fuer
    beliebig viele nachfolgende Anfragen gueltig bleiben, nicht nur fuer die
    erste - genau das Verhalten, das ein normaler Dashboard-Nutzungsablauf
    (Seite wechseln, speichern, wieder wechseln, ...) braucht."""
    client.post("/api/auth/login", json={"username": "admin", "password": "test-passwort-123"})
    for _ in range(10):
        response = client.get("/api/protected")
        assert response.status_code == 200


def test_session_survives_backend_restart():
    """Regression fuer die eigentliche Root Cause der gemeldeten
    Zwangs-Logouts: Sessions lagen zuvor nur in einem In-Memory-Dict
    (core/auth.py) - jeder Neustart/Reload des Backend-Prozesses (z.B.
    `uvicorn --reload` waehrend normaler Entwicklung/Wartung) hat dadurch
    JEDE angemeldete Session augenblicklich invalidiert, obwohl aus
    Nutzersicht nichts falsch gemacht wurde. Simuliert einen Neustart durch
    eine komplett neue FastAPI-App/TestClient-Instanz (frische Python-
    Objekte, neue DB-Engine ueber reset_engine_for_tests) gegen dieselbe
    zugrundeliegende SQLite-Datei - die Session muss trotzdem gueltig
    bleiben, weil sie in database/models.py::DashboardSession persistiert
    ist statt in einem prozesslokalen Dict."""
    import tempfile

    from database.database import reset_engine_for_tests as _reset

    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = f"{tmp_dir}/test_restart.db"
        db_url = f"sqlite+aiosqlite:///{db_path}"

        import os

        os.environ["DASHBOARD_USERNAME"] = "admin"
        os.environ["DASHBOARD_PASSWORD"] = "test-passwort-123"
        os.environ["DATABASE_URL"] = db_url
        get_settings.cache_clear()
        asyncio.run(_reset())
        asyncio.run(init_db())

        def _build_app() -> FastAPI:
            app = FastAPI()
            app.include_router(auth_router)

            @app.get("/api/protected")
            async def protected(_: None = Depends(require_auth)) -> dict:
                return {"ok": True}

            return app

        try:
            # "Vor dem Neustart": einloggen, Session-Cookie merken.
            with TestClient(_build_app()) as first_process_client:
                login = first_process_client.post(
                    "/api/auth/login",
                    json={"username": "admin", "password": "test-passwort-123"},
                )
                assert login.status_code == 200
                session_cookie_value = first_process_client.cookies["dario_dashboard_session"]

            # Simuliert den Backend-Neustart: Engine verwerfen (wie beim
            # tatsaechlichen Prozessende) und alles komplett neu aufbauen -
            # absichtlich KEIN gemeinsamer Python-Zustand mit oben mehr.
            asyncio.run(_reset())

            with TestClient(_build_app()) as second_process_client:
                second_process_client.cookies.set("dario_dashboard_session", session_cookie_value)
                response = second_process_client.get("/api/protected")
                assert response.status_code == 200, (
                    "Session wurde durch den simulierten Backend-Neustart ungueltig - "
                    "genau der gemeldete Zwangs-Logout-Fehler."
                )
        finally:
            asyncio.run(_reset())
            get_settings.cache_clear()


def test_expired_session_is_rejected():
    """Test 12: eine TATSAECHLICH abgelaufene Session (nicht nur eine, die
    durch einen Prozess-Neustart verloren ging) muss weiterhin korrekt als
    ungueltig erkannt werden - die Persistenz-Aenderung darf die
    TTL-Durchsetzung nicht aufweichen."""
    import os
    from datetime import datetime, timedelta

    from database.database import get_session_factory
    from database.database import reset_engine_for_tests as _reset
    from database.repository import DashboardSessionRepository

    with __import__("tempfile").TemporaryDirectory() as tmp_dir:
        db_path = f"{tmp_dir}/test_expired.db"
        os.environ["DASHBOARD_USERNAME"] = "admin"
        os.environ["DASHBOARD_PASSWORD"] = "test-passwort-123"
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_path}"
        get_settings.cache_clear()
        asyncio.run(_reset())
        asyncio.run(init_db())

        async def _seed_expired_session() -> str:
            factory = get_session_factory()
            async with factory() as db_session:
                repo = DashboardSessionRepository(db_session)
                await repo.create("expired-token-abc", datetime.utcnow() - timedelta(hours=1))
            return "expired-token-abc"

        try:
            token = asyncio.run(_seed_expired_session())

            app = FastAPI()
            app.include_router(auth_router)

            @app.get("/api/protected")
            async def protected(_: None = Depends(require_auth)) -> dict:
                return {"ok": True}

            with TestClient(app) as test_client:
                test_client.cookies.set("dario_dashboard_session", token)
                response = test_client.get("/api/protected")
                assert response.status_code == 401
        finally:
            asyncio.run(_reset())
            get_settings.cache_clear()
