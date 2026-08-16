"""Do-Not-Call: harte, persistente Sperre - keine reine Prompt-Regel.

is_do_not_call() MUSS vor jedem Outbound-Call geprueft werden
(siehe phone/call_controller.py::start_outbound_call).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from database.repository import DoNotCallRepository, LeadRepository


async def set_do_not_call(session: AsyncSession, phone: str, lead_id: int | None, reason: str = "Kunde hat widersprochen") -> None:
    dnc_repo = DoNotCallRepository(session)
    await dnc_repo.add(phone, reason=reason)
    if lead_id is not None:
        lead_repo = LeadRepository(session)
        await lead_repo.set_do_not_call(lead_id, True)


async def is_do_not_call(session: AsyncSession, phone: str) -> bool:
    dnc_repo = DoNotCallRepository(session)
    return await dnc_repo.is_blocked(phone)
