from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from tests.conftest import fresh_db
from trim.connectors.simulated import SimulatedConnector
from trim.evaluate import Metrics, evaluate, evaluate_seed
from trim.models import Alert
from trim.services.anomaly import score_agents
from trim.services.sync import SyncReport, run_sync, sync_inventory
from trim.simulator import ARCHETYPES, build_scenario, load_into


@pytest.fixture(scope="module")
def scenario():
    return build_scenario(seed=11, n_users=24, days=24, baseline_days=14, incidents=8)


@pytest.fixture
def loaded(scenario):
    conn = SimulatedConnector()
    load_into(scenario, conn)
    db = fresh_db()
    with db.session() as s:
        sync_inventory(s, conn, scenario.start, SyncReport())
    with db.session() as s:
        run_sync(s, conn, scenario.now, 365)
    return db, conn


def test_simulator_is_deterministic_and_well_formed(scenario):
    again = build_scenario(seed=11, n_users=24, days=24, baseline_days=14, incidents=8)
    assert [e.uid for e in scenario.events[:50]] == [e.uid for e in again.events[:50]]
    assert len(scenario.events) == len(again.events)
    assert len({u[0] for u in scenario.users}) == 24
    assert len(scenario.agents) == sum(len(a.names) for a in ARCHETYPES)
    assert all(d >= scenario.start.date() + timedelta(days=14) for i in scenario.incidents for d in i.days)
    for a in ARCHETYPES:
        assert set(a.needed) <= set(a.granted) or a.key in {
            "inbox_copilot",
            "meeting_notes",
            "sales_reach",
            "devops_helper",
        }  # narrowed ones


def test_detects_injected_incidents_with_reasons(loaded, scenario):
    db, _ = loaded
    with db.session() as s:
        report = score_agents(s, scenario.now, 14)
        assert report.mode == "model"
        flagged = {(r.client_id, r.day) for r in report.scored_days if r.flagged}
        truth = scenario.anomalous_days
        assert len(flagged & truth) / len(truth) >= 0.6
        assert len(flagged & truth) / max(len(flagged), 1) >= 0.7
        alerts = list(s.scalars(select(Alert)))
        assert len(alerts) == report.alerts_created == len(flagged)
        assert all(a.reasons and a.reasons[0]["text"] for a in alerts)
        # Re-scoring updates instead of duplicating.
        assert score_agents(s, scenario.now, 14).alerts_created == 0
        assert s.scalar(select(func.count(Alert.id))) == len(alerts)


def test_agents_still_in_baseline_are_not_scored(loaded, scenario):
    db, _ = loaded
    with db.session() as s:
        report = score_agents(s, scenario.start + timedelta(days=10), 14, persist=False)
        assert report.scored_days == [] and report.alerts_created == 0


def test_rules_fallback_with_little_history():
    from trim.connectors.base import ActivityRecord

    conn = SimulatedConnector()
    conn.add_user("a@x.eu")
    conn.add_grant("solo", "Solo", "a@x.eu", ["openid"])
    start = datetime(2026, 9, 1, tzinfo=UTC)
    events = [
        ActivityRecord(
            f"e{d}-{i}", "solo", "Solo", "a@x.eu", "drive", "drive.files.get", 1000, start + timedelta(days=d, hours=10)
        )
        for d in range(5)
        for i in range(5)
    ]
    events += [
        ActivityRecord(
            f"x{i}",
            "solo",
            "Solo",
            "a@x.eu",
            "drive",
            "drive.files.export",
            900_000,
            start + timedelta(days=5, hours=3),
        )
        for i in range(60)
    ]
    conn.add_activity(events)
    db = fresh_db()
    with db.session() as s:
        run_sync(s, conn, start + timedelta(days=6), 365)
        report = score_agents(s, start + timedelta(days=6), 3)
        assert report.mode == "rules"
        hit = [r for r in report.scored_days if r.flagged]
        assert [r.day for r in hit] == [date(2026, 9, 6)]
        texts = " ".join(x["text"] for x in hit[0].reasons)
        assert "never used before" in texts and "outside working hours" in texts


def test_metrics_math():
    m = Metrics(tp=8, fp=2, fn=2)
    assert (m.precision, m.recall, round(m.f1, 2)) == (0.8, 0.8, 0.8)
    assert Metrics().precision == 1.0 and Metrics().recall == 1.0
    assert Metrics(tp=0, fp=1, fn=1).f1 == 0.0


def test_quality_gate_on_simulated_org():
    """Regression gate: the models must keep their measured quality."""
    r = evaluate_seed(5)
    assert r.removal.precision >= 0.99
    assert r.removal.recall >= 0.9
    assert r.anomaly.precision >= 0.8
    assert r.anomaly.recall >= 0.6
    summary = evaluate([5])
    assert summary["removal"]["precision"] == round(r.removal.precision, 3)
    assert set(summary["anomaly_recall_by_attack"]) <= {"exfiltration", "goal_hijack", "off_hours", "slow_creep"}
