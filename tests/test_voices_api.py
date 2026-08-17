"""Tests fuer api/voices.py (Stimmenverwaltung, Abschnitt 22-23).

Mockt ChatterboxTTSProvider.synthesize statt echter Sprachsynthese: eine
echte Chatterbox-Generierung dauert auf CPU ca. 25-30s (siehe CLAUDE.md
"Darios Stimme") - fuer die schnelle Test-Suite wird hier nur der
Kontrollfluss (Endpunkt -> Provider -> Datei -> Response) verifiziert, nicht
die tatsaechliche Audioqualitaet (die ist bereits im lokalen Voice-Test
manuell verifiziert).
"""

from __future__ import annotations

import wave

import pytest
from fastapi.testclient import TestClient

import app.main as app_main
from core.config import get_settings
from database.database import reset_engine_for_tests
from voice.tts.chatterbox_tts import ChatterboxTTSProvider


def _write_minimal_wav(path: str) -> str:
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(8000)
        f.writeframes(b"\x00\x00" * 800)
    return path


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_voices.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("DASHBOARD_USERNAME", "admin")
    monkeypatch.setenv("DASHBOARD_PASSWORD", "test-passwort-123")

    async def fake_synthesize(self, text: str, output_path: str) -> str:
        return _write_minimal_wav(output_path)

    async def fake_is_available(self) -> bool:
        return True

    monkeypatch.setattr(ChatterboxTTSProvider, "synthesize", fake_synthesize)
    monkeypatch.setattr(ChatterboxTTSProvider, "is_available", fake_is_available)

    get_settings.cache_clear()
    import asyncio

    asyncio.run(reset_engine_for_tests())

    with TestClient(app_main.app) as test_client:
        test_client.post(
            "/api/auth/login", json={"username": "admin", "password": "test-passwort-123"}
        )
        yield test_client

    asyncio.run(reset_engine_for_tests())
    get_settings.cache_clear()


def test_voices_auto_seed_from_production_config(client):
    response = client.get("/api/voices")
    assert response.status_code == 200
    voices = response.json()
    assert len(voices) == 1
    assert voices[0]["is_active"] is True


def test_upload_rename_activate_delete_voice(client, tmp_path):
    # Erst die Baseline (Produktions-Seed) abrufen, damit die Tabelle beim
    # spaeteren Loeschen NICHT leer wird - sonst wuerde _ensure_seeded()
    # sofort eine neue Zeile nachziehen, die dank SQLite-Rowid-Wiederverwendung
    # zufaellig dieselbe ID wie die geloeschte erhalten kann (kein Bug, aber
    # eine irrefuehrende Test-Assertion, wenn man nur per ID vergleicht).
    baseline = client.get("/api/voices").json()
    assert len(baseline) == 1

    wav_path = tmp_path / "neue_stimme.wav"
    _write_minimal_wav(str(wav_path))

    with open(wav_path, "rb") as f:
        upload = client.post(
            "/api/voices/upload?name=Neue+Stimme",
            files={"file": ("neue_stimme.wav", f, "audio/wav")},
        )
    assert upload.status_code == 201, upload.text
    new_voice = upload.json()
    assert new_voice["name"] == "Neue Stimme"
    assert new_voice["is_active"] is False

    rename = client.patch(f"/api/voices/{new_voice['id']}", json={"name": "Umbenannt"})
    assert rename.status_code == 200
    assert rename.json()["name"] == "Umbenannt"

    activate = client.post(f"/api/voices/{new_voice['id']}/activate")
    assert activate.status_code == 200
    assert activate.json()["is_active"] is True

    voices = client.get("/api/voices").json()
    active_voices = [v for v in voices if v["is_active"]]
    assert len(active_voices) == 1
    assert active_voices[0]["id"] == new_voice["id"]

    delete = client.delete(f"/api/voices/{new_voice['id']}")
    assert delete.status_code == 204

    remaining = client.get("/api/voices").json()
    assert all(v["id"] != new_voice["id"] for v in remaining)
    assert len(remaining) == len(baseline)


def test_builtin_voice_cannot_be_deleted(client):
    # Die per _ensure_seeded() erzeugte Produktionsstimme ist NICHT builtin
    # (sie hat eine echte Referenzdatei) - is_builtin=True kommt nur zustande,
    # wenn CHATTERBOX_REFERENCE_AUDIO_PATH leer ist (siehe api/voices.py::
    # _ensure_seeded). Fuer einen deterministischen Test wird eine builtin-
    # Stimme direkt ueber das Repository angelegt statt ueber die API (die
    # beim Upload immer is_builtin=False setzt).
    import asyncio

    from database.database import get_session_factory
    from database.repository import VoiceProfileRepository

    async def create_builtin() -> int:
        async with get_session_factory()() as session:
            profile = await VoiceProfileRepository(session).create(
                name="Chatterbox Standardstimme", file_path="", is_builtin=True
            )
            return profile.id

    builtin_id = asyncio.run(create_builtin())
    response = client.delete(f"/api/voices/{builtin_id}")
    assert response.status_code == 400

    still_there = client.get("/api/voices").json()
    assert any(v["id"] == builtin_id for v in still_there)


def test_voice_test_endpoint_returns_audio(client):
    voices = client.get("/api/voices").json()
    voice_id = voices[0]["id"]
    response = client.post(f"/api/voices/{voice_id}/test")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert len(response.content) > 0
