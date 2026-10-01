from datetime import timedelta

import pytest
from sqlalchemy import func, select

from tests.conftest import MAIL_FULL, NOW, START, build_world
from trim.connectors.base import ActivityRecord, Capabilities, ConnectorError
from trim.connectors.simulated import SimulatedConnector
from trim.models import ActivityEvent, Agent, AgentStatus, Alert, AlertStatus, Decision, Grant, RequestStatus
from trim.scopes import GOOGLE_PREFIX as G
from trim.services import remediation
from trim.services import requests as rq
from trim.services.recommender import AgentState, recommend
from trim.services.sync import run_sync


def agent(s, client_id) -> Agent:
    return s.scalar(select(Agent).where(Agent.client_id == client_id))


# ---- sync -------------------------------------------------------------------


def test_sync_is_idempotent_and_tracks_cursor(world):
    with world.db.session() as s:
        before = s.scalar(select(func.count(ActivityEvent.id)))
        report = run_sync(s, world.connector, NOW, retention_days=365)
        assert report.events_new == 0
        assert s.scalar(select(func.count(ActivityEvent.id))) == before == 180
        assert agent(s, "mailbot").first_seen == START.replace(hour=9)  # earliest activity wins


def test_sync_marks_removed_grants_and_prunes_old_activity(world):
    world.connector.revoke("bob@acme.eu", "mailbot")
    with world.db.session() as s:
        report = run_sync(s, world.connector, NOW, retention_days=5)
        assert report.grants_removed == 1
        assert report.events_pruned > 0
        oldest = s.scalar(select(func.min(ActivityEvent.occurred_at)))
        assert oldest >= NOW - timedelta(days=5)


def test_sync_creates_agents_seen_only_in_activity(world):
    world.connector.add_activity(
        [ActivityRecord("new1", "ghost", "Ghost", None, "drive", "drive.files.list", 1, NOW - timedelta(hours=1))]
    )
    with world.db.session() as s:
        report = run_sync(s, world.connector, NOW, 365)
        assert report.agents_new == 1 and agent(s, "ghost").name == "Ghost"


# ---- recommender ------------------------------------------------------------


def test_recommendation_narrows_and_revokes_unused_users(world):
    with world.db.session() as s:
        rec = recommend(s, agent(s, "mailbot"), NOW, 14)
        assert rec.state is AgentState.ready
        plans = {p.user_email: p for p in rec.grants}
        assert set(plans["alice@acme.eu"].keep) == {"openid", G + "gmail.readonly", G + "gmail.send"}
        assert set(plans["bob@acme.eu"].keep) == {"openid", G + "gmail.readonly"}
        assert rec.scope_status[MAIL_FULL] == "narrowed" and rec.scope_status[G + "calendar"] == "unused"
        assert rec.calls == 14 * 9 or rec.calls > 0


def test_dormant_agent_loses_everything(world):
    with world.db.session() as s:
        rec = recommend(s, agent(s, "idle"), NOW, 14)
        assert rec.dormant and rec.state is AgentState.ready
        assert rec.grants[0].keep == [] and rec.unused_scopes == [G + "drive"]


def test_new_agent_is_learning(world):
    with world.db.session() as s:
        rec = recommend(s, agent(s, "mailbot"), START + timedelta(days=3), 14)
        assert rec.state is AgentState.learning and rec.learning_until is not None
        assert not rec.changes and all(v == "learning" for v in rec.scope_status.values())


def test_exempt_and_suspended_states(world):
    with world.db.session() as s:
        a = agent(s, "mailbot")
        a.exempt = True
        assert recommend(s, a, NOW, 14).state is AgentState.exempt
        a.exempt, a.status = False, AgentStatus.suspended
        assert recommend(s, a, NOW, 14).state is AgentState.suspended


def test_alerted_days_do_not_justify_permissions(world):
    # Bob's agent "deletes" mail on one day; with an open alert that day is ignored.
    day = NOW - timedelta(days=2)
    world.connector.add_activity(
        [ActivityRecord("x1", "mailbot", "Mail Bot", "bob@acme.eu", "gmail", "gmail.users.messages.delete", 1, day)]
    )
    with world.db.session() as s:
        run_sync(s, world.connector, NOW, 365)
        a = agent(s, "mailbot")
        bob = {p.user_email: p for p in recommend(s, a, NOW, 14).grants}["bob@acme.eu"]
        assert MAIL_FULL in bob.keep
        s.add(Alert(agent_id=a.id, day=day.date(), score=1.0, reasons=[]))
        s.flush()
        bob = {p.user_email: p for p in recommend(s, a, NOW, 14).grants}["bob@acme.eu"]
        assert MAIL_FULL not in bob.keep and day.date() in recommend(s, a, NOW, 14).excluded_days
        s.scalar(select(Alert)).status = AlertStatus.dismissed  # reviewer says benign: counts again
        assert MAIL_FULL in {p.user_email: p for p in recommend(s, a, NOW, 14).grants}["bob@acme.eu"].keep


# ---- remediation ------------------------------------------------------------


def test_trim_then_undo_restores_exact_state(world):
    original = {(g.user_email, g.client_id): g.scopes for g in world.connector.list_grants()}
    with world.db.session() as s:
        a = agent(s, "mailbot")
        d = remediation.trim_agent(s, world.connector, a, "ana", NOW, 14)
        assert d.before["alice@acme.eu"] == ["openid", MAIL_FULL, G + "calendar"]
        assert MAIL_FULL not in d.after["alice@acme.eu"]
        provider = {(g.user_email, g.client_id): g.scopes for g in world.connector.list_grants()}
        assert set(provider[("alice@acme.eu", "mailbot")]) == {"openid", G + "gmail.readonly", G + "gmail.send"}
        assert recommend(s, a, NOW, 14).state is AgentState.trimmed
        with pytest.raises(remediation.NothingToChange):
            remediation.trim_agent(s, world.connector, a, "ana", NOW, 14)

        restored = remediation.undo(s, world.connector, d, "ana", NOW)
        assert restored.undo_of_id == d.id and d.undone_at == NOW
        assert {(g.user_email, g.client_id): g.scopes for g in world.connector.list_grants()} == original
        with pytest.raises(remediation.NotUndoable):
            remediation.undo(s, world.connector, d, "ana", NOW)
        with pytest.raises(remediation.NotUndoable):
            remediation.undo(s, world.connector, restored, "ana", NOW)


def test_trim_revokes_dormant_grant_and_undo_recreates_it(world):
    with world.db.session() as s:
        d = remediation.trim_agent(s, world.connector, agent(s, "idle"), "ana", NOW, 14)
        assert d.after == {"carol@acme.eu": []}
        assert not any(g.client_id == "idle" for g in world.connector.list_grants())
        remediation.undo(s, world.connector, d, "ana", NOW)
        assert any(g.client_id == "idle" for g in world.connector.list_grants())
        grant = s.scalar(select(Grant).where(Grant.agent_id == agent(s, "idle").id))
        assert grant.active and grant.scopes == [G + "drive"]


def test_provider_failure_rolls_back_everything(world):
    original = sorted((g.user_email, g.scopes) for g in world.connector.list_grants())
    with world.db.session() as s:
        a = agent(s, "mailbot")
        snapshot = world.connector.snapshot()
        # Fail on the second grant: the first must be put back.
        calls = {"n": 0}
        real = world.connector.set_scopes

        def flaky(email, client, scopes):
            calls["n"] += 1
            if calls["n"] == 2:
                raise ConnectorError("boom")
            real(email, client, scopes)

        world.connector.set_scopes = flaky
        with pytest.raises(remediation.ProviderFailure):
            remediation.trim_agent(s, world.connector, a, "ana", NOW, 14)
        assert s.scalar(select(func.count(Decision.id))) == 0
    assert sorted((g.user_email, g.scopes) for g in world.connector.list_grants()) == original
    assert snapshot["grants"] == world.connector.snapshot()["grants"]


class RevokeOnly(SimulatedConnector):
    """Behaves like Google: can revoke, cannot narrow or restore."""

    provider = "google-like"
    capabilities = Capabilities(narrow_scopes=False, restore=False)

    def set_scopes(self, user_email, client_id, scopes):
        if scopes:
            raise ConnectorError("cannot narrow")
        super().set_scopes(user_email, client_id, scopes)


def _world_with(connector_cls):
    w = build_world()
    c = connector_cls()
    c.reset()
    with c.edit() as state, w.connector.edit() as src:
        state.update(src)
    w.connector = c
    return w


def test_revoke_only_provider_requires_confirmation():
    w = _world_with(RevokeOnly)
    with w.db.session() as s:
        a = agent(s, "mailbot")
        with pytest.raises(remediation.NeedsConfirmation):
            remediation.trim_agent(s, w.connector, a, "ana", NOW, 14)
        d = remediation.trim_agent(s, w.connector, a, "ana", NOW, 14, confirm_revoke=True)
        assert all(v == [] for v in d.after.values())
        with pytest.raises(remediation.NotUndoable):
            remediation.undo(s, w.connector, d, "ana", NOW)


def test_revoke_only_partial_failure_is_recorded_honestly():
    w = _world_with(RevokeOnly)
    with w.db.session() as s:
        w.connector.revoke
        a = agent(s, "mailbot")
        real = w.connector.set_scopes
        calls = {"n": 0}

        def flaky(email, client, scopes):
            calls["n"] += 1
            if calls["n"] == 2:
                raise ConnectorError("boom")
            real(email, client, scopes)

        w.connector.set_scopes = flaky
        with pytest.raises(remediation.PartialFailure) as exc:
            remediation.trim_agent(s, w.connector, a, "ana", NOW, 14, confirm_revoke=True)
        d = s.get(Decision, exc.value.decision_id)
        assert len(d.after) == 1 and "partial" in d.reason


def test_suspend_and_undo(world):
    with world.db.session() as s:
        a = agent(s, "mailbot")
        d = remediation.suspend_agent(s, world.connector, a, "ana", NOW)
        assert a.status is AgentStatus.suspended
        assert not any(g.client_id == "mailbot" for g in world.connector.list_grants())
        with pytest.raises(remediation.NothingToChange):
            remediation.suspend_agent(s, world.connector, a, "ana", NOW)
        with pytest.raises(remediation.NothingToChange):
            remediation.trim_agent(s, world.connector, a, "ana", NOW, 14)
        remediation.undo(s, world.connector, d, "ana", NOW)
        assert a.status is AgentStatus.active
        assert sum(g.client_id == "mailbot" for g in world.connector.list_grants()) == 2


# ---- permission requests ------------------------------------------------------


def test_allow_once_expires_and_restores(world):
    with world.db.session() as s:
        a = agent(s, "mailbot")
        req = rq.create_request(s, a, "bob@acme.eu", [G + "drive.readonly", "openid"], "attach files", NOW)
        assert req.scopes == [G + "drive.readonly"]  # already-held scopes are dropped
        rq.decide(s, world.connector, req, rq.RequestChoice.allow_once, "ana", NOW, 30)
        assert req.status is RequestStatus.approved_once and req.expires_at == NOW + timedelta(minutes=30)
        bob = {g.user_email: g for g in world.connector.list_grants() if g.client_id == "mailbot"}["bob@acme.eu"]
        assert G + "drive.readonly" in bob.scopes

        assert rq.expire_due(s, world.connector, NOW + timedelta(minutes=10)) == []
        expired = rq.expire_due(s, world.connector, NOW + timedelta(minutes=31))
        assert [r.id for r in expired] == [req.id] and req.status is RequestStatus.expired
        bob = {g.user_email: g for g in world.connector.list_grants() if g.client_id == "mailbot"}["bob@acme.eu"]
        assert G + "drive.readonly" not in bob.scopes
        with pytest.raises(rq.RequestError):
            rq.decide(s, world.connector, req, rq.RequestChoice.deny, "ana", NOW, 30)


def test_allow_always_and_deny(world):
    with world.db.session() as s:
        a = agent(s, "idle")
        r1 = rq.create_request(s, a, "carol@acme.eu", [G + "calendar.readonly"], "", NOW)
        rq.decide(s, world.connector, r1, rq.RequestChoice.allow_always, "ana", NOW, 30)
        assert r1.expires_at is None and r1.status is RequestStatus.approved_always
        r2 = rq.create_request(s, a, "carol@acme.eu", [G + "gmail.send"], "", NOW)
        rq.decide(s, world.connector, r2, rq.RequestChoice.deny, "ana", NOW, 30)
        assert r2.status is RequestStatus.denied
        carol = next(g for g in world.connector.list_grants() if g.client_id == "idle")
        assert G + "calendar.readonly" in carol.scopes and G + "gmail.send" not in carol.scopes


def test_request_validation(world):
    with world.db.session() as s:
        a = agent(s, "mailbot")
        with pytest.raises(rq.RequestError):
            rq.create_request(s, a, "nobody@acme.eu", ["openid"], "", NOW)
        with pytest.raises(rq.RequestError):
            rq.create_request(s, a, "alice@acme.eu", ["openid"], "", NOW)
        a.status = AgentStatus.suspended
        with pytest.raises(rq.RequestError):
            rq.create_request(s, a, "alice@acme.eu", [G + "drive"], "", NOW)


def test_requests_on_revoke_only_provider_are_refused():
    w = _world_with(RevokeOnly)
    with w.db.session() as s:
        req = rq.create_request(s, agent(s, "mailbot"), "bob@acme.eu", [G + "drive"], "", NOW)
        with pytest.raises(remediation.NotUndoable):
            rq.decide(s, w.connector, req, rq.RequestChoice.allow_always, "ana", NOW, 30)
