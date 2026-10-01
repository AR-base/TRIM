"""One full cycle: sync from the provider, expire temporary grants, score behaviour, notify."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from trim.connectors.base import Connector
from trim.models import Agent
from trim.services.anomaly import score_agents
from trim.services.notify import Notifier
from trim.services.requests import expire_due
from trim.services.sync import SyncReport, run_sync


@dataclass
class CycleReport:
    sync: dict
    expired_requests: int
    alerts_created: int
    anomaly_mode: str


def run_cycle(
    session: Session,
    connector: Connector,
    now: datetime,
    retention_days: int,
    baseline_days: int,
    notifier: Notifier | None = None,
    lookback_hours: int = 72,
) -> CycleReport:
    report: SyncReport = run_sync(session, connector, now, retention_days, lookback_hours)
    expired = expire_due(session, connector, now)
    scores = score_agents(session, now, baseline_days)
    if notifier and scores.alerts_created:
        flagged = [d for d in scores.scored_days if d.flagged]
        for d in flagged[-scores.alerts_created :]:
            agent = session.get(Agent, d.agent_id)
            first = d.reasons[0]["text"] if d.reasons else "unusual behaviour"
            notifier.send(f"Trim alert: {agent.name if agent else d.client_id} on {d.day}: {first}")
    return CycleReport(asdict(report), len(expired), scores.alerts_created, scores.mode)
