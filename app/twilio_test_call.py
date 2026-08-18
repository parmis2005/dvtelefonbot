"""Echter Twilio-Testanruf fuer Dario.

Loest einen ECHTEN, kostenpflichtigen Outbound-Call ueber Twilio Programmable
Voice aus, der an Darios bestehende STT -> Conversation Engine -> TTS
Pipeline angebunden wird (siehe api/twilio.py, phone/twilio_media_handler.py).
Fragt vor dem eigentlichen Anruf ausdruecklich im Terminal nach Bestaetigung,
ausser der Nutzer uebergibt bewusst --yes. Ein Anruf wird nie ohne explizite
Bestaetigung oder explizites --yes ausgeloest.

Voraussetzungen:
  - `uvicorn app.main:app` laeuft (liefert den TwiML-Webhook + die
    Media-Stream-WebSocket)
  - ein oeffentlicher Tunnel (z.B. `ngrok http 8000`) zeigt auf diesen Server,
    und TWILIO_PUBLIC_BASE_URL in .env ist auf die Tunnel-URL gesetzt

Aufruf:
    python -m app.twilio_test_call
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from core.config import get_settings
from core.logging import get_logger
from database.database import get_session_factory, init_db
from database.repository import CallRepository, LeadRepository
from phone.twilio_voice import TwilioConfigError, TwilioProvider
from services.call_service import CallService
from services.greeting_audio import prepare_greeting_audio
from services.telephony_diagnostics import check_webhook_reachable

logger = get_logger(__name__)


async def _get_or_create_test_lead(session, phone_number: str):
    repo = LeadRepository(session)
    existing = await repo.get_by_phone(phone_number)
    if existing is not None:
        return existing
    return await repo.create(
        unternehmen="Twilio Testanruf",
        ansprechpartner="Testperson",
        telefonnummer=phone_number,
        branche="Test",
        online_auftritt_geprueft=True,
        entwurf_vorhanden=True,
        entwurf_link="https://beispiel.digital-vision-entwurf.de/demo",
    )


async def run(args: argparse.Namespace) -> int:
    settings = get_settings()

    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        print("FEHLER: TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN fehlen in .env.")
        return 1
    if not settings.twilio_caller_id:
        print("FEHLER: TWILIO_CALLER_ID fehlt in .env.")
        return 1
    if not settings.twilio_public_base_url:
        print(
            "FEHLER: TWILIO_PUBLIC_BASE_URL fehlt in .env.\n"
            "  Starte zuerst einen oeffentlichen Tunnel (z.B. 'ngrok http 8000'),\n"
            "  und trage die angezeigte https://...-URL dort ein (ohne abschliessenden Slash)."
        )
        return 1

    to_number = args.to or settings.twilio_test_number
    if not to_number:
        print("FEHLER: keine Zielnummer (--to oder TWILIO_TEST_NUMBER).")
        return 1

    print("=" * 60)
    print(" Dario Twilio-Testanruf")
    print("=" * 60)

    try:
        provider = TwilioProvider(
            settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_caller_id
        )
    except TwilioConfigError as exc:
        print(f"FEHLER: {exc}")
        return 1

    print("\n[1/3] Pruefe Twilio-Zugangsdaten ...")
    ok, detail = await asyncio.get_event_loop().run_in_executor(None, provider.verify_credentials)
    if not ok:
        print(f"  FEHLGESCHLAGEN: {detail}")
        print("  Pruefe TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN in .env.")
        return 1
    print(f"  OK ({detail})")

    print(f"\n[2/3] Pruefe Erreichbarkeit von {settings.twilio_public_base_url} ...")
    reachable, reach_detail = await check_webhook_reachable(settings.twilio_public_base_url)
    if reachable:
        print(f"  OK ({reach_detail})")
    else:
        print(f"  WARNUNG: {settings.twilio_public_base_url}/api/health nicht erreichbar ({reach_detail}).")
        print("  Laeuft 'uvicorn app.main:app' und der Tunnel (z.B. ngrok)? Twilio kann den")
        print("  Anruf sonst nicht mit Dario verbinden, auch wenn das Telefon klingelt.")

    await init_db()
    session_factory = get_session_factory()
    async with session_factory() as session:
        lead = await _get_or_create_test_lead(session, to_number)
        call_service = CallService(session, settings)

        # ignore_cooldown=True: dieser Testanruf wird gleich manuell mit
        # "ja" bestaetigt (siehe unten) - der normale Cooldown zwischen zwei
        # Anrufen desselben Leads soll fuer bewusst ausgeloeste Testanrufe
        # nicht gelten, bleibt aber fuer Einzelanrufe/Dashboard-Testanruf/
        # Kampagnen unveraendert aktiv (services/call_service.py). Do-Not-Call
        # und Telefonnummer-Validierung greifen weiterhin ausnahmslos.
        allowed, reason = await call_service.can_start_call(lead.id, ignore_cooldown=True)
        if not allowed:
            print(f"\nFEHLER: Anruf nicht erlaubt: {reason}")
            return 1

        print("\n[3/3] Anruf-Details:")
        print(f"  Von (verifizierte Caller-ID): {settings.twilio_caller_id}")
        print(f"  An:                           {to_number}")
        print(f"  Lead:                         {lead.unternehmen} (ID {lead.id})")
        print(f"  TwiML-Webhook:                {settings.twilio_public_base_url}/twilio/voice")
        print("\n  Dieser Anruf ist ECHT und KOSTENPFLICHTIG. Das Zieltelefon klingelt wirklich.")

        def _digits_only(n: str) -> str:
            return "".join(ch for ch in n if ch.isdigit())

        if _digits_only(to_number) == _digits_only(settings.twilio_caller_id):
            print(
                "\n  WARNUNG: Von- und Ziel-Nummer sind identisch. Viele Mobilfunknetze "
                "(insbesondere deutsche) weisen Anrufe mit identischer Anrufer-/Ziel-ID als "
                "'busy' zurueck, BEVOR Twilio unseren Webhook ueberhaupt aufruft - das "
                "Telefon klingelt dann nicht, unabhaengig von Darios Konfiguration. Fuer "
                "einen aussagekraeftigen Test empfiehlt sich eine ANDERE Zielnummer "
                "(--to +49...) als TWILIO_CALLER_ID."
            )

        if args.no_call:
            print("\nChecks erfolgreich. --no-call aktiv: kein Anruf ausgeloest.")
            return 0

        if args.yes:
            print("\n--yes gesetzt: Bestaetigung wurde ueber Kommandozeile erteilt.")
        else:
            try:
                answer = input("\nJetzt wirklich anrufen? Tippe 'ja' zum Bestaetigen: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print("\nAbgebrochen - kein Anruf ausgeloest.")
                print("Wenn dein Terminal den Prompt abbricht: npm run dev -- --yes")
                return 0
            if answer != "ja":
                print("Abgebrochen - kein Anruf ausgeloest.")
                print("Wenn dein Terminal den Prompt abbricht: npm run dev -- --yes")
                return 0

        call = await call_service.start_call(lead.id, ignore_cooldown=True)
        webhook_url = f"{settings.twilio_public_base_url}/twilio/voice?call_id={call.id}"
        status_callback_url = f"{settings.twilio_public_base_url}/twilio/status?call_id={call.id}"

        try:
            print("\nBereite Begruessungs-Audio vor ...")
            greeting = await prepare_greeting_audio(session, lead_id=lead.id, call_id=call.id)
            print(f"  OK ({greeting.bytes} Bytes)")
        except Exception as exc:
            print(f"\nFEHLER beim Vorbereiten der Begruessung: {exc}")
            await call_service.mark_failed(call.id)
            return 1

        try:
            call_sid = await asyncio.get_event_loop().run_in_executor(
                None, provider.start_outbound_call, to_number, webhook_url, status_callback_url
            )
        except Exception as exc:
            print(f"\nFEHLER beim Ausloesen des Anrufs: {exc}")
            await call_service.mark_failed(call.id)
            return 1

        await CallRepository(session).update(call.id, twilio_call_sid=call_sid)
        print(f"\nAnruf ausgeloest. Twilio Call-SID: {call_sid}")
        print("[CALL_TRIGGERED]")
        print(f"Dario-Call-ID (Dashboard/DB): {call.id}")
        print("Sobald abgenommen wird, verbindet Twilio den Anruf mit Darios Media-Stream-WebSocket.")
        return 2

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Echter Twilio-Testanruf fuer Dario")
    parser.add_argument(
        "--to", type=str, default=None, help="Zielnummer (Standard: TWILIO_TEST_NUMBER aus .env)"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Bestaetigt den kostenpflichtigen Testanruf explizit ohne interaktive Eingabe.",
    )
    parser.add_argument(
        "--no-call",
        action="store_true",
        help="Fuehrt nur Checks bis [3/3] aus und loest keinen Anruf aus.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        exit_code = asyncio.run(run(args))
    except KeyboardInterrupt:
        print("\nAbgebrochen - kein Anruf ausgeloest.")
        print("Wenn dein Terminal den Prompt abbricht: npm run dev -- --yes")
        exit_code = 0
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
