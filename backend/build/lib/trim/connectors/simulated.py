"""A simulated identity provider backed by a JSON file.

It behaves like a provider that supports narrowing and restoring grants (as
Microsoft 365 delegated grants do, and as Trim-managed agents do). The
simulator writes users, agents, grants and activity into it; the API and the
worker read from it exactly as they would from Google.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from trim.connectors.base import (
    ActivityRecord,
    Capabilities,
    ConnectorError,
    GrantRecord,
    UserRecord,
)

_EMPTY: dict = {"users": [], "apps": {}, "grants": {}, "activity": [], "fail_next": 0}


def _key(user_email: str, client_id: str) -> str:
    return f"{user_email}|{client_id}"


class SimulatedConnector:
    provider = "simulated"
    capabilities = Capabilities(narrow_scopes=True, restore=True)

    def __init__(self, path: str | None = None) -> None:
        self._path = Path(path) if path else None
        self._lock = threading.RLock()
        self._mem: dict = json.loads(json.dumps(_EMPTY))

    # ---- storage -------------------------------------------------------------
    def _load(self) -> dict:
        if self._path is None:
            return self._mem
        if not self._path.exists():
            return json.loads(json.dumps(_EMPTY))
        with self._path.open(encoding="utf-8") as fh:
            return json.load(fh)

    def _save(self, state: dict) -> None:
        if self._path is None:
            self._mem = state
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, prefix=".sim-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        os.replace(tmp, self._path)  # atomic on POSIX

    @contextmanager
    def edit(self) -> Iterator[dict]:
        with self._lock:
            state = self._load()
            yield state
            self._save(state)

    def snapshot(self) -> dict:
        with self._lock:
            return self._load()

    # ---- writes used by the simulator ---------------------------------------
    def reset(self) -> None:
        with self.edit() as state:
            state.clear()
            state.update(json.loads(json.dumps(_EMPTY)))

    def add_user(self, email: str, name: str = "", department: str = "") -> None:
        with self.edit() as state:
            state["users"] = [u for u in state["users"] if u["email"] != email]
            state["users"].append({"email": email, "name": name, "department": department})

    def add_grant(self, client_id: str, app_name: str, user_email: str, scopes: list[str]) -> None:
        with self.edit() as state:
            state["apps"][client_id] = app_name
            state["grants"][_key(user_email, client_id)] = list(dict.fromkeys(scopes))

    def add_activity(self, records: list[ActivityRecord]) -> None:
        with self.edit() as state:
            for r in records:
                state["apps"].setdefault(r.client_id, r.app_name)
                state["activity"].append(
                    {
                        "uid": r.uid,
                        "client_id": r.client_id,
                        "user_email": r.user_email,
                        "api_name": r.api_name,
                        "method_name": r.method_name,
                        "response_bytes": r.response_bytes,
                        "occurred_at": r.occurred_at.isoformat(),
                    }
                )

    def fail_next_calls(self, n: int) -> None:
        """Test hook: make the next n access-changing calls fail."""
        with self.edit() as state:
            state["fail_next"] = n

    # ---- Connector protocol --------------------------------------------------
    def list_users(self) -> list[UserRecord]:
        return [UserRecord(**u) for u in self.snapshot()["users"]]

    def list_grants(self) -> list[GrantRecord]:
        state = self.snapshot()
        out = []
        for key, scopes in state["grants"].items():
            user_email, client_id = key.split("|", 1)
            out.append(GrantRecord(client_id, state["apps"].get(client_id, client_id), user_email, tuple(scopes)))
        return out

    def list_activity(self, since: datetime | None) -> list[ActivityRecord]:
        state = self.snapshot()
        out = []
        for a in state["activity"]:
            ts = datetime.fromisoformat(a["occurred_at"])
            if since is not None and ts <= since:
                continue
            out.append(
                ActivityRecord(
                    uid=a["uid"],
                    client_id=a["client_id"],
                    app_name=state["apps"].get(a["client_id"], a["client_id"]),
                    user_email=a["user_email"],
                    api_name=a["api_name"],
                    method_name=a["method_name"],
                    response_bytes=int(a["response_bytes"]),
                    occurred_at=ts,
                )
            )
        out.sort(key=lambda r: r.occurred_at)
        return out

    def set_scopes(self, user_email: str, client_id: str, scopes: list[str]) -> None:
        failed = False
        with self.edit() as state:
            if state.get("fail_next", 0) > 0:
                state["fail_next"] -= 1
                failed = True
            elif not scopes:
                state["grants"].pop(_key(user_email, client_id), None)
            else:
                state["grants"][_key(user_email, client_id)] = list(dict.fromkeys(scopes))
        if failed:
            raise ConnectorError("simulated provider error")

    def revoke(self, user_email: str, client_id: str) -> None:
        self.set_scopes(user_email, client_id, [])
