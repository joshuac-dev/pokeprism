.PHONY: up down build logs logs-all ps migrate seed seed-cards capture-fixtures test lint \
        dev dev-backend dev-frontend restart shell-backend

# ── Docker Compose ────────────────────────────────────────────────────────────

up:
	docker compose up -d

down:
	docker compose down

build:
	docker compose build

restart:
	docker compose restart backend celery-worker celery-beat

ps:
	docker compose ps

logs:
	docker compose logs -f backend

logs-all:
	docker compose logs -f

shell-backend:
	docker compose exec backend bash

# ── Database ──────────────────────────────────────────────────────────────────

migrate:
	docker compose exec backend alembic upgrade head

seed:
	docker compose exec backend python /app/scripts/seed_cards.py

seed-cards:
	docker compose exec backend python /app/scripts/seed_cards.py

capture-fixtures:
	cd backend && python -m scripts.capture_fixtures

# ── Tests ─────────────────────────────────────────────────────────────────────

test:
	cd backend && python3 -m pytest tests/ -x -q

test-engine:
	cd backend && python3 -m pytest tests/test_engine/ -v

test-cards:
	cd backend && python3 -m pytest tests/test_cards/ -v

# ── Linting ───────────────────────────────────────────────────────────────────

lint:
	cd backend && python -m py_compile app/**/*.py && echo "Syntax OK"

# ── Dev (host) ────────────────────────────────────────────────────────────────
# Run backend + frontend directly on the host (outside Docker) for development.
# Requires: postgres/redis/neo4j/ollama running via `make up`.

dev-backend:
	cd backend && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

dev-frontend:
	cd frontend && npm run dev

dev:
	$(MAKE) -j2 dev-backend dev-frontend
