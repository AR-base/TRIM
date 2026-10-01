"""Google Workspace connector (Admin SDK Directory + Reports APIs).

Requires a service account with domain-wide delegation, impersonating an admin,
limited to exactly these scopes:

* admin.directory.user.readonly  - list users
* admin.directory.user.security  - list and revoke users' OAuth tokens
* admin.reports.audit.readonly   - OAuth token audit log (``applicationName=token``)

Per-call activity events (``eventName=activity``) are only produced on
Enterprise Standard/Plus, Education Standard/Plus and Cloud Identity Premium.

Google can revoke a token but cannot narrow one or re-create it without the
user consenting again, so ``capabilities`` reports both as unsupported and the
services adapt (a trim becomes a revocation that needs explicit confirmation).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

from trim.connectors.base import (
    ActivityRecord,
    Capabilities,
    ConnectorError,
    GrantRecord,
    UnsupportedOperation,
    UserRecord,
)

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.user.readonly",
    "https://www.googleapis.com/auth/admin.directory.user.security",
    "https://www.googleapis.com/auth/admin.reports.audit.readonly",
]

ServiceFactory = Callable[[str], Any]  # ("directory" | "reports") -> googleapiclient Resource


def default_service_factory(credentials_info: dict, admin_email: str) -> ServiceFactory:  # pragma: no cover
    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    creds = service_account.Credentials.from_service_account_info(credentials_info, scopes=SCOPES)
    creds = creds.with_subject(admin_email)

    def factory(kind: str):
        version = "directory_v1" if kind == "directory" else "reports_v1"
        return build("admin", version, credentials=creds, cache_discovery=False)

    return factory


def _status_of(exc: Exception) -> int | None:
    resp = getattr(exc, "resp", None)
    status = getattr(resp, "status", None)
    try:
        return int(status) if status is not None else None
    except (TypeError, ValueError):
        return None


class GoogleWorkspaceConnector:
    provider = "google"
    capabilities = Capabilities(narrow_scopes=False, restore=False)

    def __init__(
        self,
        service_factory: ServiceFactory,
        customer_id: str = "my_customer",
        max_retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._factory = service_factory
        self._customer = customer_id
        self._max_retries = max_retries
        self._sleep = sleep
        self._services: dict[str, Any] = {}

    @classmethod
    def from_credentials_json(cls, credentials_json: str, admin_email: str, customer_id: str):  # pragma: no cover
        return cls(default_service_factory(json.loads(credentials_json), admin_email), customer_id)

    def _svc(self, kind: str):
        if kind not in self._services:
            self._services[kind] = self._factory(kind)
        return self._services[kind]

    def _execute(self, request):
        """Execute with exponential backoff on rate limits and server errors."""
        delay = 1.0
        for attempt in range(self._max_retries + 1):
            try:
                return request.execute()
            except Exception as exc:
                status = _status_of(exc)
                retryable = status in (429, 500, 502, 503, 504)
                if not retryable or attempt == self._max_retries:
                    raise ConnectorError(f"Google API call failed (status {status})") from exc
                log.warning("google api retry %s after status %s", attempt + 1, status)
                self._sleep(delay)
                delay = min(delay * 2, 32)
        raise ConnectorError("unreachable")  # pragma: no cover

    def _pages(self, make_request: Callable[[str | None], Any], key: str) -> Iterator[dict]:
        token: str | None = None
        while True:
            page = self._execute(make_request(token)) or {}
            yield from page.get(key, [])
            token = page.get("nextPageToken")
            if not token:
                return

    # ---- reads ---------------------------------------------------------------
    def list_users(self) -> list[UserRecord]:
        users = self._svc("directory").users()
        out = []
        for u in self._pages(
            lambda t: users.list(customer=self._customer, maxResults=500, pageToken=t, projection="basic"),
            "users",
        ):
            if u.get("suspended"):
                continue
            out.append(
                UserRecord(
                    email=u["primaryEmail"].lower(),
                    name=(u.get("name") or {}).get("fullName", ""),
                    department=u.get("orgUnitPath", "").strip("/"),
                )
            )
        return out

    def list_grants(self) -> list[GrantRecord]:
        tokens = self._svc("directory").tokens()
        out = []
        for user in self.list_users():
            page = self._execute(tokens.list(userKey=user.email)) or {}
            for t in page.get("items", []):
                if not t.get("clientId"):
                    continue
                out.append(
                    GrantRecord(
                        client_id=t["clientId"],
                        app_name=t.get("displayText") or t["clientId"],
                        user_email=user.email,
                        scopes=tuple(t.get("scopes", [])),
                    )
                )
        return out

    def list_activity(self, since: datetime | None) -> Iterator[ActivityRecord]:
        activities = self._svc("reports").activities()
        start = since.astimezone(UTC).isoformat().replace("+00:00", "Z") if since else None

        def make(token: str | None):
            kwargs = {
                "userKey": "all",
                "applicationName": "token",
                "eventName": "activity",
                "maxResults": 1000,
                "pageToken": token,
            }
            if start:
                kwargs["startTime"] = start
            return activities.list(**kwargs)

        for item in self._pages(make, "items"):
            ident = item.get("id", {})
            when = datetime.fromisoformat(ident["time"].replace("Z", "+00:00"))
            actor = (item.get("actor") or {}).get("email")
            for i, ev in enumerate(item.get("events", [])):
                if ev.get("name") != "activity":
                    continue
                params = {p["name"]: p.get("value", p.get("intValue")) for p in ev.get("parameters", [])}
                client_id = params.get("client_id")
                method = params.get("method_name")
                if not client_id or not method:
                    continue
                yield ActivityRecord(
                    uid=f"g:{ident.get('uniqueQualifier', '')}:{ident['time']}:{i}",
                    client_id=str(client_id),
                    app_name=str(params.get("app_name") or client_id),
                    user_email=actor.lower() if actor else None,
                    api_name=str(params.get("api_name", "")),
                    method_name=str(method),
                    response_bytes=int(params.get("num_response_bytes") or 0),
                    occurred_at=when,
                )

    # ---- writes --------------------------------------------------------------
    def revoke(self, user_email: str, client_id: str) -> None:
        tokens = self._svc("directory").tokens()
        self._execute(tokens.delete(userKey=user_email, clientId=client_id))

    def set_scopes(self, user_email: str, client_id: str, scopes: list[str]) -> None:
        if scopes:
            raise UnsupportedOperation(
                "Google Workspace cannot narrow an existing token; revoke it and ask the owner to reconnect"
            )
        self.revoke(user_email, client_id)
