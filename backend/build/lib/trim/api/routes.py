"""REST API, mounted at /api/v1."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from trim import __version__
from trim import scopes as sc
from trim.api import schemas as s
from trim.api import views
from trim.api.deps import AppContext, admins, ctx, now, principal, readers, session, submitters
from trim.auth import Principal
from trim.models import (
    Agent,
    Alert,
    AlertStatus,
    Decision,
    Grant,
    PermissionRequest,
    RequestStatus,
    SyncCursor,
    User,
)
from trim.services import remediation
from trim.services import requests as req_svc
from trim.services.pipeline import run_cycle
from trim.services.recommender import AgentState, recommend

router = APIRouter(prefix="/api/v1")


def _agent(session: Session, agent_id: int) -> Agent:
    agent = session.get(Agent, agent_id)
    if agent is None:
        raise HTTPException(404, "agent not found")
    return agent


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "version": __version__}


@router.get("/me", response_model=s.Me)
def me(p: Principal = Depends(principal)) -> s.Me:
    return s.Me(name=p.name, role=p.role.value, can_change_access=p.can_change_access())


@router.get("/summary", response_model=s.Summary, dependencies=[Depends(readers)])
def summary(db: Session = Depends(session), c: AppContext = Depends(ctx), t: datetime = Depends(now)):
    by_state: dict[str, int] = {st.value: 0 for st in AgentState}
    unused = granted = high = 0
    agents = list(db.scalars(select(Agent)))
    for a in agents:
        rec = recommend(db, a, t, c.settings.observation_days)
        by_state[rec.state.value] += 1
        unused += len(rec.unused_scopes)
        granted += len(rec.granted_scopes)
        high += int(views._risk(rec.granted_scopes) >= 3)
    cursor = db.get(SyncCursor, c.connector.provider)
    return s.Summary(
        agents=len(agents),
        users=db.scalar(select(func.count(User.id))) or 0,
        active_grants=db.scalar(select(func.count(Grant.id)).where(Grant.active.is_(True))) or 0,
        by_state=by_state,
        unused_permissions=unused,
        granted_permissions=granted,
        high_risk_agents=high,
        open_alerts=db.scalar(select(func.count(Alert.id)).where(Alert.status == AlertStatus.open)) or 0,
        pending_requests=db.scalar(
            select(func.count(PermissionRequest.id)).where(PermissionRequest.status == RequestStatus.pending)
        )
        or 0,
        last_sync=cursor.last_run_at if cursor else None,
        provider=c.connector.provider,
        can_narrow=c.connector.capabilities.narrow_scopes,
        can_restore=c.connector.capabilities.restore,
    )


@router.get("/capabilities", dependencies=[Depends(readers)])
def capabilities() -> list[dict]:
    return [{"key": k, "label": label} for k, (label, _) in sc.CAPABILITIES.items()]


@router.get("/agents", response_model=list[s.AgentSummary], dependencies=[Depends(readers)])
def list_agents(
    state: AgentState | None = None,
    q: str | None = Query(default=None, max_length=100),
    can: str | None = Query(default=None, max_length=40),
    db: Session = Depends(session),
    c: AppContext = Depends(ctx),
    t: datetime = Depends(now),
):
    if can is not None and can not in sc.CAPABILITIES:
        raise HTTPException(422, f"unknown capability '{can}'")
    out = []
    needle = q.lower() if q else None
    for a in db.scalars(select(Agent).order_by(Agent.name)):
        if needle and needle not in a.name.lower() and needle not in a.client_id.lower():
            continue
        rec = recommend(db, a, t, c.settings.observation_days)
        if state and rec.state is not state:
            continue
        if can and not sc.grants_capability(rec.granted_scopes, can):
            continue
        out.append(views.agent_summary(db, a, rec))
    out.sort(key=lambda x: (-x.open_alerts, -x.unused * x.risk, x.name))
    return out


@router.get("/agents/{agent_id}", response_model=s.AgentDetail, dependencies=[Depends(readers)])
def get_agent(agent_id: int, db: Session = Depends(session), c: AppContext = Depends(ctx), t: datetime = Depends(now)):
    return views.agent_detail(db, _agent(db, agent_id), t, c.settings.observation_days, c.connector.capabilities)


@router.post("/agents/{agent_id}/trim", response_model=s.DecisionView)
def trim(
    agent_id: int,
    body: s.TrimIn,
    db: Session = Depends(session),
    c: AppContext = Depends(ctx),
    t: datetime = Depends(now),
    p: Principal = Depends(admins),
):
    d = remediation.trim_agent(
        db,
        c.connector,
        _agent(db, agent_id),
        p.name,
        t,
        c.settings.observation_days,
        confirm_revoke=body.confirm_revoke,
        reason=body.reason,
    )
    return views.decision_view(d, c.connector.capabilities)


@router.post("/agents/trim-all")
def trim_all(
    body: s.TrimIn,
    db: Session = Depends(session),
    c: AppContext = Depends(ctx),
    t: datetime = Depends(now),
    p: Principal = Depends(admins),
) -> dict:
    trimmed, skipped = [], []
    for a in db.scalars(select(Agent).order_by(Agent.id)):
        if recommend(db, a, t, c.settings.observation_days).state is not AgentState.ready:
            continue
        try:
            # Services raise before touching the database unless a change really happened,
            # so one failing agent never leaves another half-trimmed.
            d = remediation.trim_agent(
                db,
                c.connector,
                a,
                p.name,
                t,
                c.settings.observation_days,
                confirm_revoke=body.confirm_revoke,
                reason=body.reason,
            )
            trimmed.append({"agent_id": a.id, "decision_id": d.id})
        except remediation.RemediationError as exc:
            skipped.append({"agent_id": a.id, "error": exc.code, "detail": str(exc)})
    return {"trimmed": trimmed, "skipped": skipped}


@router.post("/agents/{agent_id}/suspend", response_model=s.DecisionView)
def suspend(
    agent_id: int,
    body: s.SuspendIn,
    db: Session = Depends(session),
    c: AppContext = Depends(ctx),
    t: datetime = Depends(now),
    p: Principal = Depends(admins),
):
    d = remediation.suspend_agent(db, c.connector, _agent(db, agent_id), p.name, t, body.reason)
    c.notifier.send(f"Trim: {d.agent.name} was suspended by {p.name}")
    return views.decision_view(d, c.connector.capabilities)


@router.post("/agents/{agent_id}/exempt", dependencies=[Depends(admins)])
def exempt(agent_id: int, body: s.ExemptIn, db: Session = Depends(session)) -> dict:
    agent = _agent(db, agent_id)
    agent.exempt = body.exempt
    return {"id": agent.id, "exempt": agent.exempt}


@router.get("/decisions", response_model=list[s.DecisionView], dependencies=[Depends(readers)])
def list_decisions(
    agent_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(session),
    c: AppContext = Depends(ctx),
):
    q = select(Decision).order_by(Decision.created_at.desc(), Decision.id.desc()).limit(limit)
    if agent_id is not None:
        q = q.where(Decision.agent_id == agent_id)
    return [views.decision_view(d, c.connector.capabilities) for d in db.scalars(q)]


@router.post("/decisions/{decision_id}/undo", response_model=s.DecisionView)
def undo(
    decision_id: int,
    db: Session = Depends(session),
    c: AppContext = Depends(ctx),
    t: datetime = Depends(now),
    p: Principal = Depends(admins),
):
    d = db.get(Decision, decision_id)
    if d is None:
        raise HTTPException(404, "decision not found")
    restored = remediation.undo(db, c.connector, d, p.name, t)
    return views.decision_view(restored, c.connector.capabilities)


@router.get("/alerts", response_model=list[s.AlertView], dependencies=[Depends(readers)])
def list_alerts(
    status: AlertStatus | None = None, limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(session)
):
    q = select(Alert).order_by(Alert.day.desc(), Alert.score.desc()).limit(limit)
    if status is not None:
        q = q.where(Alert.status == status)
    return [views.alert_view(a) for a in db.scalars(q)]


@router.post("/alerts/{alert_id}/review", response_model=s.AlertView, dependencies=[Depends(readers)])
def review_alert(alert_id: int, body: s.AlertReviewIn, db: Session = Depends(session)):
    a = db.get(Alert, alert_id)
    if a is None:
        raise HTTPException(404, "alert not found")
    a.status = AlertStatus(body.status)
    return views.alert_view(a)


@router.get("/requests", response_model=list[s.RequestView], dependencies=[Depends(readers)])
def list_requests(status: RequestStatus | None = None, db: Session = Depends(session)):
    q = select(PermissionRequest).order_by(PermissionRequest.created_at.desc()).limit(200)
    if status is not None:
        q = q.where(PermissionRequest.status == status)
    return [views.request_view(r) for r in db.scalars(q)]


@router.post("/requests", response_model=s.RequestView, status_code=201)
def create_request(
    body: s.RequestIn,
    db: Session = Depends(session),
    c: AppContext = Depends(ctx),
    t: datetime = Depends(now),
    p: Principal = Depends(submitters),
):
    agent = db.scalar(select(Agent).where(Agent.client_id == body.client_id))
    if agent is None:
        raise HTTPException(404, "agent not found")
    r = req_svc.create_request(db, agent, body.user_email, body.scopes, body.justification, t)
    c.notifier.send(f"Trim: {agent.name} asks for new access for {body.user_email}. Review in Trim.")
    return views.request_view(r)


@router.post("/requests/{request_id}/decide", response_model=s.RequestView)
def decide(
    request_id: int,
    body: s.DecideIn,
    db: Session = Depends(session),
    c: AppContext = Depends(ctx),
    t: datetime = Depends(now),
    p: Principal = Depends(admins),
):
    r = db.get(PermissionRequest, request_id)
    if r is None:
        raise HTTPException(404, "request not found")
    minutes = body.minutes or c.settings.allow_once_default_minutes
    req_svc.decide(db, c.connector, r, req_svc.RequestChoice(body.choice), p.name, t, minutes)
    return views.request_view(r)


@router.post("/sync", dependencies=[Depends(admins)])
def sync(db: Session = Depends(session), c: AppContext = Depends(ctx), t: datetime = Depends(now)) -> dict:
    report = run_cycle(
        db,
        c.connector,
        t,
        c.settings.activity_retention_days,
        c.settings.baseline_days,
        c.notifier,
        c.settings.activity_lookback_hours,
    )
    return report.__dict__
