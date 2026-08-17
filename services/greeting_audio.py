"""Prepare Dario's opening line before a real phone call is placed."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from agent.dario import Dario
from app.bootstrap import build_app_context, get_tts_provider
from services.tts_cache import ensure_cached_tts
from tools.call_tools import ToolExecutor


@dataclass(frozen=True)
class PreparedGreeting:
    text: str
    path: Path
    bytes: int


async def prepare_greeting_audio(
    session: AsyncSession,
    *,
    lead_id: int,
    call_id: int,
) -> PreparedGreeting:
    ctx = await build_app_context(session)
    settings = ctx.settings
    tool_executor = ToolExecutor(
        session,
        ctx.email_provider,
        ctx.whatsapp_provider,
        settings.company_name,
    )
    dario = await Dario.for_lead(
        session,
        settings,
        ctx.business_config,
        ctx.engine,
        tool_executor,
        lead_id,
        call_id,
    )
    text = dario.opening_line()
    tts = await get_tts_provider(session)
    cached = await ensure_cached_tts(tts, text, label="greeting", call_id=call_id)
    return PreparedGreeting(text=text, path=cached.path, bytes=cached.bytes)
