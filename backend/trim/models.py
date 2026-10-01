"""ORM models.

Trim stores metadata only: which agent holds which permissions, and which API
methods it called, when and how much. It never stores message or file content.
"""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from trim.db import Base, UTCDateTime, utcnow


class AgentStatus(enum.StrEnum):
    active = "active"
    suspended = "suspended"


class DecisionAction(enum.StrEnum):
    trim = "trim"
    suspend = "suspend"
    restore = "restore"
    grant_once = "grant_once"
    grant_always = "grant_always"
    expire = "expire"


class RequestStatus(enum.StrEnum):
    pending = "pending"
    approved_once = "approved_once"
    approved_always = "approved_always"
    denied = "denied"
    expired = "expired"


class AlertStatus(enum.StrEnum):
    open = "open"  # waiting for review
    confirmed = "confirmed"  # reviewer agrees it is suspicious
    dismissed = "dismissed"  # reviewer marked it benign


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    department: Mapped[str] = mapped_column(String(120), default="")
    synced_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    owner_email: Mapped[str] = mapped_column(String(320), default="")
    first_seen: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    status: Mapped[AgentStatus] = mapped_column(Enum(AgentStatus), default=AgentStatus.active)
    exempt: Mapped[bool] = mapped_column(Boolean, default=False)

    grants: Mapped[list[Grant]] = relationship(back_populates="agent", cascade="all, delete-orphan")


class Grant(Base):
    """Permissions one agent holds on behalf of one user."""

    __tablename__ = "grants"
    __table_args__ = (UniqueConstraint("agent_id", "user_id", name="uq_grant_agent_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    agent: Mapped[Agent] = relationship(back_populates="grants")
    user: Mapped[User] = relationship()


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    __table_args__ = (Index("ix_activity_agent_time", "agent_id", "occurred_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    uid: Mapped[str] = mapped_column(String(200), unique=True)  # idempotent ingestion
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    api_name: Mapped[str] = mapped_column(String(120))
    method_name: Mapped[str] = mapped_column(String(255))
    response_bytes: Mapped[int] = mapped_column(Integer, default=0)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Decision(Base):
    """Every change Trim makes to access, with the exact state before and after."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[DecisionAction] = mapped_column(Enum(DecisionAction))
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    # {user_email: [scopes]} for every grant the decision touched
    before: Mapped[dict] = mapped_column(JSON, default=dict)
    after: Mapped[dict] = mapped_column(JSON, default=dict)
    actor: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    undone_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    undo_of_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id"), nullable=True)

    agent: Mapped[Agent] = relationship()


class PermissionRequest(Base):
    __tablename__ = "permission_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    scopes: Mapped[list[str]] = mapped_column(JSON)
    justification: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[RequestStatus] = mapped_column(Enum(RequestStatus), default=RequestStatus.pending)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("decisions.id"), nullable=True)

    agent: Mapped[Agent] = relationship()
    user: Mapped[User] = relationship()


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("agent_id", "day", name="uq_alert_agent_day"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"), index=True)
    day: Mapped[date] = mapped_column(Date)
    score: Mapped[float] = mapped_column(Float)
    reasons: Mapped[list[dict]] = mapped_column(JSON, default=list)
    status: Mapped[AlertStatus] = mapped_column(Enum(AlertStatus), default=AlertStatus.open)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    agent: Mapped[Agent] = relationship()


class Connection(Base):
    """Credentials for the connected organisation, encrypted at rest with Fernet."""

    __tablename__ = "connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), unique=True)
    secret_ciphertext: Mapped[bytes] = mapped_column(default=b"")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class SyncCursor(Base):
    """Where the last activity sync stopped, per provider."""

    __tablename__ = "sync_cursors"

    provider: Mapped[str] = mapped_column(String(40), primary_key=True)
    last_event_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
