"""Small file cache for TTS snippets that must be ready before a call starts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.config import BASE_DIR
from core.logging import get_logger
from voice.tts.base import TextToSpeechProvider

logger = get_logger(__name__)

CACHE_DIR = BASE_DIR / "data" / "tts_cache"
_locks: dict[str, asyncio.Lock] = {}


@dataclass(frozen=True)
class CachedTTS:
    path: Path
    bytes: int


def _public_provider_config(tts: TextToSpeechProvider) -> dict[str, Any]:
    config: dict[str, Any] = {"provider": type(tts).__name__}
    for key, value in vars(tts).items():
        if key.startswith("_"):
            continue
        if isinstance(value, str | int | float | bool) or value is None:
            config[key] = value
    return config


def _cache_path(tts: TextToSpeechProvider, text: str, label: str) -> Path:
    payload = {"label": label, "text": text, "tts": _public_provider_config(tts)}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:24]
    return CACHE_DIR / f"{label}_{digest}.wav"


async def ensure_cached_tts(
    tts: TextToSpeechProvider,
    text: str,
    *,
    label: str = "tts",
    call_id: int | None = None,
) -> CachedTTS:
    """Generate a stable WAV once and reuse it for later calls.

    This is deliberately file-backed instead of process-only: Chatterbox is slow
    enough that a backend reload should not force the next real caller to wait
    silently through model loading and synthesis.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(tts, text, label)
    if path.exists() and path.stat().st_size > 44:
        return CachedTTS(path=path, bytes=path.stat().st_size)

    lock = _locks.setdefault(str(path), asyncio.Lock())
    async with lock:
        if path.exists() and path.stat().st_size > 44:
            return CachedTTS(path=path, bytes=path.stat().st_size)

        logger.info(
            "[TTS] generation started call_id=%s label=%s provider=%s chars=%s",
            call_id,
            label,
            type(tts).__name__,
            len(text),
        )
        with tempfile.NamedTemporaryFile(suffix=".wav", dir=CACHE_DIR, delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            await tts.synthesize(text, str(tmp_path))
            tmp_path.replace(path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            logger.exception("[TTS] generation failed call_id=%s label=%s", call_id, label)
            raise

        size = path.stat().st_size
        logger.info("[TTS] generation finished bytes=%s call_id=%s label=%s", size, call_id, label)
        return CachedTTS(path=path, bytes=size)
