"""PostgreSQL connectivity, migrations and column-type invariants (FC-01, FC-02, FC-06)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import (
    Column,
    Connection,
    Engine,
    Integer,
    MetaData,
    Table,
    create_engine,
    insert,
    select,
    text,
)
from sqlalchemy.exc import StatementError

from relay.api.app import create_app
from relay.core.config import Environment, Settings
from relay.core.currency import Currency
from relay.core.db import alembic_config, create_db_engine, current_revision, head_revision, ping
from relay.core.db_types import (
    AmountType,
    BusinessDateType,
    CurrencyCodeType,
    FxRateType,
    UtcTimestampType,
)
from relay.core.money import Money


def _upgrade(database_url: str, revision: str = "head") -> None:
    config = alembic_config(database_url)
    config.attributes["configure_logger"] = False
    command.upgrade(config, revision)


def _downgrade(database_url: str, revision: str) -> None:
    config = alembic_config(database_url)
    config.attributes["configure_logger"] = False
    command.downgrade(config, revision)


# --------------------------------------------------------------------------- connectivity


def test_connects_to_postgres_16_in_utc(engine: Engine) -> None:
    ping(engine)
    with engine.connect() as connection:
        version = connection.execute(text("SHOW server_version_num")).scalar_one()
        timezone = connection.execute(text("SHOW TimeZone")).scalar_one()
    assert int(version) // 10000 == 16
    assert timezone == "UTC"


# --------------------------------------------------------------------------- migrations


@pytest.fixture(scope="module")
def migration_database(database_url: str) -> Iterator[tuple[str, Settings, Engine]]:
    """An empty database of its own: downgrades refuse to drop governed rows other tests create."""
    parts = urlsplit(database_url)
    name = parts.path.lstrip("/").removesuffix("_test") + "_migrations_test"
    admin = create_engine(
        urlunsplit(parts._replace(path="/postgres")), isolation_level="AUTOCOMMIT"
    )
    with admin.connect() as connection:
        # Derived from the validated test database name; identifiers cannot be bound.
        connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    url = urlunsplit(parts._replace(path=f"/{name}"))
    settings = Settings(env=Environment.TEST, database_url=url)  # type: ignore[arg-type]
    db_engine = create_db_engine(settings)
    try:
        yield url, settings, db_engine
    finally:
        db_engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def test_migrations_upgrade_downgrade_upgrade(
    migration_database: tuple[str, Settings, Engine],
) -> None:
    database_url, _, engine = migration_database
    head = head_revision()
    assert head == "0008_superseded_runs"

    _upgrade(database_url)
    assert current_revision(engine) == head

    _downgrade(database_url, "-1")
    assert current_revision(engine) == "0007_errored_stages"
    _upgrade(database_url)
    assert current_revision(engine) == head

    _downgrade(database_url, "base")
    assert current_revision(engine) is None

    _upgrade(database_url)
    assert current_revision(engine) == head


def test_ready_endpoint_against_real_database(
    migration_database: tuple[str, Settings, Engine],
) -> None:
    database_url, settings, engine = migration_database
    _downgrade(database_url, "base")
    with TestClient(create_app(settings)) as client:
        behind = client.get("/health/ready")
        assert behind.status_code == 503
        assert behind.json()["database"] == {
            "reachable": True,
            "migrations": "not_at_head",
            "current_revision": None,
            "head_revision": "0008_superseded_runs",
        }

        _upgrade(database_url)
        ready = client.get("/health/ready")
        assert ready.status_code == 200
        assert ready.json() == {
            "status": "ok",
            "database": {
                "reachable": True,
                "migrations": "at_head",
                "current_revision": "0008_superseded_runs",
                "head_revision": "0008_superseded_runs",
            },
        }
    assert current_revision(engine) == "0008_superseded_runs"


# --------------------------------------------------------------------------- column types

_metadata = MetaData()
_probe = Table(
    "m0_type_probe",
    _metadata,
    Column("id", Integer, primary_key=True),
    Column("amount", AmountType()),
    Column("currency", CurrencyCodeType()),
    Column("fx_rate", FxRateType()),
    Column("business_date", BusinessDateType()),
    Column("recorded_at", UtcTimestampType()),
    prefixes=["TEMPORARY"],
)


@pytest.fixture
def probe_connection(engine: Engine) -> Iterator[Connection]:
    # Everything, including the TEMPORARY table and any SET TIME ZONE, is rolled back afterwards.
    with engine.connect() as connection:
        _metadata.create_all(connection)
        try:
            yield connection
        finally:
            connection.rollback()


def test_postgres_would_silently_round_numeric_without_the_guard(engine: Engine) -> None:
    # Documents why AmountType validates before binding: raw NUMERIC(20,4) rounds excess scale.
    with engine.connect() as connection:
        rounded = connection.execute(text("SELECT CAST('1.23456' AS NUMERIC(20,4))")).scalar_one()
    assert rounded == Decimal("1.2346")


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("0"),
        Decimal("0.0001"),
        Decimal("-0.0001"),
        Decimal("12.34"),
        Decimal("-1234567.8912"),
        Decimal("9999999999999999.9999"),
        Decimal("-9999999999999999.9999"),
    ],
)
def test_amount_round_trip_is_exact(probe_connection: Connection, amount: Decimal) -> None:
    connection = probe_connection
    connection.execute(insert(_probe).values(id=1, amount=amount, currency="USD"))
    row = connection.execute(select(_probe.c.amount, _probe.c.currency)).one()
    assert isinstance(row.amount, Decimal)
    assert row.amount == amount
    assert row.currency == Currency.of("USD")
    assert Money(row.amount, row.currency) == Money(amount, "USD")


@pytest.mark.parametrize("bad", [Decimal("1.23456"), 1.5, Decimal("1E+16"), Decimal("NaN")])
def test_amount_guard_prevents_rounding_or_float_writes(
    probe_connection: Connection, bad: object
) -> None:
    connection = probe_connection
    with pytest.raises(StatementError) as info:
        connection.execute(insert(_probe).values(id=1, amount=bad))
    assert "money." in getattr(info.value.orig, "code", "")
    assert connection.execute(select(_probe.c.id)).all() == []


def test_fx_rate_round_trip(probe_connection: Connection) -> None:
    connection = probe_connection
    connection.execute(insert(_probe).values(id=1, fx_rate=Decimal("1.0850000001")))
    assert connection.execute(select(_probe.c.fx_rate)).scalar_one() == Decimal("1.0850000001")


@pytest.mark.parametrize("session_timezone", ["UTC", "Pacific/Kiritimati", "Pacific/Pago_Pago"])
def test_business_dates_do_not_shift_with_session_timezone(
    probe_connection: Connection, session_timezone: str
) -> None:
    connection = probe_connection
    connection.execute(text(f"SET TIME ZONE '{session_timezone}'"))
    connection.execute(insert(_probe).values(id=1, business_date=date(2026, 6, 30)))
    connection.execute(text("SET TIME ZONE 'Pacific/Kiritimati'"))
    stored = connection.execute(select(_probe.c.business_date)).scalar_one()
    as_text = connection.execute(text("SELECT business_date::text FROM m0_type_probe")).scalar_one()
    assert stored == date(2026, 6, 30)
    assert type(stored) is date
    assert as_text == "2026-06-30"


def test_timestamps_round_trip_as_utc_regardless_of_session_timezone(
    probe_connection: Connection,
) -> None:
    connection = probe_connection
    instant = datetime(2026, 6, 30, 23, 30, tzinfo=ZoneInfo("America/Los_Angeles"))
    connection.execute(text("SET TIME ZONE 'Asia/Kolkata'"))
    connection.execute(insert(_probe).values(id=1, recorded_at=instant))
    stored = connection.execute(select(_probe.c.recorded_at)).scalar_one()
    assert stored == instant
    assert stored.tzinfo is UTC
    assert stored == datetime(2026, 7, 1, 6, 30, tzinfo=UTC)


def test_naive_timestamp_and_datetime_as_date_are_rejected(probe_connection: Connection) -> None:
    connection = probe_connection
    with pytest.raises(StatementError):
        connection.execute(insert(_probe).values(id=1, recorded_at=datetime(2026, 1, 1)))  # noqa: DTZ001
    with pytest.raises(StatementError):
        connection.execute(
            insert(_probe).values(id=2, business_date=datetime(2026, 1, 1, tzinfo=UTC))
        )
