"""Gemeinsame Initialisierung fuer chat_test, local_voice_test, FastAPI-App
und Telefonie-Pfad: baut Settings, Provider und die Conversation Engine.
"""

from __future__ import annotations

from dataclasses import dataclass

from agent.conversation import ConversationEngine
from core.config import BusinessConfig, Settings, get_business_config, get_settings
from core.logging import configure_logging
from llm.base import LLMProvider
from llm.local_llama import LocalLlamaProvider
from tools.base import EmailProvider, WhatsAppProvider
from tools.email import SMTPEmailProvider
from tools.whatsapp import build_provider as build_whatsapp_provider


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


def build_app_context() -> AppContext:
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
