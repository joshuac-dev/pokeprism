# PokéPrism — Project Blueprint

> **Purpose of this document:** This is the authoritative technical blueprint for PokéPrism. Any AI coding assistant (GitHub Copilot, Claude, etc.) should read this file **in full** before writing any code. It defines architecture, data contracts, schemas, implementation order, and decision rationale. When in doubt, this document is the source of truth.

> **Live-Data-First Principle:** This project is built against live data from day one. There are no mock data factories, no placeholder card definitions, no fake match generators. Every layer is wired to real TCGDex API responses, real Ollama inference, and real PostgreSQL/Neo4j storage from the moment it’s implemented. Test suites use fixtures captured from live sources, not invented schemas. This prevents the “works on mocks, breaks on real data” failure mode.

-----

## Table of Contents

1. [Project Overview](#1-project-overview)
1. [Architecture Overview](#2-architecture-overview)
1. [Technology Stack](#3-technology-stack)
1. [Repository Structure](#4-repository-structure)
1. [Docker Compose Infrastructure](#5-docker-compose-infrastructure)
1. [Phase 1 — Game Engine Core](#6-phase-1--game-engine-core)
1. [Phase 2 — Card Data Pipeline & Effect Registry](#7-phase-2--card-data-pipeline--effect-registry)
1. [Phase 3 — Heuristic Player & H/H Simulation Loop](#8-phase-3--heuristic-player--hh-simulation-loop)
1. [Phase 4 — Database Layer & Memory Stack](#9-phase-4--database-layer--memory-stack)
1. [Phase 5 — AI Player Integration (Ollama)](#10-phase-5--ai-player-integration-ollama)
1. [Phase 6 — Coach/Analyst System](#11-phase-6--coachanalyst-system)
1. [Phase 7 — Task Queue & Simulation Orchestration](#12-phase-7--task-queue--simulation-orchestration)
1. [Phase 8 — Frontend: Core Layout & Simulation Setup](#13-phase-8--frontend-core-layout--simulation-setup)
1. [Phase 9 — Frontend: Live Console & Match Viewer](#14-phase-9--frontend-live-console--match-viewer)
1. [Phase 10 — Frontend: Reporting Dashboard](#15-phase-10--frontend-reporting-dashboard)
1. [Phase 11 — Frontend: History & Memory Pages](#16-phase-11--frontend-history--memory-pages)
1. [Phase 12 — Card Pool Expansion](#17-phase-12--card-pool-expansion)
1. [Phase 13 — Polish, Hardening & Scheduling](#18-phase-13--polish-hardening--scheduling)
1. [Appendix A — Game Engine State Machine Specification](#19-appendix-a--game-engine-state-machine-specification)
1. [Appendix B — Database Schema (PostgreSQL)](#20-appendix-b--database-schema-postgresql)
1. [Appendix C — Graph Schema (Neo4j)](#21-appendix-c--graph-schema-neo4j)
1. [Appendix D — Coach Prompting Strategy](#22-appendix-d--coach-prompting-strategy)
1. [Appendix E — API Endpoint Reference](#23-appendix-e--api-endpoint-reference)
1. [Appendix F — WebSocket Event Protocol](#24-appendix-f--websocket-event-protocol)
1. [Appendix G — TCGDex Card Data Contract](#25-appendix-g--tcgdex-card-data-contract)
1. [Appendix H — Deck Format Specification](#26-appendix-h--deck-format-specification)
1. [Appendix I — Heuristic Player Decision Trees](#27-appendix-i--heuristic-player-decision-trees)
1. [Appendix J — Card Effect Implementation Guide](#28-appendix-j--card-effect-implementation-guide)

-----

## 1. Project Overview

PokéPrism is a self-hosted Pokémon TCG simulation and deck evolution engine. It plays automated matches between decks using configurable player types (heuristic rules or AI inference via Ollama), logs every decision to a persistent memory stack, and uses a Coach/Analyst AI to iteratively improve decks between rounds of play.

### Core Concept

The system does NOT fine-tune AI models. Instead, it builds an ever-growing memory graph of card performance, decision outcomes, matchup data, and synergy relationships. The AI players and Coach query this memory to make progressively better decisions as more simulation data accumulates. Think of it as giving the AI an expanding library of experience rather than rewiring its brain.

### Three Simulation Tiers

|Tier |Player 1       |Player 2       |Speed            |Data Quality             |GPU Usage|
|-----|---------------|---------------|-----------------|-------------------------|---------|
|H/H  |Heuristic      |Heuristic      |~50-100 games/min|Rough statistical data   |None     |
|AI/H |AI (Qwen3.5-9B)|Heuristic      |~2-5 games/min   |AI reasoning + stats     |Medium   |
|AI/AI|AI (Qwen3.5-9B)|AI (Qwen3.5-9B)|~0.5-1 games/min |Full reasoning both sides|High     |

### Three Deck Modes

|Mode                |Input                |Coach Behavior                                    |
|--------------------|---------------------|--------------------------------------------------|
|Full Deck (Locked)  |Complete 60-card deck|No modifications allowed; pure performance testing|
|Full Deck (Unlocked)|Complete 60-card deck|May swap up to 4 cards between rounds             |
|Partial Deck        |Incomplete deck      |Completes deck from memory, then evolves          |
|No Deck             |Nothing              |Builds entire deck from memory, avoids known meta |

-----

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        React Frontend                           │
│  (Vite + Tailwind + Recharts + D3 + xterm.js + TanStack Table) │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP REST + WebSocket (socket.io)
┌──────────────────────────▼──────────────────────────────────────┐
│                     FastAPI Application                          │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────────────┐  │
│  │ REST API │  │ WS Manager   │  │ Simulation Orchestrator   │  │
│  └──────────┘  └──────────────┘  └───────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                    Game Engine                            │   │
│  │  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐  │   │
│  │  │ State Machine│  │ Effect Engine │  │ Action Validator│  │   │
│  │  └─────────────┘  └──────────────┘  └────────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                   Player Layer                            │   │
│  │  ┌──────────┐  ┌──────────────┐  ┌────────────────────┐  │   │
│  │  │ Heuristic │  │ AI Player    │  │ Coach/Analyst      │  │   │
│  │  │ Player    │  │ (Qwen3.5-9B)│  │ (Gemma 4 E4B)     │  │   │
│  │  └──────────┘  └──────────────┘  └────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────┬───────────────┬───────────────┬──────────────────────┘
           │               │               │
    ┌──────▼──────┐  ┌─────▼─────┐  ┌──────▼──────┐
    │ PostgreSQL  │  │   Neo4j   │  │   Ollama    │
    │ + pgvector  │  │  (Graph)  │  │  (GPU/3070) │
    └─────────────┘  └───────────┘  └─────────────┘
           │
    ┌──────▼──────┐
    │    Redis    │
    │ (Celery +  │
    │  pub/sub)  │
    └─────────────┘
```

-----

## 3. Technology Stack

### Backend

|Component     |Technology     |Version|Purpose                                       |
|--------------|---------------|-------|----------------------------------------------|
|API Framework |FastAPI        |0.115+ |REST API, WebSocket, async orchestration      |
|Task Queue    |Celery         |5.4+   |Async simulation jobs, scheduling             |
|Message Broker|Redis          |7.x    |Celery broker, WebSocket pub/sub, caching     |
|RDBMS         |PostgreSQL     |16+    |Structured data (matches, decks, stats)       |
|Vector Search |pgvector       |0.7+   |Embedding similarity for decision context     |
|Graph DB      |Neo4j          |5.x    |Card synergies, decision chains, matchup graph|
|AI Runtime    |Ollama         |Latest |Local LLM inference (Qwen3.5-9B, Gemma 4 E4B) |
|Python        |3.12+          |—      |All backend code                              |
|ORM           |SQLAlchemy 2.0 |—      |Async PostgreSQL access                       |
|Migrations    |Alembic        |—      |Schema versioning                             |
|Neo4j Driver  |neo4j (Python) |5.x    |Graph queries                                 |
|WebSocket     |python-socketio|5.x    |Real-time match streaming                     |
|HTTP Client   |httpx          |—      |TCGDex API, Ollama API calls                  |

### Frontend

|Component|Technology      |Version|Purpose                             |
|---------|----------------|-------|------------------------------------|
|Framework|React           |18+    |UI framework                        |
|Bundler  |Vite            |5+     |Fast dev server, HMR                |
|Styling  |Tailwind CSS    |3.x    |Utility-first CSS                   |
|Charts   |Recharts        |2.x    |Win rates, distributions, prize race|
|Graph Viz|D3.js           |7.x    |Decision maps, memory mind-map      |
|Terminal |xterm.js        |5.x    |Live simulation console             |
|Data Grid|TanStack Table  |8.x    |History page, filterable tables     |
|WebSocket|socket.io-client|4.x    |Real-time event streaming           |
|State    |Zustand         |4.x    |Lightweight global state            |
|Router   |React Router    |6.x    |Page navigation                     |
|HTTP     |Axios           |1.x    |REST API calls                      |
|Icons    |Lucide React    |—      |UI iconography                      |

### Infrastructure

|Component       |Technology              |Purpose                    |
|----------------|------------------------|---------------------------|
|Containerization|Docker + Docker Compose |Service orchestration      |
|GPU Passthrough |NVIDIA Container Toolkit|RTX 3070 → Ollama          |
|Reverse Proxy   |Nginx                   |Frontend serving, API proxy|
|OS              |Ubuntu 24.04 (host)     |Server OS                  |

-----

## 4. Repository Structure

```
pokeprism/
├── docker-compose.yml
├── docker-compose.override.yml        # Local dev overrides
├── .env.example                        # Environment variable template
├── Makefile                            # Common commands (make up, make migrate, etc.)
│
├── docs/
│   ├── PROJECT.md                      # THIS FILE
│   ├── POKEMON_MASTER_LIST.md          # Current master list of all cards in scope
│   ├── CARDLIST.md                     # Retired compatibility note
│   └── CHANGELOG.md
│
├── backend/
│   ├── Dockerfile
│   ├── pyproject.toml                  # Poetry/uv project config
│   ├── alembic.ini
│   ├── alembic/
│   │   └── versions/                   # Migration files
│   │
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                     # FastAPI app factory
│   │   ├── config.py                   # Pydantic Settings (env-driven)
│   │   ├── dependencies.py             # FastAPI dependency injection
│   │   │
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── router.py               # Top-level router aggregator
│   │   │   ├── simulations.py          # /api/simulations endpoints
│   │   │   ├── decks.py                # /api/decks endpoints
│   │   │   ├── cards.py                # /api/cards endpoints
│   │   │   ├── history.py              # /api/history endpoints
│   │   │   ├── memory.py               # /api/memory endpoints
│   │   │   └── ws.py                   # WebSocket manager (socket.io)
│   │   │
│   │   ├── engine/
│   │   │   ├── __init__.py
│   │   │   ├── state.py                # GameState, Zone enums, data classes
│   │   │   ├── actions.py              # Action types, ActionValidator
│   │   │   ├── transitions.py          # State transition functions
│   │   │   ├── rules.py                # Rule enforcement (deck size, prize count, etc.)
│   │   │   ├── effects/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── registry.py         # EffectRegistry singleton
│   │   │   │   ├── base.py             # BaseEffect abstract class
│   │   │   │   ├── abilities.py        # Ability effect implementations
│   │   │   │   ├── attacks.py          # Attack effect implementations
│   │   │   │   ├── trainers.py         # Trainer card effect implementations
│   │   │   │   └── energies.py         # Special energy effect implementations
│   │   │   └── runner.py               # MatchRunner orchestrator
│   │   │
│   │   ├── players/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                 # PlayerInterface ABC
│   │   │   ├── heuristic.py            # HeuristicPlayer
│   │   │   └── ai_player.py            # AIPlayer (Ollama-backed)
│   │   │
│   │   ├── coach/
│   │   │   ├── __init__.py
│   │   │   ├── analyst.py              # CoachAnalyst main class
│   │   │   ├── deck_builder.py         # Deck completion/creation from memory
│   │   │   └── prompts.py              # Prompt templates for Coach
│   │   │
│   │   ├── cards/
│   │   │   ├── __init__.py
│   │   │   ├── loader.py               # POKEMON_MASTER_LIST.md parser + TCGDex sync
│   │   │   ├── models.py               # Card Pydantic models
│   │   │   └── tcgdex.py               # TCGDex API client
│   │   │
│   │   ├── memory/
│   │   │   ├── __init__.py
│   │   │   ├── postgres.py             # SQLAlchemy models & queries
│   │   │   ├── vectors.py              # pgvector embedding operations
│   │   │   ├── graph.py                # Neo4j graph operations
│   │   │   └── embeddings.py           # Embedding generation (via Ollama)
│   │   │
│   │   ├── tasks/
│   │   │   ├── __init__.py
│   │   │   ├── celery_app.py           # Celery configuration
│   │   │   ├── simulation.py           # Simulation task definitions
│   │   │   └── scheduled.py            # Periodic H/H tasks
│   │   │
│   │   └── db/
│   │       ├── __init__.py
│   │       ├── session.py              # Async SQLAlchemy session factory
│   │       ├── base.py                 # Declarative base
│   │       └── models.py               # All SQLAlchemy ORM models
│   │
│   └── tests/
│       ├── conftest.py                 # Shared fixtures (live-captured card data, etc.)
│       ├── fixtures/                   # JSON fixtures captured from TCGDex
│       ├── test_engine/
│       ├── test_players/
│       ├── test_coach/
│       ├── test_cards/
│       └── test_memory/
│
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf                      # Production Nginx config
│   ├── package.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   │
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── router.tsx                  # React Router config
│   │   │
│   │   ├── api/
│   │   │   ├── client.ts               # Axios instance
│   │   │   ├── simulations.ts          # Simulation API calls
│   │   │   ├── decks.ts                # Deck API calls
│   │   │   ├── history.ts              # History API calls
│   │   │   └── memory.ts               # Memory API calls
│   │   │
│   │   ├── stores/
│   │   │   ├── simulationStore.ts      # Zustand store for active simulation
│   │   │   ├── historyStore.ts
│   │   │   └── uiStore.ts
│   │   │
│   │   ├── hooks/
│   │   │   ├── useSocket.ts            # socket.io connection hook
│   │   │   ├── useSimulation.ts
│   │   │   └── useCardSearch.ts
│   │   │
│   │   ├── pages/
│   │   │   ├── SimulationSetup.tsx      # Deck upload, params, submit
│   │   │   ├── SimulationLive.tsx       # Console + deck changes during run
│   │   │   ├── Dashboard.tsx            # Post-simulation reporting
│   │   │   ├── History.tsx              # All simulations list
│   │   │   └── Memory.tsx              # Card/decision search + mind map
│   │   │
│   │   ├── components/
│   │   │   ├── layout/
│   │   │   │   ├── Sidebar.tsx
│   │   │   │   ├── TopBar.tsx
│   │   │   │   └── PageShell.tsx
│   │   │   ├── simulation/
│   │   │   │   ├── DeckUploader.tsx
│   │   │   │   ├── ParamForm.tsx
│   │   │   │   ├── OpponentDeckList.tsx
│   │   │   │   ├── LiveConsole.tsx      # xterm.js wrapper
│   │   │   │   ├── DeckChangesTile.tsx
│   │   │   │   └── DecisionDetail.tsx
│   │   │   ├── dashboard/
│   │   │   │   ├── WinRateCard.tsx
│   │   │   │   ├── MatchupMatrix.tsx
│   │   │   │   ├── PrizeRaceGraph.tsx
│   │   │   │   ├── DecisionMap.tsx
│   │   │   │   ├── CardHeatMap.tsx
│   │   │   │   ├── MutationDiffLog.tsx
│   │   │   │   └── WinRateDistribution.tsx
│   │   │   ├── history/
│   │   │   │   ├── SimulationTable.tsx
│   │   │   │   └── CompareModal.tsx
│   │   │   └── memory/
│   │   │       ├── SearchBar.tsx
│   │   │       ├── CardProfile.tsx
│   │   │       └── MindMapGraph.tsx     # D3 force-directed graph
│   │   │
│   │   └── utils/
│   │       ├── deckParser.ts            # Parse PTCG deck format
│   │       └── formatters.ts
│   │
│   └── public/
│       └── favicon.svg
│
└── scripts/
    ├── seed_cards.py                    # One-shot: load POKEMON_MASTER_LIST.md → TCGDex → DB
    ├── capture_fixtures.py              # Capture live TCGDex responses for test fixtures
    └── generate_cardlist_stubs.py       # Generate skeleton effect files for cards
```

-----

## 5. Docker Compose Infrastructure

### `docker-compose.yml`

```yaml
services:
  # ── AI Runtime ──────────────────────────────────────────
  ollama:
    image: ollama/ollama:latest
    container_name: pokeprism-ollama
    restart: unless-stopped
    ports:
      - "11434:11434"
    volumes:
      - ollama_data:/root/.ollama
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 30s
      timeout: 10s
      retries: 5

  # ── Databases ───────────────────────────────────────────
  postgres:
    image: pgvector/pgvector:pg16
    container_name: pokeprism-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: pokeprism
      POSTGRES_USER: ${POSTGRES_USER:-pokeprism}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}
    ports:
      - "5433:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./backend/init.sql:/docker-entrypoint-initdb.d/init.sql
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-pokeprism}"]
      interval: 10s
      timeout: 5s
      retries: 5

  neo4j:
    image: neo4j:5-community
    container_name: pokeprism-neo4j
    restart: unless-stopped
    environment:
      NEO4J_AUTH: ${NEO4J_USER:-neo4j}/${NEO4J_PASSWORD:?Set NEO4J_PASSWORD in .env}
      NEO4J_PLUGINS: '["apoc"]'
    ports:
      - "7474:7474"   # Browser
      - "7687:7687"   # Bolt
    volumes:
      - neo4j_data:/data
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 15s
      timeout: 10s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: pokeprism-redis
    restart: unless-stopped
    ports:
      - "6380:6379"
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 5

  # ── Application ─────────────────────────────────────────
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: pokeprism-backend
    restart: unless-stopped
    ports:
      - "8000:8000"
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-pokeprism}:${POSTGRES_PASSWORD}@postgres:5432/pokeprism
      REDIS_URL: redis://redis:6379/0
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: ${NEO4J_USER:-neo4j}
      NEO4J_PASSWORD: ${NEO4J_PASSWORD}
      OLLAMA_BASE_URL: http://ollama:11434
    depends_on:
      postgres:
        condition: service_healthy
      neo4j:
        condition: service_healthy
      redis:
        condition: service_healthy
      ollama:
        condition: service_healthy
    volumes:
      - ./backend/app:/app/app   # Hot reload in dev

  celery-worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: pokeprism-celery-worker
    restart: unless-stopped
    command: celery -A app.tasks.celery_app worker --loglevel=info --concurrency=2
    env_file: .env
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-pokeprism}:${POSTGRES_PASSWORD}@postgres:5432/pokeprism
      REDIS_URL: redis://redis:6379/0
      NEO4J_URI: bolt://neo4j:7687
      NEO4J_USER: ${NEO4J_USER:-neo4j}
      NEO4J_PASSWORD: ${NEO4J_PASSWORD}
      OLLAMA_BASE_URL: http://ollama:11434
    depends_on:
      - backend
      - redis

  celery-beat:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: pokeprism-celery-beat
    restart: unless-stopped
    command: celery -A app.tasks.celery_app beat --loglevel=info
    env_file: .env
    environment:
      REDIS_URL: redis://redis:6379/0
    depends_on:
      - redis

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: pokeprism-frontend
    restart: unless-stopped
    ports:
      - "3000:80"
    depends_on:
      - backend

volumes:
  ollama_data:
  postgres_data:
  neo4j_data:
  redis_data:
```

### `init.sql` (PostgreSQL initialization)

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- Fuzzy text search for card names
```

### `.env.example`

```env
POSTGRES_USER=pokeprism
POSTGRES_PASSWORD=changeme_postgres
NEO4J_USER=neo4j
NEO4J_PASSWORD=changeme_neo4j
OLLAMA_PLAYER_MODEL=qwen3.5:9b-q4_K_M
OLLAMA_COACH_MODEL=gemma4-e4b:q6_K
OLLAMA_EMBED_MODEL=nomic-embed-text
TCGDEX_BASE_URL=https://api.tcgdex.net/v2/en
```

### GPU Scheduling Note

The RTX 3070 (8 GB VRAM) is shared between the Player model and Coach model. Ollama handles request queuing internally, but to prevent OOM:

- Only ONE model should be loaded at a time. Ollama evicts models from VRAM on a LRU basis, but frequent swapping between Qwen3.5-9B and Gemma 4 E4B during AI/AI simulations will cause thrashing.
- **Recommendation:** During AI/AI + Coach simulations, run the Coach analysis as a distinct phase BETWEEN rounds, not concurrently with match play. The Celery worker should enforce this sequencing.
- H/H simulations need zero GPU and can run concurrently with any AI workload.

-----

## 6. Phase 1 — Game Engine Core

**Goal:** A fully functional, deterministic Pokémon TCG state machine that can play a complete game given two decks and a sequence of actions. No AI, no database, no frontend. Pure game logic.

**Exit Criteria:** Two decks (built from cards in CARDLIST.md, resolved via TCGDex) can play a full game to completion via baseline player agents (RandomPlayer, GreedyPlayer), with every state transition producing a structured event. 100+ games should complete with 0 crashes.

> **✅ PHASE 1 COMPLETE** — Verified with 200 games (100 Greedy/Greedy + 100 Random/Random), 0 crashes, 42 tests passing. 157 card fixtures captured from live TCGDex API. Greedy/Greedy: 53.9 avg turns, 74% prizes / 14% no_bench / 12% deck_out win conditions. Attack resolution, KO logic, and prize-taking all verified correct for flat-damage attacks. Multiplier attacks (e.g., “30×”) correctly return 0 base damage pending Phase 2 effect handlers. Note: avg game length will drop significantly once Phase 2 effects are implemented (draw/search trainers, energy acceleration abilities, multiplier attacks).

### 6.1 Game State Data Model

```python
# app/engine/state.py

from enum import Enum, auto
from dataclasses import dataclass, field
from typing import Optional
import uuid

class Zone(Enum):
    DECK = auto()
    HAND = auto()
    ACTIVE = auto()
    BENCH = auto()
    DISCARD = auto()
    PRIZES = auto()
    LOST_ZONE = auto()
    STADIUM = auto()

class Phase(Enum):
    SETUP = auto()           # Initial setup: draw 7, place basics, set prizes
    DRAW = auto()            # Mandatory draw at turn start
    MAIN = auto()            # Play trainers, attach energy, evolve, use abilities
    ATTACK = auto()          # Declare and resolve attack
    BETWEEN_TURNS = auto()   # Check conditions (poison, burn, etc.)
    GAME_OVER = auto()       # Terminal state

class StatusCondition(Enum):
    POISONED = auto()
    BURNED = auto()
    ASLEEP = auto()
    CONFUSED = auto()
    PARALYZED = auto()

class EnergyType(Enum):
    GRASS = "Grass"
    FIRE = "Fire"
    WATER = "Water"
    LIGHTNING = "Lightning"
    PSYCHIC = "Psychic"
    FIGHTING = "Fighting"
    DARKNESS = "Darkness"
    METAL = "Metal"
    DRAGON = "Dragon"
    COLORLESS = "Colorless"

@dataclass
class EnergyAttachment:
    energy_type: EnergyType
    source_card_id: str        # The energy card's unique instance ID
    provides: list[EnergyType] # What it actually provides (for special energies)

@dataclass
class CardInstance:
    """A specific instance of a card in a game. 
    card_def_id references the card definition from the DB.
    instance_id is unique per game (so two copies of the same card are distinct)."""
    instance_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    card_def_id: str = ""          # References cards.tcgdex_id in DB
    card_name: str = ""
    card_type: str = ""            # "pokemon", "trainer", "energy"
    zone: Zone = Zone.DECK
    
    # Energy-specific (set when CardInstance is built from a card definition)
    energy_provides: list[str] = field(default_factory=list)  # e.g., ["Fire"] for basic Fire Energy
    
    # Pokémon-specific
    current_hp: int = 0
    max_hp: int = 0
    energy_attached: list[EnergyAttachment] = field(default_factory=list)
    status_conditions: list[StatusCondition] = field(default_factory=list)
    tools_attached: list[str] = field(default_factory=list)  # instance_ids of tools
    evolved_from: Optional[str] = None       # instance_id of pre-evolution
    evolution_stage: int = 0                  # 0=Basic, 1=Stage1, 2=Stage2
    turn_played: int = -1                     # Turn this card entered play
    retreated_this_turn: bool = False
    ability_used_this_turn: bool = False
    damage_counters: int = 0                  # 10 damage per counter

@dataclass
class PlayerState:
    player_id: str                    # "p1" or "p2"
    deck: list[CardInstance] = field(default_factory=list)
    hand: list[CardInstance] = field(default_factory=list)
    active: Optional[CardInstance] = None
    bench: list[CardInstance] = field(default_factory=list)   # Max 5 (standard)
    discard: list[CardInstance] = field(default_factory=list)
    prizes: list[CardInstance] = field(default_factory=list)  # 6 prizes
    lost_zone: list[CardInstance] = field(default_factory=list)
    stadium_in_play: Optional[CardInstance] = None
    
    prizes_remaining: int = 6
    supporter_played_this_turn: bool = False
    energy_attached_this_turn: bool = False
    retreat_used_this_turn: bool = False
    gx_used: bool = False
    vstar_used: bool = False

@dataclass
class GameState:
    game_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    turn_number: int = 0
    active_player: str = "p1"       # Which player's turn it is
    phase: Phase = Phase.SETUP
    p1: PlayerState = field(default_factory=lambda: PlayerState(player_id="p1"))
    p2: PlayerState = field(default_factory=lambda: PlayerState(player_id="p2"))
    first_player: str = ""          # Who went first (determined during setup)
    winner: Optional[str] = None
    win_condition: Optional[str] = None  # "prizes", "deck_out", "no_bench"
    
    # Global effects
    stadiums: list[CardInstance] = field(default_factory=list)
    
    # Event log for this game
    events: list[dict] = field(default_factory=list)
    
    def get_player(self, player_id: str) -> PlayerState:
        return self.p1 if player_id == "p1" else self.p2
    
    def get_opponent(self, player_id: str) -> PlayerState:
        return self.p2 if player_id == "p1" else self.p1
    
    def emit_event(self, event_type: str, **kwargs):
        event = {
            "event_type": event_type,
            "turn": self.turn_number,
            "active_player": self.active_player,
            "phase": self.phase.name,
            **kwargs
        }
        self.events.append(event)
        return event
```

### 6.2 Action Types

```python
# app/engine/actions.py

from enum import Enum, auto
from dataclasses import dataclass
from typing import Optional

class ActionType(Enum):
    # Setup
    PLACE_ACTIVE = auto()
    PLACE_BENCH = auto()
    MULLIGAN_REDRAW = auto()
    
    # Main phase
    PLAY_SUPPORTER = auto()
    PLAY_ITEM = auto()
    PLAY_STADIUM = auto()
    PLAY_TOOL = auto()
    ATTACH_ENERGY = auto()
    EVOLVE = auto()
    RETREAT = auto()
    USE_ABILITY = auto()
    
    # Attack phase
    ATTACK = auto()
    
    # Forced
    CHOOSE_TARGET = auto()        # When an effect requires target selection
    CHOOSE_CARDS = auto()         # When an effect requires card selection (e.g., search deck)
    CHOOSE_OPTION = auto()        # Binary choice (e.g., flip coin effects)
    DISCARD_ENERGY = auto()       # Attack cost or effect requirement
    SWITCH_ACTIVE = auto()        # Forced switch (KO, effect)
    
    # Turn management
    PASS = auto()                 # End main phase → attack declaration
    END_TURN = auto()             # End turn without attacking

@dataclass
class Action:
    action_type: ActionType
    player_id: str
    card_instance_id: Optional[str] = None  # The card being played/used
    target_instance_id: Optional[str] = None  # Target of the action
    attack_index: Optional[int] = None       # Which attack (0 or 1)
    selected_cards: Optional[list[str]] = None  # For multi-select effects
    selected_option: Optional[int] = None      # For choice effects
    
    # AI reasoning (only populated for AI players)
    reasoning: Optional[str] = None
```

### 6.3 Action Validation

The ActionValidator is the gatekeeper. No state transition occurs without passing through it. It checks:

```python
# app/engine/actions.py (continued)

class ActionValidator:
    """
    Validates whether an action is legal given the current game state.
    Returns a list of legal actions for a given state (used by both
    heuristic and AI players to know what they can do).
    """
    
    @staticmethod
    def get_legal_actions(state: GameState, player_id: str) -> list[Action]:
        """Return ALL legal actions for the given player in the current phase."""
        actions = []
        player = state.get_player(player_id)
        
        if state.phase == Phase.MAIN:
            actions.extend(ActionValidator._get_play_actions(state, player))
            actions.extend(ActionValidator._get_energy_actions(state, player))
            actions.extend(ActionValidator._get_evolve_actions(state, player))
            actions.extend(ActionValidator._get_retreat_actions(state, player))
            actions.extend(ActionValidator._get_ability_actions(state, player))
            actions.append(Action(ActionType.PASS, player_id))  # Always can pass
            actions.append(Action(ActionType.END_TURN, player_id))  # Always can end
            
        elif state.phase == Phase.ATTACK:
            actions.extend(ActionValidator._get_attack_actions(state, player))
            actions.append(Action(ActionType.END_TURN, player_id))
            
        # ... other phases
        
        return actions
    
    @staticmethod
    def validate(state: GameState, action: Action) -> tuple[bool, str]:
        """Returns (is_valid, error_message)."""
        legal = ActionValidator.get_legal_actions(state, action.player_id)
        # Check if the proposed action matches any legal action
        # ... validation logic
```

**Key validation rules to implement (Pokémon TCG Standard rules):**

1. Only one Supporter per turn
1. Only one manual energy attachment per turn
1. Cannot evolve a Pokémon the same turn it was played
1. Cannot evolve a Pokémon the same turn it was evolved
1. First player cannot attack on their first turn
1. Cannot retreat if no bench Pokémon
1. Retreat cost must be paid (correct energy types or Colorless)
1. Attack energy cost must be met
1. Maximum 5 bench Pokémon (unless ability modifies this)
1. Cannot play a Stadium if the same Stadium is already in play
1. Evolution must follow the correct chain (Basic → Stage 1 → Stage 2)
1. Tool limit (typically 1 per Pokémon unless ability modifies)
1. Pokémon ex/V/VSTAR/VMAX give 2 prize cards when knocked out
1. VSTAR Power can only be used once per game

### 6.4 State Transitions

```python
# app/engine/transitions.py

class StateTransition:
    """
    Pure functions that take a GameState and an Action and return a new
    GameState. Every transition emits events. The game state is mutated
    in place for performance (deep copies are expensive at H/H volume),
    but events provide a complete audit trail.
    """
    
    @staticmethod
    def apply(state: GameState, action: Action) -> GameState:
        """Apply a validated action to the game state. Caller must validate first."""
        handler = TRANSITION_MAP.get(action.action_type)
        if not handler:
            raise ValueError(f"No handler for {action.action_type}")
        return handler(state, action)
    
    @staticmethod
    def attach_energy(state: GameState, action: Action) -> GameState:
        player = state.get_player(action.player_id)
        energy_card = _find_card(player.hand, action.card_instance_id)
        target_card = _find_card_in_play(player, action.target_instance_id)
        
        # Move energy from hand to target's energy list
        player.hand.remove(energy_card)
        energy_card.zone = Zone.ACTIVE if target_card == player.active else Zone.BENCH
        target_card.energy_attached.append(
            EnergyAttachment(
                energy_type=EnergyType(energy_card.provides),
                source_card_id=energy_card.instance_id,
                provides=[EnergyType(energy_card.provides)]
            )
        )
        player.energy_attached_this_turn = True
        
        state.emit_event("energy_attached",
            card=energy_card.card_name,
            target=target_card.card_name,
            energy_type=energy_card.provides
        )
        return state
    
    # ... handlers for every ActionType
```

### 6.5 Match Runner

```python
# app/engine/runner.py

from dataclasses import dataclass
from typing import Callable, Optional
import random

@dataclass
class MatchResult:
    game_id: str
    winner: str                    # "p1" or "p2"
    win_condition: str             # "prizes", "deck_out", "no_bench"
    total_turns: int
    p1_prizes_taken: int
    p2_prizes_taken: int
    events: list[dict]
    p1_deck_name: str
    p2_deck_name: str

class MatchRunner:
    """
    Orchestrates a single game between two players.
    Players implement the PlayerInterface (see players/base.py).
    The runner does NOT know whether players are heuristic or AI.
    """
    
    def __init__(
        self,
        p1_player,              # PlayerInterface
        p2_player,              # PlayerInterface
        p1_deck: list[dict],    # List of card definitions
        p2_deck: list[dict],
        event_callback: Optional[Callable] = None,  # For real-time streaming
        max_turns: int = 200    # Safety valve
    ):
        self.p1_player = p1_player
        self.p2_player = p2_player
        self.p1_deck = p1_deck
        self.p2_deck = p2_deck
        self.event_callback = event_callback
        self.max_turns = max_turns
    
    async def run(self) -> MatchResult:
        state = self._initialize_game()
        
        while state.phase != Phase.GAME_OVER and state.turn_number < self.max_turns:
            player = self._get_current_player(state)
            
            # Draw phase
            state = self._handle_draw(state)
            if state.phase == Phase.GAME_OVER:
                break
            
            # Main phase loop
            state.phase = Phase.MAIN
            while state.phase == Phase.MAIN:
                legal_actions = ActionValidator.get_legal_actions(
                    state, state.active_player
                )
                action = await player.choose_action(state, legal_actions)
                
                is_valid, error = ActionValidator.validate(state, action)
                if not is_valid:
                    # Log the invalid action attempt, re-prompt
                    state.emit_event("invalid_action", error=error)
                    continue
                
                state = StateTransition.apply(state, action)
                self._emit(state.events[-1])
                
                if action.action_type == ActionType.PASS:
                    state.phase = Phase.ATTACK
                elif action.action_type == ActionType.END_TURN:
                    state = self._end_turn(state)
            
            # Attack phase
            if state.phase == Phase.ATTACK:
                legal_attacks = ActionValidator.get_legal_actions(
                    state, state.active_player
                )
                action = await player.choose_action(state, legal_attacks)
                state = StateTransition.apply(state, action)
                self._emit(state.events[-1])
                
                # Resolve KO, prize taking, etc.
                state = self._resolve_attack_aftermath(state)
            
            # Between turns
            state = self._handle_between_turns(state)
            state = self._advance_turn(state)
        
        return self._build_result(state)
    
    def _emit(self, event: dict):
        if self.event_callback:
            self.event_callback(event)
```

### 6.6 Player Interface

```python
# app/players/base.py

from abc import ABC, abstractmethod

class PlayerInterface(ABC):
    """
    Abstract base class for all player types.
    Both HeuristicPlayer and AIPlayer implement this interface.
    The game engine only ever interacts through this interface.
    """
    
    @abstractmethod
    async def choose_action(
        self, 
        state: GameState, 
        legal_actions: list[Action]
    ) -> Action:
        """
        Given the current game state and a list of legal actions,
        choose and return one action.
        
        For heuristic players: runs decision tree, returns instantly.
        For AI players: serializes state to prompt, calls Ollama, 
                        parses response, returns action with reasoning.
        """
        ...
    
    @abstractmethod
    async def choose_setup(
        self,
        state: GameState,
        hand: list[CardInstance]
    ) -> tuple[str, list[str]]:
        """
        During setup, choose which Basic to place as active
        and which (if any) to place on bench.
        Returns (active_instance_id, [bench_instance_ids])
        """
        ...
```

-----

## 7. Phase 2 — Card Data Pipeline & Effect Registry

**Goal:** Implement effect handlers for all 157 cards in the initial pool. Card definitions are already loaded as fixtures from Phase 1. This phase focuses entirely on coding the effect logic for every attack, ability, trainer, and special energy.

**Exit Criteria:** All 157 cards have definitions in the card registry (already done via Phase 1 fixtures) AND implemented effects in the effect registry. Every attack with non-flat-damage effects, every ability, every trainer card, and every special energy needs a working handler. Cards with flat-damage-only attacks must be explicitly verified as handled by the engine’s default damage path. Re-running 100 Greedy vs Greedy games should show avg game length dropping to 15-30 turns (from Phase 1’s 53.9) and deck_out rate below 5%.

### 7.1 Card List Format

The current populated source file is `docs/POKEMON_MASTER_LIST.md`. Each
processable line follows this format:

```
CardName SET CardNumber
```

Example:

```
Dwebble DRI 11
Charizard ex OBF 6
Iono PAF 80
Boss's Orders PAL 172
```

### 7.2 TCGDex Client

```python
# app/cards/tcgdex.py

import httpx
from app.config import settings

class TCGDexClient:
    """
    Client for the TCGDex REST API (https://api.tcgdex.net/v2/en).
    All card data comes from this source — never hardcoded.
    """
    BASE_URL = "https://api.tcgdex.net/v2/en"
    
    def __init__(self):
        self.client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            timeout=30.0,
            headers={"User-Agent": "PokePrism/1.0"}
        )
    
    async def get_card(self, set_code: str, card_number: str) -> dict:
        """
        Fetch a single card by set and number.
        Example: get_card("sv03", "6") → Charizard ex from Obsidian Flames
        
        TCGDex endpoint: /cards/{setId}-{localId:03d}
        The card ID is a composite of the set ID, a hyphen, and the card number
        zero-padded to 3 digits. Example: sv06-130 for Dragapult ex TWM 130.
        
        IMPORTANT: TCGDex uses its own set ID codes which may differ from
        the abbreviated codes used in PTCG deck lists. The loader must
        map PTCG set abbreviations to TCGDex set IDs.
        """
        padded_number = str(card_number).zfill(3)
        card_id = f"{set_code}-{padded_number}"
        response = await self.client.get(f"/cards/{card_id}")
        response.raise_for_status()
        return response.json()
    
    async def get_set(self, set_id: str) -> dict:
        """Fetch set metadata including card list."""
        response = await self.client.get(f"/sets/{set_id}")
        response.raise_for_status()
        return response.json()
    
    async def search_cards(self, name: str) -> list[dict]:
        """Search cards by name. Useful for fuzzy matching."""
        response = await self.client.get(f"/cards", params={"name": name})
        response.raise_for_status()
        return response.json()
```

### 7.3 Card Loader Pipeline

```python
# app/cards/loader.py

import re
from pathlib import Path

# PTCG set abbreviation → TCGDex set ID mapping
# VERIFIED against live TCGDex API during Phase 1. Zero-padded format confirmed.
# TCGDex set IDs can be found at https://api.tcgdex.net/v2/en/sets
SET_CODE_MAP = {
    # Scarlet & Violet era
    "SVI": "sv01",         # Scarlet & Violet Base
    "PAL": "sv02",         # Paldea Evolved
    "OBF": "sv03",         # Obsidian Flames
    "MEW": "sv03.5",       # 151
    "PAF": "sv04.5",       # Paldean Fates
    "TEF": "sv05",         # Temporal Forces
    "TWM": "sv06",         # Twilight Masquerade
    "SFA": "sv06.5",       # Shrouded Fable
    "SCR": "sv07",         # Stellar Crown
    "SSP": "sv08",         # Surging Sparks
    "PRE": "sv08.5",       # Prismatic Evolutions
    "JTG": "sv09",         # Journey Together
    "DRI": "sv10",         # Destined Rivals
    "WHT": "sv10.5",       # White Flare (verify — twin set w/ Black Bolt, Jul 2025)
    "BLK": "sv10.5b",      # Black Bolt (verify — twin set w/ White Flare, Jul 2025)
    # Mega Evolution era
    "MEG": "meg01",        # Mega Evolution (ME01, Sep 2025) — verify TCGDex ID
    "MEE": "meg-energy",   # Mega Evolution Energy — verify TCGDex ID
    "PFL": "meg02",        # Phantasmal Flames (ME02, Nov 2025) — verify TCGDex ID
    "ASC": "meg02.5",      # Ascended Heroes (ME2.5, Jan 2026) — verify TCGDex ID
    "POR": "meg03",        # Perfect Order (ME03, Mar 2026) — verify TCGDex ID
    # EXCLUDED — not yet released:
    # "M4": "meg04",       # Chaos Rising (ME04, releases May 22, 2026)
    #                      # Re-enable when set drops and TCGDex indexes it.
    # Promos (add as needed):
    # "PR-SV": "svp",      # SV Black Star Promos — verify TCGDex ID
    #                      # Pecharunt PR-SV 149 failed to resolve in Phase 1.
    # NOTE: ME-era TCGDex IDs above are estimates based on naming patterns.
    # The actual IDs were discovered during Phase 1 fixture capture.
    # If any fail during future card loading, query https://api.tcgdex.net/v2/en/sets
    # to find the correct ID.
}

class CardListLoader:
    """
    Parses POKEMON_MASTER_LIST.md and resolves each entry against TCGDex.
    
    Pipeline:
    1. Read POKEMON_MASTER_LIST.md
    2. Parse each line into (name, set_abbrev, number)
    3. Map set_abbrev to TCGDex set ID
    4. Fetch full card data from TCGDex
    5. Transform into internal CardDefinition model
    6. Upsert into PostgreSQL
    """
    
    def parse_cardlist(self, path: Path) -> list[dict]:
        entries = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # Parse "Dwebble DRI 11" → name="Dwebble", set="DRI", number="11"
                # Handle multi-word names: "Boss's Orders PAL 172"
                match = re.match(r"^(.+?)\s+([A-Z]{2,4})\s+(\d+)$", line)
                if match:
                    entries.append({
                        "name": match.group(1).strip(),
                        "set_abbrev": match.group(2),
                        "number": match.group(3)
                    })
        return entries
    
    async def sync_to_database(self, entries: list[dict], tcgdex: TCGDexClient, db_session):
        """
        Fetch from TCGDex and upsert into cards table.
        Captures raw TCGDex response alongside parsed fields.
        """
        for entry in entries:
            tcgdex_set_id = SET_CODE_MAP.get(entry["set_abbrev"])
            if not tcgdex_set_id:
                print(f"WARNING: Unknown set abbreviation '{entry['set_abbrev']}' "
                      f"for card '{entry['name']}'. Add to SET_CODE_MAP.")
                continue
            
            raw = await tcgdex.get_card(tcgdex_set_id, entry["number"])
            card_def = self._transform(raw, entry)
            await self._upsert(db_session, card_def)
    
    def _transform(self, raw_tcgdex: dict, entry: dict) -> dict:
        """Transform TCGDex response into internal card definition."""
        # See Appendix G for the full TCGDex response shape
        return {
            "tcgdex_id": raw_tcgdex.get("id"),
            "name": raw_tcgdex.get("name"),
            "set_abbrev": entry["set_abbrev"],
            "set_number": entry["number"],
            "category": raw_tcgdex.get("category", "").lower(),  # "pokemon", "trainer", "energy"
            "hp": raw_tcgdex.get("hp"),
            "types": raw_tcgdex.get("types", []),
            "evolve_from": raw_tcgdex.get("evolveFrom"),
            "stage": raw_tcgdex.get("stage"),
            "attacks": raw_tcgdex.get("attacks", []),
            "abilities": raw_tcgdex.get("abilities", []),
            "weaknesses": raw_tcgdex.get("weaknesses", []),
            "resistances": raw_tcgdex.get("resistances", []),
            "retreat_cost": raw_tcgdex.get("retreat"),
            "regulation_mark": raw_tcgdex.get("regulationMark"),
            "rarity": raw_tcgdex.get("rarity"),
            "image_url": raw_tcgdex.get("image"),
            "raw_tcgdex": raw_tcgdex,  # Store full response for reference
        }
```

### 7.4 Effect Registry

```python
# app/engine/effects/registry.py

from typing import Callable, Optional

class EffectRegistry:
    """
    Singleton registry mapping card IDs to their effect implementations.
    
    Every card with a non-trivial effect (attacks that do more than flat damage,
    abilities, trainer effects, special energies) needs a registered handler.
    
    Cards with attacks that only deal flat damage to the active Pokémon
    do NOT need explicit effect registration — the engine handles that
    generically via base damage calculation.
    """
    
    _instance = None
    _attack_effects: dict[str, Callable] = {}      # key: "{tcgdex_id}:{attack_index}"
    _ability_effects: dict[str, Callable] = {}      # key: "{tcgdex_id}:{ability_name}"
    _trainer_effects: dict[str, Callable] = {}      # key: "{tcgdex_id}"
    _energy_effects: dict[str, Callable] = {}       # key: "{tcgdex_id}"
    
    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def register_attack(self, card_id: str, attack_index: int, handler: Callable):
        key = f"{card_id}:{attack_index}"
        self._attack_effects[key] = handler
    
    def register_ability(self, card_id: str, ability_name: str, handler: Callable):
        key = f"{card_id}:{ability_name}"
        self._ability_effects[key] = handler
    
    def register_trainer(self, card_id: str, handler: Callable):
        self._trainer_effects[card_id] = handler
    
    def register_energy(self, card_id: str, handler: Callable):
        self._energy_effects[card_id] = handler
    
    def resolve_attack(self, card_id: str, attack_index: int, 
                        state: 'GameState', action: 'Action') -> 'GameState':
        key = f"{card_id}:{attack_index}"
        handler = self._attack_effects.get(key)
        if handler:
            return handler(state, action)
        else:
            # Default: flat damage to opponent's active
            return self._default_damage(state, action)
    
    def has_effect(self, card_id: str, effect_type: str = "attack", index: int = 0) -> bool:
        """Check if a card has a registered effect. Useful for testing completeness."""
        if effect_type == "attack":
            return f"{card_id}:{index}" in self._attack_effects
        elif effect_type == "ability":
            return any(k.startswith(f"{card_id}:") for k in self._ability_effects)
        elif effect_type == "trainer":
            return card_id in self._trainer_effects
        return False
```

### 7.5 Effect Implementation Pattern

Every effect follows this pattern. **Do not create abstract/generic effect parsers that try to interpret card text.** Each card’s effects are explicitly coded. The card text on TCGDex is for display only; the effect logic is authoritative.

```python
# app/engine/effects/trainers.py

from app.engine.effects.registry import EffectRegistry
from app.engine.state import GameState, Phase
from app.engine.actions import Action

def _iono_effect(state: GameState, action: Action) -> GameState:
    """
    Iono (PAF 80 / PAL 185):
    Each player shuffles their hand into their deck. Then, each player
    draws a card for each of their remaining Prize cards.
    """
    for player_id in ["p1", "p2"]:
        player = state.get_player(player_id)
        
        # Shuffle hand into deck
        player.deck.extend(player.hand)
        player.hand.clear()
        import random
        random.shuffle(player.deck)
        
        # Draw cards equal to remaining prizes
        draw_count = player.prizes_remaining
        for _ in range(draw_count):
            if player.deck:
                card = player.deck.pop(0)
                card.zone = Zone.HAND
                player.hand.append(card)
        
        state.emit_event("iono_resolved",
            player=player_id,
            cards_drawn=draw_count
        )
    
    return state

# Registration happens at module import time
EffectRegistry.instance().register_trainer("sv04.5-080", _iono_effect)
# Also register alternate prints of the same card:
EffectRegistry.instance().register_trainer("sv02-185", _iono_effect)
```

### 7.6 Initial Card Pool Strategy

The initial pool is **157 cards** sourced from CARDLIST.md (160 entries minus 2 M4/Chaos Rising exclusions minus 1 unresolved PR-SV promo). These cards span the SV and Mega Evolution eras and form multiple complete, competitively viable decks.

> **Phase 1 used Dragapult ex/Dusknoir and Team Rocket’s Mewtwo ex as the two test decks** — both constructed entirely from CARDLIST.md cards. These remain the baseline test decks for Phase 2 regression testing.

**CRITICAL:** The effect implementations for all 157 cards must be complete and correct before moving to Phase 3. Every attack, ability, trainer, and special energy in the pool needs a working handler. Cards with flat-damage-only attacks are handled by the engine’s default damage path — verify this explicitly, don’t assume. Incomplete effects cause silent game logic errors that compound across thousands of simulations.

**Phase 2 Regression Benchmark:** After effects are implemented, re-run 100 Greedy vs Greedy games with the same two test decks and compare to Phase 1 baselines. Expected changes: avg turns should drop from ~54 to 15-30, deck_out % should drop below 5%, total KOs and damage should increase. If these targets aren’t met, effects aren’t firing correctly.

### 7.7 Test Fixture Strategy

```python
# scripts/capture_fixtures.py

"""
Run this script ONCE to capture live TCGDex responses for the initial card pool.
Saves JSON responses to backend/tests/fixtures/ so tests don't hit the API.

Usage: make capture-fixtures
"""

import asyncio
import json
from pathlib import Path
from app.cards.tcgdex import TCGDexClient
from app.cards.loader import CardListLoader, SET_CODE_MAP

async def capture():
    loader = CardListLoader()
    entries = loader.parse_cardlist(Path("docs/POKEMON_MASTER_LIST.md"))
    client = TCGDexClient()
    fixtures_dir = Path("backend/tests/fixtures/cards")
    fixtures_dir.mkdir(parents=True, exist_ok=True)
    
    for entry in entries:
        set_id = SET_CODE_MAP.get(entry["set_abbrev"])
        if not set_id:
            print(f"WARNING: No SET_CODE_MAP entry for '{entry['set_abbrev']}' "
                  f"(card: {entry['name']}). Skipping.")
            continue
        try:
            raw = await client.get_card(set_id, entry["number"])
            fixture_path = fixtures_dir / f"{entry['set_abbrev']}_{entry['number']}.json"
            with open(fixture_path, "w") as f:
                json.dump(raw, f, indent=2)
            print(f"Captured: {entry['name']} -> {fixture_path}")
        except Exception as e:
            print(f"FAILED: {entry['name']} ({entry['set_abbrev']} {entry['number']}): {e}")

asyncio.run(capture())
```

Tests load these captured fixtures instead of hitting TCGDex. When the card pool expands in Phase 12, run this script again to capture the new cards.

-----

## 8. Phase 3 — Heuristic Player & H/H Simulation Loop

**Goal:** Implement the HeuristicPlayer, wire it to the MatchRunner, and run thousands of games between the initial decks with no AI and no database. Output goes to structured JSON files initially, then migrates to PostgreSQL in Phase 4.

**Exit Criteria:** Can run 1000+ H/H games between two decks, produce win rate statistics, and verify game engine correctness through aggregate analysis (e.g., first-player advantage should be detectable but not extreme).

### 8.1 Heuristic Player Implementation

The heuristic player uses a priority-based decision tree. It is NOT trying to be optimal — it’s trying to be “reasonable enough” that its game data is useful for the Coach/Analyst. See Appendix I for the full decision tree specification.

```python
# app/players/heuristic.py

from app.players.base import PlayerInterface
from app.engine.state import GameState
from app.engine.actions import Action, ActionType

class HeuristicPlayer(PlayerInterface):
    """
    Rule-based player that makes decisions using priority lists.
    Fast execution (no IO, no inference), suitable for bulk simulation.
    
    Design philosophy: The heuristic should play at "average human" level.
    It should make reasonable plays but miss complex multi-turn setups.
    This is intentional — the data it generates represents baseline play,
    which the Coach can improve upon.
    """
    
    async def choose_action(
        self, state: GameState, legal_actions: list[Action]
    ) -> Action:
        # Priority ordering for main phase:
        # 1. Use draw/search abilities (thin deck, find pieces)
        # 2. Play draw supporters if hand size < 4
        # 3. Evolve Pokémon that can evolve (prioritize active)
        # 4. Attach energy to active attacker (or next attacker)
        # 5. Play Pokémon to bench (basics that can evolve into useful Stage 1/2)
        # 6. Play items (tools, balls, etc.)
        # 7. Use Boss's Orders if opponent has valuable bench target
        # 8. Attack if can KO or deal significant damage
        # 9. Retreat if active is in bad matchup AND bench has better option
        # 10. End turn
        
        for evaluator in self._priority_chain:
            action = evaluator(state, legal_actions)
            if action:
                return action
        
        # Fallback: end turn
        return self._find_action(legal_actions, ActionType.END_TURN)
    
    async def choose_setup(self, state, hand):
        # Choose the basic with highest HP as active
        basics = [c for c in hand if c.card_type == "pokemon" and c.evolution_stage == 0]
        basics.sort(key=lambda c: c.max_hp, reverse=True)
        active = basics[0].instance_id
        bench = [b.instance_id for b in basics[1:5]]  # Up to 4 more on bench
        return active, bench
```

### 8.2 H/H Batch Runner

```python
# This will later become a Celery task (Phase 7), but starts as a simple script.

async def run_hh_batch(
    p1_deck: list[dict],
    p2_deck: list[dict],
    num_games: int = 1000,
    event_callback=None
) -> dict:
    """Run a batch of H/H games and return aggregate statistics."""
    results = []
    p1_player = HeuristicPlayer()
    p2_player = HeuristicPlayer()
    
    for i in range(num_games):
        runner = MatchRunner(
            p1_player=p1_player,
            p2_player=p2_player,
            p1_deck=p1_deck,
            p2_deck=p2_deck,
            event_callback=event_callback
        )
        result = await runner.run()
        results.append(result)
        
        if i % 100 == 0:
            print(f"Completed {i}/{num_games} games")
    
    # Aggregate
    p1_wins = sum(1 for r in results if r.winner == "p1")
    return {
        "total_games": num_games,
        "p1_wins": p1_wins,
        "p2_wins": num_games - p1_wins,
        "p1_win_rate": p1_wins / num_games,
        "avg_turns": sum(r.total_turns for r in results) / num_games,
        "results": results  # Full results for DB insertion in Phase 4
    }
```

-----

## 9. Phase 4 — Database Layer & Memory Stack

**Goal:** Set up PostgreSQL (with pgvector), Neo4j, and all database schemas. Migrate H/H output from flat files to the database. Wire up embedding generation via Ollama.

**Exit Criteria:** H/H simulations write all match data to PostgreSQL. Card synergy and matchup relationships are created in Neo4j. Embedding vectors are generated and stored in pgvector. All data is queryable.

### 9.1 PostgreSQL Schema

See **Appendix B** for the complete schema. Key tables:

|Table             |Purpose                                                              |
|------------------|---------------------------------------------------------------------|
|`cards`           |Card definitions from TCGDex. One row per unique card print.         |
|`decks`           |Saved deck lists. References cards via join table.                   |
|`deck_cards`      |Join table: deck_id → card_tcgdex_id + quantity                      |
|`simulations`     |Top-level simulation config (params, status, timestamps)             |
|`rounds`          |Per-round data within a simulation                                   |
|`matches`         |Individual match results within a round                              |
|`match_events`    |Every game event from a match (serialized JSON)                      |
|`decisions`       |AI decisions with reasoning text (AI/H and AI/AI modes only)         |
|`deck_mutations`  |Coach’s card swap decisions between rounds                           |
|`card_performance`|Aggregate card stats (win rate when included, avg prizes taken, etc.)|
|`embeddings`      |pgvector table for decision/state embeddings                         |

### 9.2 Neo4j Graph Schema

See **Appendix C** for the complete schema. Key node and relationship types:

**Nodes:**

|Label        |Properties                      |Purpose                |
|-------------|--------------------------------|-----------------------|
|`Card`       |tcgdex_id, name, category, types|Card identity          |
|`Deck`       |deck_id, archetype, name        |Deck identity          |
|`Archetype`  |name, description               |Deck archetype grouping|
|`Decision`   |decision_id, type, reasoning    |An AI decision point   |
|`MatchResult`|match_id, winner, turns         |Match outcome          |

**Relationships:**

|Type             |From → To          |Properties                     |Purpose                         |
|-----------------|-------------------|-------------------------------|--------------------------------|
|`SYNERGIZES_WITH`|Card → Card        |weight, games_observed         |Cards that perform well together|
|`COUNTERS`       |Card → Card        |weight, games_observed         |Cards that counter others       |
|`BELONGS_TO`     |Card → Deck        |quantity                       |Deck membership                 |
|`PERFORMS_IN`    |Card → MatchResult |prizes_taken, kos, damage_dealt|Per-card match performance      |
|`SWAPPED_FOR`    |Card → Card        |round_id, reasoning            |Coach swap decisions            |
|`BEATS`          |Deck → Deck        |win_rate, games_played         |Deck matchup results            |
|`IS_ARCHETYPE`   |Deck → Archetype   |—                              |Archetype classification        |
|`LED_TO`         |Decision → Decision|—                              |Decision chain sequencing       |

### 9.3 Memory Population Pipeline

After each match (or batch of matches), a pipeline processes the results into the memory stack:

```python
# app/memory/postgres.py (simplified)

class MatchMemoryWriter:
    """Writes match results to PostgreSQL."""
    
    async def write_match(self, result: MatchResult, simulation_id: str, 
                          round_number: int, db: AsyncSession):
        match_record = Match(
            id=result.game_id,
            simulation_id=simulation_id,
            round_number=round_number,
            winner=result.winner,
            win_condition=result.win_condition,
            total_turns=result.total_turns,
            p1_prizes_taken=result.p1_prizes_taken,
            p2_prizes_taken=result.p2_prizes_taken,
            p1_deck_name=result.p1_deck_name,
            p2_deck_name=result.p2_deck_name,
        )
        db.add(match_record)
        
        # Batch insert events (can be thousands per match)
        events = [
            MatchEvent(
                match_id=result.game_id,
                sequence=i,
                event_type=e["event_type"],
                turn=e["turn"],
                player=e.get("active_player"),
                data=e  # JSONB column
            )
            for i, e in enumerate(result.events)
        ]
        db.add_all(events)
        await db.flush()
```

```python
# app/memory/graph.py (simplified)

class GraphMemoryWriter:
    """Writes match outcomes and card relationships to Neo4j."""
    
    async def update_card_synergies(self, deck: list[dict], won: bool, driver):
        """
        After each match, update synergy weights between cards that
        appeared in the same deck. Winning boosts weight; losing decreases.
        """
        async with driver.session() as session:
            card_ids = [c["tcgdex_id"] for c in deck]
            for i in range(len(card_ids)):
                for j in range(i + 1, len(card_ids)):
                    delta = 1 if won else -0.5
                    await session.run("""
                        MERGE (a:Card {tcgdex_id: $id_a})
                        MERGE (b:Card {tcgdex_id: $id_b})
                        MERGE (a)-[r:SYNERGIZES_WITH]-(b)
                        ON CREATE SET r.weight = $delta, r.games_observed = 1
                        ON MATCH SET r.weight = r.weight + $delta,
                                     r.games_observed = r.games_observed + 1
                    """, id_a=card_ids[i], id_b=card_ids[j], delta=delta)
    
    async def update_matchup(self, p1_deck_id, p2_deck_id, winner, driver):
        """Update deck-vs-deck matchup edge."""
        async with driver.session() as session:
            winner_id = p1_deck_id if winner == "p1" else p2_deck_id
            loser_id = p2_deck_id if winner == "p1" else p1_deck_id
            await session.run("""
                MERGE (w:Deck {deck_id: $winner_id})
                MERGE (l:Deck {deck_id: $loser_id})
                MERGE (w)-[r:BEATS]->(l)
                ON CREATE SET r.win_count = 1, r.total_games = 1
                ON MATCH SET r.win_count = r.win_count + 1,
                             r.total_games = r.total_games + 1
            """, winner_id=winner_id, loser_id=loser_id)
```

### 9.4 Embedding Generation

```python
# app/memory/embeddings.py

import httpx
from app.config import settings

class EmbeddingService:
    """
    Generate embeddings via Ollama's /api/embeddings endpoint.
    Uses nomic-embed-text (or similar small embedding model).
    
    Embeddings are generated for:
    - Game state snapshots (at decision points in AI games)
    - AI reasoning text
    - Card descriptions (for semantic card search)
    - Coach analysis summaries
    """
    
    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.OLLAMA_BASE_URL}/api/embeddings",
                json={
                    "model": settings.OLLAMA_EMBED_MODEL,
                    "prompt": text
                }
            )
            response.raise_for_status()
            return response.json()["embedding"]
    
    async def embed_game_state(self, state: 'GameState', player_id: str) -> list[float]:
        """Create a text summary of the game state and embed it."""
        summary = self._state_to_text(state, player_id)
        return await self.embed(summary)
    
    def _state_to_text(self, state, player_id):
        player = state.get_player(player_id)
        opp = state.get_opponent(player_id)
        return (
            f"Turn {state.turn_number}. "
            f"Active: {player.active.card_name} ({player.active.current_hp}HP). "
            f"Bench: {', '.join(c.card_name for c in player.bench)}. "
            f"Hand size: {len(player.hand)}. Prizes left: {player.prizes_remaining}. "
            f"Opponent active: {opp.active.card_name} ({opp.active.current_hp}HP). "
            f"Opponent bench: {len(opp.bench)}. Opponent prizes: {opp.prizes_remaining}."
        )
```

-----

## 10. Phase 5 — AI Player Integration (Ollama)

**Goal:** Implement the AIPlayer that sends game state to Qwen3.5-9B via Ollama, parses the response into a valid action, and stores the reasoning. Wire up AI/H simulation mode.

**Exit Criteria:** AI/H simulations produce matches with full AI reasoning stored in PostgreSQL. The AI player makes legal moves consistently (>99% of the time without re-prompting).

### 10.1 AI Player

```python
# app/players/ai_player.py

import json
import httpx
from app.players.base import PlayerInterface
from app.engine.state import GameState
from app.engine.actions import Action, ActionType

class AIPlayer(PlayerInterface):
    """
    LLM-backed player that uses Ollama for decision-making.
    
    KEY DESIGN DECISIONS:
    - The prompt includes ONLY legal actions (pre-filtered by ActionValidator)
    - Each legal action is assigned a numeric ID for easy parsing
    - The model responds with a JSON object containing action_id and reasoning
    - If the response is unparseable, retry up to 3 times with increasing guidance
    - Failed retries fall back to heuristic for that single action
    """
    
    def __init__(
        self,
        model: str = "qwen3.5:9b-q4_K_M",
        ollama_url: str = "http://ollama:11434",
        temperature: float = 0.3,    # Low temperature for more consistent play
        max_retries: int = 3
    ):
        self.model = model
        self.ollama_url = ollama_url
        self.temperature = temperature
        self.max_retries = max_retries
        self.client = httpx.AsyncClient(timeout=120.0)
    
    async def choose_action(
        self, state: GameState, legal_actions: list[Action]
    ) -> Action:
        prompt = self._build_prompt(state, legal_actions)
        
        for attempt in range(self.max_retries):
            response = await self._call_ollama(prompt, attempt)
            parsed = self._parse_response(response, legal_actions)
            if parsed:
                return parsed
            
            # Add correction guidance for retry
            prompt += (
                f"\n\nYour previous response could not be parsed. "
                f"You MUST respond with ONLY a JSON object like: "
                f'{{"action_id": <number>, "reasoning": "<your reasoning>"}}'
            )
        
        # Final fallback: heuristic
        from app.players.heuristic import HeuristicPlayer
        fallback = HeuristicPlayer()
        action = await fallback.choose_action(state, legal_actions)
        action.reasoning = "[FALLBACK] AI response unparseable after retries"
        return action
    
    def _build_prompt(self, state: GameState, legal_actions: list[Action]) -> str:
        player_id = state.active_player
        player = state.get_player(player_id)
        opp = state.get_opponent(player_id)
        
        # Build action menu
        action_lines = []
        for i, action in enumerate(legal_actions):
            desc = self._describe_action(action, state)
            action_lines.append(f"  {i}: {desc}")
        
        return f"""You are an expert Pokémon TCG player. Analyze the board state and choose the best action.

## Current Board State

**Turn:** {state.turn_number} | **Phase:** {state.phase.name}

**Your Side:**
- Active: {player.active.card_name} (HP: {player.active.current_hp}/{player.active.max_hp}, Energy: {self._format_energy(player.active)})
- Bench: {self._format_bench(player.bench)}
- Hand ({len(player.hand)} cards): {', '.join(c.card_name for c in player.hand)}
- Prizes remaining: {player.prizes_remaining}
- Deck: {len(player.deck)} cards remaining
- Supporter played: {'Yes' if player.supporter_played_this_turn else 'No'}
- Energy attached: {'Yes' if player.energy_attached_this_turn else 'No'}

**Opponent's Side:**
- Active: {opp.active.card_name} (HP: {opp.active.current_hp}/{opp.active.max_hp}, Energy: {self._format_energy(opp.active)})
- Bench: {self._format_bench(opp.bench)}
- Hand: {len(opp.hand)} cards
- Prizes remaining: {opp.prizes_remaining}
- Deck: {len(opp.deck)} cards remaining

## Legal Actions
{chr(10).join(action_lines)}

## Instructions
Choose the action that gives you the best chance of winning. Consider:
1. Can you take a knockout this turn?
2. Are you setting up for a knockout next turn?
3. What is your opponent's likely response?
4. Board position and prize trade efficiency

Respond with ONLY a JSON object:
{{"action_id": <number from the list above>, "reasoning": "<brief explanation>"}}"""
    
    async def _call_ollama(self, prompt: str, attempt: int) -> str:
        response = await self.client.post(
            f"{self.ollama_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": self.temperature + (attempt * 0.1),
                    "num_predict": 300,
                }
            }
        )
        response.raise_for_status()
        return response.json()["response"]
    
    def _parse_response(self, response: str, legal_actions: list[Action]) -> Action | None:
        try:
            # Strip markdown code fences if present
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
            
            data = json.loads(cleaned)
            action_id = int(data["action_id"])
            reasoning = data.get("reasoning", "")
            
            if 0 <= action_id < len(legal_actions):
                action = legal_actions[action_id]
                action.reasoning = reasoning
                return action
        except (json.JSONDecodeError, KeyError, ValueError, IndexError):
            pass
        return None
```

### 10.2 Important: `think: false` for Qwen 3.5

Qwen 3.5 models have a thinking/reasoning mode that produces `<think>` tags in output. **This must be disabled** for structured JSON output parsing.

```python
# In _call_ollama, add to the request JSON:
"options": {
    "temperature": self.temperature,
    "num_predict": 300,
},
# Qwen 3.5 specific: disable thinking mode
"system": "You are a Pokémon TCG expert. Respond only with valid JSON. Do not use <think> tags.",
# And if using /api/chat endpoint instead of /api/generate:
"think": False  # Critical for Qwen 3.5
```

### 10.3 AI Decision Logging

Every AI decision gets stored with its full context:

```python
# After each AI action is applied:
decision_record = Decision(
    id=str(uuid.uuid4()),
    match_id=match.game_id,
    simulation_id=simulation_id,
    turn_number=state.turn_number,
    player_id=action.player_id,
    action_type=action.action_type.name,
    card_played=action.card_instance_id,
    target=action.target_instance_id,
    reasoning=action.reasoning,
    legal_action_count=len(legal_actions),
    game_state_summary=state_to_text(state, action.player_id),
)
# Also generate and store embedding of the reasoning + state
embedding = await embedding_service.embed(
    f"{decision_record.game_state_summary} | Decision: {decision_record.reasoning}"
)
decision_record.embedding = embedding
```

-----

## 11. Phase 6 — Coach/Analyst System

**Goal:** Implement the Coach/Analyst (Gemma 4 E4B) that analyzes round results, queries the memory stack for insights, and decides which cards to swap between rounds.

**Exit Criteria:** The Coach can analyze a round of matches, query both PostgreSQL and Neo4j for card performance data, and produce a deck mutation (0-4 card swaps) with reasoning. The mutation is applied to the deck and the next round uses the modified deck.

### 11.1 Coach Architecture

```python
# app/coach/analyst.py

from app.memory.postgres import CardPerformanceQueries
from app.memory.graph import GraphQueries
from app.memory.vectors import SimilarSituationFinder

class CoachAnalyst:
    """
    The Coach/Analyst operates BETWEEN rounds of simulation.
    It does not participate in games — it modifies the deck.
    
    Workflow:
    1. Receive round results (win rate, per-match data)
    2. Query memory for card performance insights
    3. Identify underperforming cards in the deck
    4. Query memory for potential replacements
    5. Generate swap proposal via Gemma 4 E4B
    6. Apply swaps (max 4 per round)
    7. Log all decisions to memory
    """
    
    def __init__(
        self,
        model: str = "gemma4-e4b:q6_K",  
        ollama_url: str = "http://ollama:11434",
        max_swaps: int = 4,
        db_session=None,
        neo4j_driver=None,
    ):
        self.model = model
        self.ollama_url = ollama_url
        self.max_swaps = max_swaps
        self.db = db_session
        self.graph = neo4j_driver
        self.perf_queries = CardPerformanceQueries(db_session)
        self.graph_queries = GraphQueries(neo4j_driver)
        self.vector_search = SimilarSituationFinder(db_session)
    
    async def analyze_and_mutate(
        self,
        current_deck: list[dict],
        round_results: list['MatchResult'],
        opponent_decks: list[list[dict]],
        excluded_cards: list[str],         # Cards the user excluded
        simulation_id: str,
        round_number: int,
    ) -> tuple[list[dict], list[dict]]:
        """
        Returns: (mutated_deck, list_of_swap_decisions)
        """
        # 1. Compute per-card performance this round
        card_stats = self._compute_card_stats(current_deck, round_results)
        
        # 2. Query historical performance from memory
        historical = await self.perf_queries.get_card_performance(
            [c["tcgdex_id"] for c in current_deck]
        )
        
        # 3. Find synergy data from graph
        synergies = await self.graph_queries.get_synergies(
            [c["tcgdex_id"] for c in current_deck]
        )
        
        # 4. Find similar past situations via vector search
        situation_summary = self._summarize_round(card_stats, round_results)
        similar_past = await self.vector_search.find_similar(situation_summary, k=5)
        
        # 5. Identify candidate replacements from the card pool
        candidates = await self.perf_queries.get_top_performing_cards(
            exclude_ids=[c["tcgdex_id"] for c in current_deck] + excluded_cards,
            category_filter=None,  # Consider all card types
            limit=20
        )
        
        # 6. Build Coach prompt and get swap decisions
        swaps = await self._get_swap_decisions(
            current_deck, card_stats, historical, synergies,
            similar_past, candidates, round_results
        )
        
        # 7. Apply swaps
        mutated_deck = self._apply_swaps(current_deck, swaps)
        
        # 8. Log decisions
        swap_records = []
        for swap in swaps:
            record = DeckMutation(
                simulation_id=simulation_id,
                round_number=round_number,
                card_removed=swap["removed"],
                card_added=swap["added"],
                reasoning=swap["reasoning"],
            )
            swap_records.append(record)
            
            # Update graph: record the swap relationship
            await self.graph_queries.record_swap(
                swap["removed"], swap["added"], 
                round_number, swap["reasoning"]
            )
        
        return mutated_deck, swap_records
```

### 11.2 Coach Prompting Strategy

See **Appendix D** for the full prompt templates. The key principles:

1. **Data-first prompting:** The Coach receives concrete performance numbers, not vague summaries. Win rates, damage output, KO counts, prize trade ratios — all from the database.
1. **Memory-augmented context:** Historical performance and graph synergies are injected into the prompt so the Coach makes decisions based on accumulated knowledge, not just one round.
1. **Structured output:** The Coach must respond with a specific JSON format for swap decisions. Same parsing/retry logic as the AI Player.
1. **Exclusion enforcement:** The prompt explicitly lists excluded cards so the Coach never proposes swaps involving them.
1. **Deck legality enforcement:** After the Coach proposes swaps, the system validates that the resulting deck is still legal (60 cards, correct card count limits, etc.).

### 11.3 Deck Builder (Partial/No Deck Modes)

```python
# app/coach/deck_builder.py

class DeckBuilder:
    """
    Builds or completes decks from memory.
    Used for Partial Deck and No Deck modes.
    
    IMPORTANT: These modes should NOT be used until thousands of full-deck
    matches have been completed. The UI should display a warning with the
    current match count and a recommendation threshold.
    """
    
    MINIMUM_MATCHES_RECOMMENDED = 5000
    
    async def complete_deck(
        self, partial_deck: list[dict], target_size: int = 60
    ) -> list[dict]:
        """Fill in missing cards based on historical performance and synergy data."""
        current_count = sum(c.get("quantity", 1) for c in partial_deck)
        slots_remaining = target_size - current_count
        
        if slots_remaining <= 0:
            return partial_deck
        
        # Query graph for cards with highest synergy to existing cards
        existing_ids = [c["tcgdex_id"] for c in partial_deck]
        suggestions = await self.graph_queries.suggest_cards_for_deck(
            existing_ids, limit=slots_remaining * 3  # Get 3x candidates
        )
        
        # Use Coach LLM to make final selections
        # ...
    
    async def build_from_scratch(
        self, avoid_meta: bool = True
    ) -> list[dict]:
        """
        Build an entirely new deck from memory.
        If avoid_meta=True, deprioritize cards that appear in high-frequency
        deck archetypes (the "meta" decks everyone uses).
        """
        # Query graph for underutilized cards with high individual performance
        # Identify potential cores (2-3 Pokémon lines)
        # Build around them using synergy data
        # ...
```

-----

## 12. Phase 7 — Task Queue & Simulation Orchestration

**Goal:** Wire simulations through Celery for async execution. Implement the full simulation lifecycle: create → queue → run rounds → stream events → complete. Add H/H scheduling via Celery Beat.

**Exit Criteria:** Simulations can be submitted via API, run asynchronously in Celery workers, stream events through Redis pub/sub, and report completion. H/H jobs can be scheduled on a cron.

### 12.1 Celery Configuration

```python
# app/tasks/celery_app.py

from celery import Celery
from celery.schedules import crontab
from app.config import settings

celery_app = Celery(
    "pokeprism",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=86400,       # 24 hour hard limit per task
    task_soft_time_limit=82800,  # 23 hour soft limit (allows cleanup)
    worker_prefetch_multiplier=1, # Don't prefetch (simulations are long)
    worker_concurrency=2,         # Max 2 concurrent simulations
)

# Scheduled H/H batch jobs
celery_app.conf.beat_schedule = {
    "nightly-hh-batch": {
        "task": "app.tasks.scheduled.run_scheduled_hh",
        "schedule": crontab(hour=2, minute=0),  # 2 AM daily
        "kwargs": {"num_games_per_matchup": 500},
    },
}
```

### 12.2 Simulation Task

```python
# app/tasks/simulation.py

from app.tasks.celery_app import celery_app
import redis
import json

@celery_app.task(bind=True)
def run_simulation(self, simulation_id: str):
    """
    Main simulation task. Runs in a Celery worker.
    
    This task:
    1. Loads simulation config from DB
    2. For each round:
       a. Run all matches (H/H, AI/H, or AI/AI)
       b. Stream events via Redis pub/sub
       c. Write results to DB
       d. If deck is unlocked, run Coach analysis
       e. Apply deck mutations
       f. Check if target win rate is met
    3. Mark simulation as completed
    """
    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    try:
        loop.run_until_complete(_run_simulation_async(self, simulation_id))
    finally:
        loop.close()

async def _run_simulation_async(task, simulation_id: str):
    redis_client = redis.Redis.from_url(settings.REDIS_URL)
    channel = f"simulation:{simulation_id}"
    
    # Load config
    sim = await load_simulation(simulation_id)
    
    # Update status
    await update_simulation_status(simulation_id, "running")
    task.update_state(state="RUNNING", meta={"round": 0})
    
    for round_num in range(1, sim.num_rounds + 1):
        # Publish round start
        redis_client.publish(channel, json.dumps({
            "type": "round_start", "round": round_num
        }))
        
        round_results = []
        for opponent_deck in sim.opponent_decks:
            for match_num in range(sim.matches_per_opponent):
                result = await run_single_match(
                    p1_deck=sim.current_deck,
                    p2_deck=opponent_deck,
                    game_mode=sim.game_mode,
                    event_callback=lambda e: redis_client.publish(
                        channel, json.dumps({"type": "match_event", **e})
                    )
                )
                round_results.append(result)
                
                # Write to DB
                await write_match_to_db(result, simulation_id, round_num)
                await write_match_to_graph(result, simulation_id, round_num)
        
        # Coach analysis (if deck is not locked)
        if not sim.deck_locked:
            coach = CoachAnalyst(...)
            new_deck, mutations = await coach.analyze_and_mutate(
                sim.current_deck, round_results, 
                sim.opponent_decks, sim.excluded_cards,
                simulation_id, round_num
            )
            sim.current_deck = new_deck
            
            redis_client.publish(channel, json.dumps({
                "type": "deck_mutation",
                "round": round_num,
                "mutations": [m.to_dict() for m in mutations]
            }))
        
        # Check target win rate
        win_rate = calculate_win_rate(round_results, sim.target_mode)
        if win_rate >= sim.target_win_rate:
            redis_client.publish(channel, json.dumps({
                "type": "target_reached",
                "round": round_num,
                "win_rate": win_rate
            }))
            break
        
        task.update_state(state="RUNNING", meta={
            "round": round_num, 
            "win_rate": win_rate
        })
    
    await update_simulation_status(simulation_id, "completed")
    redis_client.publish(channel, json.dumps({"type": "simulation_complete"}))
```

### 12.3 WebSocket Bridge

```python
# app/api/ws.py

import socketio
import redis.asyncio as aioredis

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")

@sio.event
async def connect(sid, environ):
    pass

@sio.event
async def subscribe_simulation(sid, data):
    """Client subscribes to a simulation's event stream."""
    simulation_id = data["simulation_id"]
    channel = f"simulation:{simulation_id}"
    
    # Create Redis subscriber for this client
    redis_client = aioredis.from_url(settings.REDIS_URL)
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(channel)
    
    # Forward Redis events to WebSocket
    async def forward_events():
        async for message in pubsub.listen():
            if message["type"] == "message":
                await sio.emit("simulation_event", 
                    json.loads(message["data"]), room=sid)
    
    sio.start_background_task(forward_events)
```

-----

## 13. Phase 8 — Frontend: Core Layout & Simulation Setup

**Goal:** Build the React frontend shell with routing, layout, and the simulation setup page (deck upload, parameter configuration, opponent deck management, submission).

**Exit Criteria:** User can paste/upload decks in PTCG format, configure all simulation parameters, select game mode, add opponent decks, and submit. The API receives the submission and queues the simulation.

### 13.1 Page Structure

|Route            |Page           |Description                    |
|-----------------|---------------|-------------------------------|
|`/`              |SimulationSetup|Deck upload, params, submit    |
|`/simulation/:id`|SimulationLive |Live console + deck changes    |
|`/dashboard/:id` |Dashboard      |Post-simulation charts/data    |
|`/history`       |History        |All simulations list           |
|`/memory`        |Memory         |Card/decision search + mind map|

### 13.2 Simulation Setup Page Layout

```
┌──────────────────────────────────────────────────────────────┐
│ [Sidebar]  │  SIMULATION SETUP                               │
│            │                                                  │
│ • New Sim  │  ┌─────────────────┐  ┌──────────────────────┐  │
│ • History  │  │ YOUR DECK       │  │ PARAMETERS           │  │
│ • Memory   │  │                 │  │                      │  │
│            │  │ [Textarea]      │  │ Game Mode: [v]       │  │
│            │  │ Paste PTCG deck │  │ Matches/Opponent: [] │  │
│            │  │                 │  │ Rounds: []           │  │
│            │  │ ○ No Deck       │  │ Target Win Rate: []% │  │
│            │  │ ○ Partial       │  │ ○ Aggregate          │  │
│            │  │ ● Full Deck     │  │ ○ Per-Opponent       │  │
│            │  │ □ Lock Deck     │  │                      │  │
│            │  └─────────────────┘  │ Excluded Cards:      │  │
│            │                       │ [Search + add chips]  │  │
│            │  ┌─────────────────┐  └──────────────────────┘  │
│            │  │ OPPONENT DECKS  │                             │
│            │  │ + Add Opponent  │                             │
│            │  │                 │                             │
│            │  │ 1. Charizard ex │                             │
│            │  │    [Remove]     │                             │
│            │  │ 2. Lugia VSTAR  │                             │
│            │  │    [Remove]     │                             │
│            │  └─────────────────┘                             │
│            │                                                  │
│            │  [========= START SIMULATION =========]          │
└──────────────────────────────────────────────────────────────┘
```

### 13.3 Deck Parser (Frontend)

```typescript
// src/utils/deckParser.ts

interface DeckCard {
  quantity: number;
  name: string;
  setAbbrev: string;
  setNumber: string;
}

interface ParsedDeck {
  pokemon: DeckCard[];
  trainers: DeckCard[];
  energy: DeckCard[];
  totalCards: number;
  errors: string[];
}

export function parsePTCGDeck(text: string): ParsedDeck {
  /**
   * Parses the standard Pokémon TCG deck list format:
   * 
   * Pokémon: 12
   * 3 Charmander OBF 4
   * 2 Charmeleon OBF 5
   * 3 Charizard ex OBF 6
   * ...
   * 
   * Trainer: 38
   * 4 Iono PAF 80
   * 4 Boss's Orders PAL 172
   * ...
   * 
   * Energy: 10
   * 10 Fire Energy SVE 2
   */
  const lines = text.trim().split("\n");
  const result: ParsedDeck = {
    pokemon: [], trainers: [], energy: [], totalCards: 0, errors: []
  };
  
  let currentSection: "pokemon" | "trainers" | "energy" | null = null;
  
  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (!line) continue;
    
    // Section headers
    if (/^Pok[eé]mon/i.test(line)) { currentSection = "pokemon"; continue; }
    if (/^Trainer/i.test(line)) { currentSection = "trainers"; continue; }
    if (/^Energy/i.test(line)) { currentSection = "energy"; continue; }
    
    // Card lines: "3 Charizard ex OBF 6"
    const match = line.match(/^(\d+)\s+(.+?)\s+([A-Z]{2,4})\s+(\d+)$/);
    if (match && currentSection) {
      const card: DeckCard = {
        quantity: parseInt(match[1]),
        name: match[2].trim(),
        setAbbrev: match[3],
        setNumber: match[4],
      };
      result[currentSection].push(card);
      result.totalCards += card.quantity;
    } else if (line && currentSection) {
      // Try to parse lines that don't match standard format
      // (e.g., basic energy without set code)
      const basicMatch = line.match(/^(\d+)\s+(.+)$/);
      if (basicMatch) {
        result[currentSection].push({
          quantity: parseInt(basicMatch[1]),
          name: basicMatch[2].trim(),
          setAbbrev: "SVE",  // Default set for basic energy
          setNumber: "0",
        });
        result.totalCards += parseInt(basicMatch[1]);
      } else {
        result.errors.push(`Could not parse line: "${line}"`);
      }
    }
  }
  
  // Validation
  if (result.totalCards !== 60 && result.totalCards > 0) {
    result.errors.push(`Deck has ${result.totalCards} cards (should be 60)`);
  }
  
  return result;
}
```

### 13.4 API Submission

```typescript
// src/api/simulations.ts

interface SimulationConfig {
  userDeck: ParsedDeck | null;       // null for No Deck mode
  deckMode: "full" | "partial" | "none";
  deckLocked: boolean;
  opponentDecks: ParsedDeck[];
  gameMode: "hh" | "ai_h" | "ai_ai";
  matchesPerOpponent: number;
  numRounds: number;
  targetWinRate: number;
  targetMode: "aggregate" | "per_opponent";
  excludedCards: string[];            // tcgdex_ids
}

export async function createSimulation(config: SimulationConfig): Promise<string> {
  const response = await api.post("/api/simulations", config);
  return response.data.simulation_id;  // UUID
}
```

-----

## 14. Phase 9 — Frontend: Live Console & Match Viewer

**Goal:** Build the real-time simulation viewer with the xterm.js console, deck changes tile, and decision detail panel.

**Exit Criteria:** User can watch a simulation in real-time, scroll through decisions, pause the console view, and click on any decision to see full details including AI reasoning.

### 14.1 Live Console Component

```typescript
// src/components/simulation/LiveConsole.tsx

/**
 * Uses xterm.js to display a scrollable, pausable terminal view
 * of simulation events as they stream in via WebSocket.
 * 
 * Features:
 * - Auto-scroll (can be paused by scrolling up)
 * - Color-coded events (green=KO, yellow=swap, red=error, etc.)
 * - Clickable decision lines → opens DecisionDetail panel
 * - Event counter in header
 * 
 * Events are written as formatted terminal lines:
 * [T12] P1: Attach Fire Energy → Charizard ex
 * [T12] P1: Attack "Burning Dark" → Dragapult ex (180 dmg) → KO!
 * [R3]  COACH: Swap Rare Candy → Counter Catcher (Reasoning: ...)
 */
```

### 14.2 Decision Detail Panel

When a user clicks on a decision line in the console:

```
┌─────────────────────────────────────────┐
│ DECISION DETAIL                    [X]  │
│                                         │
│ Turn: 12  |  Player: P1 (AI)           │
│ Phase: MAIN                             │
│                                         │
│ Action: Attach Fire Energy              │
│ Card: Fire Energy (SVE-2)               │
│ Target: Charizard ex (OBF-6)            │
│                                         │
│ AI Reasoning:                           │
│ "Charizard ex needs one more Fire       │
│  Energy to use Burning Dark. With       │
│  the opponent's Dragapult ex at 130     │
│  remaining HP, a Burning Dark will      │
│  deal 180 and secure the KO for two     │
│  prize cards, putting me at 1 prize     │
│  remaining."                            │
│                                         │
│ Legal Actions Available: 8              │
│ Board State at Decision:                │
│ [Expandable state snapshot]             │
└─────────────────────────────────────────┘
```

### 14.3 Deck Changes Tile

```
┌─────────────────────────────────────────┐
│ RECENT DECK CHANGES                     │
│                                         │
│ Round 5:                                │
│  - Rare Candy (3→2)                     │
│  + Counter Catcher (0→1)                │
│  Reason: "Counter Catcher provides..."  │
│                                         │
│ Round 4:                                │
│  - Switch (2→1)                         │
│  + Escape Rope (0→1)                    │
│  Reason: "Escape Rope provides a..."    │
│                                         │
│ [Show all changes →]                    │
└─────────────────────────────────────────┘
```

-----

## 15. Phase 10 — Frontend: Reporting Dashboard

**Goal:** Build the post-simulation reporting dashboard with all 12 visualization tiles specified in the requirements.

**Exit Criteria:** All dashboard tiles render with real simulation data. Charts are interactive (hover, toggle, filter).

### 15.1 Dashboard Tile Specifications

#### Tile 1-3: Summary Cards

Simple stat cards showing Number of Rounds, Matches/Round, Total Matches. Use large numbers with labels. Recharts not needed.

#### Tile 4: Aggregate Win Rate %

Donut chart (Recharts `PieChart`) showing wins/losses with the percentage prominently in the center.

#### Tile 5: Win Rate per Opponent Deck

Horizontal bar chart (Recharts `BarChart`) with one bar per opponent deck, colored by win rate (red < 40%, yellow 40-60%, green > 60%).

#### Tile 6: Target Win Rate %

Gauge or progress indicator showing current aggregate win rate vs. target. A line chart showing win rate progression across rounds is more informative than a static gauge.

#### Tile 7: Matchup Matrix per Round

Heat map table (custom React component) showing win rates in a grid of (Your Deck variants) × (Opponent Decks) × (Rounds). Each cell is color-coded.

#### Tile 8: Win-Rate Distribution

Histogram (Recharts `BarChart`) showing the distribution of win rates across matches. Toggle dropdown to filter by specific opponent.

#### Tile 9: Prize Race Graph

Line chart (Recharts `LineChart`) with two lines (You vs. Opponent) showing cumulative prizes taken over turns. Averaged across matches in a round. Toggle to view specific matches.

#### Tile 10: Decision Map

D3 force-directed graph. Nodes are decision types (attach energy, play supporter, attack, retreat, etc.). Edges connect sequential decisions. Node size = frequency. Edge thickness = frequency of sequence. Color = win rate when that decision was made.

#### Tile 11: Card Swap Heat Map

Custom heat map (D3 or Recharts) showing frequency of cards being swapped in/out. X-axis = rounds. Y-axis = cards. Color intensity = number of times swapped. Red = swapped out, Green = swapped in.

#### Tile 12: Mutation Diff Log

Scrollable list (TanStack Table or custom component) showing each deck mutation chronologically. Each row shows round number, card removed, card added, and Coach’s reasoning. Expandable rows for full reasoning text.

-----

## 16. Phase 11 — Frontend: History & Memory Pages

**Goal:** Build the simulation history page with full filtering/sorting and the memory exploration page with card search and mind-map visualization.

### 16.1 History Page

Built with **TanStack Table** for its out-of-the-box sorting, filtering, and column visibility features.

**Columns:**

|Column     |Type                                   |Sortable|Filterable        |
|-----------|---------------------------------------|--------|------------------|
|★ (Star)   |Toggle                                 |Yes     |Yes (starred only)|
|Status     |Badge (pending/running/error/completed)|Yes     |Yes               |
|Created    |DateTime                               |Yes     |Yes (date range)  |
|Your Deck  |Text (AI-generated name)               |Yes     |Yes (search)      |
|Opponent(s)|Text (AI-generated names)              |Yes     |Yes (search)      |
|Mode       |Badge (H/H, AI/H, AI/AI)               |Yes     |Yes               |
|Rounds     |Number                                 |Yes     |No                |
|Win Rate   |Percentage                             |Yes     |Yes (range)       |
|Actions    |Buttons (View, Compare, Delete)        |No      |No                |

**Features:**

- **Compare Mode:** User can check up to 3 simulations and click “Compare” to see a side-by-side dashboard.
- **Deck Name Generation:** When a simulation is created, the backend sends the deck to Gemma 4 with a prompt like: “Given this Pokémon TCG deck list, generate a short archetype name (2-4 words). Examples: ‘Charizard ex Control’, ‘Lugia VSTAR Turbo’, ‘Lost Box Giratina’. Respond with only the name.” The generated name is stored on the simulation and deck records.
- **Bulk filters:** Users can combine filters (e.g., starred + completed + win rate > 50%).

### 16.2 Memory Page

```
┌──────────────────────────────────────────────────────────────┐
│ [Sidebar]  │  MEMORY EXPLORER                                │
│            │                                                  │
│            │  [Search: ________________________________ 🔍]   │
│            │  Examples: "Charizard ex", "retreat", "Boss's"  │
│            │                                                  │
│            │  ┌────────────────────┐  ┌───────────────────┐  │
│            │  │ CARD PROFILE       │  │ SYNERGY GRAPH     │  │
│            │  │                    │  │                   │  │
│            │  │ Charizard ex       │  │   [D3 Force-      │  │
│            │  │ OBF-6              │  │    Directed        │  │
│            │  │                    │  │    Graph]          │  │
│            │  │ Win Rate: 62.4%    │  │                   │  │
│            │  │ Games: 3,847       │  │   Click nodes to  │  │
│            │  │ Avg KOs: 2.1/game  │  │   navigate.       │  │
│            │  │ Avg Prizes: 3.4    │  │                   │  │
│            │  │                    │  │   Node = Card      │  │
│            │  │ Best Partners:     │  │   Edge = Synergy   │  │
│            │  │ • Arcanine ex      │  │   Size = Games     │  │
│            │  │ • Rare Candy       │  │   Color = Win Rate │  │
│            │  │ • Pidgeot ex       │  │                   │  │
│            │  │                    │  │                   │  │
│            │  │ Worst Matchups:    │  │                   │  │
│            │  │ • vs Water (38%)   │  │                   │  │
│            │  │ • vs Palkia (41%)  │  │                   │  │
│            │  └────────────────────┘  └───────────────────┘  │
│            │                                                  │
│            │  ┌──────────────────────────────────────────┐   │
│            │  │ DECISION HISTORY                          │   │
│            │  │ Recent AI decisions involving this card:  │   │
│            │  │                                           │   │
│            │  │ [Scrollable table of decisions]           │   │
│            │  └──────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

The **Mind Map Graph** is the centerpiece. It’s a D3 force-directed graph where:

- **Nodes** are cards (Pokémon, Trainers, Energy)
- **Edges** are `SYNERGIZES_WITH` relationships from Neo4j
- **Node size** scales with total games observed
- **Edge thickness** scales with synergy weight
- **Node color** indicates win rate (red → yellow → green spectrum)
- **Clicking a node** recenters the graph on that card and loads its profile
- **Hovering an edge** shows the synergy stats between two cards

```typescript
// src/components/memory/MindMapGraph.tsx

/**
 * D3 force-directed graph for card synergy exploration.
 * 
 * Data comes from GET /api/memory/graph?card_id={id}&depth=2
 * which returns the card's direct and second-degree synergies from Neo4j.
 * 
 * Interactions:
 * - Drag nodes to rearrange
 * - Click node → load card profile + recenter graph
 * - Hover edge → tooltip with synergy stats
 * - Mouse wheel → zoom
 * - Double-click background → reset zoom
 * 
 * Performance: Limit to ~100 nodes. If the graph has more,
 * show only the top-N by synergy weight and add a "Show more" option.
 */
```

-----

## 17. Phase 12 — Card Pool Expansion

> **⚠️ THIS PHASE MUST NOT BE SKIPPED OR DEFERRED INDEFINITELY.**
> The initial 157-card pool is sufficient to validate the engine and pipeline, but the system’s value comes from covering the full Standard-legal card pool. Plan to begin this phase once Phases 1-11 are stable.

**Goal:** Expand the card pool to include all Standard-legal cards beyond the initial 157. This includes two categories:

1. **New cards added to POKEMON_MASTER_LIST.md** — As the meta evolves and new archetypes emerge, additional cards will be added to the master list. Each new card needs a TCGDex fixture, a card definition, and an effect implementation.
1. **M4 / Chaos Rising cards** — The 2 cards excluded from Phase 1 (set code M4, mapped to Chaos Rising ME04) release May 22, 2026. Once the English set is available and indexed by TCGDex, add the M4 entries back to SET_CODE_MAP, capture fixtures, and implement effects.
1. **PR-SV promo set** — Pecharunt PR-SV 149 failed to resolve in Phase 1 due to missing promo set mapping. Resolve the TCGDex promo set ID and add to SET_CODE_MAP.

### 17.1 Expansion Strategy

1. **Run `make capture-fixtures` on the full POKEMON_MASTER_LIST.md** to fetch all TCGDex data for the new cards. Store fixtures for test coverage.
1. **Run `seed_cards.py`** to load all new card definitions into PostgreSQL. The cards exist in the DB immediately — they just don’t have effect implementations yet.
1. **Generate effect stubs** using `generate_cardlist_stubs.py`:
   
   ```python
   # scripts/generate_cardlist_stubs.py
   # Reads POKEMON_MASTER_LIST.md, checks which cards lack effect implementations,
   # and generates skeleton Python files with TODO markers.
   # Each stub includes the card's attack/ability text from TCGDex
   # as a docstring to guide implementation.
   ```
1. **Prioritize effect implementation by category:**
- **Priority 1 — Trainer staples** (Items, Supporters, Stadiums used in many decks): These are the highest-leverage cards because they appear in most deck lists.
- **Priority 2 — Popular attackers** (Pokémon ex/V that define top meta decks): Enables simulating the most-played matchups.
- **Priority 3 — Evolution lines** (Stage 1/2 Pokémon): Complete the Pokémon lines that were partially implemented.
- **Priority 4 — Niche cards** (Tech options, single-copy includes): Fill in the long tail.
1. **Batch validation:** After every ~50 card implementations, run the full test suite and execute 100 H/H games with decks that use the new cards. Fix any engine issues before continuing.
1. **Update the Neo4j graph:** New cards should automatically get `Card` nodes on their first appearance in a match. Synergy edges will build up naturally as simulations run with the expanded pool.

### 17.2 Effect Implementation Velocity Target

The number of new cards depends on how many are added to POKEMON_MASTER_LIST.md. Many cards share common patterns that can be templated:

- **~40% of cards**: Flat damage attacks only → no effect code needed (engine handles generically)
- **~25% of cards**: Simple effects (draw N, discard energy, do X damage + effect) → can use helper functions
- **~25% of cards**: Moderate complexity (conditional damage, multi-target, search deck) → custom implementations
- **~10% of cards**: Complex effects (multi-step, player choice, board-altering abilities) → careful custom implementations

Realistic velocity: **15-25 cards per day** once patterns are established.

### 17.3 Regression Testing

After expansion, run 10,000 H/H games across all initial + new deck matchups. Compare aggregate statistics to pre-expansion baselines. Watch for:

- Crash rate (should be 0%)
- Average game length (should remain in 15-30 turn range)
- First-player win rate (should be 50-55%, not extreme)
- Deck-out frequency (should be < 5%)

-----

## 18. Phase 13 — Polish, Hardening & Scheduling

**Goal:** Production-readiness. Error handling, retry logic, graceful shutdown, monitoring, and the scheduled H/H cron system.

### 18.1 Error Handling

- **Celery task failures:** Implement `on_failure` handlers that update simulation status to “errored” and store the error message/traceback.
- **Ollama timeouts:** AI players and Coach should handle connection errors and model-not-found errors gracefully. Auto-retry 3 times, then fall back to heuristic or skip Coach analysis for that round.
- **Database connection loss:** Use SQLAlchemy’s connection pool with pre-ping enabled. Celery workers should reconnect on pool exhaustion.
- **WebSocket disconnects:** Client-side auto-reconnect with exponential backoff. Server-side cleanup of abandoned subscriptions.

### 18.2 Scheduled H/H System

The Celery Beat scheduler runs nightly H/H batches:

```python
# app/tasks/scheduled.py

@celery_app.task
def run_scheduled_hh(num_games_per_matchup: int = 500):
    """
    Scheduled task that runs H/H simulations across all known deck matchups.
    
    This builds up the statistical baseline in the memory stack so that
    the Coach has more data to draw from for future simulations.
    
    Steps:
    1. Query DB for all known decks
    2. Generate all pairwise matchups
    3. For each matchup, run num_games_per_matchup H/H games
    4. Write results to DB and graph
    5. Update card_performance aggregate table
    """
    ...
```

### 18.3 Resource Monitoring

Add a simple health endpoint that reports system status:

```python
@app.get("/api/health")
async def health():
    return {
        "postgres": await check_postgres(),
        "neo4j": await check_neo4j(),
        "redis": await check_redis(),
        "ollama": await check_ollama(),
        "ollama_models": await get_loaded_models(),
        "celery_workers": await get_worker_count(),
        "active_simulations": await get_active_sim_count(),
        "total_matches_in_db": await get_total_matches(),
    }
```

-----

## 19. Appendix A — Game Engine State Machine Specification

### Turn Structure

```
SETUP
  │
  ├── Both players shuffle decks
  ├── Both players draw 7 cards
  ├── Both players place Basic Pokémon (active + bench)
  │   └── If no basics: mulligan → reshuffle → draw 7 → opponent may draw 1
  ├── Set 6 prize cards
  ├── Coin flip → determine first player
  │
  ▼
TURN START (loops until GAME_OVER)
  │
  ├── DRAW: Active player draws 1 card
  │   └── If deck empty → GAME_OVER (deck_out, opponent wins)
  │
  ├── MAIN PHASE (loop until PASS or END_TURN)
  │   ├── Play Basic Pokémon to bench
  │   ├── Evolve Pokémon
  │   ├── Attach energy (1 per turn)
  │   ├── Play Trainer cards
  │   │   ├── Item (unlimited per turn)
  │   │   ├── Supporter (1 per turn)
  │   │   ├── Stadium (replaces existing)
  │   │   └── Tool (attach to Pokémon)
  │   ├── Use Ability
  │   ├── Retreat active (1 per turn, pay retreat cost)
  │   └── PASS → go to ATTACK
  │
  ├── ATTACK PHASE
  │   ├── Declare attack (must have energy cost)
  │   ├── Apply weakness/resistance
  │   ├── Apply damage
  │   ├── Resolve effects
  │   ├── Check KO
  │   │   ├── If KO → attacker takes prizes
  │   │   │   ├── If attacker has 0 prizes → GAME_OVER (prizes)
  │   │   │   └── If defender has no bench → GAME_OVER (no_bench)
  │   │   └── If KO'd → defending player promotes from bench
  │   └── END_TURN (if no attack chosen)
  │
  ├── BETWEEN TURNS
  │   ├── Poison: 1 damage counter
  │   ├── Burn: Flip coin → heads: 2 damage counters; tails: no damage
  │   ├── Check Asleep: Flip coin → heads: wake up
  │   ├── Paralyzed: Removed between turns (lasts 1 turn)
  │   └── Check KO from poison/burn
  │
  └── Switch active player → TURN START
```

### Damage Calculation

```
Base Damage (from attack)
  + Modifiers (abilities, tools, stadiums, etc.)
  = Pre-Weakness Damage

If attacker's type is defender's weakness:
  Pre-Weakness Damage × 2 = Post-Weakness Damage
Else:
  Pre-Weakness Damage = Post-Weakness Damage

If attacker's type is defender's resistance:
  Post-Weakness Damage - 30 = Final Damage
Else:
  Post-Weakness Damage = Final Damage

Final Damage (minimum 0) → apply to defender
```

### Win Conditions

1. **Prizes:** A player takes their last prize card.
1. **Deck Out:** A player cannot draw a card at the start of their turn because their deck is empty.
1. **No Bench:** A player’s Active Pokémon is knocked out and they have no Bench Pokémon to promote.

-----

## 20. Appendix B — Database Schema (PostgreSQL)

```sql
-- Core card data (populated from TCGDex)
CREATE TABLE cards (
    tcgdex_id       TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    set_abbrev      TEXT NOT NULL,
    set_number      TEXT NOT NULL,
    category        TEXT NOT NULL,       -- 'pokemon', 'trainer', 'energy'
    subcategory     TEXT,                -- 'item', 'supporter', 'stadium', 'tool', 'basic', 'special'
    hp              INTEGER,
    types           JSONB DEFAULT '[]',
    evolve_from     TEXT,
    stage           TEXT,                -- 'Basic', 'Stage1', 'Stage2', 'VSTAR', 'VMAX', 'ex'
    attacks         JSONB DEFAULT '[]',
    abilities       JSONB DEFAULT '[]',
    weaknesses      JSONB DEFAULT '[]',
    resistances     JSONB DEFAULT '[]',
    retreat_cost    INTEGER DEFAULT 0,
    regulation_mark TEXT,
    rarity          TEXT,
    image_url       TEXT,
    raw_tcgdex      JSONB,               -- Full TCGDex response for reference
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_cards_name ON cards USING gin (name gin_trgm_ops);
CREATE INDEX idx_cards_category ON cards (category);
CREATE INDEX idx_cards_set ON cards (set_abbrev);

-- Deck definitions
CREATE TABLE decks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT,                -- AI-generated archetype name
    archetype       TEXT,                -- e.g., "Charizard ex", "Lugia VSTAR"
    deck_text       TEXT NOT NULL,       -- Raw PTCG format text
    card_count      INTEGER NOT NULL DEFAULT 60,
    source          TEXT DEFAULT 'user', -- 'user', 'coach', 'scheduled'
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE deck_cards (
    deck_id         UUID REFERENCES decks(id) ON DELETE CASCADE,
    card_tcgdex_id  TEXT REFERENCES cards(tcgdex_id),
    quantity        INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (deck_id, card_tcgdex_id)
);

-- Simulation configuration
CREATE TABLE simulations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending, running, completed, errored, cancelled
    game_mode       TEXT NOT NULL,       -- 'hh', 'ai_h', 'ai_ai'
    deck_mode       TEXT NOT NULL,       -- 'full', 'partial', 'none'
    deck_locked     BOOLEAN DEFAULT FALSE,
    
    user_deck_id    UUID REFERENCES decks(id),
    
    matches_per_opponent  INTEGER NOT NULL DEFAULT 10,
    num_rounds            INTEGER NOT NULL DEFAULT 5,
    target_win_rate       REAL NOT NULL DEFAULT 0.6,
    target_mode           TEXT NOT NULL DEFAULT 'aggregate',  -- 'aggregate', 'per_opponent'
    excluded_cards        JSONB DEFAULT '[]',                 -- list of tcgdex_ids
    
    -- Results
    final_win_rate        REAL,
    rounds_completed      INTEGER DEFAULT 0,
    total_matches         INTEGER DEFAULT 0,
    
    -- Deck naming
    user_deck_name        TEXT,           -- AI-generated
    
    -- Timing
    started_at            TIMESTAMPTZ,
    completed_at          TIMESTAMPTZ,
    error_message         TEXT,
    
    -- User features
    starred               BOOLEAN DEFAULT FALSE,
    
    created_at            TIMESTAMPTZ DEFAULT NOW(),
    updated_at            TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_simulations_status ON simulations (status);
CREATE INDEX idx_simulations_created ON simulations (created_at DESC);

-- Simulation ↔ Opponent decks (many-to-many)
CREATE TABLE simulation_opponents (
    simulation_id   UUID REFERENCES simulations(id) ON DELETE CASCADE,
    deck_id         UUID REFERENCES decks(id),
    deck_name       TEXT,               -- AI-generated
    PRIMARY KEY (simulation_id, deck_id)
);

-- Round-level data
CREATE TABLE rounds (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_id   UUID REFERENCES simulations(id) ON DELETE CASCADE,
    round_number    INTEGER NOT NULL,
    deck_snapshot   JSONB NOT NULL,     -- The deck list used for this round
    win_rate        REAL,
    total_matches   INTEGER DEFAULT 0,
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    
    UNIQUE (simulation_id, round_number)
);

-- Individual match results
CREATE TABLE matches (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_id   UUID REFERENCES simulations(id) ON DELETE CASCADE,
    round_id        UUID REFERENCES rounds(id) ON DELETE CASCADE,
    round_number    INTEGER NOT NULL,
    opponent_deck_id UUID REFERENCES decks(id),
    
    winner          TEXT NOT NULL,       -- 'p1' or 'p2'
    win_condition   TEXT NOT NULL,       -- 'prizes', 'deck_out', 'no_bench'
    total_turns     INTEGER NOT NULL,
    p1_prizes_taken INTEGER NOT NULL,
    p2_prizes_taken INTEGER NOT NULL,
    
    -- Per-turn prize counts for prize race chart
    prize_progression JSONB,            -- [{turn: 1, p1: 6, p2: 6}, ...]
    
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_matches_simulation ON matches (simulation_id);
CREATE INDEX idx_matches_round ON matches (round_id);

-- Match events (bulk insert, query by match)
CREATE TABLE match_events (
    id              BIGSERIAL PRIMARY KEY,
    match_id        UUID REFERENCES matches(id) ON DELETE CASCADE,
    sequence        INTEGER NOT NULL,
    event_type      TEXT NOT NULL,
    turn            INTEGER,
    player          TEXT,
    data            JSONB NOT NULL,
    
    UNIQUE (match_id, sequence)
);

CREATE INDEX idx_match_events_match ON match_events (match_id);

-- AI decisions (only for AI/H and AI/AI modes)
CREATE TABLE decisions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_id            UUID REFERENCES matches(id) ON DELETE CASCADE,
    simulation_id       UUID REFERENCES simulations(id) ON DELETE CASCADE,
    turn_number         INTEGER NOT NULL,
    player_id           TEXT NOT NULL,
    action_type         TEXT NOT NULL,
    card_played         TEXT,            -- tcgdex_id
    target              TEXT,            -- tcgdex_id
    reasoning           TEXT,
    legal_action_count  INTEGER,
    game_state_summary  TEXT,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_decisions_match ON decisions (match_id);
CREATE INDEX idx_decisions_card ON decisions (card_played);

-- Coach deck mutations
CREATE TABLE deck_mutations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    simulation_id   UUID REFERENCES simulations(id) ON DELETE CASCADE,
    round_number    INTEGER NOT NULL,
    card_removed    TEXT NOT NULL,       -- tcgdex_id
    card_added      TEXT NOT NULL,       -- tcgdex_id
    reasoning       TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_mutations_simulation ON deck_mutations (simulation_id);

-- Aggregate card performance (materialized/updated after each round)
CREATE TABLE card_performance (
    card_tcgdex_id  TEXT REFERENCES cards(tcgdex_id),
    games_included  INTEGER DEFAULT 0,
    games_won       INTEGER DEFAULT 0,
    total_kos       INTEGER DEFAULT 0,
    total_damage    BIGINT DEFAULT 0,
    total_prizes    INTEGER DEFAULT 0,
    avg_kos_per_game REAL GENERATED ALWAYS AS (
        CASE WHEN games_included > 0 THEN total_kos::REAL / games_included ELSE 0 END
    ) STORED,
    win_rate        REAL GENERATED ALWAYS AS (
        CASE WHEN games_included > 0 THEN games_won::REAL / games_included ELSE 0 END
    ) STORED,
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (card_tcgdex_id)
);

-- Embeddings (pgvector)
CREATE TABLE embeddings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type     TEXT NOT NULL,       -- 'decision', 'game_state', 'card', 'coach_analysis'
    source_id       TEXT NOT NULL,       -- References the source record's ID
    content_text    TEXT,                -- The text that was embedded
    embedding       vector(768),         -- Dimension depends on embedding model
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_embeddings_source ON embeddings (source_type, source_id);
CREATE INDEX idx_embeddings_vector ON embeddings 
    USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
```

-----

## 21. Appendix C — Graph Schema (Neo4j)

### Constraints and Indexes

```cypher
-- Uniqueness constraints
CREATE CONSTRAINT card_unique IF NOT EXISTS FOR (c:Card) REQUIRE c.tcgdex_id IS UNIQUE;
CREATE CONSTRAINT deck_unique IF NOT EXISTS FOR (d:Deck) REQUIRE d.deck_id IS UNIQUE;
CREATE CONSTRAINT archetype_unique IF NOT EXISTS FOR (a:Archetype) REQUIRE a.name IS UNIQUE;
CREATE CONSTRAINT match_unique IF NOT EXISTS FOR (m:MatchResult) REQUIRE m.match_id IS UNIQUE;

-- Indexes for lookup
CREATE INDEX card_name_idx IF NOT EXISTS FOR (c:Card) ON (c.name);
CREATE INDEX card_category_idx IF NOT EXISTS FOR (c:Card) ON (c.category);
```

### Node Schemas

```cypher
-- Card node (created from card definitions)
(:Card {
    tcgdex_id: "sv3-6",
    name: "Charizard ex",
    category: "pokemon",
    types: ["Fire"],
    hp: 330,
    stage: "Stage2"
})

-- Deck node (created per simulation deck)
(:Deck {
    deck_id: "uuid",
    name: "Charizard ex Turbo",
    archetype: "Charizard ex",
    card_count: 60,
    source: "user",
    created_at: datetime()
})

-- Archetype node (grouping for decks)
(:Archetype {
    name: "Charizard ex",
    description: "Fire-type Stage 2 attacker with energy acceleration"
})

-- MatchResult node (per-match outcome)
(:MatchResult {
    match_id: "uuid",
    winner: "p1",
    win_condition: "prizes",
    total_turns: 18,
    simulation_id: "uuid",
    round_number: 3
})
```

### Relationship Schemas

```cypher
-- Card synergy (built from match co-occurrence)
(card_a:Card)-[:SYNERGIZES_WITH {
    weight: 45.5,          -- Positive = good synergy, negative = anti-synergy
    games_observed: 1200,
    win_rate: 0.58         -- Win rate when both cards are in the same deck
}]->(card_b:Card)

-- Card counter relationship
(card_a:Card)-[:COUNTERS {
    weight: 12.3,
    games_observed: 340,
    effectiveness: 0.72    -- How often card_a KOs card_b when facing it
}]->(card_b:Card)

-- Deck membership
(card:Card)-[:BELONGS_TO {
    quantity: 3
}]->(deck:Deck)

-- Card performance in a match
(card:Card)-[:PERFORMS_IN {
    prizes_taken: 2,
    kos: 2,
    damage_dealt: 360,
    times_active: 5,
    was_knocked_out: true
}]->(match:MatchResult)

-- Coach swap decision
(removed:Card)-[:SWAPPED_FOR {
    round_number: 3,
    simulation_id: "uuid",
    reasoning: "Counter Catcher provides gust effect...",
    result_delta: 0.08     -- Win rate change after swap
}]->(added:Card)

-- Deck matchup
(deck_a:Deck)-[:BEATS {
    win_count: 340,
    total_games: 500,
    win_rate: 0.68
}]->(deck_b:Deck)

-- Archetype classification
(deck:Deck)-[:IS_ARCHETYPE]->(archetype:Archetype)
```

### Useful Query Patterns

```cypher
-- Find top synergy partners for a card
MATCH (c:Card {tcgdex_id: $card_id})-[r:SYNERGIZES_WITH]-(partner:Card)
WHERE r.games_observed > 100
RETURN partner.name, r.weight, r.win_rate, r.games_observed
ORDER BY r.weight DESC
LIMIT 10

-- Find cards that counter a specific card
MATCH (counter:Card)-[r:COUNTERS]->(target:Card {tcgdex_id: $card_id})
WHERE r.games_observed > 50
RETURN counter.name, r.effectiveness, r.games_observed
ORDER BY r.effectiveness DESC

-- Get deck matchup history
MATCH (d1:Deck {deck_id: $deck_id})-[r:BEATS]->(d2:Deck)
RETURN d2.name, r.win_rate, r.total_games
ORDER BY r.total_games DESC

-- Find underutilized cards with high individual win rates
MATCH (c:Card)-[r:PERFORMS_IN]->(m:MatchResult)
WITH c, COUNT(m) AS games, 
     SUM(CASE WHEN m.winner = 'p1' THEN 1 ELSE 0 END) AS wins
WHERE games > 50
RETURN c.name, c.tcgdex_id, games, wins * 1.0 / games AS win_rate
ORDER BY win_rate DESC
LIMIT 20

-- Suggest cards for partial deck completion
MATCH (existing:Card)-[r:SYNERGIZES_WITH]-(candidate:Card)
WHERE existing.tcgdex_id IN $existing_ids
  AND NOT candidate.tcgdex_id IN $existing_ids
WITH candidate, SUM(r.weight) AS total_synergy, AVG(r.win_rate) AS avg_win_rate
RETURN candidate.name, candidate.tcgdex_id, total_synergy, avg_win_rate
ORDER BY total_synergy DESC
LIMIT $limit
```

-----

## 22. Appendix D — Coach Prompting Strategy

### Prompt Template: Deck Evolution (Between Rounds)

```python
COACH_EVOLUTION_PROMPT = """You are an expert Pokémon TCG deck builder and analyst. Your job is to analyze round performance data and suggest card swaps to improve the deck.

## Current Deck
{deck_list}

## Round {round_number} Performance
- Win Rate: {win_rate}% ({wins}/{total} games)
- Win Rate per Opponent:
{per_opponent_stats}

## Card Performance This Round
{card_performance_table}
(Columns: Card Name | Games Active | KOs | Damage Dealt | Times KO'd | Contribution Score)

## Historical Card Performance (from {total_historical_games} past games)
{historical_performance}

## Synergy Data (from memory graph)
Top synergies in current deck:
{synergy_data}

Weakest synergies in current deck:
{weak_synergy_data}

## Similar Past Situations
{similar_situations}

## Candidate Replacement Cards
{candidate_cards}
(Cards NOT in the current deck with strong historical performance)

## Excluded Cards (DO NOT suggest these)
{excluded_cards}

## Constraints
- You may swap between 0 and {max_swaps} cards
- The deck must remain exactly 60 cards
- Basic Pokémon card limit: 4 copies max per card name
- You cannot remove a Pokémon if it would break an evolution line
- Consider energy balance when swapping energy cards
- If the deck is performing well (>{good_threshold}% win rate), prefer fewer changes

## Instructions
Analyze the data and decide which cards (if any) to swap. For each swap, explain your reasoning based on the data provided.

Respond with ONLY a JSON object:
{{
  "analysis": "<2-3 sentence overall assessment>",
  "swaps": [
    {{
      "remove": "<card tcgdex_id>",
      "remove_name": "<card name>",
      "add": "<card tcgdex_id>", 
      "add_name": "<card name>",
      "reasoning": "<why this swap improves the deck>"
    }}
  ]
}}

If no swaps are needed, return {{"analysis": "<assessment>", "swaps": []}}"""
```

### Prompt Template: Deck Name Generation

```python
DECK_NAME_PROMPT = """Given this Pokémon TCG deck list, generate a short archetype name (2-4 words) that describes the deck's strategy or key Pokémon.

Examples of good names:
- "Charizard ex Control"
- "Lugia VSTAR Turbo"
- "Lost Box Giratina"
- "Dragapult Spread"
- "Iron Hands Brawl"

Deck list:
{deck_list}

Respond with ONLY the deck name, nothing else."""
```

### Prompt Template: Deck Completion (Partial Deck Mode)

```python
DECK_COMPLETION_PROMPT = """You are an expert Pokémon TCG deck builder. A player has provided a partial deck. Complete it to exactly 60 cards using the best available cards from the card pool.

## Partial Deck ({current_count}/60 cards)
{partial_deck_list}

## Available Card Pool (cards you can add)
{available_cards}

## Historical Performance Data
{card_performance}

## Synergy Data with Existing Cards
{synergies}

## Constraints
- Final deck must be exactly 60 cards
- Maximum 4 copies of any card (except Basic Energy)
- Maintain a viable energy base for the Pokémon types in the deck
- Include sufficient draw/search Trainers (typically 8-12 Supporters)
- Ensure enough Basic Pokémon for consistent setup (typically 8-15)

## Instructions
Select cards to add that create the strongest, most consistent deck.

Respond with ONLY a JSON object:
{{
  "additions": [
    {{"tcgdex_id": "<id>", "name": "<name>", "quantity": <n>, "reasoning": "<brief>"}}
  ],
  "strategy_summary": "<2-3 sentences explaining the completed deck's strategy>"
}}"""
```

### Prompt Template: Deck From Scratch (No Deck Mode)

```python
DECK_FROM_SCRATCH_PROMPT = """You are an innovative Pokémon TCG deck builder. Build a competitive 60-card deck from scratch using the available card pool. 

IMPORTANT: Avoid building a deck that matches a known meta archetype. The goal is to find an underexplored strategy.

## Known Meta Archetypes (AVOID these)
{meta_archetypes}

## Available Card Pool
{available_cards}

## Card Performance Rankings (from {total_games} simulated games)
{card_rankings}

## Underutilized High-Performers
{underutilized_cards}
(Cards with high individual win rates but low usage in existing decks)

## Synergy Clusters
{synergy_clusters}
(Groups of cards with strong mutual synergy that don't form known archetypes)

## Constraints
- Exactly 60 cards
- Maximum 4 copies of any card (except Basic Energy)
- Must include 8-15 Basic Pokémon for setup consistency
- Must include 8-12 Supporters for draw consistency  
- Energy count should support the Pokémon types chosen

Respond with ONLY a JSON object:
{{
  "deck": [
    {{"tcgdex_id": "<id>", "name": "<name>", "quantity": <n>}}
  ],
  "archetype_name": "<creative 2-4 word name>",
  "strategy": "<3-4 sentences explaining the deck's win condition and strategy>"
}}"""
```

-----

## 23. Appendix E — API Endpoint Reference

### Simulations

|Method  |Path                                    |Description                                 |
|--------|----------------------------------------|--------------------------------------------|
|`POST`  |`/api/simulations`                      |Create and queue a new simulation           |
|`GET`   |`/api/simulations`                      |List all simulations (paginated, filterable)|
|`GET`   |`/api/simulations/:id`                  |Get simulation details + status             |
|`GET`   |`/api/simulations/:id/rounds`           |Get all rounds for a simulation             |
|`GET`   |`/api/simulations/:id/rounds/:n/matches`|Get matches for a specific round            |
|`GET`   |`/api/simulations/:id/dashboard`        |Get all dashboard data (aggregated)         |
|`GET`   |`/api/simulations/:id/mutations`        |Get all deck mutations                      |
|`GET`   |`/api/simulations/:id/decisions`        |Get AI decisions (paginated)                |
|`PATCH` |`/api/simulations/:id/star`             |Toggle star status                          |
|`DELETE`|`/api/simulations/:id`                  |Delete simulation and all related data      |
|`POST`  |`/api/simulations/:id/cancel`           |Cancel a running simulation                 |
|`GET`   |`/api/simulations/compare`              |Compare up to 3 simulations (`?ids=a,b,c`)  |

### Decks

|Method|Path                  |Description                            |
|------|----------------------|---------------------------------------|
|`POST`|`/api/decks/parse`    |Parse and validate a PTCG deck list    |
|`GET` |`/api/decks/:id`      |Get deck details                       |
|`GET` |`/api/decks/:id/cards`|Get cards in a deck with full card data|

### Cards

|Method|Path                               |Description                           |
|------|-----------------------------------|--------------------------------------|
|`GET` |`/api/cards`                       |List all cards (paginated, searchable)|
|`GET` |`/api/cards/:tcgdex_id`            |Get full card details                 |
|`GET` |`/api/cards/:tcgdex_id/performance`|Get card performance stats            |
|`GET` |`/api/cards/search?q=`             |Search cards by name (fuzzy)          |

### Memory

|Method|Path                         |Description                                        |
|------|-----------------------------|---------------------------------------------------|
|`GET` |`/api/memory/card/:tcgdex_id`|Get card memory profile (stats + graph data)       |
|`GET` |`/api/memory/graph`          |Get graph data for mind map (`?card_id=&depth=`)   |
|`GET` |`/api/memory/decisions`      |Search decisions (`?card_id=&action_type=&q=`)     |
|`GET` |`/api/memory/stats`          |Get overall memory stats (total games, cards, etc.)|

### System

|Method|Path             |Description                                |
|------|-----------------|-------------------------------------------|
|`GET` |`/api/health`    |System health check                        |
|`POST`|`/api/cards/sync`|Trigger card sync from POKEMON_MASTER_LIST.md + TCGDex|

-----

## 24. Appendix F — WebSocket Event Protocol

All events are published to channel `simulation:{simulation_id}` via Redis pub/sub and forwarded to subscribed WebSocket clients.

### Event Types

```typescript
// All events have this base shape
interface SimEvent {
  type: string;
  timestamp: string;  // ISO 8601
}

// Simulation lifecycle
interface RoundStartEvent extends SimEvent {
  type: "round_start";
  round: number;
  deck_snapshot: DeckCard[];  // Current deck for this round
}

interface RoundEndEvent extends SimEvent {
  type: "round_end";
  round: number;
  win_rate: number;
  matches_played: number;
}

interface SimulationCompleteEvent extends SimEvent {
  type: "simulation_complete";
  final_win_rate: number;
  rounds_completed: number;
  total_matches: number;
}

interface SimulationErrorEvent extends SimEvent {
  type: "simulation_error";
  error: string;
}

// Match events (streamed during play)
interface MatchStartEvent extends SimEvent {
  type: "match_start";
  match_id: string;
  round: number;
  opponent_deck_name: string;
}

interface MatchEventEvent extends SimEvent {
  type: "match_event";
  match_id: string;
  event_type: string;       // "energy_attached", "attack", "ko", etc.
  turn: number;
  player: string;
  description: string;      // Human-readable description for console
  data: Record<string, any>; // Full event data
}

interface MatchEndEvent extends SimEvent {
  type: "match_end";
  match_id: string;
  winner: string;
  win_condition: string;
  total_turns: number;
}

// AI decision events (AI/H and AI/AI only)
interface DecisionEvent extends SimEvent {
  type: "decision";
  match_id: string;
  decision_id: string;      // For clicking to get details
  turn: number;
  player: string;
  action_type: string;
  card_name: string;
  reasoning: string;         // AI reasoning text
}

// Coach events
interface DeckMutationEvent extends SimEvent {
  type: "deck_mutation";
  round: number;
  mutations: Array<{
    removed: string;         // Card name
    removed_id: string;      // tcgdex_id
    added: string;           // Card name
    added_id: string;        // tcgdex_id
    reasoning: string;
  }>;
}

interface TargetReachedEvent extends SimEvent {
  type: "target_reached";
  round: number;
  win_rate: number;
  target_win_rate: number;
}
```

-----

## 25. Appendix G — TCGDex Card Data Contract

TCGDex API response shape for a card (`GET /v2/en/cards/{setId}/{number}`):

```json
{
  "id": "sv03-006",
  "localId": "006",
  "name": "Charizard ex",
  "image": "https://assets.tcgdex.net/en/sv/sv03/006",
  "category": "Pokemon",
  "illustrator": "5ban Graphics",
  "rarity": "Double Rare",
  "variants": { "normal": true, "reverse": false, "holo": false },
  "hp": 330,
  "types": ["Fire"],
  "evolveFrom": "Charmeleon",
  "stage": "Stage2",
  "attacks": [
    {
      "name": "Brave Wing",
      "cost": ["Fire", "Colorless"],
      "damage": "60",
      "effect": "If this Pokémon has any damage counters on it, this attack does 100 more damage."
    },
    {
      "name": "Burning Dark",
      "cost": ["Fire", "Fire", "Colorless"],
      "damage": "180",
      "effect": "This attack does 30 more damage for each Prize card your opponent has taken."
    }
  ],
  "abilities": [],
  "weaknesses": [{ "type": "Water", "value": "×2" }],
  "resistances": [],
  "retreat": 2,
  "regulationMark": "G",
  "set": {
    "id": "sv03",
    "name": "Obsidian Flames",
    "logo": "...",
    "symbol": "...",
    "cardCount": { "total": 230, "official": 197 }
  }
}
```

**Important TCGDex quirks to handle:**

1. **`damage` is a string**, not an integer. It can be “60”, “60+”, “30×”, or “” (no damage). Parse accordingly.
1. **`cost` is an array of energy type strings.** “Colorless” means any energy type satisfies it.
1. **`effect` is human-readable text**, NOT machine-parseable. Effect logic must be hand-coded.
1. **`retreat` is an integer** representing the number of Colorless energy required.
1. **Some cards may not have all fields.** Trainer cards typically lack `hp`, `attacks`, `weaknesses`, etc. Trainer cards use `trainerType` (item/supporter/stadium/tool) and energy cards use `energyType` (basic/special) for subcategorization.
1. **Card ID format is `{setId}-{localId:03d}`.** Example: `sv06-130` for Dragapult ex (TWM 130). The local ID is zero-padded to 3 digits.
1. **Set IDs use zero-padded format.** Example: `sv01` not `sv1`, `sv03.5` not `sv3pt5`. Always verify the mapping in `SET_CODE_MAP` against `https://api.tcgdex.net/v2/en/sets`.
1. **Mega Evolution era sets may use different ID patterns** than the SV-era `svNN` format. Verify each ME-era set ID against the API when first loading those cards.

-----

## 26. Appendix H — Deck Format Specification

### Standard PTCG Deck Format

This is the format exported by Pokémon TCG Live and PTCG Online. All deck input/output uses this format.

```
Pokémon: 15

3 Charmander OBF 4
1 Charmander MEW 4
2 Charmeleon OBF 5
3 Charizard ex OBF 6
2 Pidgey OBF 162
2 Pidgeot ex OBF 164
1 Manaphy BRS 41
1 Lumineon V BRS 40

Trainer: 35

4 Iono PAF 80
3 Boss's Orders PAL 172
2 Professor's Research SVI 189
4 Rare Candy SVI 191
4 Ultra Ball SVI 196
3 Nest Ball SVI 181
2 Super Rod PAL 188
2 Switch SVI 194
1 Lost Vacuum CRZ 135
1 Forest Seal Stone SIT 156
2 Magma Basin BRS 144
4 Battle VIP Pass FST 225
1 Choice Belt PAL 176
1 Escape Rope BST 125
1 Temple of Sinnoh ASR 155

Energy: 10

10 Fire Energy SVE 2
```

### Parser Rules

1. **Section headers** match `/^Pok[eé]mon/i`, `/^Trainer/i`, `/^Energy/i`
1. **Card lines** match `/^(\d+)\s+(.+?)\s+([A-Z]{2,4})\s+(\d+)$/`
1. **Basic energy** may appear as just `10 Fire Energy` without set/number
1. **Validation:** Total cards must equal 60. Max 4 copies of any non-basic-energy card (matched by name, not set/number — “Charmander OBF 4” and “Charmander MEW 4” count as 2 Charmander total, both capped at max 4 combined only if they share the same name).
1. **Alternate arts** of the same card (same name, different set/number) share the 4-copy limit.

-----

## 27. Appendix I — Heuristic Player Decision Trees

### Setup Phase

```
1. Identify all Basic Pokémon in hand
2. If zero basics → mulligan
3. Choose active:
   a. Prefer Pokémon with abilities that activate from Active (e.g., Lumineon V)
   b. Else prefer Pokémon that are NOT your main attacker (preserve them)
   c. Else prefer highest HP Basic
4. Choose bench:
   a. Place all other Basics from hand (up to bench limit)
   b. Prioritize Pokémon that evolve into useful Stage 1/2
```

### Main Phase Priority Chain

Each evaluator checks if it can produce an action. First one to return an action wins.

```
Priority 1: EMERGENCY ACTIONS
  - If active has ≤30 HP AND bench has a healthy Pokémon → retreat (if can pay cost)
  - If active is Paralyzed and has retreat cost 0 → retreat

Priority 2: DRAW/SEARCH ABILITIES
  - If have Pokémon with draw/search ability that hasn't been used → use it
  - Examples: Pidgeot ex "Quick Search", Lumineon V "Luminous Sign"

Priority 3: SUPPORTER PLAY
  - If hand size ≤ 3 AND haven't played Supporter → play draw Supporter
  - Priority: Professor's Research > Iono (if opponent has fewer prizes)
  - If opponent has high-value bench target AND have Boss's Orders → play it

Priority 4: EVOLUTION
  - If can evolve any Pokémon (wasn't played this turn) → evolve
  - Priority: evolve active attacker > evolve bench attacker > evolve support

Priority 5: ENERGY ATTACHMENT
  - If haven't attached energy this turn:
    a. Attach to active if it needs energy to attack
    b. Else attach to bench Pokémon closest to attacking
    c. Match energy type to Pokémon's attack cost

Priority 6: BENCH DEVELOPMENT  
  - If have Basic Pokémon in hand that aren't already represented → play to bench
  - Prioritize evolution bases over standalone basics

Priority 7: ITEM PLAY
  - Play search items (Ultra Ball, Nest Ball) to find missing pieces
  - Play tools on active attacker
  - Play Switch/Escape Rope if beneficial
  - Play Stadium if beneficial

Priority 8: PASS TO ATTACK
  - If active can attack → pass to attack phase
  - Else → end turn
```

### Attack Phase

```
1. Evaluate all available attacks:
   a. Can any attack KO the opponent's active? → use it
   b. If multiple can KO → prefer the one with lower energy cost
   c. If none can KO → prefer higher damage
   d. Consider attack effects (draw, discard, switch, etc.)

2. If no attacks are affordable → end turn

3. Special considerations:
   - If attacking gives opponent a favorable prize trade → consider not attacking
   - If opponent's active has low HP and you have spread damage → use spread
```

### Retreat Decision

```
Should retreat when:
  1. Active cannot attack AND bench Pokémon can
  2. Active is at type disadvantage AND bench has neutral/advantaged Pokémon
  3. Active has been set up as a "pivot" (low retreat cost, used to buy time)
  4. Active has status condition that prevents action AND can afford retreat cost

Should NOT retreat when:
  1. Active is the best attacker available
  2. Cannot afford retreat cost
  3. Already retreated this turn
  4. No bench Pokémon is meaningfully better
```

-----

## 28. Appendix J — Card Effect Implementation Guide

### Naming Convention

Effect files are organized by category under `app/engine/effects/`:

```
effects/
├── registry.py          # EffectRegistry singleton
├── base.py              # BaseEffect and helper functions
├── attacks.py           # Attack effects (all Pokémon attacks with non-flat damage)
├── abilities.py         # Ability effects
├── trainers.py          # Trainer card effects
└── energies.py          # Special energy effects
```

### Common Effect Patterns

#### Pattern 1: Conditional Damage

```python
def _charizard_ex_brave_wing(state: GameState, action: Action) -> GameState:
    """Brave Wing: 60 damage. +100 if this Pokémon has damage counters."""
    attacker = state.get_player(action.player_id).active
    defender = state.get_opponent(action.player_id).active
    
    base_damage = 60
    if attacker.damage_counters > 0:
        base_damage += 100
    
    final_damage = apply_weakness_resistance(base_damage, attacker, defender)
    defender.current_hp -= final_damage
    defender.damage_counters += final_damage // 10
    
    state.emit_event("attack_damage",
        attacker=attacker.card_name,
        defender=defender.card_name,
        damage=final_damage,
        bonus_applied=attacker.damage_counters > 0
    )
    return state
```

#### Pattern 2: Scaling Damage

```python
def _charizard_ex_burning_dark(state: GameState, action: Action) -> GameState:
    """Burning Dark: 180 + 30 per Prize card opponent has taken."""
    player = state.get_player(action.player_id)
    opponent = state.get_opponent(action.player_id)
    
    prizes_taken = 6 - opponent.prizes_remaining
    base_damage = 180 + (30 * prizes_taken)
    
    final_damage = apply_weakness_resistance(base_damage, player.active, opponent.active)
    opponent.active.current_hp -= final_damage
    # ...
```

#### Pattern 3: Search Deck

```python
def _ultra_ball_effect(state: GameState, action: Action) -> GameState:
    """Ultra Ball: Discard 2 cards → search deck for any Pokémon."""
    player = state.get_player(action.player_id)
    
    # action.selected_cards[0:2] are the cards to discard
    # action.selected_cards[2] is the Pokémon to search for
    
    for discard_id in action.selected_cards[:2]:
        card = find_and_remove(player.hand, discard_id)
        card.zone = Zone.DISCARD
        player.discard.append(card)
    
    if len(action.selected_cards) > 2:
        search_target = action.selected_cards[2]
        card = find_and_remove(player.deck, search_target)
        if card:
            card.zone = Zone.HAND
            player.hand.append(card)
            import random
            random.shuffle(player.deck)
    
    state.emit_event("trainer_played",
        card="Ultra Ball",
        discarded=2,
        searched=action.selected_cards[2] if len(action.selected_cards) > 2 else None
    )
    return state
```

#### Pattern 4: Global Effect (Stadium)

```python
def _magma_basin_effect(state: GameState, action: Action) -> GameState:
    """
    Magma Basin (Stadium): Once per turn, each player may attach a Fire Energy
    from discard to a benched Pokémon, then put 2 damage counters on that Pokémon.
    
    NOTE: Stadium effects are checked/offered during the main phase.
    The engine calls stadium effects at the start of each player's main phase.
    """
    player = state.get_player(action.player_id)
    
    # Find Fire energy in discard
    fire_in_discard = [c for c in player.discard 
                       if c.card_type == "energy" and "Fire" in c.provides]
    
    if fire_in_discard and action.selected_cards:
        energy_card = find_and_remove(player.discard, action.selected_cards[0])
        target = find_card_on_bench(player, action.target_instance_id)
        
        if energy_card and target:
            target.energy_attached.append(
                EnergyAttachment(EnergyType.FIRE, energy_card.instance_id, [EnergyType.FIRE])
            )
            target.damage_counters += 2
            target.current_hp -= 20
            
            state.emit_event("stadium_used",
                stadium="Magma Basin",
                energy_attached_to=target.card_name,
                damage_counters_added=2
            )
    
    return state
```

### Helper Functions

```python
# app/engine/effects/base.py

def apply_weakness_resistance(
    base_damage: int, 
    attacker: CardInstance, 
    defender: CardInstance
) -> int:
    """Apply weakness (×2) and resistance (-30) based on type matchups."""
    damage = base_damage
    
    # Check weakness (defender's weakness matches attacker's type)
    # Weakness info comes from the card definition, looked up from DB
    attacker_types = get_card_types(attacker.card_def_id)
    defender_weaknesses = get_card_weaknesses(defender.card_def_id)
    
    for weakness in defender_weaknesses:
        if weakness["type"] in attacker_types:
            damage *= 2
            break
    
    # Check resistance
    defender_resistances = get_card_resistances(defender.card_def_id)
    for resistance in defender_resistances:
        if resistance["type"] in attacker_types:
            damage -= 30
            break
    
    return max(0, damage)

def check_ko(state: GameState, target: CardInstance, target_player_id: str) -> bool:
    """Check if a Pokémon is knocked out and handle prize taking."""
    if target.current_hp <= 0:
        player = state.get_player(target_player_id)
        opponent = state.get_opponent(target_player_id)
        
        # Determine prize count (ex/V/VMAX = 2, VSTAR = 2, regular = 1)
        prizes = get_prize_value(target)
        
        # Take prizes
        for _ in range(min(prizes, opponent.prizes_remaining)):
            if opponent.prizes:
                prize_card = opponent.prizes.pop(0)
                prize_card.zone = Zone.HAND
                opponent.hand.append(prize_card)
                opponent.prizes_remaining -= 1
        
        # Move KO'd Pokémon to discard
        target.zone = Zone.DISCARD
        player.discard.append(target)
        if target == player.active:
            player.active = None
        elif target in player.bench:
            player.bench.remove(target)
        
        # Discard attached energy and tools
        for energy in target.energy_attached:
            energy_card = find_card_by_instance_id(state, energy.source_card_id)
            if energy_card:
                energy_card.zone = Zone.DISCARD
                player.discard.append(energy_card)
        target.energy_attached.clear()
        
        state.emit_event("knockout",
            pokemon=target.card_name,
            player=target_player_id,
            prizes_taken=prizes,
            attacker_prizes_remaining=opponent.prizes_remaining
        )
        
        # Check win conditions
        if opponent.prizes_remaining <= 0:
            state.phase = Phase.GAME_OVER
            state.winner = state.get_opponent(target_player_id).player_id
            state.win_condition = "prizes"
        elif player.active is None and not player.bench:
            state.phase = Phase.GAME_OVER
            state.winner = state.get_opponent(target_player_id).player_id
            state.win_condition = "no_bench"
        
        return True
    return False

def get_prize_value(card: CardInstance) -> int:
    """Determine how many prizes a KO on this card is worth."""
    # Look up from card definition
    stage = get_card_stage(card.card_def_id)
    name = card.card_name.lower()
    
    if "ex" in name or " v " in name or name.endswith(" v"):
        return 2
    if "vstar" in name or "vmax" in name:
        return 2
    return 1
```

-----

## Development Checklist Summary

|Phase |Description                     |Estimated Duration|Dependencies|Status    |
|------|--------------------------------|------------------|------------|----------|
|1     |Game Engine Core                |2-3 weeks         |None        |✅ Complete|
|2     |Card Effect Registry (157 cards)|2-3 weeks         |Phase 1     |          |
|3     |Heuristic Player & H/H Loop     |1-2 weeks         |Phases 1, 2 |          |
|4     |Database Layer & Memory Stack   |2 weeks           |Phase 3     |          |
|5     |AI Player Integration           |1-2 weeks         |Phases 3, 4 |          |
|6     |Coach/Analyst System            |2 weeks           |Phases 4, 5 |          |
|7     |Task Queue & Orchestration      |1-2 weeks         |Phase 6     |          |
|8     |Frontend: Setup Page            |1-2 weeks         |Phase 7     |          |
|9     |Frontend: Live Console          |1-2 weeks         |Phase 8     |          |
|10    |Frontend: Dashboard             |2-3 weeks         |Phase 8     |          |
|11    |Frontend: History & Memory      |2 weeks           |Phases 8, 10|          |
|**12**|**Card Pool Expansion**         |**Ongoing**       |**Phase 11**|          |
|13    |Polish & Hardening              |1-2 weeks         |All above   |          |

**Total estimated timeline: 20-30 weeks** (working part-time, 10-15 hrs/week)

-----

*This document is the authoritative blueprint for PokéPrism. All implementation decisions should reference this document. If a conflict arises between this document and ad-hoc decisions made during development, update this document to reflect the resolved decision so it remains the single source of truth.*

### Revision Log

|Date        |Changes                                                                                                                                                                                                                                                                                                                                                                                                                              |
|------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
|Initial     |Original blueprint created                                                                                                                                                                                                                                                                                                                                                                                                           |
|Post-Phase 1|SET_CODE_MAP corrected to use zero-padded TCGDex IDs (13 fixes). Added 6 ME-era sets (MEG, PFL, MEE, WHT, ASC, POR). Added M4 exclusion note. Fixed TCGDex card URL format to `{setId}-{localId:03d}`. Added `energy_provides` field to CardInstance. Updated card pool count from ~120 to 157. Added Phase 1 completion notes with baseline metrics. Added PR-SV promo gap note. Updated Phase 12 to reflect actual expansion scope.|
