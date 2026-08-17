"""SQLAlchemy Datenmodelle: Lead, Call, DoNotCall.

Wechsel zu PostgreSQL erfordert nur eine andere DATABASE_URL,
da ausschliesslich portable SQLAlchemy-Typen verwendet werden.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class LeadStatus(str, enum.Enum):
    NEW = "NEW"
    CALLED = "CALLED"
    NO_ANSWER = "NO_ANSWER"
    BUSY = "BUSY"
    GATEKEEPER = "GATEKEEPER"
    CALLBACK = "CALLBACK"
    INTERESTED = "INTERESTED"
    DESIGN_REQUESTED = "DESIGN_REQUESTED"
    DESIGN_SENT = "DESIGN_SENT"
    FOLLOW_UP = "FOLLOW_UP"
    NOT_INTERESTED = "NOT_INTERESTED"
    DO_NOT_CALL = "DO_NOT_CALL"
    QUALIFIED = "QUALIFIED"
    HANDOFF_TO_MANAGEMENT = "HANDOFF_TO_MANAGEMENT"


class PreferredContact(str, enum.Enum):
    EMAIL = "EMAIL"
    WHATSAPP = "WHATSAPP"
    UNKNOWN = "UNKNOWN"


class CallStatus(str, enum.Enum):
    CREATED = "CREATED"
    RINGING = "RINGING"
    ANSWERED = "ANSWERED"
    BUSY = "BUSY"
    NO_ANSWER = "NO_ANSWER"
    FAILED = "FAILED"
    HANGUP = "HANGUP"
    COMPLETED = "COMPLETED"


class CallResult(str, enum.Enum):
    INTERESTED = "INTERESTED"
    NOT_INTERESTED = "NOT_INTERESTED"
    DESIGN_SENT = "DESIGN_SENT"
    CALLBACK_REQUESTED = "CALLBACK_REQUESTED"
    DO_NOT_CALL = "DO_NOT_CALL"
    GATEKEEPER_ONLY = "GATEKEEPER_ONLY"
    NO_ANSWER = "NO_ANSWER"
    UNKNOWN = "UNKNOWN"


class CampaignStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    unternehmen: Mapped[str] = mapped_column(String(255), nullable=False)
    ansprechpartner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    branche: Mapped[str | None] = mapped_column(String(255), nullable=True)
    website_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    telefonnummer: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notizen: Mapped[str | None] = mapped_column(Text, nullable=True)

    online_auftritt_geprueft: Mapped[bool] = mapped_column(Boolean, default=False)
    entwurf_vorhanden: Mapped[bool] = mapped_column(Boolean, default=False)
    entwurf_link: Mapped[str | None] = mapped_column(String(500), nullable=True)

    status: Mapped[LeadStatus] = mapped_column(
        Enum(LeadStatus), default=LeadStatus.NEW, nullable=False
    )
    preferred_contact: Mapped[PreferredContact] = mapped_column(
        Enum(PreferredContact), default=PreferredContact.UNKNOWN
    )
    callback_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    callback_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    do_not_call: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    calls: Mapped[list[Call]] = relationship(
        "Call", back_populates="lead", cascade="all, delete-orphan"
    )


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id"), nullable=False, index=True)
    campaign_id: Mapped[int | None] = mapped_column(
        ForeignKey("campaigns.id"), nullable=True, index=True
    )

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)  # seconds

    status: Mapped[CallStatus] = mapped_column(
        Enum(CallStatus), default=CallStatus.CREATED, nullable=False
    )
    result: Mapped[CallResult | None] = mapped_column(Enum(CallResult), nullable=True)

    transcript: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Twilio Call-SID, sobald bekannt - erlaubt Live-Status-Updates + Hangup
    # aus dem Dashboard heraus zuzuordnen, ohne bei jedem Statuswechsel die
    # Session selbst durchsuchen zu muessen.
    twilio_call_sid: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lead: Mapped[Lead] = relationship("Lead", back_populates="calls")
    campaign: Mapped[Campaign | None] = relationship("Campaign", back_populates="calls")


class DoNotCall(Base):
    """Persistente Sperrliste. Wird VOR JEDEM Outbound-Call geprueft."""

    __tablename__ = "do_not_call"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefonnummer: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Campaign(Base):
    """Sammelanruf-Kampagne: eine Menge von Leads, die mit begrenzter
    Parallelitaet automatisch nacheinander/parallel angerufen werden
    (siehe services/campaign_service.py::CampaignManager)."""

    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    lead_ids_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON-Liste von Lead-IDs
    max_concurrent: Mapped[int] = mapped_column(Integer, default=10, nullable=False)

    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus), default=CampaignStatus.DRAFT, nullable=False
    )

    total_count: Mapped[int] = mapped_column(Integer, default=0)
    processed_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    calls: Mapped[list[Call]] = relationship("Call", back_populates="campaign")


class PromptVersion(Base):
    """Versionierter Systemprompt (Abschnitt 21). Nur die Version mit
    is_active=True wird von NEUEN Gespraechen verwendet - laufende Calls
    behalten die Version, mit der sie gestartet wurden (siehe
    agent/prompts.py::load_system_prompt)."""

    __tablename__ = "prompt_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class VoiceProfile(Base):
    """Eine hochladbare Referenzstimme fuer Chatterbox-Voice-Cloning
    (Abschnitt 22). Nur die Stimme mit is_active=True wird fuer neue
    TTS-Syntheseaufrufe verwendet (siehe app/bootstrap.py::get_tts_provider)."""

    __tablename__ = "voice_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False)  # Chatterbox-Standardstimme

    exaggeration: Mapped[float] = mapped_column(default=0.22)
    cfg_weight: Mapped[float] = mapped_column(default=0.35)
    temperature: Mapped[float] = mapped_column(default=0.55)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AppSetting(Base):
    """Laufzeit-editierbare Einstellungen (Abschnitt 28) - bewusst getrennt
    von .env: .env bleibt fuer Secrets/Umgebungswerte, diese Tabelle fuer
    Werte, die ueber das Dashboard ohne Neustart geaendert werden sollen."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
