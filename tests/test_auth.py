"""Tests fuer core/auth.py + api/auth.py (Login/Logout/Session, Abschnitt 41)."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.auth import router as auth_router
from core.auth import require_auth
from core.config import get_settings


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-passwort-123")
    get_settings.cache_clear()

    app = FastAPI()
    app.include_router(auth_router)

    @app.get("/api/protected")
    async def protected(_: None = Depends(require_auth)) -> dict:
        return {"ok": True}

    with TestClient(app) as test_client:
        yield test_client

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
