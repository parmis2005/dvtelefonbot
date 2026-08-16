"""Transcript-Service: speichert das vollstaendige Gespraechstranskript
(als JSON) - getrennt von der internen Reasoning/Prompt-Logik, damit keine
Chain-of-Thought-Inhalte gespeichert werden (Abschnitt 42)."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from agent.context import ConversationContext
from database.repository import CallRepository


def serialize_transcript(context: ConversationContext) -> str:
    turns = [
        {"speaker": t.speaker, "text": t.text, "timestamp": t.timestamp.isoformat()}
        for t in context.history
    ]
    return json.dumps(turns, ensure_ascii=False, indent=2)


async def persist_transcript(session: AsyncSession, call_id: int, context: ConversationContext) -> None:
    repo = CallRepository(session)
    await repo.update(call_id, transcript=serialize_transcript(context))


def write_transcript_file(call_id: int, context: ConversationContext, transcripts_dir: str = "./transcripts") -> Path:
    directory = Path(transcripts_dir)
    directory.mkdir(parents=True, exist_ok=True)
    filename = directory / f"call_{call_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    filename.write_text(serialize_transcript(context), encoding="utf-8")
    return filename
