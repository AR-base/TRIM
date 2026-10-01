from datetime import UTC, datetime

import pytest

from trim.connectors.base import ActivityRecord, ConnectorError, UnsupportedOperation
from trim.connectors.google import GoogleWorkspaceConnector
from trim.connectors.simulated import SimulatedConnector

# ---- simulated --------------------------------------------------------------


def test_simulated_persists_to_file_atomically(tmp_path):
    path = tmp_path / "state" / "sim.json"
    a = SimulatedConnector(str(path))
    a.add_user("x@acme.eu", "X", "Ops")
    a.add_grant("app", "App", "x@acme.eu", ["openid", "openid", "s2"])
    a.add_activity(
        [
            ActivityRecord(
                "u1",
                "app",
                "App",
                "x@acme.eu",
                "gmail",
                "gmail.users.messages.list",
                10,
                datetime(2026, 9, 1, tzinfo=UTC),
            )
        ]
    )
    b = SimulatedConnector(str(path))  # a second process sees the same state
    assert [u.email for u in b.list_users()] == ["x@acme.eu"]
    assert b.list_grants()[0].scopes == ("openid", "s2")
    assert len(b.list_activity(None)) == 1
    assert b.list_activity(datetime(2026, 9, 1, tzinfo=UTC)) == []
    assert not list(path.parent.glob(".sim-*"))  # no temp files left behind


def test_simulated_fail_hook_and_revoke():
    c = SimulatedConnector()
    c.add_grant("app", "App", "x@acme.eu", ["a", "b"])
    c.fail_next_calls(1)
    with pytest.raises(ConnectorError):
        c.set_scopes("x@acme.eu", "app", ["a"])
    assert c.list_grants()[0].scopes == ("a", "b")  # unchanged after failure
    c.set_scopes("x@acme.eu", "app", ["a"])
    assert c.list_grants()[0].scopes == ("a",)
    c.revoke("x@acme.eu", "app")
    assert c.list_grants() == []
    assert SimulatedConnector(None).list_users() == []


# ---- google (with fake Admin SDK services) ------------------------------------


class FakeHttpError(Exception):
    def __init__(self, status):
        super().__init__(f"status {status}")
        self.resp = type("R", (), {"status": status})()


class Req:
    def __init__(self, results):
        self.results = list(results)

    def execute(self):
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class Collection:
    def __init__(self, handlers):
        self.handlers = handlers
        self.calls = []

    def __getattr__(self, name):
        def method(**kwargs):
            self.calls.append((name, kwargs))
            return self.handlers[name](**kwargs)

        return method


class FakeService:
    def __init__(self, **collections):
        self._c = collections

    def __getattr__(self, name):
        return lambda: self._c[name]


def make_google(token_pages=None, activity_pages=None, delete_results=None):
    users = Collection(
        {
            "list": lambda pageToken=None, **_: Req(
                [
                    {
                        "users": [
                            {"primaryEmail": "Alice@acme.eu", "name": {"fullName": "Alice"}, "orgUnitPath": "/Sales"},
                            {"primaryEmail": "gone@acme.eu", "suspended": True},
                        ],
                        "nextPageToken": "p2",
                    }
                    if pageToken is None
                    else {"users": [{"primaryEmail": "bob@acme.eu"}]}
                ]
            )
        }
    )
    tokens = Collection(
        {
            "list": lambda userKey, **_: Req([(token_pages or {}).get(userKey, {})]),
            "delete": lambda **_: Req(delete_results or [{}]),
        }
    )
    acts = Collection(
        {"list": lambda pageToken=None, **kw: Req([(activity_pages or [{}])[0 if pageToken is None else 1]])}
    )
    directory = FakeService(users=users, tokens=tokens)
    reports = FakeService(activities=acts)
    sleeps = []
    conn = GoogleWorkspaceConnector(lambda kind: directory if kind == "directory" else reports, sleep=sleeps.append)
    return conn, tokens, acts, sleeps


def test_google_lists_users_across_pages_and_skips_suspended():
    conn, *_ = make_google()
    users = conn.list_users()
    assert [(u.email, u.name, u.department) for u in users] == [
        ("alice@acme.eu", "Alice", "Sales"),
        ("bob@acme.eu", "", ""),
    ]


def test_google_lists_grants():
    conn, *_ = make_google(
        token_pages={
            "alice@acme.eu": {
                "items": [
                    {"clientId": "c1", "displayText": "Copilot", "scopes": ["openid"]},
                    {"displayText": "no client id"},
                ]
            },
        }
    )
    grants = conn.list_grants()
    assert len(grants) == 1 and grants[0].client_id == "c1" and grants[0].scopes == ("openid",)


def test_google_parses_activity_and_paginates():
    page1 = {
        "items": [
            {
                "id": {"time": "2026-09-20T10:00:00.000Z", "uniqueQualifier": "42"},
                "actor": {"email": "Alice@acme.eu"},
                "events": [
                    {
                        "name": "activity",
                        "parameters": [
                            {"name": "client_id", "value": "c1"},
                            {"name": "app_name", "value": "Copilot"},
                            {"name": "api_name", "value": "gmail"},
                            {"name": "method_name", "value": "gmail.users.messages.get"},
                            {"name": "num_response_bytes", "intValue": "2048"},
                        ],
                    },
                    {"name": "authorize", "parameters": []},
                    {"name": "activity", "parameters": [{"name": "client_id", "value": "c1"}]},  # no method: skipped
                ],
            }
        ],
        "nextPageToken": "n",
    }
    page2 = {"items": []}
    conn, _, acts, _ = make_google(activity_pages=[page1, page2])
    recs = list(conn.list_activity(datetime(2026, 9, 19, tzinfo=UTC)))
    assert len(recs) == 1
    r = recs[0]
    assert (r.client_id, r.user_email, r.method_name, r.response_bytes) == (
        "c1",
        "alice@acme.eu",
        "gmail.users.messages.get",
        2048,
    )
    assert r.occurred_at == datetime(2026, 9, 20, 10, tzinfo=UTC)
    assert acts.calls[0][1]["applicationName"] == "token" and acts.calls[0][1]["startTime"] == "2026-09-19T00:00:00Z"


def test_google_retries_rate_limits_then_succeeds():
    conn, tokens, _, sleeps = make_google(delete_results=[FakeHttpError(429), FakeHttpError(503), {}])
    conn.revoke("alice@acme.eu", "c1")
    assert sleeps == [1.0, 2.0]
    assert tokens.calls[-1] == ("delete", {"userKey": "alice@acme.eu", "clientId": "c1"})


def test_google_does_not_retry_client_errors():
    conn, _, _, sleeps = make_google(delete_results=[FakeHttpError(403)])
    with pytest.raises(ConnectorError):
        conn.revoke("alice@acme.eu", "c1")
    assert sleeps == []


def test_google_gives_up_after_max_retries():
    conn, _, _, sleeps = make_google(delete_results=[FakeHttpError(500)] * 5)
    with pytest.raises(ConnectorError):
        conn.revoke("alice@acme.eu", "c1")
    assert len(sleeps) == 4


def test_google_cannot_narrow_but_can_revoke():
    conn, tokens, _, _ = make_google()
    assert not conn.capabilities.narrow_scopes and not conn.capabilities.restore
    with pytest.raises(UnsupportedOperation):
        conn.set_scopes("alice@acme.eu", "c1", ["openid"])
    conn.set_scopes("alice@acme.eu", "c1", [])
    assert tokens.calls[-1][0] == "delete"
