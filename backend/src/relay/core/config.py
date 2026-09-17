"""Application settings from environment variables prefixed ``RELAY_``.

Settings are validated at startup; an invalid configuration fails fast with a clear error. The
database URL is held as a secret so it never appears in ``repr`` or logs.

Only settings used by implemented code exist here. Later milestones add their own settings (see
``docs/architecture.md`` §10) together with the code that reads them.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Marker embedded in the local development password; production refuses URLs containing it.
_LOCAL_DEV_PASSWORD_MARKER = "local_dev_only"  # noqa: S105 - a marker, not a credential


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RELAY_",
        extra="ignore",
        frozen=True,
        case_sensitive=False,
    )

    env: Environment = Environment.LOCAL
    database_url: SecretStr = Field(
        description="SQLAlchemy URL, must use the psycopg driver: postgresql+psycopg://..."
    )
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_connect_timeout_seconds: int = Field(default=5, ge=1, le=60)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: SecretStr) -> SecretStr:
        parts = urlsplit(value.get_secret_value())
        if parts.scheme != "postgresql+psycopg":
            raise ValueError("database_url must use the 'postgresql+psycopg' scheme")
        if not parts.hostname:
            raise ValueError("database_url must include a host")
        if not parts.path.strip("/"):
            raise ValueError("database_url must include a database name")
        return value

    @model_validator(mode="after")
    def _validate_production(self) -> Settings:
        if self.env is Environment.PRODUCTION:
            if self.log_format != "json":
                raise ValueError("production requires log_format=json")
            password = urlsplit(self.database_url.get_secret_value()).password or ""
            if not password or _LOCAL_DEV_PASSWORD_MARKER in password:
                raise ValueError("production requires a real database password")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # values come from the environment
