"""Behaviour anomaly detection for agents.

For every agent and every day, Trim computes seven behaviour features, compares
them with that agent's own baseline (its first ``baseline_days`` of activity),
and scores the resulting deviation vector with an Isolation Forest trained on
the baseline days of all agents. Only increases are scored: an agent doing less
than usual is a dormancy question for the recommender, not a threat.

An alert needs both a high model score and at least one feature at 3 or more
standard deviations above baseline, so every alert carries a plain reason.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
from sklearn.ensemble import IsolationForest
from sqlalchemy import select
from sqlalchemy.orm import Session

from trim import scopes as sc
from trim.models import ActivityEvent, Agent, Alert

FEATURES = ("calls", "distinct_methods", "new_method_share", "bytes", "offhours_share", "users", "write_share")
# Minimum spread per feature so a perfectly regular baseline does not make every tiny change "infinite".
STD_FLOOR = {
    "calls": 0.35,
    "distinct_methods": 1.0,
    "new_method_share": 0.05,
    "bytes": 0.5,
    "offhours_share": 0.06,
    "users": 1.0,
    "write_share": 0.06,
}
Z_CAP = 20.0
REASON_Z = 3.0
WORK_HOURS = range(7, 20)  # UTC
MIN_TRAIN_ROWS = 30


@dataclass
class DayFeatures:
    raw: dict[str, float]
    vec: np.ndarray
    new_methods: list[str] = field(default_factory=list)


@dataclass
class DayScore:
    agent_id: int
    client_id: str
    day: date
    score: float
    flagged: bool
    reasons: list[dict]


@dataclass
class ScoreReport:
    scored_days: list[DayScore]
    alerts_created: int
    threshold: float
    mode: str  # "model" | "rules"


def _day_features(events: list[tuple], seen_before: set[str]) -> DayFeatures:
    calls = len(events)
    methods = [e[1] for e in events]
    new = [m for m in methods if m not in seen_before]
    raw = {
        "calls": float(calls),
        "distinct_methods": float(len(set(methods))),
        "new_method_share": len(new) / calls if calls else 0.0,
        "bytes": float(sum(e[2] for e in events)),
        "offhours_share": (sum(1 for e in events if e[3].hour not in WORK_HOURS) / calls) if calls else 0.0,
        "users": float(len({e[0] for e in events if e[0] is not None})),
        "write_share": (sum(1 for m in methods if sc.is_write_method(m)) / calls) if calls else 0.0,
    }
    vec = np.array(
        [
            math.log1p(raw["calls"]),
            raw["distinct_methods"],
            raw["new_method_share"],
            math.log1p(raw["bytes"]),
            raw["offhours_share"],
            raw["users"],
            raw["write_share"],
        ]
    )
    return DayFeatures(raw=raw, vec=vec, new_methods=sorted(set(new)))


def _reason(feature: str, z: float, today: dict[str, float], base: dict[str, float], new: list[str]) -> dict:
    def ratio(a: float, b: float) -> str:
        return f"{a / b:.0f}×" if b > 0 else "far"

    if feature == "calls":
        text = f"Made {int(today['calls'])} API calls, {ratio(today['calls'], base['calls'])} its usual volume"
    elif feature == "bytes":
        text = f"Downloaded {ratio(today['bytes'], base['bytes'])} more data than usual"
    elif feature == "new_method_share":
        shown = ", ".join(new[:3]) + ("…" if len(new) > 3 else "")
        text = f"Used {len(new)} API method(s) it had never used before: {shown}"
    elif feature == "distinct_methods":
        text = f"Used {int(today['distinct_methods'])} different methods (usually {base['distinct_methods']:.0f})"
    elif feature == "offhours_share":
        text = f"{today['offhours_share']:.0%} of activity outside working hours (usually {base['offhours_share']:.0%})"
    elif feature == "users":
        text = f"Acted for {int(today['users'])} people (usually {base['users']:.0f})"
    else:
        text = f"{today['write_share']:.0%} of calls changed data (usually {base['write_share']:.0%})"
    return {"feature": feature, "z": round(float(z), 1), "text": text}


def score_agents(
    session: Session, now: datetime, baseline_days: int, persist: bool = True, threshold_quantile: float = 0.99
) -> ScoreReport:
    rows = session.execute(
        select(
            ActivityEvent.agent_id,
            ActivityEvent.user_id,
            ActivityEvent.method_name,
            ActivityEvent.response_bytes,
            ActivityEvent.occurred_at,
        )
        .where(ActivityEvent.occurred_at < now)
        .order_by(ActivityEvent.agent_id, ActivityEvent.occurred_at)
    )
    by_agent_day: dict[int, dict[date, list[tuple]]] = defaultdict(lambda: defaultdict(list))
    for agent_id, user_id, method, nbytes, ts in rows:
        by_agent_day[agent_id][ts.date()].append((user_id, method, nbytes, ts))

    agents = {a.id: a for a in session.scalars(select(Agent))}
    last_day = (now - timedelta(seconds=1)).date()

    train: list[np.ndarray] = []
    to_score: list[tuple[int, date, DayFeatures, np.ndarray, dict[str, float]]] = []
    for agent_id, days in by_agent_day.items():
        first = min(days)
        base_end = first + timedelta(days=baseline_days)
        if last_day < base_end:
            continue  # still learning its baseline
        seen: set[str] = set()
        base_feats: list[DayFeatures] = []
        later: list[tuple[date, DayFeatures]] = []
        d = first
        while d <= last_day:
            evs = days.get(d, [])
            f = _day_features(evs, seen)
            if d < base_end:
                base_feats.append(f)
            else:
                later.append((d, f))
            seen.update(e[1] for e in evs)
            d += timedelta(days=1)
        # On an agent's first day every method is "new"; that is discovery, not behaviour.
        base_feats[0].vec[FEATURES.index("new_method_share")] = 0.0
        base_feats[0].raw["new_method_share"] = 0.0
        mat = np.vstack([f.vec for f in base_feats])
        mean = mat.mean(axis=0)
        std = np.maximum(mat.std(axis=0), np.array([STD_FLOOR[k] for k in FEATURES]))
        raw_mean = {k: float(np.mean([f.raw[k] for f in base_feats])) for k in FEATURES}

        def z_of(f: DayFeatures, mean=mean, std=std) -> np.ndarray:
            return np.clip((f.vec - mean) / std, 0.0, Z_CAP)

        train.extend(z_of(f) for f in base_feats)
        for day, f in later:
            to_score.append((agent_id, day, f, z_of(f), raw_mean))

    if not to_score:
        return ScoreReport([], 0, float("nan"), "rules")

    X = np.vstack([t[3] for t in to_score])
    if len(train) >= MIN_TRAIN_ROWS:
        model = IsolationForest(n_estimators=200, random_state=0)
        Xtrain = np.vstack(train)
        model.fit(Xtrain)
        threshold = float(np.quantile(-model.score_samples(Xtrain), threshold_quantile))
        scores = -model.score_samples(X)
        mode = "model"
    else:
        threshold = REASON_Z + 1
        scores = X.max(axis=1)
        mode = "rules"

    results: list[DayScore] = []
    created = 0
    for (agent_id, day, f, z, base), score in zip(to_score, scores, strict=True):
        strong = [(FEATURES[i], z[i]) for i in np.argsort(-z) if z[i] >= REASON_Z]
        flagged = bool(score > threshold and strong)
        reasons = [_reason(k, v, f.raw, base, f.new_methods) for k, v in strong] if flagged else []
        results.append(
            DayScore(
                agent_id,
                agents[agent_id].client_id if agent_id in agents else str(agent_id),
                day,
                float(score),
                flagged,
                reasons,
            )
        )
        if flagged and persist:
            existing = session.scalar(select(Alert).where(Alert.agent_id == agent_id, Alert.day == day))
            if existing is None:
                session.add(Alert(agent_id=agent_id, day=day, score=float(score), reasons=reasons, created_at=now))
                created += 1
            else:
                existing.score, existing.reasons = float(score), reasons
    if persist:
        session.flush()
    return ScoreReport(results, created, threshold, mode)
