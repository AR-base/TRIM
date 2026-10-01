from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from trim.auth import hash_token
from trim.config import Settings
from trim.connectors.base import ActivityRecord
from trim.connectors.simulated import SimulatedConnector
from trim.db import Database
from trim.main import create_app
from trim.scopes import GOOGLE_PREFIX as G
from trim.services.notify import Notifier
from trim.services.sync import SyncReport, run_sync, sync_inventory

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
START = NOW - timedelta(days=20)
MAIL_FULL = "https://mail.google.com/"
ADMIN, REVIEWER, SERVICE = "admin-token", "reviewer-token", "service-token"


@dataclass
class World:
    db: Database
    connector: SimulatedConnector
    now: datetime


def seed_connector(conn: SimulatedConnector) -> None:
    for email in ("alice@acme.eu", "bob@acme.eu", "carol@acme.eu"):
        conn.add_user(email, email.split("@")[0].title(), "Sales")
    for user in ("alice@acme.eu", "bob@acme.eu"):
        conn.add_grant("mailbot", "Mail Bot", user, ["openid", MAIL_FULL, G + "calendar"])
    conn.add_grant("idle", "Idle Bot", "carol@acme.eu", [G + "drive"])
    events = []
    n = 0
    for d in range(20):
        day = START + timedelta(days=d)
        for h in (9, 11, 14):
            for user, method in (
                ("alice@acme.eu", "gmail.users.messages.list"),
                ("alice@acme.eu", "gmail.users.messages.send"),
                ("bob@acme.eu", "gmail.users.messages.list"),
            ):
                n += 1
                events.append(
                    ActivityRecord(
                        uid=f"t{n}",
                        client_id="mailbot",
                        app_name="Mail Bot",
                        user_email=user,
                        api_name="gmail",
                        method_name=method,
                        response_bytes=4000,
                        occurred_at=day.replace(hour=h),
                    )
                )
    conn.add_activity(events)


def build_world() -> World:
    conn = SimulatedConnector()
    seed_connector(conn)
    db = Database("sqlite://")
    db.create_all()
    with db.session() as s:
        sync_inventory(s, conn, START, SyncReport())
    with db.session() as s:
        run_sync(s, conn, NOW, retention_days=365)
    return World(db, conn, NOW)


@pytest.fixture
def world() -> World:
    return build_world()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        env="test",
        api_tokens=",".join(
            [
                f"ana:admin:{hash_token(ADMIN)}",
                f"rev:reviewer:{hash_token(REVIEWER)}",
                f"bot:service:{hash_token(SERVICE)}",
            ]
        ),
        observation_days=14,
        baseline_days=14,
    )


@pytest.fixture
def notifier() -> Notifier:
    return Notifier("")


@pytest.fixture
def client(world: World, settings: Settings, notifier: Notifier) -> TestClient:
    app = create_app(settings, db=world.db, connector=world.connector, clock=lambda: world.now, notifier=notifier)
    return TestClient(app)


def auth(token: str = ADMIN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
