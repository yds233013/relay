"""FastAPI application factory.

Run with: ``uvicorn relay.api.app:create_app --factory``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from relay import __version__
from relay.api.middleware import RequestContextMiddleware
from relay.api.problems import install_problem_handlers
from relay.api.routers import ai, governance, health, issues, runs, setup, workspace
from relay.core.clock import SystemClock
from relay.core.config import Settings, get_settings
from relay.core.db import create_db_engine, create_session_factory
from relay.core.logging import configure_logging
from relay.imports.blob_store import LocalBlobStore

API_PREFIX = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved.log_level, resolved.log_format)

    # The engine connects lazily; creating it does not require the database to be up.
    engine = create_db_engine(resolved)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title="Relay API",
        version=__version__,
        lifespan=lifespan,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs" if resolved.env != "production" else None,
        redoc_url=None,
    )
    app.state.settings = resolved
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    app.state.blob_store = LocalBlobStore(resolved.storage_dir)
    app.state.clock = SystemClock()

    app.add_middleware(RequestContextMiddleware)
    install_problem_handlers(app)
    app.include_router(health.router)
    app.include_router(workspace.router)
    app.include_router(runs.router)
    app.include_router(governance.router)
    app.include_router(issues.router)
    app.include_router(setup.router)
    app.include_router(ai.router)
    return app
