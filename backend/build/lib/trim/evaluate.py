"""Measures the recommender and the anomaly model against the simulator's ground truth.

Run: ``trim evaluate --seeds 1 2 3 4 5``. Results are reported per seed and
averaged, so the report can show variance rather than one lucky run.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from sqlalchemy import select

from trim.connectors.simulated import SimulatedConnector
from trim.db import Database
from trim.models import Agent
from trim.services.anomaly import score_agents
from trim.services.recommender import recommend
from trim.services.sync import SyncReport, run_sync, sync_inventory
from trim.simulator import build_scenario, load_into


@dataclass
class Metrics:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def as_dict(self) -> dict:
        return {
            **asdict(self),
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
        }


@dataclass
class EvalResult:
    seed: int
    removal: Metrics
    anomaly: Metrics
    anomaly_by_kind: dict[str, dict[str, int]]
    agents: int
    events: int
    granted_permissions: int
    removable_permissions: int
    mode: str


def evaluate_seed(seed: int, observation_days: int = 14, baseline_days: int = 14) -> EvalResult:
    scenario = build_scenario(seed=seed, baseline_days=baseline_days)
    connector = SimulatedConnector()
    load_into(scenario, connector)
    db = Database("sqlite://")
    db.create_all()
    now = scenario.now

    # Trim is connected on day one: the inventory is discovered then, activity accrues after.
    with db.session() as s:
        sync_inventory(s, connector, scenario.start, SyncReport())
    with db.session() as s:
        run_sync(s, connector, now, retention_days=365)
    with db.session() as s:
        report = score_agents(s, now, baseline_days, persist=True)

    removal = Metrics()
    granted_total = removable_total = 0
    with db.session() as s:
        for agent in s.scalars(select(Agent)):
            rec = recommend(s, agent, now, observation_days)
            needed = scenario.needed_scopes(agent.client_id)
            for plan in rec.grants:
                granted = set(plan.granted)
                should_remove = granted - needed
                removed = granted - set(plan.keep)
                granted_total += len(granted)
                removable_total += len(removed)
                removal.tp += len(removed & should_remove)
                removal.fp += len(removed - should_remove)
                removal.fn += len(should_remove - removed)

    anomaly = Metrics()
    truth = scenario.anomalous_days
    kind_of = {(i.client_id, d): i.kind for i in scenario.incidents for d in i.days}
    by_kind: dict[str, dict[str, int]] = {}
    flagged = {(r.client_id, r.day) for r in report.scored_days if r.flagged}
    scored = {(r.client_id, r.day) for r in report.scored_days}
    for key in scored:
        is_true, is_flag = key in truth, key in flagged
        if is_true and is_flag:
            anomaly.tp += 1
        elif is_flag:
            anomaly.fp += 1
        elif is_true:
            anomaly.fn += 1
        if is_true:
            k = by_kind.setdefault(kind_of[key], {"detected": 0, "total": 0})
            k["total"] += 1
            k["detected"] += int(is_flag)

    return EvalResult(
        seed,
        removal,
        anomaly,
        by_kind,
        len(scenario.agents),
        len(scenario.events),
        granted_total,
        removable_total,
        report.mode,
    )


def evaluate(seeds: list[int]) -> dict:
    results = [evaluate_seed(s) for s in seeds]
    total_removal, total_anomaly = Metrics(), Metrics()
    kinds: dict[str, dict[str, int]] = {}
    for r in results:
        for m, t in ((r.removal, total_removal), (r.anomaly, total_anomaly)):
            t.tp, t.fp, t.fn = t.tp + m.tp, t.fp + m.fp, t.fn + m.fn
        for k, v in r.anomaly_by_kind.items():
            agg = kinds.setdefault(k, {"detected": 0, "total": 0})
            agg["detected"] += v["detected"]
            agg["total"] += v["total"]
    return {
        "seeds": seeds,
        "per_seed": [
            {
                "seed": r.seed,
                "agents": r.agents,
                "events": r.events,
                "granted_permissions": r.granted_permissions,
                "removed_permissions": r.removable_permissions,
                "removal": r.removal.as_dict(),
                "anomaly": r.anomaly.as_dict(),
                "mode": r.mode,
            }
            for r in results
        ],
        "removal": total_removal.as_dict(),
        "anomaly": total_anomaly.as_dict(),
        "anomaly_recall_by_attack": kinds,
    }
