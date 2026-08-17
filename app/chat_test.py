"""Text-Testmodus fuer Dario - ohne Telefon, ohne Audio.

Nutzt exakt dieselbe Conversation Engine wie der spaetere Telefonie-Pfad.

Aufruf:
    python -m app.chat_test
    python -m app.chat_test --lead-id 3
    python -m app.chat_test --entwurf --geprueft   (Test-Lead mit Entwurf/Pruefung anlegen)
"""

from __future__ import annotations

import argparse
import asyncio

from agent.dario import Dario
from app.bootstrap import build_app_context
from database.database import get_session_factory, init_db
from database.repository import LeadRepository
from tools.call_tools import ToolExecutor


async def _get_or_create_test_lead(session, args) -> int:
    repo = LeadRepository(session)
    if args.lead_id:
        lead = await repo.get(args.lead_id)
        if lead is None:
            raise SystemExit(f"Lead {args.lead_id} nicht gefunden")
        return lead.id

    lead = await repo.create(
        unternehmen=args.unternehmen,
        ansprechpartner=args.ansprechpartner,
        branche="Beispielbranche",
        telefonnummer="+491701234567",
        email=None,
        online_auftritt_geprueft=args.geprueft,
        entwurf_vorhanden=args.entwurf,
        entwurf_link="https://beispiel.digital-vision-entwurf.de/demo" if args.entwurf else None,
    )
    return lead.id


async def run_chat(args: argparse.Namespace) -> None:
    await init_db()

    session_factory = get_session_factory()
    async with session_factory() as session:
        ctx = await build_app_context(session)
        lead_id = await _get_or_create_test_lead(session, args)

        tool_executor = ToolExecutor(
            session=session,
            email_provider=ctx.email_provider,
            whatsapp_provider=ctx.whatsapp_provider,
            company_name=ctx.settings.company_name,
        )

        dario = await Dario.for_lead(
            session=session,
            settings=ctx.settings,
            business_config=ctx.business_config,
            engine=ctx.engine,
            tool_executor=tool_executor,
            lead_id=lead_id,
            call_id=None,
        )

        print("=" * 60)
        print(f" Dario Text-Test  |  Lead-ID {lead_id}  |  'exit' zum Beenden")
        print("=" * 60)

        opening = dario.opening_line()
        print(f"\nDario: {opening}")

        while dario.call_active:
            try:
                user_text = input("Du: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[Beendet]")
                break
            if not user_text:
                continue
            if user_text.lower() in {"exit", "quit", "q"}:
                print("[Test manuell beendet]")
                break

            outcome = await dario.process_utterance(user_text)
            if outcome.reply_text:
                print(f"Dario: {outcome.reply_text}")
            for note in outcome.tool_results or []:
                print(f"   [tool] {note}")
            if outcome.call_ended:
                print(f"\n[Call beendet | Zustand: {dario.context.state.value} | "
                      f"Ergebnis: {dario.context.call_result}]")
                break


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dario Text-Testmodus")
    parser.add_argument("--lead-id", type=int, default=None, help="bestehenden Lead verwenden")
    parser.add_argument("--unternehmen", type=str, default="Beauty Studio Beispiel")
    parser.add_argument("--ansprechpartner", type=str, default="Frau Mueller")
    parser.add_argument("--entwurf", action="store_true", help="Test-Lead mit vorhandenem Entwurf anlegen")
    parser.add_argument("--geprueft", action="store_true", help="Test-Lead mit geprueftem Online-Auftritt anlegen")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_chat(args))


if __name__ == "__main__":
    main()
