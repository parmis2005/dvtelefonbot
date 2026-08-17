"""Audio-Codecs/Resampling fuer den Twilio Media-Stream-Pfad.

Twilio Media Streams senden/erwarten G.711 mu-law bei 8kHz, mono, 8bit -
unsere STT/TTS-Pipeline arbeitet mit PCM16 bei 16kHz (whisper.cpp) bzw.
22050/24000Hz (Piper/Chatterbox). Dieses Modul konvertiert dazwischen.

Bewusst ohne das eingebaute (seit Python 3.13 entfernte) `audioop`-Modul
implementiert, damit das Projekt nicht an eine bestimmte Python-Version
gebunden ist - mu-law-(De-)Kodierung folgt dem Standardalgorithmus aus
ITU-T G.711 (Segment-Tabelle, wie u.a. in Suns klassischem `g711.c`).
"""

from __future__ import annotations

import numpy as np

MULAW_BIAS = 0x84
MULAW_CLIP = 32635

# Obere Grenze jedes der 8 mu-law-Segmente (Standard-G.711-Tabelle)
_SEG_END = np.array([0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF, 0x3FFF, 0x7FFF], dtype=np.int32)


def pcm16_to_mulaw(pcm: np.ndarray) -> np.ndarray:
    """PCM16 (int16) -> G.711 mu-law (uint8), vektorisiert."""
    samples = pcm.astype(np.int32)
    sign = np.where(samples < 0, 0x80, 0x00).astype(np.int32)
    magnitude = np.clip(np.abs(samples), 0, MULAW_CLIP) + MULAW_BIAS

    segment = np.searchsorted(_SEG_END, magnitude, side="left").astype(np.int32)
    segment = np.clip(segment, 0, 7)

    shift = segment + 3
    mantissa = (magnitude >> shift) & 0x0F
    mulaw_byte = ~(sign | (segment << 4) | mantissa) & 0xFF
    return mulaw_byte.astype(np.uint8)


_MULAW_DECODE_TABLE: np.ndarray | None = None


def _build_mulaw_decode_table() -> np.ndarray:
    table = np.zeros(256, dtype=np.int16)
    for i in range(256):
        byte = ~i & 0xFF
        sign = byte & 0x80
        exponent = (byte >> 4) & 0x07
        mantissa = byte & 0x0F
        magnitude = ((mantissa << 3) + MULAW_BIAS) << exponent
        magnitude -= MULAW_BIAS
        table[i] = -magnitude if sign else magnitude
    return table


def mulaw_to_pcm16(mulaw: bytes | np.ndarray) -> np.ndarray:
    """G.711 mu-law (uint8 Bytes) -> PCM16 (int16 numpy array)."""
    global _MULAW_DECODE_TABLE
    if _MULAW_DECODE_TABLE is None:
        _MULAW_DECODE_TABLE = _build_mulaw_decode_table()
    indices = np.frombuffer(mulaw, dtype=np.uint8) if isinstance(mulaw, bytes) else mulaw
    return _MULAW_DECODE_TABLE[indices]


def resample_pcm16(pcm: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Resampled PCM16-Mono-Audio zwischen beliebigen Sample-Raten.

    Nutzt scipy's polyphase-Resampler (bereits transitive Abhaengigkeit ueber
    librosa/chatterbox) fuer deutlich bessere Qualitaet als einfache lineare
    Interpolation - wichtig fuer Sprachverstaendlichkeit bei 8kHz Telefonie.
    """
    if src_rate == dst_rate:
        return pcm.astype(np.int16)
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(src_rate, dst_rate)
    up, down = dst_rate // g, src_rate // g
    resampled = resample_poly(pcm.astype(np.float32), up, down)
    return np.clip(resampled, -32768, 32767).astype(np.int16)
