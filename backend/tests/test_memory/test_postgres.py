"""Integration tests for MatchMemoryWriter → PostgreSQL.

These tests require a live Postgres instance (started via docker compose).
They are skipped if the DB is unreachable so CI without Docker still passes.
"""

import asyncio
import uuid

import pytest

from app.engine.runner import MatchResult

# ---------------------------------------------------------------------------
# Skip guard — if Postgres is unreachable, skip the whole module
# ---------------------------------------------------------------------------

def _db_reachable() -> bool:
    try:
        from app.config import settings

        async def _check():
            import asyncpg
            url = settings.DATABASE_URL.replace(
                "postgresql+asyncpg://", "postgresql://"
            )
            conn = await asyncpg.connect(url, timeout=3)
            await conn.close()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_check())
        finally:
            loop.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_reachable(), reason="Postgres not reachable — skipping DB integration tests"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_result() -> MatchResult:
    return MatchResult(
        game_id=str(uuid.uuid4()),
        winner="p1",
        win_condition="prizes",
        total_turns=30,
        p1_prizes_taken=6,
        p2_prizes_taken=2,
        events=[
            {"type": "game_start"},
            {"type": "attack", "player": "p1", "damage": 60},
            {"type": "game_over", "winner": "p1"},
        ],
        p1_deck_name="TestDeck-A",
        p2_deck_name="TestDeck-B",
    )


@pytest.fixture
def minimal_cards():
    from app.cards.models import CardDefinition
    return [
        CardDefinition(tcgdex_id="test-001", name="TestPoke", set_abbrev="TST",
                       set_number="001", hp=100, category="Pokemon"),
        CardDefinition(tcgdex_id="test-002", name="TestTrainer", set_abbrev="TST",
                       set_number="002", category="Trainer"),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_write_match_creates_row(sample_result, minimal_cards, db_session):
    """write_match() inserts a row in matches and rows in match_events."""
    from sqlalchemy import text
    from app.memory.postgres import MatchMemoryWriter

    db = db_session
    writer = MatchMemoryWriter()
    sim_id = uuid.uuid4()
    round_id = uuid.uuid4()

    await writer.ensure_cards(minimal_cards, db)
    deck_id = await writer.ensure_deck("TestDeck-A", minimal_cards * 30, db)
    deck_id_b = await writer.ensure_deck("TestDeck-B", minimal_cards * 30, db)
    await writer.ensure_simulation(sim_id, db)
    await writer.ensure_round(round_id, sim_id, 1, {"test": True}, db)

    match_id = await writer.write_match(
        result=sample_result,
        simulation_id=sim_id,
        round_id=round_id,
        round_number=1,
        p1_deck_id=deck_id,
        p2_deck_id=deck_id_b,
        db=db,
    )
    await db.commit()

    match_count = (await db.execute(
        text("SELECT COUNT(*) FROM matches WHERE id = :mid"),
        {"mid": match_id},
    )).scalar()
    event_count = (await db.execute(
        text("SELECT COUNT(*) FROM match_events WHERE match_id = :mid"),
        {"mid": match_id},
    )).scalar()

    assert match_count == 1, "Expected 1 row in matches"
    assert event_count == len(sample_result.events), (
        f"Expected {len(sample_result.events)} events, got {event_count}"
    )


@pytest.mark.asyncio
async def test_ensure_deck_idempotent(minimal_cards, db_session):
    """ensure_deck() returns the same UUID on repeated calls."""
    from app.memory.postgres import MatchMemoryWriter

    db = db_session
    writer = MatchMemoryWriter()
    await writer.ensure_cards(minimal_cards, db)
    id1 = await writer.ensure_deck("IdempotentDeck", minimal_cards * 30, db)
    id2 = await writer.ensure_deck("IdempotentDeck", minimal_cards * 30, db)
    await db.commit()

    assert id1 == id2, "ensure_deck should return the same UUID for the same name"
