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

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    lead: Mapped[Lead] = relationship("Lead", back_populates="calls")


class DoNotCall(Base):
    """Persistente Sperrliste. Wird VOR JEDEM Outbound-Call geprueft."""

    __tablename__ = "do_not_call"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefonnummer: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
