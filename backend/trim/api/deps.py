"""FastAPI dependencies: the per-app context, sessions and authenticated principals."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from trim.auth import Principal, Role, TokenAuthenticator
from trim.config import Settings
from trim.connectors.base import Connector
from trim.db import Database
from trim.services.notify import Notifier
from trim.services.remediation import PartialFailure


@dataclass
class AppContext:
    settings: Settings
    db: Database
    connector: Connector
    auth: TokenAuthenticator
    notifier: Notifier
    clock: Callable[[], datetime]


def ctx(request: Request) -> AppContext:
    return request.app.state.ctx


def session(c: AppContext = Depends(ctx)) -> Iterator[Session]:
    with c.db.session() as s:
        try:
            yield s
        except PartialFailure:
            # Some provider changes did happen: keep the record of them.
            s.commit()
            raise


def now(c: AppContext = Depends(ctx)) -> datetime:
    return c.clock()


def principal(request: Request, c: AppContext = Depends(ctx)) -> Principal:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    p = c.auth.authenticate(token.strip()) if scheme.lower() == "bearer" else None
    if p is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "missing or invalid token", headers={"WWW-Authenticate": "Bearer"}
        )
    return p


def require(*roles: Role):
    def checker(p: Principal = Depends(principal)) -> Principal:
        if p.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, f"role '{p.role.value}' cannot do this")
        return p

    return checker


readers = require(Role.admin, Role.reviewer)
admins = require(Role.admin)
submitters = require(Role.admin, Role.service)
