# Relay backend image (API and job worker). Local development / CI only.
# Base images are pinned by digest (SEC-31). Update tag and digest together.

FROM ghcr.io/astral-sh/uv:0.12.5@sha256:e85be844203885286c60ffad8a858d48afb6c5a5c237ca0e67f12e74b8f174b1 AS uv

FROM python:3.12.14-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH"

COPY --from=uv /uv /usr/local/bin/uv

RUN groupadd --system --gid 10001 relay \
    && useradd --system --uid 10001 --gid relay --home-dir /app --no-create-home relay \
    && mkdir -p /data/blobs && chown relay:relay /data/blobs && chmod 700 /data/blobs

WORKDIR /app

# Dependencies first for layer caching; the lockfile is authoritative.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY src ./src
RUN uv sync --locked --no-dev

USER relay
EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=6 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"]

CMD ["uvicorn", "relay.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
