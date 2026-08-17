"""Login/Logout/Session-Status fuer das DVTelefonbot-Dashboard (Abschnitt 41)."""

from __future__ import annotations

from datetime import UTC
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import (
    SESSION_COOKIE_NAME,
    create_session,
    is_session_valid,
    revoke_session,
    verify_credentials,
)
from core.config import get_settings
from database.database import get_db_session

router = APIRouter(prefix="/api/auth", tags=["auth"])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


class LoginRequest(BaseModel):
    username: str
    password: str


@router.post("/login")
async def login(payload: LoginRequest, response: Response, session: DbSession) -> dict:
    if not verify_credentials(payload.username, payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login fehlgeschlagen")
    settings = get_settings()
    token, expires_at = await create_session(session)
    # Wichtig: expires_at als datetime uebergeben, NICHT als int-Timestamp -
    # Python's http.cookies behandelt einen rohen int bei "expires" als
    # Sekunden-Offset AB JETZT (nicht als absoluten Unix-Timestamp), was
    # einen Epoch-Wert wie 1786000000 auf ca. das Jahr 2083 abbilden wuerde.
    # core/auth.py haelt Sessions bewusst als naiv-UTC (Projektkonvention),
    # Starlettes Cookie-Serialisierung (usegmt=True) verlangt jedoch ein
    # tz-aware datetime - daher hier nur fuer die Ausgabe angereichert.
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        samesite=settings.dashboard_cookie_samesite,
        secure=settings.dashboard_cookie_secure,
        expires=expires_at.replace(tzinfo=UTC),
    )
    return {"ok": True}


@router.post("/logout")
async def logout(
    response: Response,
    session: DbSession,
    dario_dashboard_session: str | None = Cookie(default=None),
) -> dict:
    if dario_dashboard_session:
        await revoke_session(session, dario_dashboard_session)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
async def me(session: DbSession, dario_dashboard_session: str | None = Cookie(default=None)) -> dict:
    return {"authenticated": await is_session_valid(session, dario_dashboard_session)}
