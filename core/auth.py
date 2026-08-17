"""Session-basierte Authentifizierung fuer das DVTelefonbot-Dashboard.

Einzelner Admin-Account (Zugangsdaten aus .env, siehe core/config.py) - keine
Nutzertabelle noetig. Sessions werden serverseitig in-memory gehalten (dieser
Backend-Prozess laeuft dauerhaft, siehe CLAUDE.md "Architektur") und als
opakes, zufaelliges Token in einem httpOnly-Cookie an den Browser gegeben.
Weder Passwort noch Token-Geheimnis verlassen den Server in les- oder
erratbarer Form.
"""

from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import Cookie, HTTPException, status

from core.config import get_settings

SESSION_COOKIE_NAME = "dario_dashboard_session"

# token -> Ablaufzeitpunkt. In-Memory bewusst statt DB-Tabelle: ein
# Neustart des Backends soll ohnehin alle Sessions invalidieren (kein
# unbeaufsichtigter Zugriff mit einem alten Cookie nach einem Deploy).
_sessions: dict[str, datetime] = {}


def verify_credentials(username: str, password: str) -> bool:
    settings = get_settings()
    if not settings.dashboard_username or not settings.dashboard_password:
        return False
    user_ok = hmac.compare_digest(username, settings.dashboard_username)
    pass_ok = hmac.compare_digest(password, settings.dashboard_password)
    return user_ok and pass_ok


def create_session() -> tuple[str, datetime]:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=settings.dashboard_session_ttl_hours)
    _sessions[token] = expires_at
    return token, expires_at


def revoke_session(token: str) -> None:
    _sessions.pop(token, None)


def is_session_valid(token: str | None) -> bool:
    if not token or token not in _sessions:
        return False
    if _sessions[token] < datetime.utcnow():
        _sessions.pop(token, None)
        return False
    return True


async def require_auth(
    dario_dashboard_session: str | None = Cookie(default=None),
) -> None:
    """FastAPI-Dependency fuer alle geschuetzten Dashboard-API-Routen (siehe
    Abschnitt 41 "Login, sichere Session, Logout, geschuetzte Routen").
    Twilio-Webhooks (api/twilio.py) nutzen bewusst NICHT diese Dependency -
    sie werden stattdessen per Twilio-Signatur validiert."""
    if not is_session_valid(dario_dashboard_session):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet")
