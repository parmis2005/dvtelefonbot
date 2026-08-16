"""Dashboard-Router: einfaches, serverseitig gerendertes Web-UI (Abschnitt 53).

Bewusst schlank gehalten - Version 1 zeigt Lead-Liste, Lead-Detail mit
Transkript/Zusammenfassung und erlaubt das Ausloesen eines Outbound-Calls
ueber die bestehende API.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from database.database import get_db_session
from database.repository import CallRepository, LeadRepository

router = APIRouter(tags=["dashboard"])

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/", response_class=HTMLResponse)
async def dashboard_index(request: Request, session: DbSession) -> HTMLResponse:
    leads = await LeadRepository(session).list_all()
    call_repo = CallRepository(session)

    rows = []
    for lead in leads:
        calls = await call_repo.list_for_lead(lead.id)
        last_call = calls[0] if calls else None
        rows.append({"lead": lead, "last_call": last_call})

    return templates.TemplateResponse(request, "index.html", {"rows": rows})


@router.get("/leads/{lead_id}", response_class=HTMLResponse)
async def dashboard_lead_detail(request: Request, lead_id: int, session: DbSession) -> HTMLResponse:
    lead = await LeadRepository(session).get(lead_id)
    calls = await CallRepository(session).list_for_lead(lead_id) if lead else []
    return templates.TemplateResponse(request, "lead_detail.html", {"lead": lead, "calls": calls})
