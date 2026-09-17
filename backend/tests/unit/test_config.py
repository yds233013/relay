"""Settings validation."""

from __future__ import annotations

import os

import pytest
from pydantic import ValidationError

from relay.core.config import Environment, Settings

LOCAL_URL = "postgresql+psycopg://relay:relay_local_dev_only@localhost:55432/relay"


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ):
        if key.upper().startswith("RELAY_"):
            monkeypatch.delenv(key)


def test_defaults_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RELAY_DATABASE_URL", LOCAL_URL)
    settings = Settings()
    assert settings.env is Environment.LOCAL
    assert settings.log_level == "INFO"
    assert settings.log_format == "json"
    assert settings.db_pool_size == 5


def test_database_url_is_required() -> None:
    with pytest.raises(ValidationError, match="database_url"):
        Settings()


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://relay:pw@localhost/relay",  # wrong driver
        "sqlite:///relay.db",
        "postgresql+psycopg://relay:pw@/relay",  # no host
        "postgresql+psycopg://relay:pw@localhost",  # no database
        "not a url",
    ],
)
def test_invalid_database_urls(url: str) -> None:
    with pytest.raises(ValidationError):
        Settings(database_url=url)  # type: ignore[arg-type]


def test_database_url_is_secret() -> None:
    settings = Settings(database_url="postgresql+psycopg://relay:s3cret-pw@db:5432/relay")  # type: ignore[arg-type]
    assert "s3cret-pw" not in repr(settings)
    assert "s3cret-pw" not in str(settings.model_dump())
    assert "s3cret-pw" in settings.database_url.get_secret_value()


@pytest.mark.parametrize(
    ("env", "value"),
    [
        ("RELAY_ENV", "staging"),
        ("RELAY_LOG_LEVEL", "TRACE"),
        ("RELAY_LOG_FORMAT", "xml"),
        ("RELAY_DB_POOL_SIZE", "0"),
        ("RELAY_DB_POOL_SIZE", "many"),
    ],
)
def test_invalid_values(monkeypatch: pytest.MonkeyPatch, env: str, value: str) -> None:
    monkeypatch.setenv("RELAY_DATABASE_URL", LOCAL_URL)
    monkeypatch.setenv(env, value)
    with pytest.raises(ValidationError):
        Settings()


def test_production_rejects_local_dev_password() -> None:
    with pytest.raises(ValidationError, match="real database password"):
        Settings(env=Environment.PRODUCTION, database_url=LOCAL_URL)  # type: ignore[arg-type]


def test_production_rejects_missing_password() -> None:
    with pytest.raises(ValidationError, match="real database password"):
        Settings(env="production", database_url="postgresql+psycopg://relay@db/relay")  # type: ignore[arg-type]


def test_production_requires_json_logs() -> None:
    with pytest.raises(ValidationError, match="log_format=json"):
        Settings(
            env="production",  # type: ignore[arg-type]
            database_url="postgresql+psycopg://relay:Xk2-long-random@db/relay",  # type: ignore[arg-type]
            log_format="console",
        )


def test_valid_production_settings() -> None:
    settings = Settings(
        env="production",  # type: ignore[arg-type]
        database_url="postgresql+psycopg://relay:Xk2-long-random@db/relay",  # type: ignore[arg-type]
    )
    assert settings.env is Environment.PRODUCTION


def test_dev_identity_defaults_by_environment_and_is_refused_in_production() -> None:
    assert Settings(database_url=LOCAL_URL).dev_identity_active  # type: ignore[arg-type]
    production = Settings(
        env="production",  # type: ignore[arg-type]
        database_url="postgresql+psycopg://relay:Xk2-long-random@db/relay",  # type: ignore[arg-type]
    )
    assert not production.dev_identity_active
    with pytest.raises(ValidationError, match="development identity"):
        Settings(
            env="production",  # type: ignore[arg-type]
            database_url="postgresql+psycopg://relay:Xk2-long-random@db/relay",  # type: ignore[arg-type]
            dev_identity_enabled=True,
        )


def test_settings_are_immutable() -> None:
    settings = Settings(database_url=LOCAL_URL)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        settings.log_level = "DEBUG"  # type: ignore[misc]
