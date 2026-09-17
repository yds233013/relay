# Relay — Progress Log

One entry per milestone: what was built, what changed from the plan, and why.

---

## M0 — Repository foundation

Status: **Implemented, awaiting review (not committed).**

### Built

**Backend (`backend/`)** — Python 3.12, uv, FastAPI, SQLAlchemy 2.0 (sync) + psycopg 3, Alembic, Pydantic v2, structlog.

- `relay.core.currency`: ISO 4217 registry with minor units.
- `relay.core.money`: `Money`, amount validation against the `NUMERIC(20,4)` envelope, exact arithmetic, currency-safe comparison, tolerance checks, FX conversion (the only rounding), debit/credit → signed amounts, explicit-format parsing of source amount text, Pydantic integration. Decisions: [decisions/0001-money-representation.md](decisions/0001-money-representation.md).
- `relay.core.dates`: business dates (`date` only, datetimes rejected), explicit-format parsing, ambiguity detection, fiscal periods, Pydantic `BusinessDate` type.
- `relay.core.timestamps`: aware-UTC timestamps, RFC 3339 parse/format, Pydantic `UtcTimestamp` type.
- `relay.core.clock`, `ids` (UUIDv7), `hashing` (canonical JSON, SHA-256), `errors`, `config`, `logging`.
- `relay.core.db`: engine (UTC session time zone), session factory, unit-of-work scope, declarative base with naming conventions, Alembic helpers.
- `relay.core.db_types`: column types that reject floats, over-scale amounts, naive timestamps and datetimes posing as dates *before* PostgreSQL can round or coerce them.
- `relay.api`: app factory, `GET /health`, `GET /health/ready`, problem+json errors, request-id and request-logging middleware, baseline security headers.
- Alembic baseline revision `0001_baseline` (empty schema) and a ruff post-write hook for new revisions.
- Tests: unit, property-based (Hypothesis), and integration tests against PostgreSQL 16.

**Web (`web/`)** — Next.js 16, React 19, TypeScript strict, Tailwind 4, ESLint, Prettier, Vitest.

- Server-side config parsing (`RELAY_API_URL`), health probe with runtime response validation, and one development status page showing API and database health.

**Infrastructure**

- `docker-compose.yml`: `db` (PostgreSQL 16.15), `migrate` (one-shot), `api`, `web`. Localhost-only ports, digest-pinned base images, non-root containers, health checks.
- `Makefile` as the developer interface; `make check` is the canonical verification.
- GitHub Actions: `make setup`, `make check`, then `make up` and `make smoke`.
- `.env.example`, root `.gitignore`.

### Changed from the plan, and why

| Change | Reason |
|---|---|
| Health endpoints are `/health` and `/health/ready`, not `/healthz`/`/readyz` | Requested for M0; "ready" is documented as the HTTP sense, not launch readiness. |
| npm instead of pnpm | pnpm via corepack failed on the development machine; npm ships with Node and removes a toolchain dependency. Lockfile is `web/package-lock.json`. |
| No `worker` service or `relay.jobs` package | The jobs table and worker belong to M3. Creating a worker process with nothing to do would be fake functionality. |
| No `fixtures/` or `evals/` directories | They would be empty until M1/M8. |
| Added `core/currency.py`, `core/timestamps.py`, `core/db_types.py`, `api/problems.py`, `api/middleware.py` | Separating these kept `money.py`, `dates.py` and `app.py` focused. |
| `httpx2` instead of `httpx` for the test client | Starlette 1.6 deprecates `httpx` for `TestClient`. |
| Web calls the API from the server only | Avoids exposing the API URL to browsers and needing CORS before any browser-side API use exists. |
| Import-linter has one contract (`api` → `core` layers) | The other contracts reference modules that do not exist yet; they are added with those modules. |

### Known warnings and limitations

- `pytest` ignores exactly one third-party `DeprecationWarning` raised when `starlette.testclient` is imported (a deprecated anyio alias). All other warnings fail tests.
- `eslint@9` prints an npm deprecation notice on install; it is the version `eslint-config-next@16.3.5` supports.
- GitHub Actions has not been run yet (no remote). Every CI step was run locally.
- Security headers do not yet include a Content Security Policy (SEC-15). A nonce-based CSP for Next.js is deferred until there is real UI.
- No authentication exists (planned for M3 as a development identity only).
- `web/AGENTS.md` and `web/CLAUDE.md` are written by `next dev` (Next.js 16) and point agents at the bundled Next.js docs. They are regenerated if deleted, so they are kept.
- Tests do not yet block network sockets globally (testing.md §1.4); the only network-shaped unit test targets a refused localhost port. Add socket blocking when external integrations appear.
- GitHub Actions are pinned by major version tag, not commit SHA.
