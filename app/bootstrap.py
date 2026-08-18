"""Gemeinsame Initialisierung fuer chat_test, local_voice_test, FastAPI-App
und Telefonie-Pfad: baut Settings, Provider und die Conversation Engine.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from agent.conversation import ConversationEngine
from core.config import BusinessConfig, Settings, get_business_config, get_settings
from core.logging import configure_logging
from database.repository import VoiceProfileRepository
from llm.base import LLMProvider
from llm.local_llama import LocalLlamaProvider
from tools.base import EmailProvider, WhatsAppProvider
from tools.email import SMTPEmailProvider
from tools.whatsapp import build_provider as build_whatsapp_provider
from voice.tts.base import TextToSpeechProvider


@dataclass
class AppContext:
    settings: Settings
    business_config: BusinessConfig
    llm_provider: LLMProvider
    email_provider: EmailProvider
    whatsapp_provider: WhatsAppProvider
    engine: ConversationEngine


def build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "local_llama":
        return LocalLlamaProvider(
            server_url=settings.llama_server_url,
            model_name=settings.llama_model_name,
            timeout=settings.llama_timeout,
        )
    raise ValueError(f"Unbekannter LLM_PROVIDER: {settings.llm_provider}")


def build_email_provider(settings: Settings) -> EmailProvider:
    if settings.email_provider == "smtp":
        return SMTPEmailProvider(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            from_addr=settings.smtp_from,
            use_tls=settings.smtp_use_tls,
        )
    raise ValueError(f"Unbekannter EMAIL_PROVIDER: {settings.email_provider}")


def build_whatsapp_provider_from_settings(settings: Settings) -> WhatsAppProvider:
    return build_whatsapp_provider(
        settings.whatsapp_api_url, settings.whatsapp_api_token, settings.whatsapp_phone_number_id
    )


def build_tts_provider(settings: Settings) -> TextToSpeechProvider:
    if settings.tts_provider == "local_piper":
        from voice.tts.piper_tts import LocalTTSProvider

        return LocalTTSProvider(settings.piper_binary, settings.piper_model_path, settings.piper_speaker)
    if settings.tts_provider == "chatterbox":
        from voice.tts.chatterbox_tts import ChatterboxTTSProvider

        return ChatterboxTTSProvider(
            language=settings.chatterbox_language,
            exaggeration=settings.chatterbox_exaggeration,
            cfg_weight=settings.chatterbox_cfg_weight,
            temperature=settings.chatterbox_temperature,
            device=settings.chatterbox_device,
            max_attempts=settings.chatterbox_max_attempts,
            reference_audio_path=settings.chatterbox_reference_audio_path or None,
        )
    if settings.tts_provider == "elevenlabs":
        from voice.tts.elevenlabs_tts import ElevenLabsTTSProvider

        return ElevenLabsTTSProvider(
            api_key=settings.elevenlabs_api_key,
            voice_id=settings.elevenlabs_voice_id,
            model_id=settings.elevenlabs_model_id,
            output_format=settings.elevenlabs_output_format,
            stability=settings.elevenlabs_stability,
            similarity_boost=settings.elevenlabs_similarity_boost,
            style=settings.elevenlabs_style,
            use_speaker_boost=settings.elevenlabs_use_speaker_boost,
        )
    raise ValueError(f"Unbekannter TTS_PROVIDER: {settings.tts_provider}")


_tts_provider_cache: dict[tuple, TextToSpeechProvider] = {}


def _tts_signature(settings: Settings, reference_audio_path: str | None,
                    exaggeration: float, cfg_weight: float, temperature: float) -> tuple:
    return (
        settings.tts_provider,
        settings.elevenlabs_voice_id if settings.tts_provider == "elevenlabs" else "",
        settings.elevenlabs_model_id if settings.tts_provider == "elevenlabs" else "",
        reference_audio_path or "",
        round(exaggeration, 4),
        round(cfg_weight, 4),
        round(temperature, 4),
    )


async def get_tts_provider(session: AsyncSession | None = None) -> TextToSpeechProvider:
    """Prozessweit wiederverwendete TTS-Provider-Instanz.

    Beruecksichtigt die in der Datenbank als aktiv markierte
    database/models.py::VoiceProfile (siehe Abschnitt 22 der Dashboard-Spec:
    "Stimme aktivieren" wirkt sofort auf alle kommenden Anrufe, ohne
    Backend-Neustart). Ohne aktives VoiceProfile (z.B. frische Installation)
    gelten die Chatterbox-Werte aus .env als Fallback.

    Pro (Referenzstimme, Parameter)-Kombination wird genau eine Provider-
    Instanz zwischengehalten, damit ein aktiviertes Voice-Profil das
    Chatterbox-Modell (~2GB) nicht bei jedem Call neu laedt (siehe
    voice/tts/chatterbox_tts.py::_get_model) - ein Wechsel der aktiven
    Stimme baut dagegen automatisch eine neue Instanz mit der neuen
    Referenzaufnahme.
    """
    settings = get_settings()

    reference_audio_path = settings.chatterbox_reference_audio_path or None
    exaggeration = settings.chatterbox_exaggeration
    cfg_weight = settings.chatterbox_cfg_weight
    temperature = settings.chatterbox_temperature

    if session is not None and settings.tts_provider == "chatterbox":
        active_voice = await VoiceProfileRepository(session).get_active()
        if active_voice is not None:
            reference_audio_path = None if active_voice.is_builtin else (active_voice.file_path or None)
            exaggeration = active_voice.exaggeration
            cfg_weight = active_voice.cfg_weight
            temperature = active_voice.temperature

    signature = _tts_signature(settings, reference_audio_path, exaggeration, cfg_weight, temperature)
    cached = _tts_provider_cache.get(signature)
    if cached is not None:
        return cached

    if settings.tts_provider == "chatterbox":
        from voice.tts.chatterbox_tts import ChatterboxTTSProvider

        provider: TextToSpeechProvider = ChatterboxTTSProvider(
            language=settings.chatterbox_language,
            exaggeration=exaggeration,
            cfg_weight=cfg_weight,
            temperature=temperature,
            device=settings.chatterbox_device,
            max_attempts=settings.chatterbox_max_attempts,
            reference_audio_path=reference_audio_path,
        )
    elif settings.tts_provider == "elevenlabs":
        provider = build_tts_provider(settings)
    else:
        provider = build_tts_provider(settings)

    _tts_provider_cache[signature] = provider
    return provider


async def build_app_context(session: AsyncSession | None = None) -> AppContext:
    """Baut den Anwendungskontext fuer einen Call-Start.

    Mit `session` werden Dashboard-Einstellungen (Abschnitt 28, z.B.
    Agent-Name/Firma/Standort/Wartezeit/Stille-Timeout/Cooldown, siehe
    services/effective_settings.py) auf die .env-Basiswerte ueberlagert -
    ein NEUER Call bekommt so automatisch die zuletzt im Dashboard
    gespeicherten Werte, ohne Backend-Neustart. Ohne `session` (z.B.
    app/chat_test.py, app/local_voice_test.py - lokale Entwicklungswerkzeuge
    ohne Dashboard) gelten die reinen .env-Werte."""
    if session is not None:
        from services.effective_settings import get_effective_settings

        settings = await get_effective_settings(session)
    else:
        settings = get_settings()

    business_config = get_business_config()
    configure_logging(settings.log_level, settings.log_dir)

    llm_provider = build_llm_provider(settings)
    email_provider = build_email_provider(settings)
    whatsapp_provider = build_whatsapp_provider_from_settings(settings)

    engine = ConversationEngine(settings, business_config, llm_provider)

    return AppContext(
        settings=settings,
        business_config=business_config,
        llm_provider=llm_provider,
        email_provider=email_provider,
        whatsapp_provider=whatsapp_provider,
        engine=engine,
    )
