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
BACKEND_DB_ENV := RELAY_ENV=local RELAY_DATABASE_URL='$(HOST_DATABASE_URL)' RELAY_STORAGE_DIR=.data/blobs

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

.PHONY: dev dev-api dev-web worker up down logs smoke test-e2e
dev: db-migrate ## Run API (reload) and web (next dev) on the host against Compose PostgreSQL
	@trap 'kill 0' EXIT INT TERM; \
		$(MAKE) dev-api & \
		$(MAKE) dev-web & \
		wait

dev-api: ## Run only the API with auto-reload (expects migrated database)
	$(UV) env $(BACKEND_DB_ENV) RELAY_LOG_FORMAT=console \
		uvicorn relay.api.app:create_app --factory --reload --no-access-log \
		--host 127.0.0.1 --port $(RELAY_API_HOST_PORT)

worker: ## Run the job worker on the host (imports, pipeline runs) against Compose PostgreSQL
	$(UV) env $(BACKEND_DB_ENV) RELAY_LOG_FORMAT=console relay worker

dev-web: ## Run only the web dev server
	cd web && RELAY_API_URL=http://127.0.0.1:$(RELAY_API_HOST_PORT) \
		npm run dev -- --hostname 127.0.0.1 --port $(RELAY_WEB_HOST_PORT)

up: ## Build and start the full Compose stack (db, migrate, api, web) and wait for health
	docker compose up -d --build --wait

down: ## Stop the Compose stack (data volume is kept)
	docker compose down

logs: ## Follow Compose logs
	docker compose logs -f

smoke: ## Verify a running stack end to end: the web status page shows API and database healthy
	@curl -fsS http://127.0.0.1:$(RELAY_API_HOST_PORT)/health >/dev/null
	@curl -fsS http://127.0.0.1:$(RELAY_API_HOST_PORT)/health/ready >/dev/null
	@page=$$(curl -fsS http://127.0.0.1:$(RELAY_WEB_HOST_PORT)/status); \
		count=$$(grep -o 'UP (HTTP <!-- -->200<!-- -->)\|UP (HTTP 200)' <<<"$$page" | wc -l | tr -d ' '); \
		if [ "$$count" -ne 2 ]; then echo "smoke: expected 2 healthy checks on web page, found $$count"; exit 1; fi; \
		grep -q 'at_head' <<<"$$page" || { echo "smoke: migrations not at head"; exit 1; }
	@echo "smoke: web -> api -> database OK"

test-e2e: ## Playwright end-to-end tests against a freshly seeded stack (`make up`, then `make demo-seed` or `make demo-reset`); uses local Chrome
	cd web && E2E_BASE_URL=http://127.0.0.1:$(RELAY_WEB_HOST_PORT) E2E_API_URL=http://127.0.0.1:$(RELAY_API_HOST_PORT) \
		E2E_FAST_FORWARD="cd $(CURDIR) && $(MAKE) --no-print-directory demo-fast-forward" npx playwright test

# ------------------------------------------------------------------------------------ demo data

.PHONY: demo-ai demo-ai-off demo-data demo-kestrel demo-kestrel-check demo-kestrel-verify demo-check demo-verify demo-manifest demo-seed demo-reset demo-portfolio demo-fast-forward demo-seed-host verify-audit eval-ai eval-ai-scripted
demo-data: ## Generate Brightwater source fixtures into fixtures/demo/brightwater and print a summary
	$(UV) relay-demo generate

demo-seed: ## Load Brightwater into the running Compose stack (day-9 state) through the services; run `make up` first
	docker compose run --rm --no-deps -v "$(CURDIR)/fixtures:/fixtures:ro" api \
		relay-demo seed --fixtures /fixtures/demo/brightwater \
		--mapping-set /fixtures/demo/brightwater_config/column_mapping_set_v1.json

demo-reset: ## DESTROYS the local Compose database, recreates it, and seeds Brightwater again (E2E tests change the demo state)
	docker compose stop api worker
	docker compose exec -T db psql -U relay -d postgres -c 'DROP DATABASE IF EXISTS relay WITH (FORCE)' -c 'CREATE DATABASE relay'
	docker compose run --rm migrate
	docker compose up -d --wait api worker
	$(MAKE) demo-seed

demo-portfolio: ## With the stack up and seeded: add two more fictional migrations (one signed off, one early stage)
	docker compose run --rm --no-deps -v "$(CURDIR)/fixtures:/fixtures:ro" api \
		relay-demo seed-portfolio \
		--mapping-set /fixtures/demo/brightwater_config/column_mapping_set_v1.json

demo-ai: ## Turn on AI investigation for the demo: restart the stack with the demo provider and record consent through an approved policy change
	RELAY_AI_PROVIDER=demo docker compose up -d --build --wait
	docker compose run --rm --no-deps api relay-demo enable-ai
	@echo "AI investigation is on, replaying authored transcripts (no model, no key)."

demo-ai-off: ## Restart the stack with AI off (consent stays recorded; the provider is what changes)
	RELAY_AI_PROVIDER=disabled docker compose up -d --build --wait
	@echo "AI investigation is off."

demo-fast-forward: ## Apply the documented resolutions to the seeded Brightwater stack as the seeded users (demo step 10); needs `make up` and a seed
	docker compose run --rm --no-deps api relay-demo fast-forward --to before-signoff

eval-ai: ## MANUAL, COSTS MONEY: live investigator evals E1-E6 against a freshly seeded local database (needs ANTHROPIC_API_KEY); results in evals/results/
	$(UV) env $(BACKEND_DB_ENV) relay-eval ai --provider anthropic --out ../evals/results/investigator-$$(date -u +%Y%m%dT%H%M%SZ).json

eval-ai-scripted: ## Investigator evals E1-E6 with the scripted provider against the local seeded database (no model calls)
	$(UV) env $(BACKEND_DB_ENV) relay-eval ai --provider scripted

demo-seed-host: db-migrate ## Load Brightwater into the local database with host-run processes (stop the Compose worker first)
	$(UV) env $(BACKEND_DB_ENV) relay-demo seed

verify-audit: ## Verify every audit hash chain in the local database
	$(UV) env $(BACKEND_DB_ENV) relay verify-audit

demo-check: ## Verify committed Brightwater fixtures match a fresh generation byte for byte
	$(UV) relay-demo check

demo-kestrel: ## Generate the second company's fixtures (generalization test) into fixtures/demo/kestrel
	$(UV) relay-demo generate-kestrel

demo-kestrel-check: ## Verify committed second-company fixtures match a fresh generation byte for byte
	$(UV) relay-demo check-kestrel

demo-kestrel-verify: ## EVALUATION ONLY: run the engine over the second company and compare with its expectations
	$(UV) relay-eval verify-kestrel

demo-verify: ## EVALUATION ONLY: verify fixtures against the golden manifest
	$(UV) relay-eval verify-brightwater

demo-manifest: ## EVALUATION ONLY: print the golden manifest (reveals expected answers)
	$(UV) relay-eval show-manifest

# ------------------------------------------------------------------------------------ engine

.PHONY: engine-run engine-perf pipeline-perf openapi
engine-run: ## Run the deterministic engine over the Brightwater fixtures (Run #1) and print gates and findings
	$(UV) relay engine run --migration ../fixtures/demo/brightwater --mapping-set ../fixtures/demo/brightwater_config/column_mapping_set_v1.json

openapi: ## Regenerate web/src/lib/api/openapi.json from the API (a unit test fails on drift)
	$(UV) python -m relay.api.openapi

engine-perf: ## Measure the engine on a synthetic clean 250,000-line migration (about a minute)
	$(UV) relay-demo perf-engine --lines 250000

PERF_DB_ENV = RELAY_ENV=local RELAY_DATABASE_URL='$(PERF_DATABASE_URL)' RELAY_STORAGE_DIR=.data/perf-blobs
PERF_DATABASE_URL := postgresql+psycopg://relay:$(RELAY_DB_PASSWORD)@127.0.0.1:$(RELAY_DB_HOST_PORT)/relay_perf
pipeline-perf: db-up ## Measure imports, runs, readiness and reads on a synthetic 250,000-line migration in a throwaway database (several minutes)
	docker compose exec -T db psql -U relay -d postgres -c 'DROP DATABASE IF EXISTS relay_perf WITH (FORCE)'
	docker compose exec -T db psql -U relay -d postgres -c 'CREATE DATABASE relay_perf'
	rm -rf backend/.data/perf-blobs
	$(UV) env $(PERF_DB_ENV) alembic upgrade head
	$(UV) env $(PERF_DB_ENV) relay-demo perf-pipeline --lines 250000
	rm -rf backend/.data/perf-blobs
	docker compose exec -T db psql -U relay -d postgres -c 'DROP DATABASE IF EXISTS relay_perf WITH (FORCE)'

# ------------------------------------------------------------------------------------ build & verify

.PHONY: build build-web compose-config compose-build check test-all clean
build: build-web compose-build ## Production web build and Docker images

build-web: ## Next.js production build
	$(NPM) run build

compose-config: ## Validate docker-compose.yml
	docker compose config --quiet

compose-build: ## Build Docker images
	docker compose build

check: fmt-check lint typecheck test demo-check demo-verify demo-kestrel-check demo-kestrel-verify test-integration build-web compose-config ## Full verification (CI runs this)
	@echo "make check: all checks passed"

test-all: ## Everything, from a clean clone: make check, then build the stack, seed it and run the end-to-end suite
	$(MAKE) check
	$(MAKE) up
	$(MAKE) smoke
	$(MAKE) demo-reset
	$(MAKE) test-e2e
	@echo "make test-all: checks, stack and end-to-end suite all passed"

clean: ## Remove caches and build output (keeps dependencies and database volume)
	rm -rf backend/.mypy_cache backend/.ruff_cache backend/.pytest_cache backend/.hypothesis backend/.import_linter_cache
	find backend -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf web/.next web/coverage web/tsconfig.tsbuildinfo
