"""ChatterboxTTSProvider: lokale, natuerlichere deutsche Stimme ueber Chatterbox
Multilingual (Resemble AI, MIT-Lizenz, https://github.com/resemble-ai/chatterbox).

Ergebnis einer mehrstufigen Stimmauswahl (siehe Projekt-Historie): Piper klang
zu hoch/kehlig/kuenstlich; Chatterbox' Standardstimme kam der Zielstimme am
naechsten. Die hier verwendeten Parameter (exaggeration/cfg_weight/temperature)
sind das Ergebnis dieser Feinabstimmung, nicht Zufallswerte.

Optional kann eine Referenzstimme (reference_audio_path) angegeben werden -
Chatterbox klont dann Timbre/Charakter dieser Aufnahme, statt die im Modell
mitgelieferte Standardstimme zu nutzen. Die Referenzdatei muss lokal
vorliegen; es werden keine Referenzstimmen automatisch aus dem Internet
bezogen. Wer immer die Referenzdatei bereitstellt, muss die Rechte an dieser
Stimme haben (siehe README) - das prueft dieser Code nicht automatisch.

Besonderheiten gegenueber Piper:
- Deutlich schwereres Modell (PyTorch, ~2GB), laeuft auf diesem Projekt-Stand
  bewusst auf CPU (Chatterbox hat aktuell bekannte Kompatibilitaetsprobleme
  mit Apple-Silicon-MPS-Tensoren) - spuerbar langsamer als Piper.
- Nicht deterministisch: derselbe Text mit denselben Parametern kann bei
  wiederholter Generierung leicht unterschiedlich (in seltenen Faellen auch
  fehlerhaft/halluziniert) ausfallen. Deshalb wird das Ergebnis nach der
  Erzeugung mit einer schnellen, lokalen Plausibilitaetspruefung bewertet und
  bei Bedarf automatisch neu erzeugt (kein teurer STT-Rueckweg im Live-Pfad).
- Erzeugt automatisch ein unhoerbares Provenance-Wasserzeichen (PerthNet) in
  jeder Ausgabe - das ist eine bewusste Sicherheitsfunktion der Bibliothek
  gegen Deepfake-Missbrauch und wird hier nicht deaktiviert.
"""

from __future__ import annotations

import asyncio
import importlib.util
import random

from agent.guardrails import strip_disallowed_audio_artifacts
from core.logging import get_logger
from voice.tts.base import TextToSpeechProvider

logger = get_logger(__name__)


class ChatterboxUnavailableError(Exception):
    pass


class ChatterboxTTSProvider(TextToSpeechProvider):
    def __init__(
        self,
        language: str = "de",
        exaggeration: float = 0.22,
        cfg_weight: float = 0.35,
        temperature: float = 0.55,
        device: str = "cpu",
        max_attempts: int = 3,
        reference_audio_path: str | None = None,
    ):
        self.language = language
        self.exaggeration = exaggeration
        self.cfg_weight = cfg_weight
        self.temperature = temperature
        self.device = device
        self.max_attempts = max_attempts
        self.reference_audio_path = reference_audio_path
        self._model = None  # lazy geladen, einmal pro Prozess wiederverwendet
        self._load_lock = asyncio.Lock()
        # Chatterbox' generate() ruft bei jedem Aufruf intern prepare_conditionals()
        # auf, was das GETEILTE Modell-Attribut self.conds ueberschreibt (kein
        # per-Aufruf-Zustand). Bei mehreren gleichzeitigen Anrufen (bis zu 10
        # parallele Kampagnen-Calls teilen sich denselben prozessweit gecachten
        # Provider, siehe app/bootstrap.py::get_tts_provider) wuerde ein zweiter,
        # ueberlappender synthesize()-Aufruf die Konditionierung des ersten
        # mitten in dessen Generierung ueberschreiben - beobachtbares Symptom:
        # verzerrtes/rauschendes Audio. Dieser Lock serialisiert alle
        # generate()-Aufrufe auf demselben Modell (CPU-gebunden ohnehin nicht
        # sinnvoll parallelisierbar) und macht sie dadurch sicher.
        self._generate_lock = asyncio.Lock()

    async def is_available(self) -> bool:
        if importlib.util.find_spec("chatterbox") is None:
            return False
        if self.reference_audio_path:
            from pathlib import Path

            if not Path(self.reference_audio_path).exists():
                return False
        return True

    async def _get_model(self):
        if self._model is not None:
            return self._model
        async with self._load_lock:
            if self._model is None:
                if not await self.is_available():
                    raise ChatterboxUnavailableError(
                        "Paket 'chatterbox-tts' nicht installiert. "
                        "Siehe pyproject.toml Extra 'chatterbox' / README."
                    )
                logger.info("Lade Chatterbox Multilingual Modell (device=%s) ...", self.device)
                loop = asyncio.get_event_loop()
                self._model = await loop.run_in_executor(None, self._load_model_sync)
                logger.info("Chatterbox Modell geladen.")
        return self._model

    def _load_model_sync(self):
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        return ChatterboxMultilingualTTS.from_pretrained(device=self.device)

    def _generate_sync(self, model, text: str, seed: int) -> object:
        import torch

        torch.manual_seed(seed)
        kwargs = {
            "language_id": self.language,
            "exaggeration": self.exaggeration,
            "cfg_weight": self.cfg_weight,
            "temperature": self.temperature,
        }
        if self.reference_audio_path:
            kwargs["audio_prompt_path"] = self.reference_audio_path
        return model.generate(text, **kwargs)

    @staticmethod
    def _is_plausible(wav, sample_rate: int, text: str) -> bool:
        """Schnelle, lokale Plausibilitaetspruefung ohne STT-Rueckweg:
        erkennt Stille/NaN und grob unplausible Laenge (z.B. Halluzinations-
        Ausreisser wie in Tests beobachtet), ohne die Latenz eines vollen
        Transkriptions-Rueckwegs im Live-Gespraech zu verursachen."""
        import torch

        if wav is None or wav.numel() == 0:
            return False
        if torch.isnan(wav).any() or torch.isinf(wav).any():
            return False

        rms = torch.sqrt(torch.mean(wav.float() ** 2)).item()
        if rms < 0.005:  # praktisch Stille
            return False

        duration = wav.shape[-1] / sample_rate
        word_count = max(1, len(text.split()))
        # grobzuegiger, aber wirksamer Korridor gegen abgeschnittene/
        # halluzinierte Ausreisser (siehe Feinabstimmung: normale Werte lagen
        # bei ca. 0.4-0.6s/Wort fuer ruhige Sprache)
        min_dur = word_count * 0.25
        max_dur = word_count * 1.1 + 1.5
        return min_dur <= duration <= max_dur

    async def synthesize(self, text: str, output_path: str) -> str:
        import torchaudio

        clean_text = strip_disallowed_audio_artifacts(text)
        if not clean_text:
            raise ValueError("Kein Text zum Sprechen nach Bereinigung uebrig.")

        model = await self._get_model()
        loop = asyncio.get_event_loop()

        last_wav = None
        async with self._generate_lock:
            for attempt in range(self.max_attempts):
                seed = random.randint(0, 2**31 - 1)
                wav = await loop.run_in_executor(
                    None, self._generate_sync, model, clean_text, seed
                )
                last_wav = wav
                if self._is_plausible(wav, model.sr, clean_text):
                    if attempt > 0:
                        logger.info(
                            "Chatterbox-Ausgabe erst nach %d Versuch(en) plausibel.", attempt + 1
                        )
                    break
                logger.warning(
                    "Chatterbox-Ausgabe (Versuch %d/%d) wirkte unplausibel (Stille/Laenge) - "
                    "erzeuge neu.",
                    attempt + 1,
                    self.max_attempts,
                )
            else:
                logger.warning(
                    "Chatterbox lieferte nach %d Versuchen kein eindeutig plausibles Ergebnis - "
                    "verwende letzten Versuch.",
                    self.max_attempts,
                )

        await loop.run_in_executor(None, torchaudio.save, output_path, last_wav, model.sr)
        return output_path
