"""Lokaler Voice-Test: Mac-Mikrofon -> STT -> Dario -> LLM -> TTS -> Lautsprecher.

Nutzt exakt dieselbe Conversation Engine wie chat_test.py und der spaetere
Telefonie-Pfad. Erfordert:
  - installierte Voice-Extras: pip install -e ".[voice]"
  - ein lokales whisper.cpp Binary + Modell (WHISPER_*)
  - einen TTS-Provider gemaess TTS_PROVIDER in .env (local_piper oder
    chatterbox - siehe app/bootstrap.py::build_tts_provider)

Aufruf:
    python -m app.local_voice_test
"""

from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path

from agent.dario import Dario
from app.bootstrap import build_app_context, build_tts_provider
from core.logging import get_logger
from database.database import get_session_factory, init_db
from database.repository import LeadRepository
from tools.call_tools import ToolExecutor
from voice.stt.whisper_cpp import LocalWhisperProvider
from voice.tts.base import TextToSpeechProvider

logger = get_logger(__name__)


async def _get_or_create_test_lead(session, args) -> int:
    repo = LeadRepository(session)
    if args.lead_id:
        lead = await repo.get(args.lead_id)
        if lead is None:
            raise SystemExit(f"Lead {args.lead_id} nicht gefunden")
        return lead.id
    lead = await repo.create(
        unternehmen=args.unternehmen,
        ansprechpartner=args.ansprechpartner,
        telefonnummer="+491701234567",
        online_auftritt_geprueft=args.geprueft,
        entwurf_vorhanden=args.entwurf,
        entwurf_link="https://beispiel.digital-vision-entwurf.de/demo" if args.entwurf else None,
    )
    return lead.id


async def run_voice_test(args: argparse.Namespace) -> None:
    await init_db()
    ctx = build_app_context()
    settings = ctx.settings

    stt = LocalWhisperProvider(settings.whisper_cpp_binary, settings.whisper_model_path, settings.whisper_language)
    tts = build_tts_provider(settings)

    if not await stt.is_available():
        raise SystemExit(
            f"Whisper nicht verfuegbar (Binary '{settings.whisper_cpp_binary}' oder Modell "
            f"'{settings.whisper_model_path}' fehlt). Siehe scripts/setup_mac.sh / README.md."
        )
    if not await tts.is_available():
        raise SystemExit(
            f"TTS-Provider '{settings.tts_provider}' nicht verfuegbar (fehlendes Binary/Modell "
            f"oder Python-Paket). Siehe scripts/setup_mac.sh / README.md."
        )

    session_factory = get_session_factory()
    async with session_factory() as session:
        lead_id = await _get_or_create_test_lead(session, args)
        tool_executor = ToolExecutor(session, ctx.email_provider, ctx.whatsapp_provider, settings.company_name)
        dario = await Dario.for_lead(session, settings, ctx.business_config, ctx.engine, tool_executor, lead_id)

        print("=" * 60)
        print(f" Dario Voice-Test  |  Lead-ID {lead_id}  |  Strg+C zum Beenden")
        print("=" * 60)

        opening = dario.opening_line()
        print(f"\nDario: {opening}")
        await _speak(tts, opening)

        # Turn-Ende-Erkennung (wie lange Stille bedeutet "Nutzer ist fertig")
        # ist bewusst kurz und fix (siehe voice/vad.py::EndpointConfig-Default),
        # unabhaengig von SILENCE_TIMEOUT - das steuert im Telefonie-Pfad etwas
        # anderes (wann "Sind Sie noch da?" gefragt wird, nicht die Turn-Segmentierung).
        TURN_SILENCE_MS = 900

        while dario.call_active:
            print("\n[Hoere zu ... sprechen Sie jetzt]")
            from voice.audio_stream import record_until_silence

            wav_path = await record_until_silence(max_seconds=20, silence_timeout_ms=TURN_SILENCE_MS)
            transcription = await stt.transcribe(wav_path)
            Path(wav_path).unlink(missing_ok=True)

            if not transcription.text.strip():
                print("[Nichts verstanden - versuchen Sie es erneut]")
                continue

            print(f"Du: {transcription.text}")
            outcome = await dario.process_utterance(transcription.text)
            if outcome.reply_text:
                print(f"Dario: {outcome.reply_text}")
                await _speak(tts, outcome.reply_text)
            if outcome.call_ended:
                print(f"\n[Call beendet | Ergebnis: {dario.context.call_result}]")
                break


async def _speak(tts: TextToSpeechProvider, text: str) -> None:
    from voice.audio_stream import play_wav

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        out_path = tmp.name
    try:
        await tts.synthesize(text, out_path)
        play_wav(out_path)
    finally:
        Path(out_path).unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Dario lokaler Voice-Test")
    parser.add_argument("--lead-id", type=int, default=None)
    parser.add_argument("--unternehmen", type=str, default="Beauty Studio Beispiel")
    parser.add_argument("--ansprechpartner", type=str, default="Frau Mueller")
    parser.add_argument("--entwurf", action="store_true")
    parser.add_argument("--geprueft", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    asyncio.run(run_voice_test(args))


if __name__ == "__main__":
    main()
