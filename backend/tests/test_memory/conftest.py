"""Shared fixtures for memory integration tests."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def db_session():
    """Fresh AsyncSession per test (avoids event-loop-binding issues with the module singleton)."""
    from app.config import settings
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def reset_neo4j_singleton():
    """Forcefully nil the Neo4j driver singleton before each test.

    GraphMemoryWriter uses the module-level _driver which is bound to an event
    loop. pytest-asyncio creates a new loop per test, so we must nil the
    singleton before each test so it is recreated in the current loop.
    We do NOT await close() because the old loop is already shut down.
    """
    from app.db import graph as graph_module
    graph_module._driver = None
    yield
    graph_module._driver = None
