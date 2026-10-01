"""Applies access changes through the connector, atomically, and makes them undoable.

Invariant: the database and the provider never disagree after a call returns.
Each change is applied grant by grant; if any provider call fails, the grants
already changed are put back (when the provider can restore) and nothing is
recorded. Providers that cannot restore (Google) get no silent partial state
either: what actually happened is recorded and reported as a partial failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from trim.connectors.base import Connector, ConnectorError
from trim.models import Agent, AgentStatus, Decision, DecisionAction, Grant, User
from trim.services.recommender import AgentState, recommend


class RemediationError(Exception):
    code = "remediation_error"


class NothingToChange(RemediationError):
    code = "nothing_to_change"


class NeedsConfirmation(RemediationError):
    code = "needs_confirmation"


class NotUndoable(RemediationError):
    code = "not_undoable"


class ProviderFailure(RemediationError):
    code = "provider_failure"


class PartialFailure(RemediationError):
    code = "partial_failure"

    def __init__(self, message: str, decision_id: int) -> None:
        super().__init__(message)
        self.decision_id = decision_id


@dataclass
class _Change:
    grant: Grant
    email: str
    before: list[str]
    after: list[str]


def _grants_with_users(session: Session, agent: Agent, active_only: bool = True) -> list[tuple[Grant, User]]:
    q = select(Grant, User).join(User, Grant.user_id == User.id).where(Grant.agent_id == agent.id)
    if active_only:
        q = q.where(Grant.active.is_(True))
    return [(g, u) for g, u in session.execute(q)]


def _apply(
    session: Session,
    connector: Connector,
    agent: Agent,
    changes: list[_Change],
    action: DecisionAction,
    actor: str,
    reason: str,
    now: datetime,
    undo_of: Decision | None = None,
) -> Decision:
    applied: list[_Change] = []
    try:
        for ch in changes:
            connector.set_scopes(ch.email, agent.client_id, ch.after)
            applied.append(ch)
    except ConnectorError as exc:
        if connector.capabilities.restore:
            for ch in reversed(applied):
                try:
                    connector.set_scopes(ch.email, agent.client_id, ch.before)
                except ConnectorError:  # pragma: no cover - double failure, surfaced below
                    break
            else:
                raise ProviderFailure(f"provider rejected the change; nothing was modified ({exc})") from exc
        if not applied:
            raise ProviderFailure(f"provider rejected the change; nothing was modified ({exc})") from exc
        decision = _record(
            session,
            agent,
            applied,
            action,
            actor,
            f"{reason} [partial: provider failed after {len(applied)} of {len(changes)}]",
            now,
            undo_of,
        )
        raise PartialFailure(
            f"provider failed after {len(applied)} of {len(changes)} changes; applied changes were recorded",
            decision.id,
        ) from exc
    return _record(session, agent, applied, action, actor, reason, now, undo_of)


def _record(
    session: Session,
    agent: Agent,
    applied: list[_Change],
    action: DecisionAction,
    actor: str,
    reason: str,
    now: datetime,
    undo_of: Decision | None,
) -> Decision:
    for ch in applied:
        ch.grant.scopes = list(ch.after)
        ch.grant.active = bool(ch.after)
        ch.grant.updated_at = now
    decision = Decision(
        action=action,
        agent_id=agent.id,
        before={ch.email: ch.before for ch in applied},
        after={ch.email: ch.after for ch in applied},
        actor=actor,
        reason=reason,
        created_at=now,
        undo_of_id=undo_of.id if undo_of else None,
    )
    session.add(decision)
    session.flush()
    return decision


def trim_agent(
    session: Session,
    connector: Connector,
    agent: Agent,
    actor: str,
    now: datetime,
    observation_days: int,
    confirm_revoke: bool = False,
    reason: str = "",
) -> Decision:
    rec = recommend(session, agent, now, observation_days)
    if rec.state in (AgentState.learning, AgentState.exempt, AgentState.suspended):
        raise NothingToChange(f"agent is {rec.state.value}; nothing to trim")
    plans = {p.user_email: p for p in rec.changes}
    if not plans:
        raise NothingToChange("every permission this agent holds is in use")

    changes: list[_Change] = []
    for grant, user in _grants_with_users(session, agent):
        plan = plans.get(user.email)
        if plan is None:
            continue
        after = list(plan.keep)
        if after and not connector.capabilities.narrow_scopes:
            if not confirm_revoke:
                raise NeedsConfirmation(
                    f"{connector.provider} cannot narrow permissions in place; trimming will revoke access "
                    "and the owner must reconnect with fewer permissions. Confirm to continue."
                )
            after = []
        changes.append(_Change(grant, user.email, list(grant.scopes), after))

    removed = sum(len(set(c.before) - set(c.after)) for c in changes)
    why = reason or f"removed {removed} unused permission(s) across {len(changes)} user(s)"
    return _apply(session, connector, agent, changes, DecisionAction.trim, actor, why, now)


def suspend_agent(
    session: Session, connector: Connector, agent: Agent, actor: str, now: datetime, reason: str = ""
) -> Decision:
    if agent.status is AgentStatus.suspended:
        raise NothingToChange("agent is already suspended")
    changes = [_Change(g, u.email, list(g.scopes), []) for g, u in _grants_with_users(session, agent)]
    if not changes:
        raise NothingToChange("agent holds no active access")
    decision = _apply(
        session,
        connector,
        agent,
        changes,
        DecisionAction.suspend,
        actor,
        reason or "suspended: all access removed",
        now,
    )
    agent.status = AgentStatus.suspended
    return decision


def undo(session: Session, connector: Connector, decision: Decision, actor: str, now: datetime) -> Decision:
    if decision.undone_at is not None:
        raise NotUndoable("this decision was already undone")
    if decision.action in (DecisionAction.restore, DecisionAction.expire):
        raise NotUndoable("restorations and expiries cannot be undone; make a new decision instead")
    if not connector.capabilities.restore:
        raise NotUndoable(f"{connector.provider} cannot restore access on its own; ask the owner to reconnect the app")
    agent = decision.agent
    by_email = {u.email: (g, u) for g, u in _grants_with_users(session, agent, active_only=False)}
    changes: list[_Change] = []
    for email, before_scopes in decision.before.items():
        current = decision.after.get(email, [])
        if email in by_email:
            grant = by_email[email][0]
            current = list(grant.scopes) if grant.active else []
        else:
            user = session.scalar(select(User).where(User.email == email))
            if user is None:
                continue
            grant = Grant(agent_id=agent.id, user_id=user.id, scopes=[], active=False)
            session.add(grant)
            session.flush()
        changes.append(_Change(grant, email, current, list(before_scopes)))

    restored = _apply(
        session,
        connector,
        agent,
        changes,
        DecisionAction.restore,
        actor,
        f"undo of decision #{decision.id}",
        now,
        undo_of=decision,
    )
    decision.undone_at = now
    if decision.action is DecisionAction.suspend:
        agent.status = AgentStatus.active
    return restored
