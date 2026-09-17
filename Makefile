# Relay developer interface. `make help` lists targets; `make check` is the canonical full verification.
#
# Requirements: uv, Node.js 24 + npm, Docker with Compose v2.
# Local overrides (ports, dev DB password) go in .env; see .env.example.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help
MAKEFLAGS += --no-print-directory

-include .env

RELAY_DB_PASSWORD ?= relay_local_dev_only
RELAY_DB_HOST_PORT ?= 55432
RELAY_API_HOST_PORT ?= 8000
RELAY_WEB_HOST_PORT ?= 3000

HOST_DATABASE_URL := postgresql+psycopg://relay:$(RELAY_DB_PASSWORD)@127.0.0.1:$(RELAY_DB_HOST_PORT)/relay
TEST_DATABASE_URL := postgresql+psycopg://relay:$(RELAY_DB_PASSWORD)@127.0.0.1:$(RELAY_DB_HOST_PORT)/relay_test

export NEXT_TELEMETRY_DISABLED := 1
export RELAY_DB_PASSWORD RELAY_DB_HOST_PORT RELAY_API_HOST_PORT RELAY_WEB_HOST_PORT

UV := cd backend && uv run --locked
NPM := cd web && npm
BACKEND_DB_ENV := RELAY_ENV=local RELAY_DATABASE_URL='$(HOST_DATABASE_URL)'

.PHONY: help
help: ## List available targets
	@grep -hE '^[a-zA-Z0-9_-]+:.*## ' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ------------------------------------------------------------------------------------ setup

.PHONY: setup setup-backend setup-web
setup: setup-backend setup-web ## Install backend and web dependencies from lockfiles

setup-backend:
	cd backend && uv sync --locked

setup-web:
	$(NPM) ci --no-audit --no-fund

# ------------------------------------------------------------------------------------ quality

.PHONY: fmt fmt-check lint typecheck
fmt: ## Format all code (ruff, prettier)
	$(UV) ruff format .
	$(UV) ruff check --select I --fix .
	$(NPM) run format

fmt-check: ## Check formatting without changing files
	$(UV) ruff format --check .
	$(NPM) run format:check

lint: ## Lint Python (ruff, import contracts) and TypeScript (eslint)
	$(UV) ruff check .
	$(UV) lint-imports
	$(NPM) run lint

typecheck: ## Static type checks (mypy --strict, tsc --noEmit)
	$(UV) mypy
	$(NPM) run typecheck

# ------------------------------------------------------------------------------------ tests

.PHONY: test test-backend test-web test-integration
test: test-backend test-web ## Unit and property tests (no database)

test-backend:
	$(UV) pytest -m "not integration"

test-web:
	$(NPM) test

test-integration: db-up ## Integration tests against Compose PostgreSQL (uses database relay_test)
	$(UV) env RELAY_TEST_DATABASE_URL='$(TEST_DATABASE_URL)' pytest -m integration

# ------------------------------------------------------------------------------------ database

.PHONY: db-up db-stop db-migrate db-downgrade db-current db-revision
db-up: ## Start PostgreSQL 16 and wait until healthy
	docker compose up -d --wait db

db-stop: ## Stop PostgreSQL (data volume is kept)
	docker compose stop db

db-migrate: db-up ## Apply Alembic migrations to the local database
	$(UV) env $(BACKEND_DB_ENV) alembic upgrade head

db-downgrade: db-up ## Roll back the most recent migration
	$(UV) env $(BACKEND_DB_ENV) alembic downgrade -1

db-current: db-up ## Show the current migration revision
	$(UV) env $(BACKEND_DB_ENV) alembic current

db-revision: ## Create an empty migration: make db-revision m="add imports table"
	@test -n "$(m)" || (echo 'usage: make db-revision m="message"' && exit 1)
	$(UV) env RELAY_DATABASE_URL='$(HOST_DATABASE_URL)' alembic revision -m "$(m)"

# ------------------------------------------------------------------------------------ run

.PHONY: dev dev-api dev-web up down logs smoke
dev: db-migrate ## Run API (reload) and web (next dev) on the host against Compose PostgreSQL
	@trap 'kill 0' EXIT INT TERM; \
		$(MAKE) dev-api & \
		$(MAKE) dev-web & \
		wait

dev-api: ## Run only the API with auto-reload (expects migrated database)
	$(UV) env $(BACKEND_DB_ENV) RELAY_LOG_FORMAT=console \
		uvicorn relay.api.app:create_app --factory --reload --no-access-log \
		--host 127.0.0.1 --port $(RELAY_API_HOST_PORT)

dev-web: ## Run only the web dev server
	cd web && RELAY_API_URL=http://127.0.0.1:$(RELAY_API_HOST_PORT) \
		npm run dev -- --hostname 127.0.0.1 --port $(RELAY_WEB_HOST_PORT)

up: ## Build and start the full Compose stack (db, migrate, api, web) and wait for health
	docker compose up -d --build --wait

down: ## Stop the Compose stack (data volume is kept)
	docker compose down

logs: ## Follow Compose logs
	docker compose logs -f

smoke: ## Verify a running stack end to end: web page shows API and database healthy
	@curl -fsS http://127.0.0.1:$(RELAY_API_HOST_PORT)/health >/dev/null
	@curl -fsS http://127.0.0.1:$(RELAY_API_HOST_PORT)/health/ready >/dev/null
	@page=$$(curl -fsS http://127.0.0.1:$(RELAY_WEB_HOST_PORT)/); \
		count=$$(grep -o 'UP (HTTP <!-- -->200<!-- -->)\|UP (HTTP 200)' <<<"$$page" | wc -l | tr -d ' '); \
		if [ "$$count" -ne 2 ]; then echo "smoke: expected 2 healthy checks on web page, found $$count"; exit 1; fi; \
		grep -q 'at_head' <<<"$$page" || { echo "smoke: migrations not at head"; exit 1; }
	@echo "smoke: web -> api -> database OK"

# ------------------------------------------------------------------------------------ build & verify

.PHONY: build build-web compose-config compose-build check clean
build: build-web compose-build ## Production web build and Docker images

build-web: ## Next.js production build
	$(NPM) run build

compose-config: ## Validate docker-compose.yml
	docker compose config --quiet

compose-build: ## Build Docker images
	docker compose build

check: fmt-check lint typecheck test test-integration build-web compose-config ## Full verification (CI runs this)
	@echo "make check: all checks passed"

clean: ## Remove caches and build output (keeps dependencies and database volume)
	rm -rf backend/.mypy_cache backend/.ruff_cache backend/.pytest_cache backend/.hypothesis backend/.import_linter_cache
	find backend -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf web/.next web/coverage web/tsconfig.tsbuildinfo
