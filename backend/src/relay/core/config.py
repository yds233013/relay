"""Application settings from environment variables prefixed ``RELAY_``.

Settings are validated at startup; an invalid configuration fails fast with a clear error. The
database URL is held as a secret so it never appears in ``repr`` or logs.

Only settings used by implemented code exist here. Later milestones add their own settings (see
``docs/architecture.md`` §10) together with the code that reads them.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
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
    storage_dir: Path = Path("/data/blobs")
    max_upload_bytes: int = Field(default=52_428_800, ge=1024, le=1_073_741_824)
    max_rows_per_import: int = Field(default=500_000, ge=1, le=2_000_000)
    max_uploads_per_hour: int = Field(default=300, ge=1, le=10_000)
    dev_identity_enabled: bool | None = Field(
        default=None,
        description=(
            "Accept the X-Relay-User development header. Defaults to on in local and test, off "
            "otherwise; enabling it in production is refused (SEC-11)."
        ),
    )

    ai_provider: Literal["disabled", "scripted", "demo", "anthropic"] = Field(
        default="disabled",
        description="AI investigation provider. Every workflow works with 'disabled'.",
    )
    ai_model: str = Field(default="claude-opus-5", min_length=1, max_length=100)
    ai_api_base_url: str = "https://api.anthropic.com"
    anthropic_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="ANTHROPIC_API_KEY",
        description="From the environment only; never logged, returned or sent to the browser.",
    )
    ai_scripts_dir: Path | None = Field(
        default=None, description="Transcripts replayed by the scripted provider (demo, tests)."
    )
    ai_max_tool_calls: int = Field(default=15, ge=1, le=50)
    ai_max_seconds: int = Field(default=120, ge=5, le=600)
    ai_max_total_tokens: int = Field(default=200_000, ge=1_000, le=2_000_000)

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
            if self.dev_identity_enabled:
                raise ValueError("the development identity header cannot be enabled in production")
        if self.ai_provider == "anthropic" and self.anthropic_api_key is None:
            raise ValueError("ai_provider=anthropic requires ANTHROPIC_API_KEY in the environment")
        return self

    @property
    def dev_identity_active(self) -> bool:
        if self.dev_identity_enabled is None:
            return self.env in {Environment.LOCAL, Environment.TEST}
        return self.dev_identity_enabled and self.env is not Environment.PRODUCTION


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # values come from the environment
