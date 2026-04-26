.PHONY: up down build logs ps migrate seed-cards capture-fixtures test lint

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

logs:
	docker compose logs -f backend

ps:
	docker compose ps

migrate:
	docker compose exec backend alembic upgrade head

seed-cards:
	docker compose exec backend python /app/scripts/seed_cards.py

capture-fixtures:
	cd backend && python -m scripts.capture_fixtures

test:
	cd backend && pytest tests/ -v

lint:
	cd backend && python -m py_compile app/**/*.py && echo "Syntax OK"

shell:
	docker compose exec backend bash

# Phase 1: run engine tests without Docker (pure Python)
test-engine:
	cd backend && python -m pytest tests/test_engine/ -v

test-cards:
	cd backend && python -m pytest tests/test_cards/ -v
