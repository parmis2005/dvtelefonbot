"""Duenner asynchroner Client fuer die Asterisk REST Interface (ARI).

Echte HTTP/WebSocket-Kommunikation mit einem laufenden Asterisk-Server -
kein Mock. Siehe https://docs.asterisk.org/Configuration/Interfaces/
Asterisk-REST-Interface-ARI/

Ohne laufenden Asterisk-Server schlagen die Aufrufe mit einem echten
Verbindungsfehler fehl (aiohttp.ClientError) - erwartetes Verhalten, bis
Asterisk konfiguriert ist (siehe Abschnitt 70 der Spezifikation).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from core.logging import get_logger

logger = get_logger(__name__)


class AriError(Exception):
    pass


class AriClient:
    def __init__(self, base_url: str, username: str, password: str, app_name: str):
        self.base_url = base_url.rstrip("/")
        self.auth = aiohttp.BasicAuth(username, password)
        self.app_name = app_name
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    async def __aenter__(self) -> AriClient:
        self._session = aiohttp.ClientSession(auth=self.auth)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        if self._ws is not None:
            await self._ws.close()
        if self._session is not None:
            await self._session.close()

    def _require_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            raise AriError("AriClient wurde nicht als Context Manager geoeffnet (async with)")
        return self._session

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        session = self._require_session()
        url = f"{self.base_url}/ari{path}"
        try:
            async with session.request(method, url, **kwargs) as response:
                if response.status >= 400:
                    body = await response.text()
                    raise AriError(f"ARI {method} {path} -> {response.status}: {body}")
                if response.content_type == "application/json":
                    return await response.json()
                return await response.text()
        except aiohttp.ClientError as exc:
            raise AriError(f"ARI Verbindung fehlgeschlagen ({method} {path}): {exc}") from exc

    # --- Channels -----------------------------------------------------------

    async def originate(
        self,
        endpoint: str,
        extension: str | None = None,
        context: str | None = None,
        priority: int = 1,
        caller_id: str | None = None,
        channel_id: str | None = None,
        variables: dict[str, str] | None = None,
    ) -> dict:
        params = {"endpoint": endpoint, "app": self.app_name}
        if extension:
            params["extension"] = extension
        if context:
            params["context"] = context
            params["priority"] = str(priority)
        if caller_id:
            params["callerId"] = caller_id
        if channel_id:
            params["channelId"] = channel_id
        payload = {"variables": variables} if variables else {}
        return await self._request("POST", "/channels", params=params, json=payload)

    async def answer(self, channel_id: str) -> None:
        await self._request("POST", f"/channels/{channel_id}/answer")

    async def hangup(self, channel_id: str, reason: str = "normal") -> None:
        await self._request("DELETE", f"/channels/{channel_id}", params={"reason": reason})

    async def play(self, channel_id: str, media_uri: str) -> dict:
        return await self._request(
            "POST", f"/channels/{channel_id}/play", params={"media": media_uri}
        )

    async def stop_playback(self, playback_id: str) -> None:
        await self._request("DELETE", f"/playbacks/{playback_id}")

    async def get_channel(self, channel_id: str) -> dict:
        return await self._request("GET", f"/channels/{channel_id}")

    async def record(
        self,
        channel_id: str,
        name: str,
        max_duration_seconds: int = 15,
        max_silence_seconds: int = 2,
        format_: str = "wav",
    ) -> dict:
        """Nimmt die Sprache des Gespraechspartners auf (turn-basiert), bis
        Stille erkannt wird oder die Maximaldauer erreicht ist. Das Ergebnis
        liegt anschliessend im Asterisk-Aufnahmeverzeichnis und kann fuer die
        STT-Transkription gelesen werden."""
        params = {
            "name": name,
            "format": format_,
            "maxDurationSeconds": str(max_duration_seconds),
            "maxSilenceSeconds": str(max_silence_seconds),
            "ifExists": "overwrite",
            "beep": "false",
        }
        return await self._request("POST", f"/channels/{channel_id}/record", params=params)

    async def stop_recording(self, recording_name: str) -> None:
        await self._request("POST", f"/recordings/live/{recording_name}/stop")

    async def create_external_media(
        self,
        external_host: str,
        encapsulation: str = "rtp",
        transport: str = "udp",
        codec_format: str = "slin16",
        channel_id: str | None = None,
    ) -> dict:
        """Startet einen ExternalMedia-Channel, um rohes Audio per RTP an
        einen eigenen Prozess (STT-Pipeline) zu streamen."""
        params = {
            "app": self.app_name,
            "external_host": external_host,
            "encapsulation": encapsulation,
            "transport": transport,
            "format": codec_format,
        }
        if channel_id:
            params["channelId"] = channel_id
        return await self._request("POST", "/channels/externalMedia", params=params)

    async def create_bridge(self, bridge_type: str = "mixing") -> dict:
        return await self._request("POST", "/bridges", params={"type": bridge_type})

    async def add_channel_to_bridge(self, bridge_id: str, channel_id: str) -> None:
        await self._request(
            "POST", f"/bridges/{bridge_id}/addChannel", params={"channel": channel_id}
        )

    # --- Events (WebSocket) ---------------------------------------------

    async def events(self) -> AsyncIterator[dict]:
        session = self._require_session()
        ws_url = (
            f"{self.base_url.replace('http', 'ws', 1)}/ari/events"
            f"?app={self.app_name}&api_key={self.auth.login}:{self.auth.password}"
        )
        async with session.ws_connect(ws_url) as ws:
            self._ws = ws
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    yield msg.json()
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
