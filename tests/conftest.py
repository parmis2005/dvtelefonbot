"""Gemeinsame Test-Fixtures: isolierte SQLite-Testdatenbank pro Test."""

from __future__ import annotations

import pytest_asyncio

from core.config import get_settings
from database.database import get_session_factory, init_db, reset_engine_for_tests
from database.repository import LeadRepository


@pytest_asyncio.fixture
async def db_session(tmp_path, monkeypatch):
    db_path = tmp_path / "test_dario.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    get_settings.cache_clear()
    await reset_engine_for_tests()

    await init_db()
    session_factory = get_session_factory()
    async with session_factory() as session:
        yield session

    await reset_engine_for_tests()
    get_settings.cache_clear()


@pytest_asyncio.fixture
async def sample_lead(db_session):
    repo = LeadRepository(db_session)
    lead = await repo.create(
        unternehmen="Beauty Studio Beispiel",
        ansprechpartner="Frau Mueller",
        telefonnummer="+491701234567",
        email=None,
        online_auftritt_geprueft=True,
        entwurf_vorhanden=True,
        entwurf_link="https://beispiel.de/entwurf",
    )
    return lead
