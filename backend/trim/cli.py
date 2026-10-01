"""Command-line entry point: `trim <command>`."""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import signal
import sys
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from trim.auth import Role, hash_token, new_token
from trim.config import get_settings
from trim.connectors import build_connector
from trim.connectors.simulated import SimulatedConnector
from trim.crypto import SecretBox
from trim.db import Database, utcnow
from trim.models import Agent
from trim.services.notify import Notifier
from trim.services.pipeline import run_cycle
from trim.services.requests import RequestError, create_request
from trim.services.sync import SyncReport, sync_inventory
from trim.simulator import build_scenario, load_into

log = logging.getLogger("trim")

DEMO_REQUESTS = [
    ("meeting_notes-1", "https://www.googleapis.com/auth/gmail.send", "Send the meeting recap to attendees"),
    ("scheduler-1", "https://www.googleapis.com/auth/drive.readonly", "Attach agenda documents to invites"),
    ("sales_reach-1", "https://www.googleapis.com/auth/calendar.events", "Book demo calls with prospects"),
]


def _db() -> Database:
    return Database(get_settings().database_url)


def cmd_token(args: argparse.Namespace) -> int:
    token = new_token()
    print(f"token (shown once, give it to {args.name}):\n  {token}")
    print(f"add this entry to TRIM_API_TOKENS (comma-separated):\n  {args.name}:{args.role}:{hash_token(token)}")
    return 0


def cmd_key(_: argparse.Namespace) -> int:
    print(SecretBox.generate_key())
    return 0


def cmd_connect(args: argparse.Namespace) -> int:
    from pathlib import Path

    from trim.services.connection import store_credentials

    settings = get_settings()
    raw = Path(args.credentials).read_text(encoding="utf-8")
    info = json.loads(raw)  # validate it is JSON before storing
    if info.get("type") != "service_account":
        print("expected a Google service-account key file", file=sys.stderr)
        return 2
    db = _db()
    db.create_all()
    with db.session() as s:
        store_credentials(s, SecretBox(settings.encryption_key), "google", raw)
    print("Google credentials stored encrypted; you can now delete the key file")
    return 0


def cmd_init_db(_: argparse.Namespace) -> int:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    command.upgrade(cfg, "head")
    print("database schema is at the latest migration")
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    settings = get_settings()
    if settings.connector != "simulated":
        print("simulate needs TRIM_CONNECTOR=simulated", file=sys.stderr)
        return 2
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=args.days)
    scenario = build_scenario(seed=args.seed, n_users=args.users, days=args.days, start=start)
    connector = SimulatedConnector(settings.sim_state_path)
    load_into(scenario, connector)

    db = _db()
    db.create_all()
    with db.session() as s:
        sync_inventory(s, connector, scenario.start, SyncReport())  # Trim was connected on day one
    now = utcnow()
    with db.session() as s:
        report = run_cycle(s, connector, now, settings.activity_retention_days, settings.baseline_days)
    with db.session() as s:
        for prefix, scope, why in DEMO_REQUESTS:
            agent = s.scalar(select(Agent).where(Agent.client_id.startswith(prefix)))
            if agent is None or not agent.grants:
                continue
            with contextlib.suppress(RequestError):
                create_request(s, agent, agent.grants[0].user.email, [scope], why, now)
    print(
        json.dumps(
            {
                "users": len(scenario.users),
                "agents": len(scenario.agents),
                "events": len(scenario.events),
                "incidents": [
                    {"agent": i.client_id, "kind": i.kind, "days": [str(d) for d in i.days]} for i in scenario.incidents
                ],
                "cycle": report.__dict__,
            },
            indent=2,
            default=str,
        )
    )
    return 0


def cmd_sync(_: argparse.Namespace) -> int:
    settings = get_settings()
    db = _db()
    with db.session() as s:
        report = run_cycle(
            s,
            build_connector(settings, db),
            utcnow(),
            settings.activity_retention_days,
            settings.baseline_days,
            Notifier(settings.webhook_url),
            settings.activity_lookback_hours,
        )
    print(json.dumps(report.__dict__, default=str))
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    settings = get_settings()
    db = _db()
    connector, notifier = build_connector(settings, db), Notifier(settings.webhook_url)
    stop = {"now": False}

    def _stop(*_):
        stop["now"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    log.info("worker started, interval %ss", args.interval)
    while not stop["now"]:
        try:
            with db.session() as s:
                report = run_cycle(
                    s,
                    connector,
                    utcnow(),
                    settings.activity_retention_days,
                    settings.baseline_days,
                    notifier,
                    settings.activity_lookback_hours,
                )
            log.info("cycle done: %s", json.dumps(report.__dict__, default=str))
        except Exception:
            log.exception("cycle failed; will retry next interval")
        for _ in range(args.interval):
            if stop["now"]:
                break
            time.sleep(1)
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    from trim.evaluate import evaluate

    print(json.dumps(evaluate(args.seeds), indent=2))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:  # pragma: no cover - starts a server
    import uvicorn

    uvicorn.run("trim.main:app_factory", factory=True, host=args.host, port=args.port, proxy_headers=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="trim", description="Least-privilege access control for AI agents")
    sub = p.add_subparsers(dest="cmd", required=True)

    t = sub.add_parser("token", help="create an API token")
    t.add_argument("action", choices=["create"])
    t.add_argument("--name", required=True)
    t.add_argument("--role", choices=[r.value for r in Role], required=True)
    t.set_defaults(fn=cmd_token)

    k = sub.add_parser("key", help="create an encryption key")
    k.add_argument("action", choices=["create"])
    k.set_defaults(fn=cmd_key)

    c = sub.add_parser("connect", help="store Google service-account credentials, encrypted")
    c.add_argument("provider", choices=["google"])
    c.add_argument("--credentials", required=True, help="path to the service-account JSON key")
    c.set_defaults(fn=cmd_connect)

    sub.add_parser("init-db", help="create the database schema").set_defaults(fn=cmd_init_db)

    s = sub.add_parser("simulate", help="generate a test organisation and load it")
    s.add_argument("--seed", type=int, default=7)
    s.add_argument("--users", type=int, default=40)
    s.add_argument("--days", type=int, default=28)
    s.set_defaults(fn=cmd_simulate)

    sub.add_parser("sync", help="run one sync, expiry and scoring cycle").set_defaults(fn=cmd_sync)

    w = sub.add_parser("worker", help="run cycles forever")
    w.add_argument("--interval", type=int, default=900)
    w.set_defaults(fn=cmd_worker)

    e = sub.add_parser("evaluate", help="measure the models on simulated data")
    e.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3, 4, 5])
    e.set_defaults(fn=cmd_evaluate)

    v = sub.add_parser("serve", help="run the API server")
    v.add_argument("--host", default="127.0.0.1")
    v.add_argument("--port", type=int, default=8000)
    v.set_defaults(fn=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    args = build_parser().parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
