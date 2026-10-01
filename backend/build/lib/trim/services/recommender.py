"""Turns observed activity into least-privilege recommendations, and derives each agent's state."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trim import scopes as sc
from trim.models import (
    ActivityEvent,
    Agent,
    AgentStatus,
    Alert,
    AlertStatus,
    Decision,
    DecisionAction,
    Grant,
    User,
)


class AgentState(StrEnum):
    learning = "learning"  # still inside the observation window
    ready = "ready"  # has permissions it never used: recommendation waiting
    trimmed = "trimmed"  # Trim removed access and nothing more is unused
    right_sized = "right_sized"  # nothing unused and never needed trimming
    exempt = "exempt"
    suspended = "suspended"


@dataclass
class GrantPlan:
    user_email: str
    granted: list[str]
    keep: list[str]
    remove: list[str]
    reasons: dict[str, list[str]] = field(default_factory=dict)  # kept scope -> methods
    narrowed: dict[str, list[str]] = field(default_factory=dict)
    uncovered: list[str] = field(default_factory=list)
    calls: int = 0

    @property
    def changes(self) -> bool:
        return set(self.keep) != set(self.granted)


@dataclass
class Recommendation:
    agent_id: int
    state: AgentState
    window_start: datetime
    window_end: datetime
    learning_until: datetime | None
    grants: list[GrantPlan]
    granted_scopes: list[str]
    used_scopes: list[str]
    unused_scopes: list[str]
    scope_status: dict[str, str]  # granted scope -> used | narrowed | unused | learning
    narrowed_to: dict[str, list[str]]
    calls: int
    dormant: bool
    excluded_days: list = field(default_factory=list)

    @property
    def changes(self) -> list[GrantPlan]:
        return [g for g in self.grants if g.changes]


def _has_active_trim(session: Session, agent_id: int) -> bool:
    q = select(func.count(Decision.id)).where(
        Decision.agent_id == agent_id,
        Decision.action == DecisionAction.trim,
        Decision.undone_at.is_(None),
    )
    return (session.scalar(q) or 0) > 0


def recommend(session: Session, agent: Agent, now: datetime, observation_days: int) -> Recommendation:
    window_start = now - timedelta(days=observation_days)
    learning_until = agent.first_seen + timedelta(days=observation_days)
    grants = list(
        session.execute(
            select(Grant, User)
            .join(User, Grant.user_id == User.id)
            .where(Grant.agent_id == agent.id, Grant.active.is_(True))
        )
    )

    # Days with an open or confirmed alert are left out: suspicious activity must not
    # justify keeping a permission.
    excluded_days = set(
        session.scalars(
            select(Alert.day).where(
                Alert.agent_id == agent.id, Alert.status.in_([AlertStatus.open, AlertStatus.confirmed])
            )
        )
    )
    usage: dict[int | None, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for user_id, method, ts in session.execute(
        select(ActivityEvent.user_id, ActivityEvent.method_name, ActivityEvent.occurred_at).where(
            ActivityEvent.agent_id == agent.id,
            ActivityEvent.occurred_at >= window_start,
            ActivityEvent.occurred_at <= now,
        )
    ):
        if ts.date() in excluded_days:
            continue
        usage[user_id][method] += 1
    total_calls = sum(sum(m.values()) for m in usage.values())

    plans: list[GrantPlan] = []
    used_all: set[str] = set()
    granted_all: list[str] = []
    for grant, user in sorted(grants, key=lambda gu: gu[1].email):
        granted = list(grant.scopes)
        granted_all.extend(granted)
        methods = usage.get(user.id, {})
        cover = sc.minimal_cover(granted, methods.keys())
        # No activity for this user in the window: nothing justifies the grant, so revoke it.
        keep = list(cover.keep) if methods else []
        for k, ms in cover.keep.items():
            if ms:
                used_all.add(k)
        plans.append(
            GrantPlan(
                user_email=user.email,
                granted=granted,
                keep=keep,
                remove=[g for g in granted if g not in keep],
                reasons={k: v for k, v in cover.keep.items() if k in keep},
                narrowed=cover.narrowed if methods else {},
                uncovered=cover.uncovered,
                calls=sum(methods.values()),
            )
        )

    granted_distinct = list(dict.fromkeys(granted_all))
    kept_union = {k for p in plans for k in p.keep}
    narrowed_to: dict[str, list[str]] = {}
    for p in plans:
        for broad, narrow in p.narrowed.items():
            narrowed_to.setdefault(broad, [])
            narrowed_to[broad] = sorted(set(narrowed_to[broad]) | set(narrow))
    scope_status: dict[str, str] = {}
    for g in granted_distinct:
        if g in kept_union:
            scope_status[g] = "used"
        elif g in narrowed_to:
            scope_status[g] = "narrowed"
        else:
            scope_status[g] = "unused"
    unused = [g for g in granted_distinct if scope_status[g] != "used"]
    used_distinct = sorted(used_all)

    if agent.status is AgentStatus.suspended:
        state = AgentState.suspended
    elif agent.exempt:
        state = AgentState.exempt
    elif now < learning_until:
        state = AgentState.learning
    elif any(p.changes for p in plans):
        state = AgentState.ready
    elif _has_active_trim(session, agent.id):
        state = AgentState.trimmed
    else:
        state = AgentState.right_sized

    if state is AgentState.learning:
        plans = [GrantPlan(p.user_email, p.granted, p.granted, [], calls=p.calls) for p in plans]
        unused, narrowed_to = [], {}
        scope_status = {g: "learning" for g in granted_distinct}

    return Recommendation(
        agent_id=agent.id,
        state=state,
        window_start=window_start,
        window_end=now,
        learning_until=learning_until if now < learning_until else None,
        grants=plans,
        granted_scopes=granted_distinct,
        used_scopes=used_distinct,
        unused_scopes=unused,
        scope_status=scope_status,
        narrowed_to=narrowed_to,
        calls=total_calls,
        dormant=total_calls == 0 and state is not AgentState.learning,
        excluded_days=sorted(excluded_days),
    )
