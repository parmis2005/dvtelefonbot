"""Test-Hilfsfunktionen: bauen eine ConversationEngine/Context ohne DB/LLM auf."""

from __future__ import annotations

from agent.context import ConversationContext, LeadData
from agent.conversation import ConversationEngine
from agent.state_machine import CallState
from core.config import BusinessConfig, Settings


def make_settings(**overrides) -> Settings:
    defaults = {"max_rejections": 2}
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def make_business_config() -> BusinessConfig:
    return BusinessConfig(
        {
            "pricing": {
                "website_monthly_from": 300,
                "maintenance_monthly_from": 100,
                "seo_monthly_from": 200,
            }
        }
    )


def make_engine(**settings_overrides) -> ConversationEngine:
    settings = make_settings(**settings_overrides)
    return ConversationEngine(settings, make_business_config(), llm_provider=None)


def make_context(
    *,
    entwurf_vorhanden: bool = True,
    online_auftritt_geprueft: bool = True,
    state: CallState = CallState.DISCOVERY,
) -> ConversationContext:
    ctx = ConversationContext()
    ctx.lead = LeadData(
        unternehmen="Beauty Studio Beispiel",
        ansprechpartner="Frau Mueller",
        telefonnummer="+491701234567",
        entwurf_vorhanden=entwurf_vorhanden,
        entwurf_link="https://beispiel.de/entwurf" if entwurf_vorhanden else "",
        online_auftritt_geprueft=online_auftritt_geprueft,
    )
    ctx.state = state
    return ctx
