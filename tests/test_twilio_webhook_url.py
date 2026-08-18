from __future__ import annotations

from types import SimpleNamespace

from starlette.datastructures import URL, Headers

from api.twilio import _websocket_url_from_request


def _request(headers: dict[str, str], url: str = "http://127.0.0.1:8000/twilio/voice"):
    return SimpleNamespace(headers=Headers(headers), url=URL(url))


def test_websocket_url_uses_ngrok_forwarded_headers():
    request = _request(
        {
            "host": "127.0.0.1:8000",
            "x-forwarded-host": "auto-tunnel.ngrok-free.app",
            "x-forwarded-proto": "https",
        }
    )

    assert (
        _websocket_url_from_request(request, 42)
        == "wss://auto-tunnel.ngrok-free.app/twilio/media-stream?call_id=42"
    )


def test_websocket_url_falls_back_to_request_host():
    request = _request({"host": "localhost:8000"})

    assert _websocket_url_from_request(request, 7) == "ws://localhost:8000/twilio/media-stream?call_id=7"
