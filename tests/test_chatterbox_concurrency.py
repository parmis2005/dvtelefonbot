"""Regression-Test fuer die Nebenlaeufigkeits-Absicherung in
voice/tts/chatterbox_tts.py::ChatterboxTTSProvider.

Hintergrund: Chatterbox' generate() ruft bei jedem Aufruf intern
prepare_conditionals() auf, was das GETEILTE Modell-Attribut self.conds
ueberschreibt statt einen per-Aufruf-Zustand zu verwenden. Der TTS-Provider
ist prozessweit gecacht und wird von ALLEN gleichzeitigen Anrufen geteilt
(app/bootstrap.py::get_tts_provider, siehe CLAUDE.md) - bei bis zu 10
parallelen Kampagnen-Calls (Abschnitt "10 parallele Gespraeche") wuerde ein
zweiter, ueberlappender synthesize()-Aufruf die Konditionierung des ersten
mitten in dessen Generierung ueberschreiben. Beobachtbares Symptom auf der
Leitung: verzerrtes/rauschendes Audio. Dieser Test verifiziert, dass
ChatterboxTTSProvider._generate_lock ueberlappende generate()-Aufrufe auf
demselben Modell tatsaechlich serialisiert, statt sie parallel laufen zu
lassen."""

from __future__ import annotations

import asyncio
import threading
import time

import pytest
import torch

from voice.tts.chatterbox_tts import ChatterboxTTSProvider


class _RaceDetectingFakeModel:
    """Simuliert Chatterbox' Modell: generate() darf laut Produktionscode nie
    von zwei Threads gleichzeitig betreten werden, weil es geteilten Zustand
    (hier: self.conds) mutiert. Erkennt eine Verletzung explizit, statt nur
    auf Zufall/Timing zu hoffen."""

    def __init__(self) -> None:
        self.sr = 24000
        self.conds = None
        self._active = 0
        self._lock = threading.Lock()
        self.concurrent_entries_detected = False
        self.call_log: list[str] = []

    def generate(self, text: str, **kwargs) -> torch.Tensor:
        with self._lock:
            self._active += 1
            if self._active > 1:
                self.concurrent_entries_detected = True
            self.call_log.append(f"start:{text}")

        # Simuliert prepare_conditionals(), das self.conds ueberschreibt -
        # waehrend dieses "Fensters" duerfte KEIN anderer Thread hier sein.
        self.conds = text
        time.sleep(0.1)
        assert self.conds == text, "self.conds wurde von einem anderen Thread ueberschrieben!"

        with self._lock:
            self.call_log.append(f"end:{text}")
            self._active -= 1

        word_count = max(1, len(text.split()))
        # rms >= 0.005 und Dauer im von _is_plausible erwarteten Korridor
        samples = int(0.4 * word_count * self.sr)
        wav = 0.1 * torch.ones(1, samples)
        return wav


@pytest.mark.asyncio
async def test_concurrent_synthesize_calls_do_not_race_on_shared_model(tmp_path):
    provider = ChatterboxTTSProvider(max_attempts=1)
    fake_model = _RaceDetectingFakeModel()

    async def fake_get_model():
        return fake_model

    provider._get_model = fake_get_model  # type: ignore[method-assign]

    out_a = str(tmp_path / "a.wav")
    out_b = str(tmp_path / "b.wav")

    await asyncio.gather(
        provider.synthesize("Erster Anruf Text", out_a),
        provider.synthesize("Zweiter Anruf Text", out_b),
    )

    assert fake_model.concurrent_entries_detected is False, (
        "generate() wurde gleichzeitig von zwei synthesize()-Aufrufen betreten - "
        "der _generate_lock serialisiert nicht korrekt."
    )
    # Beide Aufrufe muessen vollstaendig (start...end) abgeschlossen sein, bevor
    # der jeweils andere beginnt - kein Verschachteln der Log-Eintraege.
    log = fake_model.call_log
    assert log[0].startswith("start:")
    assert log[1].startswith("end:")
    assert log[1].split(":", 1)[1] == log[0].split(":", 1)[1]
    assert log[2].startswith("start:")
    assert log[3].startswith("end:")
