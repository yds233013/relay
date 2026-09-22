# Relay backend for Railway: the API and the job worker in ONE service.
#
# Build context is the repository root (Railway builds from the GitHub checkout).
#
# Why this file exists instead of reusing backend/Dockerfile:
#   - Relay's blob store is a POSIX directory the API writes and the worker reads. Railway attaches
#     a volume to exactly one service and cannot share it, so the two processes that must see the
#     same files run in the same container (docs/railway-deployment.md §2).
#   - Railway runs no compose file, so the demo transcripts and the seed fixtures that compose
#     bind-mounts are copied into the image instead.
#   - Railway mounts volumes root-owned, so the container starts as root for exactly one command —
#     handing /data/blobs to the relay user — and then drops privileges for everything else. No
#     Relay code ever runs as root. (Railway's own suggestion, RAILWAY_RUN_UID=0, would run all of
#     it as root; this does not.)
#
# The Python layers below mirror backend/Dockerfile step for step, with the same pinned digests
# (SEC-31). Change them together.

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

COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/src ./src
RUN uv sync --locked --no-dev

# What compose bind-mounts, baked in read-only. Transcripts for the demo provider; fixtures for the
# first-boot seed. Neither contains an answer or a secret (tested in tests/scenario).
COPY fixtures/ai-scripts /ai-scripts
COPY fixtures/demo/brightwater /fixtures/demo/brightwater
COPY fixtures/demo/brightwater_config /fixtures/demo/brightwater_config
COPY deploy/railway/backend-start.sh /usr/local/bin/relay-railway-start
RUN chmod 0755 /usr/local/bin/relay-railway-start

ENV RELAY_AI_SCRIPTS_DIR=/ai-scripts
EXPOSE 8000
CMD ["relay-railway-start"]
