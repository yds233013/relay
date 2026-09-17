"""Integration test fixtures against a real PostgreSQL server.

``RELAY_TEST_DATABASE_URL`` must point at a database *name* reserved for tests (it is dropped and
recreated per session). Missing configuration is a hard failure, never a silent skip: running the
integration suite without a database must not look green.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import Engine, create_engine, text

from relay.core.config import Environment, Settings
from relay.core.db import create_db_engine


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/integration/" in str(item.path).replace("\\", "/"):
            item.add_marker(pytest.mark.integration)


def _test_database_url() -> str:
    url = os.environ.get("RELAY_TEST_DATABASE_URL")
    if not url:
        pytest.fail("RELAY_TEST_DATABASE_URL is not set; run `make test-integration`.")
    database = urlsplit(url).path.lstrip("/")
    if not database.endswith("_test"):
        pytest.fail(
            "RELAY_TEST_DATABASE_URL must name a database ending in '_test'; it is dropped."
        )
    return url


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = _test_database_url()
    parts = urlsplit(url)
    database = parts.path.lstrip("/")
    admin_url = urlunsplit(parts._replace(path="/postgres"))

    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        # The name was validated above; identifiers cannot be bound as parameters.
        connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{database}"'))
    try:
        yield url
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture(scope="session")
def settings(database_url: str) -> Settings:
    return Settings(env=Environment.TEST, database_url=database_url)  # type: ignore[arg-type]


@pytest.fixture(scope="session")
def engine(settings: Settings) -> Iterator[Engine]:
    db_engine = create_db_engine(settings)
    try:
        yield db_engine
    finally:
        db_engine.dispose()
