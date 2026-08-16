"""Provider-Abstraktion fuer Telefonie. Ermoeglicht spaeter einen Wechsel
oder eine Ergaenzung um andere SIP/Telefonie-Backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass
class OutboundCallHandle:
    provider_channel_id: str
    endpoint: str


class TelephonyProvider(ABC):
    @abstractmethod
    async def start_outbound_call(self, phone_number: str, caller_id: str | None = None) -> OutboundCallHandle: ...

    @abstractmethod
    async def answer_call(self, channel_id: str) -> None: ...

    @abstractmethod
    async def play_audio(self, channel_id: str, media_uri: str) -> str: ...

    @abstractmethod
    async def stop_audio(self, playback_id: str) -> None: ...

    @abstractmethod
    async def end_call(self, channel_id: str) -> None: ...

    @abstractmethod
    def events(self) -> AsyncIterator[dict]: ...
