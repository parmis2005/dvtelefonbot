"""Strukturiertes Logging fuer Digital Vision Dario.

- JSON-Logs in Datei (fuer Auswertung)
- lesbare Logs auf der Konsole
- Telefonnummern werden in Logs maskiert
- Passwoerter/API-Keys werden nie geloggt (siehe mask_phone / redact_secrets)
"""

from __future__ import annotations

import logging
import logging.handlers
import re
import sys
from pathlib import Path

_PHONE_RE = re.compile(r"(\+?\d[\d\s\-/]{5,}\d)")
_SECRET_KEY_RE = re.compile(
    r"(password|passwort|token|api[_-]?key|secret)\s*[:=]\s*\S+", re.IGNORECASE
)


def mask_phone(value: str) -> str:
    """Maskiert Telefonnummern fuer Logs: +491701234567 -> +4917******67"""

    def _mask(match: re.Match) -> str:
        digits = match.group(1)
        if len(digits) <= 4:
            return "*" * len(digits)
        return digits[:4] + "*" * (len(digits) - 6) + digits[-2:]

    return _PHONE_RE.sub(_mask, value)


def redact_secrets(value: str) -> str:
    return _SECRET_KEY_RE.sub(lambda m: m.group(0).split(m.group(0)[len(m.group(1)) :])[0] + "=***", value)


class PrivacyFilter(logging.Filter):
    """Maskiert Telefonnummern und Secrets bevor Logs geschrieben werden."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        record.msg = mask_phone(msg)
        record.args = ()
        return True


def configure_logging(log_level: str = "INFO", log_dir: str | Path = "./logs") -> None:
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(log_level.upper())
    root.handlers.clear()

    console_formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(PrivacyFilter())
    root.addHandler(console_handler)

    file_formatter = logging.Formatter(
        fmt='{"time": "%(asctime)s", "level": "%(levelname)s", '
        '"logger": "%(name)s", "message": "%(message)s"}',
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "dario.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(file_formatter)
    file_handler.addFilter(PrivacyFilter())
    root.addHandler(file_handler)

    # Drittanbieter-Logger nicht zu geschwaetzig
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
