"""Stores the provider credentials encrypted in the database (never in plaintext)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from trim.crypto import SecretBox
from trim.models import Connection


def store_credentials(session: Session, box: SecretBox, provider: str, secret: str) -> None:
    row = session.scalar(select(Connection).where(Connection.provider == provider))
    if row is None:
        row = Connection(provider=provider)
        session.add(row)
    row.secret_ciphertext = box.encrypt(secret)
    session.flush()


def load_credentials(session: Session, box: SecretBox, provider: str) -> str | None:
    row = session.scalar(select(Connection).where(Connection.provider == provider))
    return box.decrypt(row.secret_ciphertext) if row else None
