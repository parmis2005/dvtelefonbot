"""Zentrale Konfiguration fuer Digital Vision Dario.

Laedt Secrets/Umgebungswerte aus .env (pydantic-settings) und
statische Geschaeftskonfiguration aus config.yaml.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Umgebungsabhaengige Konfiguration, geladen aus .env / echten env vars."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Agent / Unternehmen
    agent_name: str = "Dario"
    company_name: str = "Digital Vision"
    company_location: str = "Moenchengladbach"

    # Provider-Auswahl
    stt_provider: str = "local_whisper"
    llm_provider: str = "local_llama"
    tts_provider: str = "local_piper"
    telephony_provider: str = "asterisk"
    email_provider: str = "smtp"
    whatsapp_provider: str = "none"

    # Datenbank
    database_url: str = "sqlite+aiosqlite:///./data/dario.db"

    # Verhalten
    wait_timeout: int = 25
    silence_timeout: int = 8
    call_cooldown: int = 86400
    max_rejections: int = 2

    # LLM (llama.cpp Server)
    llama_server_url: str = "http://127.0.0.1:8080"
    llama_model_name: str = "local-model"
    llama_timeout: int = 30

    # Whisper
    whisper_cpp_binary: str = "whisper-cli"
    whisper_model_path: str = "./models/whisper/ggml-small.bin"
    whisper_language: str = "de"

    # TTS (Piper)
    piper_binary: str = "piper"
    piper_model_path: str = "./models/piper/de_DE-thorsten-high.onnx"
    piper_speaker: str | None = None

    # TTS (Chatterbox Multilingual) - siehe voice/tts/chatterbox_tts.py fuer den
    # Hintergrund zu diesen Werten (Ergebnis einer mehrstufigen Stimmauswahl).
    chatterbox_language: str = "de"
    chatterbox_exaggeration: float = 0.22
    chatterbox_cfg_weight: float = 0.35
    chatterbox_temperature: float = 0.55
    chatterbox_device: str = "cpu"
    chatterbox_max_attempts: int = 3
    # Leer = Chatterbox' eingebaute Standardstimme. Gesetzt = Stimme wird aus
    # dieser Referenzaufnahme geklont (siehe voice/tts/chatterbox_tts.py).
    chatterbox_reference_audio_path: str = ""

    # Asterisk / ARI
    asterisk_ari_url: str = "http://127.0.0.1:8088"
    asterisk_ari_app: str = "dario"
    asterisk_username: str = ""
    asterisk_password: str = ""
    asterisk_sip_trunk: str = "default_trunk"
    asterisk_caller_id: str = ""

    # Twilio Programmable Voice (alternativer Telefonie-Provider zu Asterisk,
    # siehe phone/twilio_voice.py). TWILIO_PUBLIC_BASE_URL muss von aussen
    # erreichbar sein (z.B. ngrok-Tunnel) - Twilio ruft darueber unseren
    # TwiML-Webhook und die Media-Stream-WebSocket auf.
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_caller_id: str = ""
    twilio_test_number: str = ""
    twilio_public_base_url: str = ""
    twilio_validate_signature: bool = True

    # SMTP
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    # WhatsApp
    whatsapp_api_url: str = ""
    whatsapp_api_token: str = ""
    whatsapp_phone_number_id: str = ""

    # Logging
    log_level: str = "INFO"
    log_dir: str = "./logs"

    @property
    def secrets_configured(self) -> dict[str, bool]:
        return {
            "smtp": bool(self.smtp_host and self.smtp_username and self.smtp_password),
            "asterisk": bool(self.asterisk_username and self.asterisk_password),
            "whatsapp": bool(self.whatsapp_api_url and self.whatsapp_api_token),
            "twilio": bool(self.twilio_account_sid and self.twilio_auth_token),
        }


class BusinessConfig:
    """Statische Geschaeftskonfiguration aus config.yaml (kein Secret-Material)."""

    def __init__(self, data: dict[str, Any]):
        self._data = data

    @classmethod
    def load(cls, path: Path | None = None) -> BusinessConfig:
        path = path or (BASE_DIR / "config.yaml")
        if not path.exists():
            return cls({})
        with open(path, encoding="utf-8") as f:
            return cls(yaml.safe_load(f) or {})

    @property
    def pricing(self) -> dict[str, Any]:
        return self._data.get("pricing", {})

    @property
    def conversation(self) -> dict[str, Any]:
        return self._data.get("conversation", {})

    @property
    def call(self) -> dict[str, Any]:
        return self._data.get("call", {})

    @property
    def services(self) -> list[str]:
        return self._data.get("services", [])

    @property
    def company(self) -> dict[str, Any]:
        return self._data.get("company", {})


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_business_config() -> BusinessConfig:
    return BusinessConfig.load()
