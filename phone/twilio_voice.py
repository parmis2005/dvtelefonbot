"""TwilioProvider: echte Anbindung an Twilio Programmable Voice.

Alternative zu phone/asterisk.py. Nutzt das offizielle Twilio Python SDK fuer
Call-Origination (REST API) sowie TwiML-Generierung fuer den bidirektionalen
Media-Stream (WebSocket), ueber den Darios STT/TTS-Pipeline in Echtzeit an
den Anruf angebunden wird (siehe phone/twilio_media_handler.py).

Erfordert einen oeffentlich erreichbaren Webhook/WebSocket-Endpunkt
(TWILIO_PUBLIC_BASE_URL, z.B. ein ngrok-Tunnel) - Twilio muss diesen von
aussen erreichen koennen.
"""

from __future__ import annotations

from twilio.request_validator import RequestValidator
from twilio.rest import Client
from twilio.twiml.voice_response import Connect, VoiceResponse

from core.logging import get_logger, mask_phone

logger = get_logger(__name__)


class TwilioConfigError(Exception):
    pass


class TwilioProvider:
    def __init__(self, account_sid: str, auth_token: str, caller_id: str):
        if not account_sid or not auth_token:
            raise TwilioConfigError(
                "TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN fehlen in .env - siehe README."
            )
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.caller_id = caller_id
        self._client = Client(account_sid, auth_token)
        self._validator = RequestValidator(auth_token)

    def verify_credentials(self) -> tuple[bool, str]:
        """Prueft die Zugangsdaten gegen die Twilio-API, OHNE einen Call
        auszuloesen (reiner Account-Abruf) - fuer den Selbsttest vor einem
        echten Anruf."""
        try:
            account = self._client.api.accounts(self.account_sid).fetch()
            return True, f"Account-Status: {account.status}"
        except Exception as exc:  # Twilio-SDK wirft diverse eigene Exception-Typen
            return False, str(exc)

    def start_outbound_call(self, to_number: str, twiml_webhook_url: str) -> str:
        """Loest einen echten, kostenpflichtigen Outbound-Call aus. Gibt die
        Twilio Call-SID zurueck."""
        logger.info(
            "Starte Twilio Outbound-Call an %s (Webhook: %s)",
            mask_phone(to_number),
            twiml_webhook_url,
        )
        call = self._client.calls.create(
            to=to_number,
            from_=self.caller_id,
            url=twiml_webhook_url,
            method="POST",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
        )
        return call.sid

    def end_call(self, call_sid: str) -> None:
        self._client.calls(call_sid).update(status="completed")

    def validate_signature(self, url: str, params: dict, signature: str) -> bool:
        return self._validator.validate(url, params, signature)

    @staticmethod
    def build_connect_stream_twiml(websocket_url: str, call_id: int) -> str:
        """TwiML, das den Anruf an eine bidirektionale Media-Stream-WebSocket
        uebergibt - darueber laeuft Darios komplette STT->Dario->TTS-Schleife
        in Echtzeit (siehe phone/twilio_media_handler.py).

        call_id wird bewusst als <Parameter> statt als URL-Query-String
        uebergeben: Twilio reicht Query-Parameter in der Stream-URL nicht
        zuverlaessig durch (fuehrte zu Fehler 31920 "WebSocket Handshake
        Error", weil unser Server die fehlende call_id ablehnte) - offiziell
        empfohlener Weg sind <Parameter>-Elemente, die Twilio im "start"-
        Event als customParameters an die WebSocket liefert.
        """
        response = VoiceResponse()
        connect = Connect()
        stream = connect.stream(url=websocket_url)
        stream.parameter(name="call_id", value=str(call_id))
        response.append(connect)
        return str(response)
