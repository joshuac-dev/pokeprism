"""Integration tests for GraphMemoryWriter → Neo4j.

Skipped if Neo4j is unreachable so CI without Docker still passes.
"""

import asyncio
import uuid

import pytest

from app.engine.runner import MatchResult


def _neo4j_reachable() -> bool:
    try:
        from app.config import settings
        from neo4j import AsyncGraphDatabase

        async def _check():
            driver = AsyncGraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            )
            await driver.verify_connectivity()
            await driver.close()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_check())
        finally:
            loop.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _neo4j_reachable(),
    reason="Neo4j not reachable — skipping graph integration tests",
)


@pytest.fixture
def sample_result() -> MatchResult:
    return MatchResult(
        game_id=str(uuid.uuid4()),
        winner="p1",
        win_condition="prizes",
        total_turns=20,
        p1_prizes_taken=6,
        p2_prizes_taken=1,
        events=[{"type": "game_over"}],
        p1_deck_name="GraphTestDeck-A",
        p2_deck_name="GraphTestDeck-B",
    )


@pytest.fixture
def small_deck():
    from app.cards.models import CardDefinition
    return [
        CardDefinition(tcgdex_id=f"gt-{i:03d}", name=f"GraphCard{i}",
                       set_abbrev="GT", set_number=f"{i:03d}",
                       hp=100, category="Pokemon")
        for i in range(3)
    ] * 20   # 60-card deck from 3 unique cards


def _unique_deck(prefix: str, count: int = 3):
    from app.cards.models import CardDefinition
    return [
        CardDefinition(tcgdex_id=f"{prefix}-{i:03d}", name=f"{prefix} Card {i}",
                       set_abbrev="GT", set_number=f"{i:03d}",
                       hp=100, category="Pokemon")
        for i in range(count)
    ]


@pytest.mark.asyncio
async def test_write_match_creates_deck_nodes(sample_result, small_deck):
    """write_match() creates Deck nodes in Neo4j."""
    from app.db.graph import graph_session
    from app.memory.graph import GraphMemoryWriter

    writer = GraphMemoryWriter()
    p1_id = uuid.uuid4()
    p2_id = uuid.uuid4()
    match_id = uuid.uuid4()

    await writer.write_match(
        result=sample_result,
        match_id=match_id,
        p1_deck_id=p1_id,
        p2_deck_id=p2_id,
        p1_card_defs=small_deck,
        p2_card_defs=small_deck,
    )

    async with graph_session() as session:
        result = await session.run(
            "MATCH (d:Deck {deck_id: $did}) RETURN d.name AS name",
            did=str(p1_id),
        )
        record = await result.single()

    assert record is not None, "Deck node for P1 should exist in Neo4j"
    assert record["name"] == "GraphTestDeck-A"


@pytest.mark.asyncio
async def test_synergizes_with_edges_created(sample_result, small_deck):
    """Winning deck cards get SYNERGIZES_WITH edges with positive weight."""
    from app.db.graph import graph_session
    from app.memory.graph import GraphMemoryWriter

    writer = GraphMemoryWriter()
    p1_id = uuid.uuid4()
    p2_id = uuid.uuid4()

    await writer.write_match(
        result=sample_result,
        match_id=uuid.uuid4(),
        p1_deck_id=p1_id,
        p2_deck_id=p2_id,
        p1_card_defs=small_deck,
        p2_card_defs=small_deck,
    )

    async with graph_session() as session:
        result = await session.run(
            """
            MATCH (a:Card {tcgdex_id: $id_a})-[r:SYNERGIZES_WITH]-(b:Card {tcgdex_id: $id_b})
            RETURN r.weight AS weight
            """,
            id_a="gt-000",
            id_b="gt-001",
        )
        record = await result.single()

    assert record is not None, "SYNERGIZES_WITH edge should exist"
    assert record["weight"] > 0, "Weight should be positive for winning deck"


@pytest.mark.asyncio
async def test_winning_synergy_write_creates_exact_relationship_values(sample_result):
    """A winning 3-unique-card deck creates 3 pair edges at +1.0."""
    from app.db.graph import graph_session
    from app.memory.graph import GraphMemoryWriter

    writer = GraphMemoryWriter()
    deck = _unique_deck(f"gt-win-{uuid.uuid4().hex[:8]}")

    async with graph_session() as session:
        await writer._update_synergies(session, deck, won=True)
        result = await session.run(
            """
            MATCH (a:Card)-[r:SYNERGIZES_WITH]-(b:Card)
            WHERE a.tcgdex_id IN $ids AND b.tcgdex_id IN $ids
              AND a.tcgdex_id < b.tcgdex_id
            RETURN count(r) AS edge_count,
                   collect(r.weight) AS weights,
                   collect(r.games_observed) AS games
            """,
            ids=[c.tcgdex_id for c in deck],
        )
        record = await result.single()

    assert record["edge_count"] == 3
    assert sorted(record["weights"]) == [1.0, 1.0, 1.0]
    assert sorted(record["games"]) == [1, 1, 1]


@pytest.mark.asyncio
async def test_losing_synergy_write_creates_exact_relationship_values():
    """A losing 3-unique-card deck creates 3 pair edges at -0.5."""
    from app.db.graph import graph_session
    from app.memory.graph import GraphMemoryWriter

    writer = GraphMemoryWriter()
    deck = _unique_deck(f"gt-loss-{uuid.uuid4().hex[:8]}")

    async with graph_session() as session:
        await writer._update_synergies(session, deck, won=False)
        result = await session.run(
            """
            MATCH (a:Card)-[r:SYNERGIZES_WITH]-(b:Card)
            WHERE a.tcgdex_id IN $ids AND b.tcgdex_id IN $ids
              AND a.tcgdex_id < b.tcgdex_id
            RETURN count(r) AS edge_count,
                   collect(r.weight) AS weights,
                   collect(r.games_observed) AS games
            """,
            ids=[c.tcgdex_id for c in deck],
        )
        record = await result.single()

    assert record["edge_count"] == 3
    assert sorted(record["weights"]) == [-0.5, -0.5, -0.5]
    assert sorted(record["games"]) == [1, 1, 1]


@pytest.mark.asyncio
async def test_repeated_win_and_loss_accumulates_same_pair_values():
    """Repeated win + loss on the same deck gives weight 0.5, games 2."""
    from app.db.graph import graph_session
    from app.memory.graph import GraphMemoryWriter

    writer = GraphMemoryWriter()
    deck = _unique_deck(f"gt-mix-{uuid.uuid4().hex[:8]}", count=2)

    async with graph_session() as session:
        await writer._update_synergies(session, deck, won=True)
        await writer._update_synergies(session, deck, won=False)
        result = await session.run(
            """
            MATCH (a:Card {tcgdex_id: $id_a})-[r:SYNERGIZES_WITH]-(b:Card {tcgdex_id: $id_b})
            RETURN r.weight AS weight, r.games_observed AS games
            """,
            id_a=deck[0].tcgdex_id,
            id_b=deck[1].tcgdex_id,
        )
        record = await result.single()

    assert record is not None
    assert record["weight"] == 0.5
    assert record["games"] == 2


@pytest.mark.asyncio
async def test_beats_edge_updated(sample_result, small_deck):
    """BEATS edge win_count increments on repeat calls."""
    from app.db.graph import graph_session
    from app.memory.graph import GraphMemoryWriter

    writer = GraphMemoryWriter()
    p1_id = uuid.uuid4()
    p2_id = uuid.uuid4()

    for _ in range(3):
        await writer.write_match(
            result=sample_result,
            match_id=uuid.uuid4(),
            p1_deck_id=p1_id,
            p2_deck_id=p2_id,
            p1_card_defs=small_deck,
            p2_card_defs=small_deck,
        )

    async with graph_session() as session:
        result = await session.run(
            """
            MATCH (a:Deck {deck_id: $p1})-[r:BEATS]->(b:Deck {deck_id: $p2})
            RETURN r.win_count AS wc, r.total_games AS tg, r.win_rate AS wr
            """,
            p1=str(p1_id),
            p2=str(p2_id),
        )
        record = await result.single()

    assert record is not None, "BEATS edge should exist"
    assert record["wc"] == 3, f"win_count should be 3, got {record['wc']}"
    assert record["tg"] == 3, f"total_games should be 3, got {record['tg']}"
    assert abs(record["wr"] - 1.0) < 0.01, "win_rate should be ~1.0 for 3/3"
