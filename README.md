# PokéPrism

PokéPrism is a self-hosted Pokémon TCG simulation and deck evolution engine. It runs automated Pokémon TCG Pocket simulations, records match and decision data, and uses local LLMs plus a persistent memory stack to analyze performance and evolve decks.

This project is intended for local/self-hosted experimentation and development, not as an official Pokémon product.

## Current status

PokéPrism has a working full-stack implementation with backend simulation services, a React frontend, Docker Compose infrastructure, database/memory services, and a broad implemented card pool. The current development status is tracked in [`docs/STATUS.md`](docs/STATUS.md).

The original phase buildout, Phase 13, and the 2026-05-03 hardening sweep are complete. Current work is ongoing post-phase development: DB-backed audits, card-effect correctness, handler implementation, simulation validation, AI/coach hardening, and operational refinement.

Do not rely on README card/test counts as live metrics. Use [`docs/STATUS.md`](docs/STATUS.md) for dated current-state snapshots and commands to re-check fast-changing values.

## What it does

PokéPrism provides:

- **Pokémon TCG simulation engine** with deterministic state transitions and comprehensive card effect handling
- **Multiple simulation modes**: heuristic-vs-heuristic (H/H), AI-vs-heuristic (AI/H), and AI-vs-AI modes for different speed/depth tradeoffs
- **Local LLM integration** through Ollama for AI-driven players and deck analysis
- **Coach/Analyst system** for full-deck analysis and evolution across simulation rounds
- **TCGDex-backed card data pipeline** — all card definitions sourced from the live TCGDex API
- **PostgreSQL + pgvector** for structured data storage and embedding similarity search
- **Neo4j graph layer** for card relationships, synergies, and decision history
- **Redis/Celery** for async simulation orchestration and task scheduling
- **FastAPI backend** with REST endpoints and Socket.IO streaming for real-time match viewing
- **React/Vite frontend** for full-deck simulation setup, live console viewing, dashboards, match history, and memory exploration
- **Docker Compose stack** for complete local service deployment

## Architecture

PokéPrism follows a layered architecture with clear separation between the game engine, player logic, orchestration, and data persistence:

```
Frontend (React/Vite)
       ↓ HTTP REST + Socket.IO
Backend (FastAPI)
   ├─ Game Engine (state machine, effect registry, action validation)
   ├─ Player Layer (heuristic, AI via Ollama, Coach/Analyst)
   ├─ Simulation Orchestrator
   └─ API Layer
       ↓
Services:
   ├─ PostgreSQL + pgvector (structured data + embeddings)
   ├─ Neo4j (graph relationships)
   ├─ Redis (broker/cache/pub-sub)
   ├─ Ollama (local LLM runtime)
   ├─ Celery Worker (async jobs)
   └─ Celery Beat (scheduled tasks)
```

**Service responsibilities:**

- `frontend`: React UI served via Nginx in production (port 3000), or Vite dev server (port 5173) in development
- `backend`: FastAPI application hosting the game engine, simulation orchestration, card services, and memory APIs (port 8000)
- `celery-worker`: Async simulation job execution
- `celery-beat`: Scheduled background tasks
- `postgres`: PostgreSQL 16 with pgvector extension for relational data and vector search (host port 5433)
- `neo4j`: Neo4j 5 for graph memory and card relationship storage (HTTP port 7474, Bolt port 7687)
- `redis`: Message broker, cache, and pub/sub (host port 6380)
- `ollama`: Local LLM inference runtime (port 11434) — requires GPU for AI simulation modes
- TCGDex: External live API for card definitions (https://api.tcgdex.net/v2/en)

## Repository layout

```
.
├── backend/              # FastAPI app, game engine, effects, players, memory, tasks, tests
│   ├── app/
│   │   ├── main.py       # Application factory
│   │   ├── api/          # REST endpoints + WebSocket manager
│   │   ├── engine/       # Core game state machine and effects
│   │   ├── players/      # Heuristic and AI player implementations
│   │   ├── cards/        # Card data models and TCGDex integration
│   │   ├── db/           # SQLAlchemy models and session management
│   │   ├── memory/       # Neo4j graph and pgvector services
│   │   └── tasks/        # Celery task definitions
│   ├── tests/            # Pytest test suite
│   ├── alembic/          # Database migrations
│   ├── pyproject.toml    # Python dependencies
│   └── Dockerfile
├── frontend/             # React/Vite UI
│   ├── src/
│   │   ├── pages/        # Route components
│   │   ├── components/   # Reusable UI components
│   │   └── stores/       # Zustand state management
│   ├── package.json      # Node.js dependencies
│   └── Dockerfile
├── docs/                 # Status, audit rules, historical blueprint, proposals
│   ├── STATUS.md         # Current implementation status (read this first!)
│   ├── CHANGELOG.md      # Evidence-based historical record
│   ├── AUDIT_RULES.md    # Active DB-backed card audit procedure
│   ├── AUDIT_STATE.md    # Active rotating audit cursor
│   ├── PROJECT.md        # Historical architecture blueprint/context
│   ├── POKEMON_MASTER_LIST.md  # Historical/supporting expansion-era list
│   └── ...
├── scripts/              # Utility scripts (card seeding, fixture capture)
├── docker-compose.yml    # Full local service stack
├── Makefile              # Common dev/test/service commands
├── .env.example          # Required environment variables
└── README.md             # This file
```

## Prerequisites

To run PokéPrism locally, you need:

- **Docker and Docker Compose** — for service orchestration
- **Python 3.12+** — for backend host development (optional, not needed for Docker-only usage)
- **Node.js 18+ and npm** — for frontend host development (optional)
- **NVIDIA GPU + NVIDIA Container Toolkit** — required for GPU-accelerated Ollama (AI simulation modes only)
  - H/H (heuristic-vs-heuristic) simulations do not require GPU
  - AI-backed modes (AI/H, AI/AI) depend on Ollama LLM inference

**Ollama models** (configurable in `.env`):
- Player model: `qwen3.5:9b-q4_K_M` (default)
- Coach model: `gemma4-e4b:q6_K` (default)
- Embedding model: `nomic-embed-text` (default)

These models must be available in your Ollama instance. Pull them with `ollama pull <model-name>` before starting the stack.

**TCGDex API access**: The system fetches card data from `https://api.tcgdex.net/v2/en` by default. No authentication is required for TCGDex, but internet connectivity is needed for card seeding.

## Configuration

1. Copy the environment variable template:
   ```bash
   cp .env.example .env
   ```

2. Edit `.env` and set the required credentials:
   ```bash
   POSTGRES_USER=pokeprism
   POSTGRES_PASSWORD=<your-postgres-password>
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=<your-neo4j-password>
   OLLAMA_PLAYER_MODEL=qwen3.5:9b-q4_K_M
   OLLAMA_COACH_MODEL=gemma4-e4b:q6_K
   OLLAMA_EMBED_MODEL=nomic-embed-text
   TCGDEX_BASE_URL=https://api.tcgdex.net/v2/en
   ```

Do not commit real passwords. The `.env` file is gitignored.

## Quick start

1. **Clone the repository:**
   ```bash
   git clone <repository-url>
   cd pokeprism
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your passwords
   ```

3. **Start all services:**
   ```bash
   make up
   ```
   This starts the full Docker Compose stack: frontend, backend, postgres, neo4j, redis, ollama, celery-worker, celery-beat.

4. **Run database migrations:**
   ```bash
   make migrate
   ```

5. **Seed card definitions from TCGDex:**
   ```bash
   make seed
   ```
   This populates PostgreSQL from the repository's current seed pipeline. The exact card count changes as card data and audit work evolve; see `docs/STATUS.md` for the latest dated snapshot and DB query.

6. **Access the application:**
   - **Frontend (production)**: http://localhost:3000
   - **Backend API**: http://localhost:8000
   - **Health check**: http://localhost:8000/health
   - **API docs**: http://localhost:8000/docs (Swagger UI)
   - **API docs (alternate)**: http://localhost:8000/redoc (ReDoc)
   - **Neo4j Browser**: http://localhost:7474 (credentials from `.env`)

7. **Check service health:**
   ```bash
   curl http://localhost:8000/health
   ```
   This shows the status of postgres, neo4j, redis, ollama, and celery workers.

## Local development

### Common Makefile commands

**Docker operations:**
```bash
make help           # Show all available commands
make up             # Start all services (docker compose up -d)
make down           # Stop all services
make build          # Rebuild containers (add ARGS=--no-cache for full rebuild)
make restart        # Restart backend + workers
make ps             # Show container status
make logs           # Tail backend logs
make logs-all       # Tail all service logs
make shell-backend  # Open bash shell in backend container
```

**Database operations:**
```bash
make migrate        # Run Alembic migrations (alembic upgrade head)
make seed           # Seed card pool from TCGDex
make reset-data     # Clear all simulation data (preserve card definitions)
```

**Host development (infrastructure in Docker, app on host):**
```bash
make dev            # Run backend + frontend on host concurrently
make dev-backend    # Run backend with uvicorn --reload on :8000
make dev-frontend   # Run Vite dev server on :5173
```

The `make dev` command runs the backend and frontend directly on your host machine while keeping postgres, neo4j, redis, ollama, and celery services in Docker. This provides fast hot-reload for code changes.

## Testing

### Running tests

```bash
make test           # Run all backend tests (pytest)
make test-engine    # Run engine tests with verbose output
make test-cards     # Run card-specific tests with verbose output
make lint           # Syntax-check all backend Python files
cd frontend && npm test       # Run frontend unit/component tests
cd frontend && npm run build  # Type-check and build the frontend bundle
docker compose config --quiet # Validate Docker Compose configuration
```

Backend tests use pytest and live in `backend/tests/`. Frontend tests use Vitest
and React Testing Library.

For current test baselines, see [`docs/STATUS.md`](docs/STATUS.md). The latest hardening report documents a full backend baseline of 374 passed / 4 skipped on 2026-05-03, but re-run the suite before publishing updated counts.

### Docker smoke checks

For a local end-to-end smoke pass, start or rebuild the services, verify health,
then submit one small H/H simulation for each deck mode:

```bash
docker compose up -d --build backend celery-worker frontend
curl -fsS http://localhost:8000/health
curl -fsS -I http://localhost:3000
```

Use `POST /api/simulations` with `deck_mode` set to `full`, `partial`, or
`none`. Partial mode must include a 1-59 card deck list; no-deck mode must omit
`deck_text`. The API returns `deck_build` metadata for partial and no-deck
submissions.

### Test structure

- `backend/tests/test_engine/` — Core engine logic, state transitions, action validation
- `backend/tests/test_cards/` — Card-specific effect implementations

### Validation requirements

Card effect changes should be validated against TCGDex fixtures or live TCGDex data. The project follows a **live-data-first principle**: avoid fabricated card data. Test fixtures are captured from TCGDex, not hand-invented.

Use `make capture-fixtures` to fetch live card data from TCGDex for test fixtures. `docs/POKEMON_MASTER_LIST.md` is retained as historical/supporting expansion-era input; it is not the active DB-backed audit authority.

## API and service endpoints

The backend exposes a REST API under the `/api` prefix and a Socket.IO endpoint for real-time simulation streaming.

**Core endpoints:**
- `GET /health` — Health check (postgres, neo4j, redis, ollama, celery status)
- `/api/simulations` — Simulation creation, status, control
- `/api/decks` — Deck management
- `/api/cards` — Card search and retrieval
- `/api/history` — Match history and replay
- `/api/memory` — Memory graph queries (Neo4j + pgvector)
- `/api/coverage` — Card handler coverage metrics
- `/socket.io` — WebSocket connection for live match streaming

**Interactive API documentation:**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

The API uses FastAPI's automatic OpenAPI schema generation, so endpoint details are always up-to-date at runtime.

## Data model and source-of-truth principles

PokéPrism adheres to strict data integrity principles:

### TCGDex is the card-data source of truth

- All card definitions are fetched from the live TCGDex API (https://api.tcgdex.net/v2/en)
- The project **does not fabricate card data** or use mock card factories
- Test fixtures are captured from live TCGDex responses, not hand-written
- If a card exists in the database, its data originates from TCGDex

### Memory system

The memory stack records match outcomes, decisions, card performance, embeddings, and graph relationships:

- **PostgreSQL**: Structured simulation data (matches, rounds, decks, card performance, embeddings)
- **pgvector**: Embedding similarity search for decision context retrieval
- **Neo4j**: Graph relationships among cards, synergies, decision chains, and matchup history

This memory grows with every simulation and is queried by AI players and the Coach to improve decision-making over time.

### Data integrity

- Card seeding: `make seed` fetches all cards from TCGDex and inserts them into PostgreSQL
- Schema migrations: `make migrate` applies Alembic migrations
- Data reset: `make reset-data` clears simulation data while preserving card definitions

## Documentation

Detailed technical documentation is available in the `docs/` directory:

- [`docs/STATUS.md`](docs/STATUS.md) — **Current state and operational handoff** (read this first)
- [`docs/CHANGELOG.md`](docs/CHANGELOG.md) — **Evidence-based historical record** of what changed and why
- [`docs/AUDIT_RULES.md`](docs/AUDIT_RULES.md) and [`docs/AUDIT_STATE.md`](docs/AUDIT_STATE.md) — **Active DB-backed card audit workflow**
- [`docs/PROJECT.md`](docs/PROJECT.md) — Historical project blueprint and architecture rationale
- [`docs/proposals/`](docs/proposals/) — Supporting proposals, assessments, accepted/rejected design notes
- [`docs/CARD_EXPANSION_RULES.md`](docs/CARD_EXPANSION_RULES.md), [`docs/CARDLIST.md`](docs/CARDLIST.md), and [`docs/POKEMON_MASTER_LIST.md`](docs/POKEMON_MASTER_LIST.md) — Historical or supporting expansion-era docs, not active audit authority

For deep architectural detail, implementation phases, database schemas, and engine specifications, see `docs/PROJECT.md`. For current implementation state, prefer `docs/STATUS.md`.

## Known limitations

PokéPrism is under active development. Known caveats and simplifications include:

- **Some card effects may be simplified**: Where the actual card text requires player choice, certain implementations use auto-selection (e.g., heal effects that pick targets automatically). These are documented in `docs/STATUS.md` under "Known Issues / Gaps."
- **Some effects are flagged for verification**: A small number of card implementations may not perfectly match the official card text and are marked for future verification against TCGDex.
- **LLM performance depends on hardware**: AI/AI simulations are significantly slower than H/H. Local LLM quality depends on GPU, model quantization, and Ollama configuration.
- **AI modes require GPU**: Heuristic simulations run on CPU, but AI-backed modes require a GPU-enabled Ollama instance.
- **Active development**: Post-phase audit, handler refinement, simulation validation, and operational hardening are ongoing.
- **Deck modes**: Full-deck, partial-deck completion, and no-deck/from-scratch simulations are runnable. Partial/no-deck modes use a conservative deterministic baseline `DeckBuilder` until enough historical match data exists for memory-optimized building.

For the full list of known issues and verification items, see [`docs/STATUS.md`](docs/STATUS.md).

## Roadmap

Current next steps are tracked in [`docs/STATUS.md`](docs/STATUS.md). Broad ongoing priorities are:

1. **Continue DB-backed card audits** — Cross-check database cards against live TCGDex data and current handlers
2. **Tuning & Evaluation** — Baseline win-rate benchmarks, coach quality metrics, simulation performance analysis
3. **Card-handler refinement** — Implement or correct handlers found by audits and coverage gates
4. **UI/analytics improvements** — Enhanced dashboards, better memory visualization, detailed match replays
5. **Production deployment hardening** — If public/hosted deployment is a goal

See [`docs/STATUS.md`](docs/STATUS.md) for the current handoff and [`docs/CHANGELOG.md`](docs/CHANGELOG.md) for completed historical work.

## Contributing and AI-agent workflow

Guidelines for contributors and AI coding assistants:

1. **Always read [`docs/STATUS.md`](docs/STATUS.md) before [`docs/PROJECT.md`](docs/PROJECT.md)** — `STATUS.md` reflects current implementation state; `PROJECT.md` is historical blueprint/context.
2. **Keep this README factual and in sync with implementation** — Do not document unimplemented features as if they exist.
3. **Validate card behavior against TCGDex** — Use live TCGDex data or captured fixtures. Do not invent card effects.
4. **Run tests after engine/card changes** — Use `make test`, `make test-engine`, or `make test-cards` to validate changes.
5. **Avoid mock card data** — Unless a test fixture was captured from live data, do not create fabricated card definitions.
6. **Update docs in the right place** — `STATUS.md` gets current operational state; `CHANGELOG.md` gets completed historical changes and evidence; audit cursor changes belong in `AUDIT_STATE.md` only after actual audits.

## Legal note

Pokémon, Pokémon TCG, Pokémon TCG Pocket, and related names are trademarks of their respective owners. PokéPrism is an unofficial fan/developer tool and is not affiliated with or endorsed by The Pokémon Company, Nintendo, Creatures, or Game Freak.

## License

No license file is currently present. Add one before distributing or accepting outside contributions.
