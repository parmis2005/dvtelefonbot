from __future__ import annotations

import wave

import httpx
import numpy as np
import pytest

from app.bootstrap import build_tts_provider
from tests.factories import make_settings
from voice.tts.elevenlabs_tts import ElevenLabsConfigError, ElevenLabsTTSProvider


def _pcm_response() -> bytes:
    samples = (np.sin(np.linspace(0, 20, 1600)) * 8000).astype(np.int16)
    return samples.tobytes()


@pytest.mark.asyncio
async def test_elevenlabs_requires_api_key_and_voice(tmp_path):
    provider = ElevenLabsTTSProvider(api_key="", voice_id="")

    assert await provider.is_available() is False
    with pytest.raises(ElevenLabsConfigError):
        await provider.synthesize("Hallo", str(tmp_path / "out.wav"))


@pytest.mark.asyncio
async def test_elevenlabs_writes_pcm_stream_as_wav(tmp_path, monkeypatch):
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("xi-api-key")
        captured["json"] = request.read().decode()
        return httpx.Response(200, content=_pcm_response())

    transport = httpx.MockTransport(handler)
    original_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return original_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fake_client)

    out_path = tmp_path / "eleven.wav"
    provider = ElevenLabsTTSProvider(
        api_key="test-key",
        voice_id="voice-123",
        model_id="eleven_turbo_v2_5",
        output_format="pcm_16000",
    )

    result = await provider.synthesize("Hallo!!!", str(out_path))

    assert result == str(out_path)
    assert "voice-123/stream" in captured["url"]
    assert "output_format=pcm_16000" in captured["url"]
    assert captured["api_key"] == "test-key"
    assert out_path.exists()
    with wave.open(str(out_path), "rb") as wav:
        assert wav.getframerate() == 16000
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getnframes() > 0


def test_build_tts_provider_supports_elevenlabs():
    provider = build_tts_provider(
        make_settings(
            tts_provider="elevenlabs",
            elevenlabs_api_key="key",
            elevenlabs_voice_id="voice",
        )
    )

    assert isinstance(provider, ElevenLabsTTSProvider)
