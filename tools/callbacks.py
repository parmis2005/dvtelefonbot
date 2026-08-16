"""set_callback Tool: speichert Rueckrufwuensche strukturiert.

Bestaetigt NIEMALS eine feste Terminbuchung, solange kein Kalendersystem
angebunden ist (Abschnitt 15/43) - das wird hier bewusst nicht simuliert.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from agent.guardrails import guard_callback
from database.models import LeadStatus
from database.repository import LeadRepository


async def set_callback(
    session: AsyncSession, lead_id: int, callback_note: str, preferred_contact: str | None = None
) -> tuple[bool, str]:
    allowed, reason = guard_callback(callback_note)
    if not allowed:
        return False, reason

    repo = LeadRepository(session)
    fields: dict = {"callback_note": callback_note, "status": LeadStatus.CALLBACK}
    if preferred_contact:
        fields["preferred_contact"] = preferred_contact
    lead = await repo.update(lead_id, **fields)
    if lead is None:
        return False, "Lead nicht gefunden"
    return True, "Rueckrufwunsch gespeichert (nicht kalenderverbindlich)"
