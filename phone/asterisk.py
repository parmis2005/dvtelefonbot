"""AsteriskProvider: TelephonyProvider-Implementierung auf Basis von ARI.

Fuehrt echte ARI-Aufrufe gegen einen konfigurierten Asterisk-Server aus.
Der SIP-Trunk/Endpoint-Name kommt aus der Konfiguration (ASTERISK_SIP_TRUNK).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from core.logging import get_logger, mask_phone
from phone.ari import AriClient
from phone.base import OutboundCallHandle, TelephonyProvider

logger = get_logger(__name__)


class AsteriskProvider(TelephonyProvider):
    def __init__(
        self,
        ari_url: str,
        username: str,
        password: str,
        app_name: str,
        sip_trunk: str,
        default_caller_id: str = "",
    ):
        self.ari_url = ari_url
        self.username = username
        self.password = password
        self.app_name = app_name
        self.sip_trunk = sip_trunk
        self.default_caller_id = default_caller_id
        self._client: AriClient | None = None

    async def __aenter__(self) -> AsteriskProvider:
        self._client = AriClient(self.ari_url, self.username, self.password, self.app_name)
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._client is not None:
            await self._client.__aexit__(*exc_info)

    def _require_client(self) -> AriClient:
        if self._client is None:
            raise RuntimeError("AsteriskProvider wurde nicht als Context Manager geoeffnet")
        return self._client

    async def start_outbound_call(self, phone_number: str, caller_id: str | None = None) -> OutboundCallHandle:
        client = self._require_client()
        endpoint = f"PJSIP/{phone_number}@{self.sip_trunk}"
        logger.info("Starte Outbound-Call an %s ueber %s", mask_phone(phone_number), self.sip_trunk)
        channel = await client.originate(
            endpoint=endpoint,
            caller_id=caller_id or self.default_caller_id,
        )
        return OutboundCallHandle(provider_channel_id=channel["id"], endpoint=endpoint)

    async def answer_call(self, channel_id: str) -> None:
        await self._require_client().answer(channel_id)

    async def play_audio(self, channel_id: str, media_uri: str) -> str:
        result = await self._require_client().play(channel_id, media_uri)
        return result.get("id", "")

    async def stop_audio(self, playback_id: str) -> None:
        if playback_id:
            await self._require_client().stop_playback(playback_id)

    async def end_call(self, channel_id: str) -> None:
        await self._require_client().hangup(channel_id)

    async def record_utterance(
        self, channel_id: str, recording_name: str, max_duration: int = 15, max_silence: int = 2
    ) -> dict:
        return await self._require_client().record(
            channel_id, recording_name, max_duration_seconds=max_duration, max_silence_seconds=max_silence
        )

    async def start_external_media(self, channel_id: str, media_target_host: str) -> dict:
        """Startet Audio-Streaming per RTP an unsere STT-Pipeline (Abschnitt 50)."""
        return await self._require_client().create_external_media(
            external_host=media_target_host, channel_id=channel_id
        )

    def events(self) -> AsyncIterator[dict]:
        return self._require_client().events()
