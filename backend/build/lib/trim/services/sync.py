"""Pulls users, grants and activity from the connector into the database."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from trim.connectors.base import Connector
from trim.models import ActivityEvent, Agent, Grant, SyncCursor, User

BATCH = 1000


@dataclass
class SyncReport:
    users: int = 0
    agents_new: int = 0
    grants_active: int = 0
    grants_removed: int = 0
    events_new: int = 0
    events_pruned: int = 0
    errors: list[str] = field(default_factory=list)


def _users_by_email(session: Session) -> dict[str, User]:
    return {u.email: u for u in session.scalars(select(User))}


def _agents_by_client(session: Session) -> dict[str, Agent]:
    return {a.client_id: a for a in session.scalars(select(Agent))}


def _ensure_user(session: Session, users: dict[str, User], email: str, now: datetime) -> User:
    email = email.lower()
    u = users.get(email)
    if u is None:
        u = User(email=email, synced_at=now)
        session.add(u)
        session.flush()
        users[email] = u
    return u


def _ensure_agent(
    session: Session,
    agents: dict[str, Agent],
    client_id: str,
    name: str,
    owner: str,
    now: datetime,
    report: SyncReport,
) -> Agent:
    a = agents.get(client_id)
    if a is None:
        a = Agent(client_id=client_id, name=name[:255] or client_id, owner_email=owner, first_seen=now)
        session.add(a)
        session.flush()
        agents[client_id] = a
        report.agents_new += 1
    return a


def sync_inventory(session: Session, connector: Connector, now: datetime, report: SyncReport) -> None:
    users = _users_by_email(session)
    for rec in connector.list_users():
        u = _ensure_user(session, users, rec.email, now)
        u.name, u.department, u.synced_at = rec.name, rec.department, now
    report.users = len(users)

    agents = _agents_by_client(session)
    existing = {(g.agent_id, g.user_id): g for g in session.scalars(select(Grant))}
    seen: set[tuple[int, int]] = set()
    for rec in sorted(connector.list_grants(), key=lambda r: (r.client_id, r.user_email)):
        agent = _ensure_agent(session, agents, rec.client_id, rec.app_name, rec.user_email, now, report)
        user = _ensure_user(session, users, rec.user_email, now)
        key = (agent.id, user.id)
        seen.add(key)
        g = existing.get(key)
        if g is None:
            g = Grant(agent_id=agent.id, user_id=user.id)
            session.add(g)
            existing[key] = g
        new_scopes = list(dict.fromkeys(rec.scopes))
        if g.scopes != new_scopes or not g.active:
            g.scopes, g.active, g.updated_at = new_scopes, True, now
        report.grants_active += 1

    for key, g in existing.items():
        if key not in seen and g.active:
            g.active, g.scopes, g.updated_at = False, [], now
            report.grants_removed += 1
    session.flush()


def sync_activity(
    session: Session,
    connector: Connector,
    now: datetime,
    retention_days: int,
    report: SyncReport,
    lookback_hours: int = 72,
) -> None:
    cursor = session.get(SyncCursor, connector.provider)
    if cursor is None:
        cursor = SyncCursor(provider=connector.provider)
        session.add(cursor)

    users = _users_by_email(session)
    agents = _agents_by_client(session)
    pending: list = []
    newest = cursor.last_event_at

    def flush_batch() -> None:
        if not pending:
            return
        uids = [r.uid for r in pending]
        known = set(session.scalars(select(ActivityEvent.uid).where(ActivityEvent.uid.in_(uids))))
        for r in pending:
            if r.uid in known:
                continue
            known.add(r.uid)
            agent = _ensure_agent(session, agents, r.client_id, r.app_name, r.user_email or "", now, report)
            if r.occurred_at < agent.first_seen:
                agent.first_seen = r.occurred_at
            user = _ensure_user(session, users, r.user_email, now) if r.user_email else None
            session.add(
                ActivityEvent(
                    uid=r.uid,
                    agent_id=agent.id,
                    user_id=user.id if user else None,
                    api_name=r.api_name[:120],
                    method_name=r.method_name[:255],
                    response_bytes=max(0, int(r.response_bytes)),
                    occurred_at=r.occurred_at,
                )
            )
            report.events_new += 1
        session.flush()
        pending.clear()

    since = cursor.last_event_at - timedelta(hours=lookback_hours) if cursor.last_event_at else None
    for rec in connector.list_activity(since):
        pending.append(rec)
        if newest is None or rec.occurred_at > newest:
            newest = rec.occurred_at
        if len(pending) >= BATCH:
            flush_batch()
    flush_batch()

    cursor.last_event_at = newest
    cursor.last_run_at = now
    cutoff = now - timedelta(days=retention_days)
    res = session.execute(delete(ActivityEvent).where(ActivityEvent.occurred_at < cutoff))
    report.events_pruned = res.rowcount or 0
    session.flush()


def run_sync(
    session: Session, connector: Connector, now: datetime, retention_days: int, lookback_hours: int = 72
) -> SyncReport:
    report = SyncReport()
    sync_inventory(session, connector, now, report)
    sync_activity(session, connector, now, retention_days, report, lookback_hours)
    return report
