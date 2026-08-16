"""Test 9 (Abschnitt 60): Barge-In - TTS-Wiedergabe wird sofort abgebrochen,
sobald der Gespraechspartner waehrend Darios Antwort zu sprechen beginnt."""

from __future__ import annotations

import asyncio

import pytest

from voice.barge_in import BargeInController
from voice.vad import FRAME_BYTES, VoiceActivityDetector


class FakeVad:
    """Deterministische VAD-Attrappe: liefert vordefinierte Sprach-Frames,
    ohne echtes WebRTC-VAD/Audio zu benoetigen."""

    def __init__(self, pattern: list[bool]):
        self._pattern = pattern
        self._i = 0

    def is_speech(self, frame: bytes, sample_rate: int = 16000) -> bool:
        value = self._pattern[min(self._i, len(self._pattern) - 1)]
        self._i += 1
        return value


@pytest.mark.asyncio
async def test_barge_in_cancels_playback_task_and_clears_queue():
    controller = BargeInController(vad=FakeVad([True]))

    async def long_playback():
        await asyncio.sleep(10)

    task = asyncio.ensure_future(long_playback())
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(b"chunk1")
    await queue.put(b"chunk2")

    controller.attach_playback(task, queue)
    assert controller.is_speaking_dario is True

    triggered = await controller.on_incoming_frame(b"\x00" * FRAME_BYTES)

    assert triggered is True
    assert controller.is_speaking_dario is False
    assert queue.empty()
    await asyncio.sleep(0)  # dem Event-Loop erlauben, die Cancellation zu verarbeiten
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_no_barge_in_when_dario_not_speaking():
    controller = BargeInController(vad=FakeVad([True]))
    controller.is_speaking_dario = False

    triggered = await controller.on_incoming_frame(b"\x00" * FRAME_BYTES)

    assert triggered is False


def test_real_vad_rejects_wrong_frame_size():
    vad = VoiceActivityDetector()
    assert vad.is_speech(b"\x00\x00") is False
