"""The connector contract every identity provider integration implements.

A connector translates a provider (Google Workspace, Microsoft 365, the
simulator) into the same small vocabulary: users, grants, activity, and the
access changes Trim can make. ``Capabilities`` tells the services honestly what
a provider can and cannot do, e.g. Google can revoke a token but cannot narrow
it or restore it without the user consenting again.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class UserRecord:
    email: str
    name: str = ""
    department: str = ""


@dataclass(frozen=True)
class GrantRecord:
    client_id: str
    app_name: str
    user_email: str
    scopes: tuple[str, ...]


@dataclass(frozen=True)
class ActivityRecord:
    uid: str
    client_id: str
    app_name: str
    user_email: str | None
    api_name: str
    method_name: str
    response_bytes: int
    occurred_at: datetime


@dataclass(frozen=True)
class Capabilities:
    narrow_scopes: bool  # can replace a grant's scopes with a smaller set in place
    restore: bool  # can re-create a grant exactly (needed for undo and Allow once)


class ConnectorError(RuntimeError):
    """A provider call failed; nothing should be assumed to have changed."""


class UnsupportedOperation(ConnectorError):
    pass


@runtime_checkable
class Connector(Protocol):
    provider: str
    capabilities: Capabilities

    def list_users(self) -> list[UserRecord]: ...

    def list_grants(self) -> list[GrantRecord]: ...

    def list_activity(self, since: datetime | None) -> Iterable[ActivityRecord]: ...

    def set_scopes(self, user_email: str, client_id: str, scopes: list[str]) -> None:
        """Replace the grant's scopes. Raises UnsupportedOperation if not capable."""

    def revoke(self, user_email: str, client_id: str) -> None:
        """Remove the agent's access for this user entirely."""
