"""Builds API views from models and recommendations."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trim import scopes as sc
from trim.api import schemas as s
from trim.connectors.base import Capabilities
from trim.models import ActivityEvent, Agent, Alert, AlertStatus, Decision, DecisionAction, PermissionRequest
from trim.services.recommender import Recommendation, recommend


def _risk(scopes: list[str]) -> int:
    meaningful = [sc.risk(x) for x in scopes if not (sc.info(x) and sc.info(x).essential)]
    return max(meaningful, default=0)


def _open_alerts(session: Session, agent_id: int) -> int:
    return (
        session.scalar(select(func.count(Alert.id)).where(Alert.agent_id == agent_id, Alert.status == AlertStatus.open))
        or 0
    )


def _last_activity(session: Session, agent_id: int) -> datetime | None:
    return session.scalar(select(func.max(ActivityEvent.occurred_at)).where(ActivityEvent.agent_id == agent_id))


def agent_summary(session: Session, agent: Agent, rec: Recommendation) -> s.AgentSummary:
    users = len(rec.grants)
    return s.AgentSummary(
        id=agent.id,
        name=agent.name,
        client_id=agent.client_id,
        owner_email=agent.owner_email,
        state=rec.state.value,
        reach=sc.reach_sentence(rec.granted_scopes, users) if users else "Holds no access.",
        users=users,
        granted=len(rec.granted_scopes),
        unused=len(rec.unused_scopes),
        risk=_risk(rec.granted_scopes),
        open_alerts=_open_alerts(session, agent.id),
        last_activity=_last_activity(session, agent.id),
        first_seen=agent.first_seen,
    )


def decision_view(d: Decision, caps: Capabilities) -> s.DecisionView:
    removed = added = 0
    for email in set(d.before) | set(d.after):
        b, a = set(d.before.get(email, [])), set(d.after.get(email, []))
        removed += len(b - a)
        added += len(a - b)
    undoable = d.undone_at is None and d.action not in (DecisionAction.restore, DecisionAction.expire) and caps.restore
    return s.DecisionView(
        id=d.id,
        action=d.action.value,
        agent_id=d.agent_id,
        agent_name=d.agent.name if d.agent else "",
        actor=d.actor,
        reason=d.reason,
        created_at=d.created_at,
        undone_at=d.undone_at,
        undo_of_id=d.undo_of_id,
        before=d.before,
        after=d.after,
        removed=removed,
        added=added,
        undoable=undoable,
    )


def alert_view(a: Alert) -> s.AlertView:
    return s.AlertView(
        id=a.id,
        agent_id=a.agent_id,
        agent_name=a.agent.name if a.agent else "",
        day=a.day,
        score=a.score,
        status=a.status.value,
        reasons=a.reasons,
        created_at=a.created_at,
    )


def request_view(r: PermissionRequest) -> s.RequestView:
    return s.RequestView(
        id=r.id,
        agent_id=r.agent_id,
        agent_name=r.agent.name,
        user_email=r.user.email,
        scopes=r.scopes,
        phrases=[sc.info(x).phrase if sc.info(x) else f"use {sc.short_name(x)}" for x in r.scopes],
        justification=r.justification,
        status=r.status.value,
        created_at=r.created_at,
        decided_by=r.decided_by,
        decided_at=r.decided_at,
        expires_at=r.expires_at,
    )


def _activity_by_day(session: Session, agent_id: int, now: datetime, days: int = 28) -> list[s.DayCount]:
    start = (now - timedelta(days=days - 1)).date()
    counts: Counter[date] = Counter()
    for (ts,) in session.execute(
        select(ActivityEvent.occurred_at).where(
            ActivityEvent.agent_id == agent_id,
            ActivityEvent.occurred_at >= datetime.combine(start, datetime.min.time(), tzinfo=now.tzinfo),
        )
    ):
        counts[ts.date()] += 1
    return [
        s.DayCount(day=start + timedelta(days=i), calls=counts.get(start + timedelta(days=i), 0)) for i in range(days)
    ]


def agent_detail(
    session: Session, agent: Agent, now: datetime, observation_days: int, caps: Capabilities
) -> s.AgentDetail:
    rec = recommend(session, agent, now, observation_days)
    summary = agent_summary(session, agent, rec)
    users_per_scope: Counter[str] = Counter()
    for p in rec.grants:
        users_per_scope.update(set(p.granted))
    scope_views = []
    for scope in sorted(rec.granted_scopes, key=lambda x: (-sc.risk(x), sc.short_name(x))):
        i = sc.info(scope)
        scope_views.append(
            s.ScopeView(
                scope=scope,
                short=sc.short_name(scope),
                phrase=i.phrase if i else f"use {sc.short_name(scope)}",
                risk=sc.risk(scope),
                status=rec.scope_status.get(scope, "used"),
                narrowed_to=[sc.short_name(n) for n in rec.narrowed_to.get(scope, [])],
                users=users_per_scope[scope],
                essential=bool(i and i.essential),
            )
        )
    kept = list(dict.fromkeys(k for p in rec.grants for k in p.keep))
    alerts = session.scalars(select(Alert).where(Alert.agent_id == agent.id).order_by(Alert.day.desc()).limit(10))
    decisions = session.scalars(
        select(Decision).where(Decision.agent_id == agent.id).order_by(Decision.created_at.desc()).limit(10)
    )
    return s.AgentDetail(
        **summary.model_dump(),
        reach_after=sc.reach_sentence(kept, len([p for p in rec.grants if p.keep]))
        if kept
        else "Would hold no access.",
        learning_until=rec.learning_until,
        window_start=rec.window_start,
        window_end=rec.window_end,
        calls=rec.calls,
        dormant=rec.dormant,
        excluded_days=rec.excluded_days,
        scopes=scope_views,
        grants=[
            s.GrantView(
                user_email=p.user_email,
                granted=[sc.short_name(x) for x in p.granted],
                keep=[sc.short_name(x) for x in p.keep],
                remove=[sc.short_name(x) for x in p.remove],
                calls=p.calls,
                reasons={sc.short_name(k): v for k, v in p.reasons.items()},
            )
            for p in rec.grants
        ],
        alerts=[alert_view(a) for a in alerts],
        decisions=[decision_view(d, caps) for d in decisions],
        activity=_activity_by_day(session, agent.id, now),
        can_narrow=caps.narrow_scopes,
        can_restore=caps.restore,
    )
