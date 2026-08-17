"""Session-basierte Authentifizierung fuer das DVTelefonbot-Dashboard.

Einzelner Admin-Account (Zugangsdaten aus .env, siehe core/config.py) - keine
Nutzertabelle noetig. Sessions werden in database/models.py::DashboardSession
persistiert und als opakes, zufaelliges Token in einem httpOnly-Cookie an den
Browser gegeben. Weder Passwort noch Token-Geheimnis verlassen den Server in
les- oder erratbarer Form.

Bewusst NICHT mehr in-memory (fruehere Version): ein Neustart/Reload des
Backend-Prozesses (z.B. `uvicorn --reload` waehrend der Entwicklung) hat
zuvor JEDE angemeldete Dashboard-Session ohne Vorwarnung invalidiert - beim
naechsten Klick landete man kommentarlos wieder auf der Login-Seite, obwohl
aus Nutzersicht "die Session eigentlich noch gueltig" war. Fuer eine als
taegliches Kontrollzentrum gedachte Anwendung ist das nicht akzeptabel
(siehe CLAUDE.md Abschnitt "DVTelefonbot Dashboard"). Die TTL-Durchsetzung
und der explizite Logout bleiben unveraendert scharf - nur die Haltbarkeit
ueber einen Prozess-Neustart hinweg wurde ergaenzt, kein
Sicherheits-Abstrich.
"""

from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import get_settings
from database.database import get_db_session
from database.repository import DashboardSessionRepository

SESSION_COOKIE_NAME = "dario_dashboard_session"

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def verify_credentials(username: str, password: str) -> bool:
    settings = get_settings()
    if not settings.dashboard_username or not settings.dashboard_password:
        return False
    user_ok = hmac.compare_digest(username, settings.dashboard_username)
    pass_ok = hmac.compare_digest(password, settings.dashboard_password)
    return user_ok and pass_ok


async def create_session(session: AsyncSession) -> tuple[str, datetime]:
    settings = get_settings()
    repo = DashboardSessionRepository(session)
    await repo.delete_expired()
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=settings.dashboard_session_ttl_hours)
    await repo.create(token, expires_at)
    return token, expires_at


async def revoke_session(session: AsyncSession, token: str) -> None:
    await DashboardSessionRepository(session).delete(token)


async def is_session_valid(session: AsyncSession, token: str | None) -> bool:
    if not token:
        return False
    row = await DashboardSessionRepository(session).get_valid(token)
    return row is not None


async def require_auth(
    db_session: DbSession,
    dario_dashboard_session: str | None = Cookie(default=None),
) -> None:
    """FastAPI-Dependency fuer alle geschuetzten Dashboard-API-Routen (siehe
    Abschnitt 41 "Login, sichere Session, Logout, geschuetzte Routen").
    Twilio-Webhooks (api/twilio.py) nutzen bewusst NICHT diese Dependency -
    sie werden stattdessen per Twilio-Signatur validiert."""
    if not await is_session_valid(db_session, dario_dashboard_session):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet")
