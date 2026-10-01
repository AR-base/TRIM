"""Bearer-token authentication with three roles.

Tokens are random 32-byte values shown once at creation. Only their SHA-256
hashes are configured (TRIM_API_TOKENS), so a leaked config file does not leak
working credentials. Comparison is constant-time.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    admin = "admin"  # connect, trim, undo, decide requests
    reviewer = "reviewer"  # read everything, acknowledge alerts; cannot change access
    service = "service"  # machine identity: submits permission requests


_ENTRY = re.compile(r"^(?P<name>[A-Za-z0-9._@-]{1,64}):(?P<role>admin|reviewer|service):(?P<hash>[0-9a-f]{64})$")


@dataclass(frozen=True)
class Principal:
    name: str
    role: Role

    def can_change_access(self) -> bool:
        return self.role is Role.admin


class TokenConfigError(ValueError):
    pass


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_token() -> str:
    return "trim_" + secrets.token_urlsafe(32)


def parse_token_config(raw: str) -> list[tuple[str, Role, str]]:
    entries: list[tuple[str, Role, str]] = []
    for part in (p.strip() for p in raw.split(",")):
        if not part:
            continue
        m = _ENTRY.match(part)
        if not m:
            raise TokenConfigError("invalid TRIM_API_TOKENS entry; expected name:role:sha256hex")
        entries.append((m["name"], Role(m["role"]), m["hash"]))
    return entries


class TokenAuthenticator:
    def __init__(self, raw_config: str) -> None:
        self._entries = parse_token_config(raw_config)

    def authenticate(self, presented: str | None) -> Principal | None:
        if not presented or len(presented) > 256:
            return None
        digest = hash_token(presented)
        match: Principal | None = None
        # Check every entry so timing does not reveal which one matched.
        for name, role, expected in self._entries:
            if hmac.compare_digest(digest, expected):
                match = Principal(name=name, role=role)
        return match
