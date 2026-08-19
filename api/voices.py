"""Stimmenverwaltung (Abschnitt 22-23): Upload/Umbenennen/Auswaehlen/Loeschen/
Testen/Aktivieren von Chatterbox-Referenzstimmen.

Aktivieren wirkt sofort auf alle NEUEN Anrufe, ohne Backend-Neustart (siehe
app/bootstrap.py::get_tts_provider). Keine kuenstlichen Pitch-/Time-Stretch-
Effekte: voice/tts/chatterbox_tts.py wendet ausschliesslich
exaggeration/cfg_weight/temperature + Referenzstimmen-Cloning an, keine
nachtraegliche DSP-Verarbeitung.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agent.guardrails import looks_like_prompt_leak
from core.auth import require_auth
from core.config import get_settings
from database.database import get_db_session
from database.models import VoiceProfile
from database.repository import VoiceProfileRepository
from services.dashboard_state_export import export_dashboard_state_safely

router = APIRouter(prefix="/api/voices", tags=["voices"], dependencies=[Depends(require_auth)])

DbSession = Annotated[AsyncSession, Depends(get_db_session)]

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "models" / "voice_reference" / "uploads"
SAMPLE_DIR = BASE_DIR / "models" / "voice_reference" / "samples"

DEFAULT_TEST_TEXT = (
    "Guten Tag, hier ist Dario von Digital Vision. Ich melde mich kurz zu Ihrem Online-Auftritt."
)
MAX_VOICE_TEST_TEXT_CHARS = 280


class VoiceProfileOut(BaseModel):
    id: int
    name: str
    is_active: bool
    is_builtin: bool
    exaggeration: float
    cfg_weight: float
    temperature: float
    created_at: str

    @classmethod
    def from_model(cls, v: VoiceProfile) -> VoiceProfileOut:
        return cls(
            id=v.id,
            name=v.name,
            is_active=v.is_active,
            is_builtin=v.is_builtin,
            exaggeration=v.exaggeration,
            cfg_weight=v.cfg_weight,
            temperature=v.temperature,
            created_at=v.created_at.isoformat(),
        )


class VoiceProfileRename(BaseModel):
    name: str


async def _ensure_seeded(repo: VoiceProfileRepository) -> None:
    """Frische Installation: die bereits produktiv entschiedene Dario-Stimme
    (siehe CLAUDE.md 'Darios Stimme') wird als erstes, aktives Profil
    uebernommen, statt den Nutzer erneut hochladen zu lassen."""
    existing = await repo.list_all()
    if existing:
        return
    settings = get_settings()
    ref_path = settings.chatterbox_reference_audio_path
    if ref_path and Path(ref_path).exists():
        await repo.create(
            name="Dario (aktuell)",
            file_path=str(Path(ref_path).resolve()),
            is_builtin=False,
            exaggeration=settings.chatterbox_exaggeration,
            cfg_weight=settings.chatterbox_cfg_weight,
            temperature=settings.chatterbox_temperature,
            activate=True,
        )
    else:
        await repo.create(
            name="Chatterbox Standardstimme",
            file_path="",
            is_builtin=True,
            exaggeration=settings.chatterbox_exaggeration,
            cfg_weight=settings.chatterbox_cfg_weight,
            temperature=settings.chatterbox_temperature,
            activate=True,
        )


@router.get("", response_model=list[VoiceProfileOut])
async def list_voices(session: DbSession) -> list[VoiceProfileOut]:
    repo = VoiceProfileRepository(session)
    await _ensure_seeded(repo)
    return [VoiceProfileOut.from_model(v) for v in await repo.list_all()]


@router.post("/upload", response_model=VoiceProfileOut, status_code=201)
async def upload_voice(session: DbSession, name: str, file: UploadFile) -> VoiceProfileOut:
    if not file.filename or not file.filename.lower().endswith(".wav"):
        raise HTTPException(status_code=422, detail="Nur WAV-Dateien werden unterstuetzt.")

    raw = await file.read()
    if len(raw) < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise HTTPException(status_code=422, detail="Datei ist keine gueltige WAV-Datei.")
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(status_code=422, detail="Datei zu gross (max. 25MB).")

    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c for c in name if c.isalnum() or c in " _-").strip() or "stimme"
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex}_{safe_name}.wav"
    dest.write_bytes(raw)

    settings = get_settings()
    repo = VoiceProfileRepository(session)
    profile = await repo.create(
        name=name,
        file_path=str(dest.resolve()),
        is_builtin=False,
        exaggeration=settings.chatterbox_exaggeration,
        cfg_weight=settings.chatterbox_cfg_weight,
        temperature=settings.chatterbox_temperature,
        activate=False,
    )
    await export_dashboard_state_safely(session, reason="voice_uploaded")
    return VoiceProfileOut.from_model(profile)


@router.patch("/{voice_id}", response_model=VoiceProfileOut)
async def rename_voice(voice_id: int, payload: VoiceProfileRename, session: DbSession) -> VoiceProfileOut:
    profile = await VoiceProfileRepository(session).rename(voice_id, payload.name)
    if profile is None:
        raise HTTPException(status_code=404, detail="Stimme nicht gefunden")
    await export_dashboard_state_safely(session, reason="voice_renamed")
    return VoiceProfileOut.from_model(profile)


@router.post("/{voice_id}/activate", response_model=VoiceProfileOut)
async def activate_voice(voice_id: int, session: DbSession) -> VoiceProfileOut:
    profile = await VoiceProfileRepository(session).activate(voice_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Stimme nicht gefunden")
    await export_dashboard_state_safely(session, reason="voice_activated")
    return VoiceProfileOut.from_model(profile)


@router.delete("/{voice_id}", status_code=204)
async def delete_voice(voice_id: int, session: DbSession) -> None:
    repo = VoiceProfileRepository(session)
    profile = await repo.get(voice_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Stimme nicht gefunden")
    if profile.is_builtin:
        raise HTTPException(status_code=400, detail="Die eingebaute Standardstimme kann nicht geloescht werden.")
    file_path = profile.file_path
    await repo.delete(voice_id)
    if file_path and Path(file_path).exists() and Path(file_path).is_relative_to(UPLOAD_DIR):
        Path(file_path).unlink(missing_ok=True)
    await export_dashboard_state_safely(session, reason="voice_deleted")


@router.post("/{voice_id}/test")
async def test_voice(voice_id: int, session: DbSession, text: str | None = None) -> FileResponse:
    """Erzeugt ein Sample mit den Parametern dieses Profils (kein
    Pitch-/Time-Stretch, siehe Moduldocstring) und liefert es als WAV
    zurueck - fuer den 'Audio generieren'/'Anhoeren'-Button."""
    repo = VoiceProfileRepository(session)
    profile = await repo.get(voice_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Stimme nicht gefunden")

    from voice.tts.chatterbox_tts import ChatterboxTTSProvider

    settings = get_settings()
    provider = ChatterboxTTSProvider(
        language=settings.chatterbox_language,
        exaggeration=profile.exaggeration,
        cfg_weight=profile.cfg_weight,
        temperature=profile.temperature,
        device=settings.chatterbox_device,
        max_attempts=settings.chatterbox_max_attempts,
        reference_audio_path=None if profile.is_builtin else (profile.file_path or None),
    )
    if not await provider.is_available():
        raise HTTPException(
            status_code=502,
            detail="Chatterbox nicht verfuegbar (Paket fehlt oder Referenzdatei nicht gefunden).",
        )

    spoken_text = (text or DEFAULT_TEST_TEXT).strip()
    if len(spoken_text) > MAX_VOICE_TEST_TEXT_CHARS:
        raise HTTPException(
            status_code=422,
            detail=(
                "Der Stimmtest-Text ist zu lang. Bitte maximal "
                f"{MAX_VOICE_TEST_TEXT_CHARS} Zeichen verwenden."
            ),
        )
    if looks_like_prompt_leak(spoken_text):
        raise HTTPException(
            status_code=422,
            detail="Der Stimmtest darf keinen Systemprompt oder Prompt-Text sprechen.",
        )

    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SAMPLE_DIR / f"test_{voice_id}.wav"
    try:
        await provider.synthesize(spoken_text, str(out_path))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Sprachsynthese fehlgeschlagen: {exc}") from exc

    return FileResponse(out_path, media_type="audio/wav", filename=f"{profile.name}.wav")
