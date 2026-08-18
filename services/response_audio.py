"""Prepare likely early response audio before a real call starts."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from agent.dario import Dario
from app.bootstrap import build_app_context, get_tts_provider
from services.tts_cache import ensure_cached_tts
from tools.call_tools import ToolExecutor


@dataclass(frozen=True)
class PreparedResponseAudio:
    text: str
    bytes: int


async def prepare_initial_response_audio(
    session: AsyncSession,
    *,
    lead_id: int,
    call_id: int | None = None,
) -> list[PreparedResponseAudio]:
    """Cache the deterministic first reply for common positive answers.

    The separate CLI process cannot warm the backend model itself, but it can
    populate the shared file cache. The live WebSocket path then streams this
    prepared response immediately when the generated text matches.
    """
    ctx = await build_app_context(session)
    settings = ctx.settings
    tool_executor = ToolExecutor(
        session,
        ctx.email_provider,
        ctx.whatsapp_provider,
        settings.company_name,
    )
    tts = await get_tts_provider(session)

    prepared: list[PreparedResponseAudio] = []
    seen_texts: set[str] = set()
    for sample_reply in ("Ja, habe ich.", "Ja, ich habe kurz Zeit.", "Ja, kein Problem."):
        dario = await Dario.for_lead(
            session,
            settings,
            ctx.business_config,
            ctx.engine,
            tool_executor,
            lead_id,
            call_id,
        )
        dario.opening_line()
        outcome = await dario.process_utterance(sample_reply)
        text = outcome.reply_text.strip()
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        cached = await ensure_cached_tts(tts, text, label="tts", call_id=call_id)
        prepared.append(PreparedResponseAudio(text=text, bytes=cached.bytes))

    return prepared
