"""Repository Layer: einziger Datenzugriffspfad fuer Leads/Calls/Do-Not-Call.

Das LLM erhaelt NIE direkten SQL-Zugriff - jede Aenderung laeuft ueber
diese Methoden, die validiert und geloggt werden koennen.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    AppSetting,
    Call,
    CallStatus,
    Campaign,
    CampaignStatus,
    DashboardSession,
    DoNotCall,
    Lead,
    LeadStatus,
    PromptVersion,
    VoiceProfile,
)


class LeadRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, **fields: Any) -> Lead:
        lead = Lead(**fields)
        self.session.add(lead)
        await self.session.commit()
        await self.session.refresh(lead)
        return lead

    async def get(self, lead_id: int) -> Lead | None:
        return await self.session.get(Lead, lead_id)

    async def get_by_phone(self, phone: str) -> Lead | None:
        result = await self.session.execute(select(Lead).where(Lead.telefonnummer == phone))
        return result.scalar_one_or_none()

    async def list_all(self, limit: int = 500) -> list[Lead]:
        result = await self.session.execute(
            select(Lead).order_by(Lead.updated_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def update(self, lead_id: int, **fields: Any) -> Lead | None:
        lead = await self.get(lead_id)
        if lead is None:
            return None
        for key, value in fields.items():
            if value is not None and hasattr(lead, key):
                setattr(lead, key, value)
        lead.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(lead)
        return lead

    async def set_status(self, lead_id: int, status: LeadStatus) -> Lead | None:
        return await self.update(lead_id, status=status)

    async def delete(self, lead_id: int) -> bool:
        lead = await self.get(lead_id)
        if lead is None:
            return False
        await self.session.delete(lead)
        await self.session.commit()
        return True

    async def set_do_not_call(self, lead_id: int, value: bool = True) -> Lead | None:
        lead = await self.update(lead_id, do_not_call=value)
        if lead and value:
            await self.update(lead_id, status=LeadStatus.DO_NOT_CALL)
        return lead

    async def can_call_now(self, lead_id: int, cooldown_seconds: int) -> tuple[bool, str]:
        """Prueft Cooldown und aktive Calls VOR jedem Outbound-Call.

        Die Do-Not-Call-Pruefung erfolgt separat (siehe services/call_service.py),
        da sie zusaetzlich die nummernbasierte, leadunabhaengige Sperrliste
        beruecksichtigen muss.
        """
        lead = await self.get(lead_id)
        if lead is None:
            return False, "Lead nicht gefunden"

        call_repo = CallRepository(self.session)
        last_call = await call_repo.get_last_call_for_lead(lead_id)
        if last_call and last_call.started_at:
            elapsed = (datetime.utcnow() - last_call.started_at).total_seconds()
            if elapsed < cooldown_seconds:
                remaining = int(cooldown_seconds - elapsed)
                return False, f"Cooldown aktiv, noch {remaining}s"

        active = await call_repo.get_active_call_for_lead(lead_id)
        if active is not None:
            return False, "Lead befindet sich bereits in einem aktiven Gespraech"

        return True, "ok"


class CallRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, lead_id: int, **fields: Any) -> Call:
        call = Call(lead_id=lead_id, started_at=datetime.utcnow(), **fields)
        self.session.add(call)
        await self.session.commit()
        await self.session.refresh(call)
        return call

    async def get(self, call_id: int) -> Call | None:
        return await self.session.get(Call, call_id)

    async def list_all(self, limit: int = 500) -> list[Call]:
        result = await self.session.execute(
            select(Call).order_by(Call.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def list_for_lead(self, lead_id: int) -> list[Call]:
        result = await self.session.execute(
            select(Call).where(Call.lead_id == lead_id).order_by(Call.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_for_campaign(self, campaign_id: int) -> list[Call]:
        result = await self.session.execute(
            select(Call).where(Call.campaign_id == campaign_id).order_by(Call.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_last_call_for_lead(self, lead_id: int) -> Call | None:
        result = await self.session.execute(
            select(Call)
            .where(Call.lead_id == lead_id)
            .order_by(Call.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_active_call_for_lead(self, lead_id: int) -> Call | None:
        active_statuses = [CallStatus.CREATED, CallStatus.RINGING, CallStatus.ANSWERED]
        result = await self.session.execute(
            select(Call).where(Call.lead_id == lead_id, Call.status.in_(active_statuses))
        )
        return result.scalar_one_or_none()

    async def update(self, call_id: int, **fields: Any) -> Call | None:
        call = await self.get(call_id)
        if call is None:
            return None
        for key, value in fields.items():
            if value is not None and hasattr(call, key):
                setattr(call, key, value)
        await self.session.commit()
        await self.session.refresh(call)
        return call

    async def mark_ended(
        self, call_id: int, status: CallStatus, result: str | None = None
    ) -> Call | None:
        call = await self.get(call_id)
        if call is None:
            return None
        call.ended_at = datetime.utcnow()
        call.status = status
        if result:
            call.result = result
        if call.started_at:
            call.duration = int((call.ended_at - call.started_at).total_seconds())
        await self.session.commit()
        await self.session.refresh(call)
        return call


class DoNotCallRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def add(self, phone: str, reason: str | None = None) -> DoNotCall:
        existing = await self.is_blocked(phone)
        if existing:
            result = await self.session.execute(
                select(DoNotCall).where(DoNotCall.telefonnummer == phone)
            )
            return result.scalar_one()
        entry = DoNotCall(telefonnummer=phone, reason=reason)
        self.session.add(entry)
        await self.session.commit()
        await self.session.refresh(entry)
        return entry

    async def is_blocked(self, phone: str) -> bool:
        result = await self.session.execute(
            select(DoNotCall).where(DoNotCall.telefonnummer == phone)
        )
        return result.scalar_one_or_none() is not None

    async def list_all(self, limit: int = 1000) -> list[DoNotCall]:
        result = await self.session.execute(
            select(DoNotCall).order_by(DoNotCall.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def remove(self, phone: str) -> bool:
        result = await self.session.execute(
            select(DoNotCall).where(DoNotCall.telefonnummer == phone)
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            return False
        await self.session.delete(entry)
        await self.session.commit()
        return True


class CampaignRepository:
    """Datenzugriff fuer Sammelanruf-Kampagnen. Die eigentliche
    Ablaufsteuerung (Nebenlaeufigkeit, Pause/Fortsetzen/Stop) lebt in
    services/campaign_service.py::CampaignManager - dieses Repository
    kennt nur Persistenz."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, name: str, lead_ids_json: str, max_concurrent: int) -> Campaign:
        campaign = Campaign(
            name=name,
            lead_ids_json=lead_ids_json,
            max_concurrent=max_concurrent,
            total_count=len(json.loads(lead_ids_json)),
        )
        self.session.add(campaign)
        await self.session.commit()
        await self.session.refresh(campaign)
        return campaign

    async def get(self, campaign_id: int) -> Campaign | None:
        return await self.session.get(Campaign, campaign_id)

    async def list_all(self, limit: int = 200) -> list[Campaign]:
        result = await self.session.execute(
            select(Campaign).order_by(Campaign.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def list_running_or_paused(self) -> list[Campaign]:
        result = await self.session.execute(
            select(Campaign).where(
                Campaign.status.in_([CampaignStatus.RUNNING, CampaignStatus.PAUSED])
            )
        )
        return list(result.scalars().all())

    async def update(self, campaign_id: int, **fields: Any) -> Campaign | None:
        campaign = await self.get(campaign_id)
        if campaign is None:
            return None
        for key, value in fields.items():
            if value is not None and hasattr(campaign, key):
                setattr(campaign, key, value)
        campaign.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(campaign)
        return campaign

    async def increment_processed(self, campaign_id: int) -> Campaign | None:
        campaign = await self.get(campaign_id)
        if campaign is None:
            return None
        campaign.processed_count += 1
        campaign.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(campaign)
        return campaign


class PromptVersionRepository:
    """Versionierter Systemprompt. Immer genau eine Version hat
    is_active=True; neue Calls lesen sie ueber agent/prompts.py."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_version(
        self, content: str, label: str | None = None, activate: bool = True
    ) -> PromptVersion:
        result = await self.session.execute(
            select(PromptVersion).order_by(PromptVersion.version_number.desc()).limit(1)
        )
        last = result.scalar_one_or_none()
        next_number = (last.version_number + 1) if last else 1

        if activate:
            active_result = await self.session.execute(
                select(PromptVersion).where(PromptVersion.is_active.is_(True))
            )
            for existing in active_result.scalars().all():
                existing.is_active = False

        version = PromptVersion(
            version_number=next_number, content=content, label=label, is_active=activate
        )
        self.session.add(version)
        await self.session.commit()
        await self.session.refresh(version)
        return version

    async def get(self, version_id: int) -> PromptVersion | None:
        return await self.session.get(PromptVersion, version_id)

    async def get_active(self) -> PromptVersion | None:
        result = await self.session.execute(
            select(PromptVersion).where(PromptVersion.is_active.is_(True)).limit(1)
        )
        return result.scalar_one_or_none()

    async def list_all(self, limit: int = 200) -> list[PromptVersion]:
        result = await self.session.execute(
            select(PromptVersion).order_by(PromptVersion.version_number.desc()).limit(limit)
        )
        return list(result.scalars().all())

    async def activate(self, version_id: int) -> PromptVersion | None:
        version = await self.get(version_id)
        if version is None:
            return None
        result = await self.session.execute(
            select(PromptVersion).where(PromptVersion.is_active.is_(True))
        )
        for existing in result.scalars().all():
            existing.is_active = False
        version.is_active = True
        await self.session.commit()
        await self.session.refresh(version)
        return version


class VoiceProfileRepository:
    """Hochladbare Chatterbox-Referenzstimmen. Genau eine Stimme hat
    is_active=True; app/bootstrap.py::get_tts_provider() liest sie."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        name: str,
        file_path: str,
        is_builtin: bool = False,
        exaggeration: float = 0.22,
        cfg_weight: float = 0.35,
        temperature: float = 0.55,
        activate: bool = False,
    ) -> VoiceProfile:
        if activate:
            result = await self.session.execute(
                select(VoiceProfile).where(VoiceProfile.is_active.is_(True))
            )
            for existing in result.scalars().all():
                existing.is_active = False
        profile = VoiceProfile(
            name=name,
            file_path=file_path,
            is_builtin=is_builtin,
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
            temperature=temperature,
            is_active=activate,
        )
        self.session.add(profile)
        await self.session.commit()
        await self.session.refresh(profile)
        return profile

    async def get(self, profile_id: int) -> VoiceProfile | None:
        return await self.session.get(VoiceProfile, profile_id)

    async def get_active(self) -> VoiceProfile | None:
        result = await self.session.execute(
            select(VoiceProfile).where(VoiceProfile.is_active.is_(True)).limit(1)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[VoiceProfile]:
        result = await self.session.execute(
            select(VoiceProfile).order_by(VoiceProfile.created_at.desc())
        )
        return list(result.scalars().all())

    async def rename(self, profile_id: int, name: str) -> VoiceProfile | None:
        profile = await self.get(profile_id)
        if profile is None:
            return None
        profile.name = name
        await self.session.commit()
        await self.session.refresh(profile)
        return profile

    async def activate(self, profile_id: int) -> VoiceProfile | None:
        profile = await self.get(profile_id)
        if profile is None:
            return None
        result = await self.session.execute(
            select(VoiceProfile).where(VoiceProfile.is_active.is_(True))
        )
        for existing in result.scalars().all():
            existing.is_active = False
        profile.is_active = True
        await self.session.commit()
        await self.session.refresh(profile)
        return profile

    async def delete(self, profile_id: int) -> bool:
        profile = await self.get(profile_id)
        if profile is None:
            return False
        await self.session.delete(profile)
        await self.session.commit()
        return True


class AppSettingRepository:
    """Laufzeit-editierbare Dashboard-Einstellungen (kein Secret-Material -
    siehe database/models.py::AppSetting)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, key: str) -> str | None:
        setting = await self.session.get(AppSetting, key)
        return setting.value if setting else None

    async def get_all(self) -> dict[str, str]:
        result = await self.session.execute(select(AppSetting))
        return {row.key: row.value for row in result.scalars().all()}

    async def set(self, key: str, value: str) -> AppSetting:
        setting = await self.session.get(AppSetting, key)
        if setting is None:
            setting = AppSetting(key=key, value=value)
            self.session.add(setting)
        else:
            setting.value = value
            setting.updated_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(setting)
        return setting

    async def set_many(self, values: dict[str, str]) -> None:
        for key, value in values.items():
            await self.set(key, value)


class DashboardSessionRepository:
    """Persistenter Speicher fuer Dashboard-Login-Sessions (core/auth.py) -
    siehe database/models.py::DashboardSession fuer die Begruendung, warum
    dies nicht nur In-Memory gehalten wird."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, token: str, expires_at: datetime) -> DashboardSession:
        row = DashboardSession(token=token, expires_at=expires_at)
        self.session.add(row)
        await self.session.commit()
        return row

    async def get_valid(self, token: str) -> DashboardSession | None:
        row = await self.session.get(DashboardSession, token)
        if row is None:
            return None
        if row.expires_at < datetime.utcnow():
            await self.session.delete(row)
            await self.session.commit()
            return None
        return row

    async def delete(self, token: str) -> None:
        await self.session.execute(delete(DashboardSession).where(DashboardSession.token == token))
        await self.session.commit()

    async def delete_expired(self) -> None:
        """Beilaeufiges Aufraeumen abgelaufener Zeilen (z.B. bei jedem
        Login-Versuch aufgerufen) - keine eigene Cron-Infrastruktur noetig
        fuer eine so kleine, seltene Tabelle."""
        await self.session.execute(
            delete(DashboardSession).where(DashboardSession.expires_at < datetime.utcnow())
        )
        await self.session.commit()
