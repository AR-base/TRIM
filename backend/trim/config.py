"""Runtime configuration, read from environment variables (prefix TRIM_).

Secrets (API token hashes, the encryption key, Google credentials) are only
ever read from the environment or mounted files; nothing secret lives in code.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TRIM_", env_file=".env", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    database_url: str = "sqlite:///./trim.db"

    # Comma-separated "name:role:sha256hex" entries. Generate with `trim token create`.
    api_tokens: str = ""

    # Fernet key used to encrypt connector credentials at rest. Generate with `trim key create`.
    encryption_key: str = ""

    # Which connector backs this deployment.
    connector: Literal["simulated", "google"] = "simulated"
    sim_state_path: str = "./sim_state.json"
    google_customer_id: str = "my_customer"
    google_admin_email: str = ""
    google_credentials_file: str = ""

    observation_days: int = Field(default=14, ge=1, le=180)
    baseline_days: int = Field(default=14, ge=3, le=180)
    # Audit logs arrive late; each sync re-reads this far back (duplicates are ignored by event id).
    activity_lookback_hours: int = Field(default=72, ge=0, le=24 * 30)
    activity_retention_days: int = Field(default=90, ge=7, le=3650)
    allow_once_default_minutes: int = Field(default=60, ge=5, le=24 * 60)

    cors_origins: str = "http://localhost:5173"
    webhook_url: str = ""

    @field_validator("database_url")
    @classmethod
    def _not_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("database_url must not be empty")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
