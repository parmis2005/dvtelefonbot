"""Repository Layer: einziger Datenzugriffspfad fuer Leads/Calls/Do-Not-Call.

Das LLM erhaelt NIE direkten SQL-Zugriff - jede Aenderung laeuft ueber
diese Methoden, die validiert und geloggt werden koennen.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Call, CallStatus, DoNotCall, Lead, LeadStatus


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
