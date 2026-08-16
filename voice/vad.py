"""Voice Activity Detection + einfache Endpoint Detection auf Basis von
WebRTC VAD. Arbeitet auf 16kHz/mono/16bit PCM Frames (10/20/30ms).
"""

from __future__ import annotations

from dataclasses import dataclass

import webrtcvad

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_BYTES = int(SAMPLE_RATE * (FRAME_MS / 1000.0)) * 2  # 16bit = 2 bytes/sample


@dataclass
class EndpointConfig:
    silence_timeout_ms: int = 800  # so lange Stille => Sprech-Ende
    min_speech_ms: int = 200  # kuerzer als das zaehlt nicht als Sprache


class VoiceActivityDetector:
    def __init__(self, aggressiveness: int = 2):
        self._vad = webrtcvad.Vad(aggressiveness)

    def is_speech(self, frame: bytes, sample_rate: int = SAMPLE_RATE) -> bool:
        if len(frame) != FRAME_BYTES:
            return False
        return self._vad.is_speech(frame, sample_rate)


class EndpointDetector:
    """Erkennt das Ende einer Sprechpause fuer Streaming-STT-Segmentierung."""

    def __init__(self, config: EndpointConfig | None = None):
        self.config = config or EndpointConfig()
        self._speech_ms = 0
        self._silence_ms = 0
        self._triggered = False

    def process_frame(self, is_speech: bool) -> bool:
        """Gibt True zurueck, sobald ein Sprechende erkannt wurde."""
        if is_speech:
            self._speech_ms += FRAME_MS
            self._silence_ms = 0
            if self._speech_ms >= self.config.min_speech_ms:
                self._triggered = True
            return False

        if self._triggered:
            self._silence_ms += FRAME_MS
            if self._silence_ms >= self.config.silence_timeout_ms:
                self.reset()
                return True
        return False

    def reset(self) -> None:
        self._speech_ms = 0
        self._silence_ms = 0
        self._triggered = False
