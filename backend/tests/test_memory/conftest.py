"""Shared fixtures for memory integration tests."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine


@pytest.fixture
async def db_session():
    """Fresh AsyncSession per test with rollback teardown for test isolation.

    Uses a connection-level outer transaction that is always rolled back at
    teardown, with a SAVEPOINT for the session. When a test calls
    session.commit(), it releases the SAVEPOINT (data becomes visible within
    the outer transaction) but the outer transaction is rolled back at
    teardown — nothing persists to the production DB.
    """
    from app.config import settings
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            await session.begin_nested()  # SAVEPOINT — session.commit() releases it
            yield session
        await conn.rollback()
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
