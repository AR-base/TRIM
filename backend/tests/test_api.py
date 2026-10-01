from datetime import timedelta

import pytest

from tests.conftest import ADMIN, MAIL_FULL, REVIEWER, SERVICE, auth
from trim.config import Settings
from trim.connectors.simulated import SimulatedConnector
from trim.db import Database
from trim.main import create_app
from trim.models import Alert
from trim.scopes import GOOGLE_PREFIX as G

API = "/api/v1"


def agent_id(client, client_id):
    return next(a["id"] for a in client.get(f"{API}/agents", headers=auth()).json() if a["client_id"] == client_id)


# ---- security -----------------------------------------------------------------


def test_health_is_public_and_hardened(client):
    r = client.get(f"{API}/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"
    h = r.headers
    assert h["content-security-policy"].startswith("default-src 'none'")
    assert h["x-frame-options"] == "DENY" and h["x-content-type-options"] == "nosniff"
    assert h["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer nope"}, {"Authorization": "Basic YTpi"}, {"Authorization": f"Token {ADMIN}"}],
)
def test_requires_valid_bearer_token(client, headers):
    r = client.get(f"{API}/summary", headers=headers)
    assert r.status_code == 401 and r.headers["www-authenticate"] == "Bearer"
    assert r.json()["error"] == "http_401"


def test_roles_are_enforced(client):
    aid = agent_id(client, "mailbot")
    assert client.get(f"{API}/summary", headers=auth(REVIEWER)).status_code == 200
    assert client.post(f"{API}/agents/{aid}/trim", json={}, headers=auth(REVIEWER)).status_code == 403
    assert client.post(f"{API}/sync", headers=auth(REVIEWER)).status_code == 403
    assert client.get(f"{API}/agents", headers=auth(SERVICE)).status_code == 403
    me = client.get(f"{API}/me", headers=auth(REVIEWER)).json()
    assert me == {"name": "rev", "role": "reviewer", "can_change_access": False}


def test_validation_errors_do_not_echo_input(client):
    evil = "<script>alert(1)</script>"
    r = client.post(
        f"{API}/requests", json={"client_id": evil, "user_email": evil, "scopes": [evil]}, headers=auth(SERVICE)
    )
    assert r.status_code == 422 and r.json()["error"] == "invalid_request"
    assert "<script>" not in r.text
    r = client.post(f"{API}/agents/1/trim", json={"confirm_revoke": True, "extra": 1}, headers=auth())
    assert r.status_code == 422


def test_rejects_oversized_bodies(client):
    r = client.post(
        f"{API}/agents/1/trim",
        content=b"{" + b" " * 70_000 + b"}",
        headers={**auth(), "Content-Type": "application/json"},
    )
    assert r.status_code == 413


def test_docs_disabled_in_production(world):
    app = create_app(Settings(env="prod", api_tokens=""), db=world.db, connector=world.connector)
    from fastapi.testclient import TestClient

    c = TestClient(app)
    assert c.get("/api/docs").status_code == 404 and c.get("/api/openapi.json").status_code == 404


def test_unknown_capability_and_missing_resources(client):
    assert client.get(f"{API}/agents?can=hack", headers=auth()).status_code == 422
    assert client.get(f"{API}/agents/999", headers=auth()).status_code == 404
    assert client.post(f"{API}/decisions/999/undo", headers=auth()).status_code == 404
    assert client.post(f"{API}/alerts/999/review", json={"status": "dismissed"}, headers=auth()).status_code == 404
    assert client.post(f"{API}/requests/999/decide", json={"choice": "deny"}, headers=auth()).status_code == 404


# ---- product flows ------------------------------------------------------------


def test_summary_and_inventory(client):
    s = client.get(f"{API}/summary", headers=auth()).json()
    assert s["agents"] == 2 and s["users"] == 3 and s["by_state"]["ready"] == 2
    assert s["provider"] == "simulated" and s["can_restore"]
    agents = client.get(f"{API}/agents", headers=auth()).json()
    mail = next(a for a in agents if a["client_id"] == "mailbot")
    assert mail["reach"].startswith("Can read, send and permanently delete all email")
    assert mail["users"] == 2 and mail["risk"] == 3
    assert [a["name"] for a in client.get(f"{API}/agents?q=idle", headers=auth()).json()] == ["Idle Bot"]
    assert [a["client_id"] for a in client.get(f"{API}/agents?can=delete_email", headers=auth()).json()] == ["mailbot"]
    assert client.get(f"{API}/agents?state=learning", headers=auth()).json() == []
    assert any(c["key"] == "send_email" for c in client.get(f"{API}/capabilities", headers=auth()).json())


def test_agent_detail_explains_the_recommendation(client):
    d = client.get(f"{API}/agents/{agent_id(client, 'mailbot')}", headers=auth()).json()
    statuses = {x["short"]: x["status"] for x in d["scopes"]}
    assert statuses == {"mail.full": "narrowed", "calendar": "unused", "openid": "used"}
    mail = next(x for x in d["scopes"] if x["short"] == "mail.full")
    assert mail["narrowed_to"] == ["gmail.readonly", "gmail.send"]
    assert d["reach_after"] == "Can read all email and send email as the user, for 2 people."
    alice = next(g for g in d["grants"] if g["user_email"] == "alice@acme.eu")
    assert alice["reasons"]["gmail.send"] == ["gmail.users.messages.send"]
    assert len(d["activity"]) == 28 and sum(x["calls"] for x in d["activity"]) == 180
    assert d["can_narrow"] and d["can_restore"]


def test_trim_undo_flow_over_http(client, world):
    aid = agent_id(client, "mailbot")
    r = client.post(f"{API}/agents/{aid}/trim", json={"reason": "quarterly review"}, headers=auth())
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["action"] == "trim" and d["actor"] == "ana" and d["undoable"] and d["removed"] == 4
    assert client.post(f"{API}/agents/{aid}/trim", json={}, headers=auth()).json()["error"] == "nothing_to_change"
    assert client.get(f"{API}/agents/{aid}", headers=auth()).json()["state"] == "trimmed"
    u = client.post(f"{API}/decisions/{d['id']}/undo", headers=auth())
    assert u.status_code == 200 and u.json()["action"] == "restore" and u.json()["added"] == 4
    again = client.post(f"{API}/decisions/{d['id']}/undo", headers=auth())
    assert again.status_code == 409 and again.json()["error"] == "not_undoable"
    history = client.get(f"{API}/decisions", headers=auth()).json()
    assert [h["action"] for h in history] == ["restore", "trim"]
    assert client.get(f"{API}/decisions?agent_id={aid}&limit=1", headers=auth()).json()[0]["action"] == "restore"


def test_trim_all(client):
    r = client.post(f"{API}/agents/trim-all", json={}, headers=auth()).json()
    assert len(r["trimmed"]) == 2 and r["skipped"] == []
    assert client.get(f"{API}/summary", headers=auth()).json()["by_state"]["trimmed"] == 2


def test_provider_failure_is_reported_and_nothing_changes(client, world):
    world.connector.fail_next_calls(1)
    r = client.post(f"{API}/agents/{agent_id(client, 'mailbot')}/trim", json={}, headers=auth())
    assert r.status_code == 502 and r.json()["error"] == "provider_failure"
    assert client.get(f"{API}/decisions", headers=auth()).json() == []


def test_suspend_and_exempt(client, notifier):
    aid = agent_id(client, "mailbot")
    r = client.post(f"{API}/agents/{aid}/suspend", json={"reason": "hijacked"}, headers=auth())
    assert r.status_code == 200 and r.json()["action"] == "suspend"
    assert client.get(f"{API}/agents/{aid}", headers=auth()).json()["state"] == "suspended"
    assert any("suspended" in m for m in notifier.sent)
    assert client.post(f"{API}/agents/{aid}/suspend", json={}, headers=auth()).status_code == 409
    other = agent_id(client, "idle")
    assert client.post(f"{API}/agents/{other}/exempt", json={"exempt": True}, headers=auth()).json()["exempt"]
    assert client.get(f"{API}/agents/{other}", headers=auth()).json()["state"] == "exempt"


def test_permission_request_lifecycle(client, world, notifier):
    body = {
        "client_id": "mailbot",
        "user_email": "Bob@acme.eu",
        "scopes": [G + "drive.readonly"],
        "justification": "attach files",
    }
    r = client.post(f"{API}/requests", json=body, headers=auth(SERVICE))
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "pending" and req["user_email"] == "bob@acme.eu"
    assert req["phrases"] == ["read every Drive file"]
    assert any("asks for new access" in m for m in notifier.sent)
    assert client.get(f"{API}/requests?status=pending", headers=auth()).json()[0]["id"] == req["id"]
    assert (
        client.post(
            f"{API}/requests/{req['id']}/decide", json={"choice": "allow_once"}, headers=auth(SERVICE)
        ).status_code
        == 403
    )
    d = client.post(
        f"{API}/requests/{req['id']}/decide", json={"choice": "allow_once", "minutes": 15}, headers=auth()
    ).json()
    assert d["status"] == "approved_once" and d["expires_at"]
    world.now = world.now + timedelta(minutes=20)
    cycle = client.post(f"{API}/sync", headers=auth()).json()
    assert cycle["expired_requests"] == 1
    assert client.get(f"{API}/requests", headers=auth()).json()[0]["status"] == "expired"
    bad = client.post(f"{API}/requests", json={**body, "client_id": "nope"}, headers=auth(SERVICE))
    assert bad.status_code == 404
    held = client.post(f"{API}/requests", json={**body, "scopes": ["openid"]}, headers=auth(SERVICE))
    assert held.status_code == 409 and held.json()["error"] == "request_error"


def test_alert_review(client, world):
    with world.db.session() as s:
        s.add(
            Alert(
                agent_id=agent_id(client, "mailbot"),
                day=world.now.date(),
                score=0.9,
                reasons=[{"feature": "calls", "z": 5, "text": "Made 900 API calls"}],
            )
        )
    alerts = client.get(f"{API}/alerts?status=open", headers=auth(REVIEWER)).json()
    assert len(alerts) == 1 and alerts[0]["agent_name"] == "Mail Bot"
    r = client.post(f"{API}/alerts/{alerts[0]['id']}/review", json={"status": "dismissed"}, headers=auth(REVIEWER))
    assert r.json()["status"] == "dismissed"
    assert (
        client.post(f"{API}/alerts/{alerts[0]['id']}/review", json={"status": "open"}, headers=auth()).status_code
        == 422
    )


def test_sync_endpoint_runs_full_cycle(client):
    r = client.post(f"{API}/sync", headers=auth())
    assert r.status_code == 200
    body = r.json()
    assert body["sync"]["users"] == 3 and body["anomaly_mode"] in ("model", "rules")
    assert client.get(f"{API}/summary", headers=auth()).json()["last_sync"] is not None


def test_google_like_provider_needs_confirmation_over_http(settings):
    from tests.test_services import RevokeOnly, _world_with

    w = _world_with(RevokeOnly)
    from fastapi.testclient import TestClient

    c = TestClient(create_app(settings, db=w.db, connector=w.connector, clock=lambda: w.now))
    aid = agent_id(c, "mailbot")
    r = c.post(f"{API}/agents/{aid}/trim", json={}, headers=auth())
    assert r.status_code == 409 and r.json()["error"] == "needs_confirmation"
    r = c.post(f"{API}/agents/{aid}/trim", json={"confirm_revoke": True}, headers=auth())
    assert r.status_code == 200 and not r.json()["undoable"]
    assert c.post(f"{API}/decisions/{r.json()['id']}/undo", headers=auth()).status_code == 409


def test_partial_failure_returns_502_and_keeps_the_record(settings):
    from tests.test_services import RevokeOnly, _world_with

    w = _world_with(RevokeOnly)
    real = w.connector.set_scopes
    calls = {"n": 0}

    def flaky(email, client_id, scopes):
        calls["n"] += 1
        if calls["n"] == 2:
            from trim.connectors.base import ConnectorError

            raise ConnectorError("boom")
        real(email, client_id, scopes)

    w.connector.set_scopes = flaky
    from fastapi.testclient import TestClient

    c = TestClient(create_app(settings, db=w.db, connector=w.connector, clock=lambda: w.now))
    r = c.post(f"{API}/agents/{agent_id(c, 'mailbot')}/trim", json={"confirm_revoke": True}, headers=auth())
    assert r.status_code == 502 and r.json()["error"] == "partial_failure" and r.json()["decision_id"]
    assert len(c.get(f"{API}/decisions", headers=auth()).json()) == 1


def test_create_app_from_settings_uses_simulated_connector(tmp_path):
    s = Settings(
        env="test",
        database_url=f"sqlite:///{tmp_path / 't.db'}",
        sim_state_path=str(tmp_path / "s.json"),
        api_tokens="",
    )
    app = create_app(s)
    assert isinstance(app.state.ctx.connector, SimulatedConnector)
    assert isinstance(app.state.ctx.db, Database)
    assert MAIL_FULL  # imported constant used across modules
