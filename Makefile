.PHONY: help install dev api test lint format typecheck migrate migration up down logs reset-db check

COMPOSE := docker compose --env-file .env -f infra/docker/docker-compose.dev.yml
ALEMBIC := cd apps/api && uv run --project ../.. alembic

help:  ## Show available targets
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install:  ## Install all workspace dependencies
	uv sync --extra dev

up:  ## Start local dependencies (Postgres, Qdrant, Redis, MinIO)
	$(COMPOSE) up -d
	@echo "Waiting for health..." && sleep 8 && $(COMPOSE) ps

down:  ## Stop local dependencies
	$(COMPOSE) down

logs:  ## Tail dependency logs
	$(COMPOSE) logs -f

migrate:  ## Apply all migrations
	$(ALEMBIC) upgrade head

migration:  ## Autogenerate a migration: make migration m="add x"
	$(ALEMBIC) revision --autogenerate -m "$(m)"

reset-db:  ## Drop and rebuild the schema from migrations
	$(ALEMBIC) downgrade base && $(ALEMBIC) upgrade head

api:  ## Run the API with reload
	uv run uvicorn course_tutor_api.app:create_app --factory --reload --port 8080

dev: up migrate api  ## Start dependencies, migrate, then run the API

test:  ## Run the test suite
	uv run pytest

lint:  ## Check formatting and lint rules
	uv run ruff check .
	uv run ruff format --check .

format:  ## Apply formatting and safe lint fixes
	uv run ruff format .
	uv run ruff check --fix .

typecheck:  ## Run mypy
	uv run mypy packages apps

check: lint typecheck test  ## Everything CI runs
