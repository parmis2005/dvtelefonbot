"""Provider-Abstraktionen fuer E-Mail und WhatsApp."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SendResult:
    success: bool
    detail: str = ""


class EmailProvider(ABC):
    @abstractmethod
    async def send(self, to_email: str, subject: str, body: str) -> SendResult: ...


class WhatsAppProvider(ABC):
    @abstractmethod
    async def send(self, to_phone: str, message: str) -> SendResult: ...

    @abstractmethod
    def is_configured(self) -> bool: ...
