"""Lokaler, lesbarer Spiegel der Dashboard-Daten fuer VS Code.

Die Datenbank bleibt die Quelle der Wahrheit. Dieser Export schreibt nach
Dashboard-Aenderungen JSON/Markdown-Dateien in ``dashboard_state/``, damit
Konfiguration, Kontakte, Kampagnen und Gespraechsdokumentation im Projektordner
nachvollziehbar sind, ohne die SQLite-Datei direkt zu oeffnen.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Call, Campaign, Lead, PromptVersion, VoiceProfile
from database.repository import (
    AppSettingRepository,
    CallRepository,
    CampaignRepository,
    LeadRepository,
    PromptVersionRepository,
    VoiceProfileRepository,
)

logger = logging.getLogger(__name__)

EXPORT_DIR = Path(__file__).resolve().parent.parent / "dashboard_state"


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(path)


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(content, encoding="utf-8")
    tmp_path.replace(path)


def _lead_to_dict(lead: Lead) -> dict[str, Any]:
    return {
        "id": lead.id,
        "unternehmen": lead.unternehmen,
        "ansprechpartner": lead.ansprechpartner,
        "branche": lead.branche,
        "website_url": lead.website_url,
        "telefonnummer": lead.telefonnummer,
        "email": lead.email,
        "notizen": lead.notizen,
        "online_auftritt_geprueft": lead.online_auftritt_geprueft,
        "entwurf_vorhanden": lead.entwurf_vorhanden,
        "entwurf_link": lead.entwurf_link,
        "status": _enum_value(lead.status),
        "preferred_contact": _enum_value(lead.preferred_contact),
        "callback_at": _iso(lead.callback_at),
        "callback_note": lead.callback_note,
        "do_not_call": lead.do_not_call,
        "created_at": _iso(lead.created_at),
        "updated_at": _iso(lead.updated_at),
    }


def _call_to_dict(call: Call) -> dict[str, Any]:
    return {
        "id": call.id,
        "lead_id": call.lead_id,
        "campaign_id": call.campaign_id,
        "status": _enum_value(call.status),
        "result": _enum_value(call.result),
        "started_at": _iso(call.started_at),
        "answered_at": _iso(call.answered_at),
        "ended_at": _iso(call.ended_at),
        "duration": call.duration,
        "summary": call.summary,
        "transcript": call.transcript,
        "twilio_call_sid": call.twilio_call_sid,
        "created_at": _iso(call.created_at),
    }


def _campaign_to_dict(campaign: Campaign) -> dict[str, Any]:
    try:
        lead_ids = json.loads(campaign.lead_ids_json)
    except json.JSONDecodeError:
        lead_ids = []
    return {
        "id": campaign.id,
        "name": campaign.name,
        "lead_ids": lead_ids,
        "max_concurrent": campaign.max_concurrent,
        "status": _enum_value(campaign.status),
        "total_count": campaign.total_count,
        "processed_count": campaign.processed_count,
        "created_at": _iso(campaign.created_at),
        "updated_at": _iso(campaign.updated_at),
        "started_at": _iso(campaign.started_at),
        "finished_at": _iso(campaign.finished_at),
    }


def _prompt_to_dict(prompt: PromptVersion) -> dict[str, Any]:
    return {
        "id": prompt.id,
        "version_number": prompt.version_number,
        "label": prompt.label,
        "is_active": prompt.is_active,
        "created_at": _iso(prompt.created_at),
        "content": prompt.content,
    }


def _voice_to_dict(voice: VoiceProfile) -> dict[str, Any]:
    return {
        "id": voice.id,
        "name": voice.name,
        "file_path": voice.file_path,
        "is_active": voice.is_active,
        "is_builtin": voice.is_builtin,
        "exaggeration": voice.exaggeration,
        "cfg_weight": voice.cfg_weight,
        "temperature": voice.temperature,
        "created_at": _iso(voice.created_at),
    }


async def export_dashboard_state(session: AsyncSession, *, reason: str) -> None:
    """Schreibt den aktuellen Dashboard-Zustand in lokale Projektdateien."""

    generated_at = datetime.utcnow().isoformat()

    settings = await AppSettingRepository(session).get_all()
    leads = [_lead_to_dict(lead) for lead in await LeadRepository(session).list_all(limit=5000)]
    calls = [_call_to_dict(call) for call in await CallRepository(session).list_all(limit=5000)]
    campaigns = [
        _campaign_to_dict(campaign)
        for campaign in await CampaignRepository(session).list_all(limit=1000)
    ]
    prompts = [
        _prompt_to_dict(prompt)
        for prompt in await PromptVersionRepository(session).list_all(limit=1000)
    ]
    voices = [_voice_to_dict(voice) for voice in await VoiceProfileRepository(session).list_all()]
    active_prompt = next((prompt for prompt in prompts if prompt["is_active"]), None)

    _write_json(
        EXPORT_DIR / "manifest.json",
        {
            "generated_at": generated_at,
            "reason": reason,
            "files": [
                "settings.json",
                "leads.json",
                "calls.json",
                "campaigns.json",
                "prompt_versions.json",
                "active_prompt.md",
                "voices.json",
            ],
        },
    )
    _write_json(EXPORT_DIR / "settings.json", {"generated_at": generated_at, "values": settings})
    _write_json(EXPORT_DIR / "leads.json", {"generated_at": generated_at, "items": leads})
    _write_json(EXPORT_DIR / "calls.json", {"generated_at": generated_at, "items": calls})
    _write_json(EXPORT_DIR / "campaigns.json", {"generated_at": generated_at, "items": campaigns})
    _write_json(
        EXPORT_DIR / "prompt_versions.json",
        {"generated_at": generated_at, "items": prompts},
    )
    _write_json(EXPORT_DIR / "voices.json", {"generated_at": generated_at, "items": voices})
    _write_text(
        EXPORT_DIR / "active_prompt.md",
        (active_prompt["content"] if active_prompt else "") + "\n",
    )


async def export_dashboard_state_safely(session: AsyncSession, *, reason: str) -> None:
    try:
        await export_dashboard_state(session, reason=reason)
    except Exception:
        logger.exception("Dashboard-State-Export fehlgeschlagen: %s", reason)
