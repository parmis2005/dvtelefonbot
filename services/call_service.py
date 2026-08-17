"""Call-Service: Cooldown/Do-Not-Call-Pruefung vor jedem Outbound-Call,
sowie Lebenszyklus-Uebergaenge eines Calls."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from agent.guardrails import guard_outbound_call, is_valid_phone
from core.config import Settings
from database.models import Call, CallStatus
from database.repository import (
    AppSettingRepository,
    CallRepository,
    DoNotCallRepository,
    LeadRepository,
)
from services.lead_service import is_valid_phone_number


class CallNotAllowedError(Exception):
    pass


class CallService:
    def __init__(self, session: AsyncSession, settings: Settings):
        self.session = session
        self.settings = settings
        self.lead_repo = LeadRepository(session)
        self.call_repo = CallRepository(session)
        self.dnc_repo = DoNotCallRepository(session)

    async def can_start_call(self, lead_id: int) -> tuple[bool, str]:
        lead = await self.lead_repo.get(lead_id)
        if lead is None:
            return False, "Lead nicht gefunden"

        # Do-Not-Call wird sowohl am Lead-Flag als auch an der persistenten,
        # nummernbasierten Sperrliste geprueft (Abschnitt 45) - die Sperrliste
        # gilt auch, wenn dieselbe Nummer unter einem neuen/anderen Lead
        # importiert wurde.
        is_blocked = lead.do_not_call or await self.dnc_repo.is_blocked(lead.telefonnummer)

        phone_valid = is_valid_phone(lead.telefonnummer) or is_valid_phone_number(lead.telefonnummer)
        cooldown_ok, cooldown_reason = await self.lead_repo.can_call_now(
            lead_id, await self._effective_call_cooldown()
        )
        allowed, guard_reason = guard_outbound_call(
            do_not_call=is_blocked, phone_valid=phone_valid, cooldown_ok=cooldown_ok
        )
        if not allowed:
            # cooldown_reason ist spezifischer (unterscheidet Cooldown-Zeitfenster
            # von einem bereits aktiven Call) als die generische Guard-Meldung.
            reason = cooldown_reason if not cooldown_ok else guard_reason
            return False, reason
        return True, "ok"

    async def _effective_call_cooldown(self) -> int:
        """Liest eine im Dashboard gespeicherte Cooldown-Ueberschreibung
        (Abschnitt 28 "Einstellungen", database/models.py::AppSetting), sonst
        .env-Fallback (self.settings.call_cooldown)."""
        stored = await AppSettingRepository(self.session).get("call_cooldown_seconds")
        if stored:
            try:
                return int(stored)
            except ValueError:
                pass
        return self.settings.call_cooldown

    async def start_call(self, lead_id: int) -> Call:
        allowed, reason = await self.can_start_call(lead_id)
        if not allowed:
            raise CallNotAllowedError(reason)
        call = await self.call_repo.create(lead_id=lead_id, status=CallStatus.CREATED)
        return call

    async def mark_answered(self, call_id: int) -> Call | None:
        from datetime import datetime

        return await self.call_repo.update(
            call_id, status=CallStatus.ANSWERED, answered_at=datetime.utcnow()
        )

    async def mark_busy(self, call_id: int) -> Call | None:
        return await self.call_repo.mark_ended(call_id, CallStatus.BUSY, result="NO_ANSWER")

    async def mark_no_answer(self, call_id: int) -> Call | None:
        return await self.call_repo.mark_ended(call_id, CallStatus.NO_ANSWER, result="NO_ANSWER")

    async def mark_failed(self, call_id: int) -> Call | None:
        return await self.call_repo.mark_ended(call_id, CallStatus.FAILED, result="UNKNOWN")

    async def hangup(self, call_id: int, result: str | None = None) -> Call | None:
        return await self.call_repo.mark_ended(call_id, CallStatus.HANGUP, result=result)

    async def complete(self, call_id: int, result: str | None = None) -> Call | None:
        return await self.call_repo.mark_ended(call_id, CallStatus.COMPLETED, result=result)
