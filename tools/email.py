"""SMTPEmailProvider - echter SMTP-Versand ueber aiosmtplib.

Konfiguration ausschliesslich ueber .env (core/config.py). Fehlen Zugangsdaten,
wird das per SendResult(success=False, ...) zurueckgemeldet - Dario darf dann
laut agent/guardrails.py keinen Versand behaupten.
"""

from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib

from core.logging import get_logger
from tools.base import EmailProvider, SendResult

logger = get_logger(__name__)


class SMTPEmailProvider(EmailProvider):
    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        from_addr: str,
        use_tls: bool = True,
    ):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_addr = from_addr
        self.use_tls = use_tls

    def is_configured(self) -> bool:
        return bool(self.host and self.username and self.password and self.from_addr)

    async def send(self, to_email: str, subject: str, body: str) -> SendResult:
        if not self.is_configured():
            return SendResult(success=False, detail="SMTP ist nicht konfiguriert (.env fehlt)")

        message = EmailMessage()
        message["From"] = self.from_addr
        message["To"] = to_email
        message["Subject"] = subject
        message.set_content(body)

        try:
            await aiosmtplib.send(
                message,
                hostname=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                start_tls=self.use_tls,
            )
            logger.info("E-Mail erfolgreich gesendet an %s", to_email)
            return SendResult(success=True, detail="gesendet")
        except (aiosmtplib.errors.SMTPException, OSError) as exc:
            logger.error("E-Mail-Versand fehlgeschlagen: %s", exc)
            return SendResult(success=False, detail=str(exc))


def build_design_email_body(
    company_name: str,
    ansprechpartner: str,
    entwurf_link: str,
) -> str:
    anrede = f"Hallo {ansprechpartner}," if ansprechpartner else "Hallo,"
    return (
        f"{anrede}\n\n"
        f"vielen Dank fuer das nette Telefonat eben. Wie besprochen sende ich Ihnen den "
        f"unverbindlichen Webseiten-Entwurf, den {company_name} fuer Sie vorbereitet hat:\n\n"
        f"{entwurf_link}\n\n"
        f"Schauen Sie sich den Entwurf gerne in Ruhe an. Bei Fragen oder wenn Sie Interesse "
        f"an einer Umsetzung haben, meldet sich unsere Geschaeftsleitung persoenlich bei "
        f"Ihnen.\n\n"
        f"Viele Gruesse\n"
        f"{company_name}"
    )
