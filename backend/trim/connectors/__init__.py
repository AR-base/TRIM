"""Connector selection for the running deployment."""

from __future__ import annotations

from pathlib import Path

from trim.config import Settings
from trim.connectors.base import Connector, ConnectorError
from trim.connectors.simulated import SimulatedConnector


def build_connector(settings: Settings, db=None) -> Connector:
    if settings.connector == "simulated":
        return SimulatedConnector(settings.sim_state_path)
    if settings.connector == "google":  # pragma: no cover - needs live credentials
        from trim.connectors.google import GoogleWorkspaceConnector
        from trim.crypto import SecretBox
        from trim.services.connection import load_credentials

        if not settings.google_admin_email:
            raise ConnectorError("set TRIM_GOOGLE_ADMIN_EMAIL")
        creds: str | None = None
        if db is not None and settings.encryption_key:
            with db.session() as s:
                creds = load_credentials(s, SecretBox(settings.encryption_key), "google")
        if creds is None and settings.google_credentials_file:
            creds = Path(settings.google_credentials_file).read_text(encoding="utf-8")
        if creds is None:
            raise ConnectorError("no Google credentials: run `trim connect google` or set the credentials file")
        return GoogleWorkspaceConnector.from_credentials_json(
            creds, settings.google_admin_email, settings.google_customer_id
        )
    raise ConnectorError(f"unknown connector {settings.connector}")
