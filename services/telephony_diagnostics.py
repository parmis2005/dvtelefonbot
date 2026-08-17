"""Diagnose-Hilfsfunktionen fuer die Twilio-Anbindung, insbesondere die
Erreichbarkeit des oeffentlichen Webhook-Tunnels (ngrok o.ae.).

Direkter Hintergrund: ein echter Testanruf schlug mit Twilio-Fehler 11200
("Got HTTP 502 response") fehl, weil das Backend zum Anrufzeitpunkt nicht
unter TWILIO_PUBLIC_BASE_URL erreichbar war (kein Code-Fehler, siehe
CLAUDE.md "Grenzen der aktuellen Version"). Genutzt sowohl vom CLI-Testanruf
(app/twilio_test_call.py) als auch vom Dashboard-Verbindungsstatus
(api/telephony.py), damit genau diese Fehlerklasse VOR einem echten,
kostenpflichtigen Anruf sichtbar wird statt erst danach im Twilio-Debugger.
"""

from __future__ import annotations

import httpx


async def check_webhook_reachable(base_url: str) -> tuple[bool, str]:
    if not base_url:
        return False, "TWILIO_PUBLIC_BASE_URL ist nicht gesetzt"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(f"{base_url}/api/health")
            if response.status_code == 200:
                return True, "erreichbar"
            return False, f"antwortet mit Status {response.status_code}"
    except httpx.HTTPError as exc:
        return False, str(exc)
