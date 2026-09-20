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


@pytest.mark.parametrize("blank", ["", "   ", "\t", "\n", "  \n\t "])
def test_blank_anthropic_key_is_treated_as_absent(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    """A present-but-empty key is the same as no key.

    Both compose files pass ``ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY:-}``, so the variable is
    normally present and empty. Before this, ``""`` became a ``SecretStr`` and defeated the
    ai_provider guard below.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", blank)
    settings = Settings(database_url=LOCAL_URL)  # type: ignore[arg-type]
    assert settings.anthropic_api_key is None


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_anthropic_provider_is_refused_when_the_key_is_blank(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", blank)
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        Settings(
            database_url=LOCAL_URL,  # type: ignore[arg-type]
            ai_provider="anthropic",
        )


def test_anthropic_provider_is_refused_when_the_key_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        Settings(
            database_url=LOCAL_URL,  # type: ignore[arg-type]
            ai_provider="anthropic",
        )


def test_a_real_anthropic_key_is_kept_and_stays_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    settings = Settings(
        database_url=LOCAL_URL,  # type: ignore[arg-type]
        ai_provider="anthropic",
    )
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-not-a-real-key"
    assert "sk-ant-not-a-real-key" not in repr(settings)
    assert "sk-ant-not-a-real-key" not in str(settings.model_dump())


DEPLOYED_URL = "postgresql+psycopg://relay:Xk2-long-random@db/relay"


def _demo(**overrides: object) -> Settings:
    kwargs: dict[str, object] = {
        "env": "demo",
        "database_url": DEPLOYED_URL,
        "ai_provider": "demo",
    }
    kwargs.update(overrides)
    return Settings(**kwargs)  # type: ignore[arg-type]


def test_demo_is_its_own_environment() -> None:
    settings = _demo()
    assert settings.env is Environment.DEMO
    assert settings.public_demo
    assert not Settings(database_url=LOCAL_URL).public_demo  # type: ignore[arg-type]
    assert not Settings(
        env="production",  # type: ignore[arg-type]
        database_url=DEPLOYED_URL,  # type: ignore[arg-type]
    ).public_demo


def test_demo_never_accepts_an_identity_header() -> None:
    """A visitor must not be able to choose who they are (SEC-11)."""
    assert not _demo().dev_identity_active
    with pytest.raises(ValidationError, match="development identity"):
        _demo(dev_identity_enabled=True)


@pytest.mark.parametrize("provider", ["anthropic", "scripted"])
def test_demo_refuses_providers_other_than_demo_and_disabled(provider: str) -> None:
    """The structural guarantee that the public demo cannot spend money.

    A paid provider is rejected by configuration, so the process never starts and no request path
    can reach it — rather than being blocked somewhere a later change might miss.
    """
    with pytest.raises(ValidationError, match="public demo accepts only"):
        _demo(ai_provider=provider)


@pytest.mark.parametrize("provider", ["demo", "disabled"])
def test_demo_accepts_the_replay_providers(provider: str) -> None:
    assert _demo(ai_provider=provider).ai_provider == provider


def test_demo_refuses_a_key_being_pointless(monkeypatch: pytest.MonkeyPatch) -> None:
    """Even with a real key in the environment, demo cannot select the paid provider."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-not-a-real-key")
    with pytest.raises(ValidationError, match="public demo accepts only"):
        _demo(ai_provider="anthropic")


def test_demo_needs_real_deployment_settings() -> None:
    with pytest.raises(ValidationError, match="demo requires a real database password"):
        _demo(database_url=LOCAL_URL)
    with pytest.raises(ValidationError, match="demo requires log_format=json"):
        _demo(log_format="console")


def test_settings_are_immutable() -> None:
    settings = Settings(database_url=LOCAL_URL)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        settings.log_level = "DEBUG"  # type: ignore[misc]
