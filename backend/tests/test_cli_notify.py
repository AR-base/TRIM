import json

import httpx
import pytest

from trim import cli
from trim.config import get_settings
from trim.db import Database
from trim.services.connection import load_credentials, store_credentials
from trim.services.notify import Notifier


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("TRIM_DATABASE_URL", f"sqlite:///{tmp_path / 'trim.db'}")
    monkeypatch.setenv("TRIM_SIM_STATE_PATH", str(tmp_path / "sim.json"))
    monkeypatch.setenv("TRIM_CONNECTOR", "simulated")
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_token_and_key_commands(capsys):
    assert cli.main(["token", "create", "--name", "ana", "--role", "admin"]) == 0
    out = capsys.readouterr().out
    token = out.split("\n")[1].strip()
    entry = out.strip().split("\n")[-1].strip()
    from trim.auth import TokenAuthenticator

    assert TokenAuthenticator(entry).authenticate(token).name == "ana"
    assert cli.main(["key", "create"]) == 0
    from trim.crypto import SecretBox

    SecretBox(capsys.readouterr().out.strip())  # a valid key


def test_init_db_simulate_and_sync(env, capsys):
    assert cli.main(["init-db"]) == 0
    assert cli.main(["simulate", "--seed", "4", "--users", "15", "--days", "20"]) == 0
    out = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert out["agents"] == 20 and out["users"] == 15 and out["incidents"]
    assert (env / "sim.json").exists()
    assert cli.main(["sync"]) == 0
    cycle = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert cycle["sync"]["events_new"] == 0  # nothing new since the simulation

    from sqlalchemy import func, select

    from trim.models import Agent, PermissionRequest

    db = Database(f"sqlite:///{env / 'trim.db'}")
    with db.session() as s:
        assert s.scalar(select(func.count(Agent.id))) == 20
        assert s.scalar(select(func.count(PermissionRequest.id))) == 3


def test_simulate_refuses_real_connector(env, monkeypatch, capsys):
    monkeypatch.setenv("TRIM_CONNECTOR", "google")
    get_settings.cache_clear()
    assert cli.main(["simulate"]) == 2


def test_connect_stores_encrypted_credentials(env, monkeypatch, capsys):
    from trim.crypto import SecretBox

    key = SecretBox.generate_key()
    monkeypatch.setenv("TRIM_ENCRYPTION_KEY", key)
    get_settings.cache_clear()
    keyfile = env / "sa.json"
    keyfile.write_text(json.dumps({"type": "service_account", "private_key": "-----BEGIN-----"}))
    assert cli.main(["connect", "google", "--credentials", str(keyfile)]) == 0
    raw = (env / "trim.db").read_bytes()
    assert b"BEGIN" not in raw  # never stored in plaintext
    db = Database(f"sqlite:///{env / 'trim.db'}")
    with db.session() as s:
        assert json.loads(load_credentials(s, SecretBox(key), "google"))["type"] == "service_account"
        store_credentials(s, SecretBox(key), "google", '{"type": "service_account", "v": 2}')
        assert json.loads(load_credentials(s, SecretBox(key), "google"))["v"] == 2
        assert load_credentials(s, SecretBox(key), "microsoft") is None
    keyfile.write_text(json.dumps({"type": "user"}))
    assert cli.main(["connect", "google", "--credentials", str(keyfile)]) == 2


def test_evaluate_command(capsys):
    assert cli.main(["evaluate", "--seeds", "2"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["seeds"] == [2] and 0 <= result["anomaly"]["recall"] <= 1


def test_notifier_requires_https_and_never_raises(monkeypatch):
    with pytest.raises(ValueError):
        Notifier("http://hooks.example.com/x")
    with pytest.raises(ValueError):
        Notifier("javascript:alert(1)")
    assert Notifier("").send("hello") is False

    sent = {}

    def ok(url, json, timeout, follow_redirects):
        sent.update(url=url, json=json, follow=follow_redirects)
        return httpx.Response(200, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", ok)
    n = Notifier("https://hooks.example.com/x")
    assert n.send("hi") is True and sent == {
        "url": "https://hooks.example.com/x",
        "json": {"text": "hi"},
        "follow": False,
    }

    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(httpx, "post", boom)
    assert n.send("hi") is False
