"""Request and response models. Every input is validated here before reaching a service."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ScopeStr = Annotated[
    str, StringConstraints(pattern=r"^(openid|email|profile|https://[A-Za-z0-9.\-/_]{1,200})$", max_length=220)
]
EmailStr = Annotated[
    str,
    StringConstraints(
        pattern=r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,190}\.[A-Za-z]{2,24}$", max_length=320, to_lower=True
    ),
]
ClientIdStr = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._\-]{1,255}$")]
Reason = Annotated[str, StringConstraints(max_length=300, strip_whitespace=True)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---- inputs -----------------------------------------------------------------
class TrimIn(Strict):
    confirm_revoke: bool = False
    reason: Reason = ""


class SuspendIn(Strict):
    reason: Reason = ""


class ExemptIn(Strict):
    exempt: bool


class AlertReviewIn(Strict):
    status: Literal["confirmed", "dismissed"]


class RequestIn(Strict):
    client_id: ClientIdStr
    user_email: EmailStr
    scopes: list[ScopeStr] = Field(min_length=1, max_length=20)
    justification: Annotated[str, StringConstraints(max_length=500, strip_whitespace=True)] = ""


class DecideIn(Strict):
    choice: Literal["allow_once", "allow_always", "deny"]
    minutes: int | None = Field(default=None, ge=5, le=24 * 60)


# ---- outputs ----------------------------------------------------------------
class ScopeView(BaseModel):
    scope: str
    short: str
    phrase: str
    risk: int
    status: str  # used | narrowed | unused | learning
    narrowed_to: list[str] = []
    users: int
    essential: bool = False


class GrantView(BaseModel):
    user_email: str
    granted: list[str]
    keep: list[str]
    remove: list[str]
    calls: int
    reasons: dict[str, list[str]]


class AlertView(BaseModel):
    id: int
    agent_id: int
    agent_name: str
    day: date
    score: float
    status: str
    reasons: list[dict]
    created_at: datetime


class DecisionView(BaseModel):
    id: int
    action: str
    agent_id: int
    agent_name: str
    actor: str
    reason: str
    created_at: datetime
    undone_at: datetime | None
    undo_of_id: int | None
    before: dict[str, list[str]]
    after: dict[str, list[str]]
    removed: int
    added: int
    undoable: bool


class AgentSummary(BaseModel):
    id: int
    name: str
    client_id: str
    owner_email: str
    state: str
    reach: str
    users: int
    granted: int
    unused: int
    risk: int
    open_alerts: int
    last_activity: datetime | None
    first_seen: datetime


class DayCount(BaseModel):
    day: date
    calls: int


class AgentDetail(AgentSummary):
    reach_after: str
    learning_until: datetime | None
    window_start: datetime
    window_end: datetime
    calls: int
    dormant: bool
    excluded_days: list[date]
    scopes: list[ScopeView]
    grants: list[GrantView]
    alerts: list[AlertView]
    decisions: list[DecisionView]
    activity: list[DayCount]
    can_narrow: bool
    can_restore: bool


class RequestView(BaseModel):
    id: int
    agent_id: int
    agent_name: str
    user_email: str
    scopes: list[str]
    phrases: list[str]
    justification: str
    status: str
    created_at: datetime
    decided_by: str | None
    decided_at: datetime | None
    expires_at: datetime | None


class Summary(BaseModel):
    agents: int
    users: int
    active_grants: int
    by_state: dict[str, int]
    unused_permissions: int
    granted_permissions: int
    high_risk_agents: int
    open_alerts: int
    pending_requests: int
    last_sync: datetime | None
    provider: str
    can_narrow: bool
    can_restore: bool


class Me(BaseModel):
    name: str
    role: str
    can_change_access: bool


class ErrorOut(BaseModel):
    error: str
    detail: str
