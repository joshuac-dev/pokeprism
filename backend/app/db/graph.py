"""Neo4j driver singleton and constraint bootstrap."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from neo4j import AsyncGraphDatabase, AsyncDriver

from app.config import settings

_driver: AsyncDriver | None = None


def get_driver() -> AsyncDriver:
    """Return the singleton Neo4j async driver (initialised on first call)."""
    global _driver
    if _driver is None:
        _driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
        )
    return _driver


async def close_driver() -> None:
    global _driver
    if _driver is not None:
        await _driver.close()
        _driver = None


@asynccontextmanager
async def graph_session() -> AsyncGenerator:
    """Async context manager yielding a Neo4j session."""
    async with get_driver().session() as session:
        yield session


_CONSTRAINTS = [
    "CREATE CONSTRAINT card_unique IF NOT EXISTS FOR (c:Card) REQUIRE c.tcgdex_id IS UNIQUE",
    "CREATE CONSTRAINT deck_unique IF NOT EXISTS FOR (d:Deck) REQUIRE d.deck_id IS UNIQUE",
    "CREATE CONSTRAINT archetype_unique IF NOT EXISTS FOR (a:Archetype) REQUIRE a.name IS UNIQUE",
    "CREATE CONSTRAINT match_unique IF NOT EXISTS FOR (m:MatchResult) REQUIRE m.match_id IS UNIQUE",
    "CREATE INDEX card_name_idx IF NOT EXISTS FOR (c:Card) ON (c.name)",
    "CREATE INDEX card_category_idx IF NOT EXISTS FOR (c:Card) ON (c.category)",
]


async def ensure_constraints() -> None:
    """Idempotently create Neo4j constraints and indexes."""
    async with graph_session() as session:
        for cypher in _CONSTRAINTS:
            await session.run(cypher)
