"""Permission requests: Allow once, Allow always, Deny.

"Allow once" grants the extra permissions for a time window and Trim removes
them again when it ends (``expire_due``), restoring the exact previous scopes.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from trim.connectors.base import Connector
from trim.models import (
    Agent,
    AgentStatus,
    Decision,
    DecisionAction,
    Grant,
    PermissionRequest,
    RequestStatus,
    User,
)
from trim.services.remediation import NotUndoable, RemediationError, _apply, _Change


class RequestChoice(StrEnum):
    allow_once = "allow_once"
    allow_always = "allow_always"
    deny = "deny"


class RequestError(RemediationError):
    code = "request_error"


def create_request(
    session: Session, agent: Agent, user_email: str, scopes: list[str], justification: str, now: datetime
) -> PermissionRequest:
    user = session.scalar(select(User).where(User.email == user_email.lower()))
    if user is None:
        raise RequestError("unknown user")
    if agent.status is AgentStatus.suspended:
        raise RequestError("agent is suspended")
    grant = session.scalar(select(Grant).where(Grant.agent_id == agent.id, Grant.user_id == user.id))
    current = set(grant.scopes) if grant and grant.active else set()
    missing = [s for s in dict.fromkeys(scopes) if s not in current]
    if not missing:
        raise RequestError("the agent already holds every requested permission")
    req = PermissionRequest(
        agent_id=agent.id, user_id=user.id, scopes=missing, justification=justification, created_at=now
    )
    session.add(req)
    session.flush()
    return req


def decide(
    session: Session,
    connector: Connector,
    req: PermissionRequest,
    choice: RequestChoice,
    actor: str,
    now: datetime,
    minutes: int,
) -> PermissionRequest:
    if req.status is not RequestStatus.pending:
        raise RequestError(f"request is already {req.status.value}")
    if choice is RequestChoice.deny:
        req.status, req.decided_by, req.decided_at = RequestStatus.denied, actor, now
        return req
    if not connector.capabilities.restore:
        raise NotUndoable(
            f"{connector.provider} cannot grant permissions on a user's behalf; the user must reconnect the app"
        )

    agent, user = req.agent, req.user
    grant = session.scalar(select(Grant).where(Grant.agent_id == agent.id, Grant.user_id == user.id))
    if grant is None:
        grant = Grant(agent_id=agent.id, user_id=user.id, scopes=[], active=False)
        session.add(grant)
        session.flush()
    before = list(grant.scopes) if grant.active else []
    after = list(dict.fromkeys(before + list(req.scopes)))
    once = choice is RequestChoice.allow_once
    decision = _apply(
        session,
        connector,
        agent,
        [_Change(grant, user.email, before, after)],
        DecisionAction.grant_once if once else DecisionAction.grant_always,
        actor,
        f"request #{req.id}: {'allowed once' if once else 'allowed always'}" + (f" for {minutes} min" if once else ""),
        now,
    )
    req.status = RequestStatus.approved_once if once else RequestStatus.approved_always
    req.decided_by, req.decided_at, req.decision_id = actor, now, decision.id
    req.expires_at = now + timedelta(minutes=minutes) if once else None
    return req


def expire_due(session: Session, connector: Connector, now: datetime) -> list[PermissionRequest]:
    """Remove "Allow once" permissions whose window has ended."""
    expired: list[PermissionRequest] = []
    due = session.scalars(
        select(PermissionRequest).where(
            PermissionRequest.status == RequestStatus.approved_once, PermissionRequest.expires_at <= now
        )
    )
    for req in list(due):
        grant = session.scalar(select(Grant).where(Grant.agent_id == req.agent_id, Grant.user_id == req.user_id))
        current = list(grant.scopes) if grant and grant.active else []
        after = [s for s in current if s not in req.scopes]
        source = session.get(Decision, req.decision_id) if req.decision_id else None
        if source is not None:
            source.undone_at = now  # the temporary grant is over
        if grant is not None and after != current:
            _apply(
                session,
                connector,
                req.agent,
                [_Change(grant, req.user.email, current, after)],
                DecisionAction.expire,
                "trim:scheduler",
                f"request #{req.id}: allow-once window ended",
                now,
                undo_of=source,
            )
        req.status = RequestStatus.expired
        expired.append(req)
    return expired
