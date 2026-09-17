"""Database engine, sessions, declarative base and migration status.

Sync SQLAlchemy 2.0 with psycopg 3 (architecture decision D-05). Every connection uses the UTC
session time zone so ``TIMESTAMPTZ`` values are never rendered in a server-local zone.

No domain tables exist in M0; they arrive with the milestones that own them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, MetaData, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from relay.core.config import Settings

BACKEND_ROOT: Final = Path(__file__).resolve().parents[3]
ALEMBIC_INI: Final = BACKEND_ROOT / "alembic.ini"
_IDENTIFIER: Final = re.compile(r"[a-z_][a-z0-9_]{0,62}")

NAMING_CONVENTION: Final = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_db_engine(settings: Settings, *, url: str | None = None) -> Engine:
    return create_engine(
        url or settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        connect_args={
            "connect_timeout": settings.db_connect_timeout_seconds,
            "options": "-c timezone=UTC",
            "application_name": "relay",
        },
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Unit of work: commit on success, roll back on any exception."""
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def copy_rows(
    session: Session, table: str, columns: Sequence[str], rows: Iterable[Sequence[object]]
) -> int:
    """Bulk insert with PostgreSQL ``COPY`` inside the session's transaction.

    Callers pass validated values (amounts through ``validate_amount``, JSON through
    :func:`relay.core.hashing.to_canonical`); ``dict`` and ``list`` values of JSON columns must be
    wrapped with ``psycopg.types.json.Jsonb`` by the caller.
    """
    if not _IDENTIFIER.fullmatch(table) or not all(_IDENTIFIER.fullmatch(c) for c in columns):
        raise ValueError("invalid table or column identifier")
    raw = session.connection().connection.driver_connection
    if raw is None:
        raise RuntimeError("no active database connection")
    count = 0
    with (
        raw.cursor() as cursor,
        cursor.copy(
            f"COPY {table} ({', '.join(columns)}) FROM STDIN"  # identifiers validated above
        ) as copy,
    ):
        for row in rows:
            copy.write_row(row)
            count += 1
    return count


def alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_ROOT / "migrations"))
    if database_url is not None:
        # ConfigParser interpolation treats '%' specially; escape it.
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine: Engine) -> str | None:
    with engine.connect() as connection:
        if not inspect(connection).has_table("alembic_version"):
            return None
        return connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()


def ping(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
