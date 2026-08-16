"""Whisper.cpp halluziniert auf Stille/Hintergrundgeraeuschen oft Marker wie
"[Musik]" statt echten Text - diese duerfen nicht als Kundenaeusserung
durchgereicht werden (siehe voice/stt/whisper_cpp.py)."""

from __future__ import annotations

from voice.stt.whisper_cpp import strip_non_speech_artifacts


def test_pure_hallucination_marker_becomes_empty():
    assert strip_non_speech_artifacts("[MUSIK]") == ""
    assert strip_non_speech_artifacts("[Stille]") == ""
    assert strip_non_speech_artifacts("(Schritte)") == ""
    assert strip_non_speech_artifacts("[BLANK_AUDIO]") == ""


def test_real_speech_is_untouched():
    text = "Kein Interesse, danke."
    assert strip_non_speech_artifacts(text) == text


def test_marker_mixed_with_real_speech_keeps_the_speech():
    result = strip_non_speech_artifacts("[Geraeusch] Ja, gerne.")
    assert result == "Ja, gerne."
