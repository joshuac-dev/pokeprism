"""Tests for opponent-batch simulation checkpointing."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.cards.models import CardDefinition
from app.db.models import (
    CardPerformance,
    Deck,
    DeckCard,
    DeckMutation,
    Match,
    Round,
    Simulation,
    SimulationOpponentResult,
)
from app.engine.runner import MatchResult
from app.memory.postgres import MatchMemoryWriter
from app.tasks.simulation import (
    _complete_opponent_checkpoint,
    _load_opponent_match_results,
    _prepare_opponent_checkpoint,
    _round_has_persisted_mutations,
)


def _db_reachable() -> bool:
    try:
        from app.config import settings

        async def _check():
            import asyncpg
            url = settings.DATABASE_URL.replace(
                "postgresql+asyncpg://", "postgresql://"
            )
            conn = await asyncpg.connect(url, timeout=3)
            try:
                await conn.fetchval("SELECT 1 FROM simulation_opponent_results LIMIT 1")
            finally:
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
    not _db_reachable(),
    reason="Postgres/checkpoint table not reachable; skipping checkpoint integration tests",
)


@pytest.fixture
async def db_session():
    from app.config import settings

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            await session.begin_nested()
            yield session
        await conn.rollback()
    await engine.dispose()


def _card(tcgdex_id: str, name: str) -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name=name,
        set_abbrev="TST",
        set_number="1",
        category="Pokemon",
    )


def _result(winner: str = "p1", events: list[dict] | None = None) -> MatchResult:
    return MatchResult(
        game_id=str(uuid.uuid4()),
        winner=winner,
        win_condition="prizes",
        total_turns=10,
        p1_prizes_taken=6 if winner == "p1" else 2,
        p2_prizes_taken=2 if winner == "p1" else 6,
        events=events or [{"event_type": "game_over", "winner": winner}],
        p1_deck_name="Checkpoint P1",
        p2_deck_name="Checkpoint P2",
    )


async def _seed_simulation(db):
    writer = MatchMemoryWriter()
    suffix = uuid.uuid4().hex[:8]
    cards = [_card(f"chk-{suffix}-001", "Checkpoint A"), _card(f"chk-{suffix}-002", "Checkpoint B")]
    await writer.ensure_cards(cards, db)
    p1_deck_id = await writer.ensure_deck(f"Checkpoint P1 {suffix}", cards * 30, db)
    p2_deck_id = await writer.ensure_deck(f"Checkpoint P2 {suffix}", list(reversed(cards)) * 30, db)
    sim = Simulation(
        status="running",
        game_mode="hh",
        deck_mode="full",
        deck_locked=True,
        user_deck_id=p1_deck_id,
        matches_per_opponent=2,
        num_rounds=1,
        target_win_rate=60,
    )
    db.add(sim)
    await db.flush()
    round_row = Round(
        simulation_id=sim.id,
        round_number=1,
        deck_snapshot={"cards": [{"tcgdex_id": c.tcgdex_id, "name": c.name} for c in cards * 30]},
        total_matches=0,
    )
    db.add(round_row)
    await db.flush()
    await db.commit()
    return writer, sim.id, round_row.id, p1_deck_id, p2_deck_id, cards


async def _write_match(db, writer, sim_id, round_id, p1_deck_id, p2_deck_id, result):
    return await writer.write_match(
        result=result,
        simulation_id=sim_id,
        round_id=round_id,
        round_number=1,
        p1_deck_id=p1_deck_id,
        p2_deck_id=p2_deck_id,
        db=db,
    )


@pytest.mark.asyncio
async def test_ensure_deck_cards_for_id_creates_requested_deck_id(db_session):
    writer = MatchMemoryWriter()
    suffix = uuid.uuid4().hex[:8]
    cards = [_card(f"known-{suffix}-001", "Known A")]
    await writer.ensure_cards(cards, db_session)
    deck_id = uuid.uuid4()

    returned = await writer.ensure_deck_cards_for_id(
        deck_id, "Known Deck", cards * 60, db_session
    )
    await db_session.commit()

    assert returned == deck_id
    deck = (await db_session.execute(
        select(Deck).where(Deck.id == deck_id)
    )).scalar_one()
    deck_cards = (await db_session.execute(
        select(DeckCard).where(DeckCard.deck_id == deck_id)
    )).scalars().all()
    assert deck.name == "Known Deck"
    assert [(row.card_tcgdex_id, row.quantity) for row in deck_cards] == [
        (cards[0].tcgdex_id, 60)
    ]


@pytest.mark.asyncio
async def test_ensure_deck_cards_for_id_populates_existing_deck(db_session):
    writer = MatchMemoryWriter()
    suffix = uuid.uuid4().hex[:8]
    cards = [_card(f"existing-{suffix}-001", "Existing A")]
    await writer.ensure_cards(cards, db_session)
    deck_id = uuid.uuid4()
    db_session.add(
        Deck(
            id=deck_id,
            name="Existing Known Deck",
            archetype="Existing Known Deck",
            deck_text="",
            card_count=60,
            source="user",
        )
    )
    await db_session.commit()

    returned = await writer.ensure_deck_cards_for_id(
        deck_id, "Existing Known Deck", cards * 60, db_session
    )
    await db_session.commit()

    assert returned == deck_id
    quantity = (await db_session.execute(
        select(DeckCard.quantity).where(
            DeckCard.deck_id == deck_id,
            DeckCard.card_tcgdex_id == cards[0].tcgdex_id,
        )
    )).scalar_one()
    assert quantity == 60


@pytest.mark.asyncio
async def test_known_deck_ids_are_preserved_when_same_name_decks_exist(db_session):
    writer = MatchMemoryWriter()
    suffix = uuid.uuid4().hex[:8]
    p1_cards = [_card(f"same-name-{suffix}-p1", "Same Name P1")]
    p2_cards = [_card(f"same-name-{suffix}-p2", "Same Name P2")]
    await writer.ensure_cards(p1_cards + p2_cards, db_session)

    older_p1_id = await writer.ensure_deck("Same Name User", p1_cards * 60, db_session)
    older_p2_id = await writer.ensure_deck("Same Name Opponent", p2_cards * 60, db_session)
    scheduled_p1_id = uuid.uuid4()
    scheduled_p2_id = uuid.uuid4()
    db_session.add_all([
        Deck(
            id=scheduled_p1_id,
            name="Same Name User",
            archetype="Same Name User",
            deck_text="",
            card_count=60,
            source="user",
        ),
        Deck(
            id=scheduled_p2_id,
            name="Same Name Opponent",
            archetype="Same Name Opponent",
            deck_text="",
            card_count=60,
            source="opponent",
        ),
    ])
    await db_session.commit()

    p1_id = await writer.ensure_deck_cards_for_id(
        scheduled_p1_id, "Same Name User", p1_cards * 60, db_session
    )
    p2_id = await writer.ensure_deck_cards_for_id(
        scheduled_p2_id, "Same Name Opponent", p2_cards * 60, db_session
    )
    await db_session.commit()

    assert p1_id == scheduled_p1_id
    assert p2_id == scheduled_p2_id
    assert p1_id != older_p1_id
    assert p2_id != older_p2_id


@pytest.mark.asyncio
async def test_same_name_opponent_checkpoint_replay_uses_scheduled_deck_id(db_session):
    writer = MatchMemoryWriter()
    suffix = uuid.uuid4().hex[:8]
    p1_cards = [_card(f"replay-{suffix}-p1", "Replay P1")]
    p2_cards = [_card(f"replay-{suffix}-p2", "Replay P2")]
    await writer.ensure_cards(p1_cards + p2_cards, db_session)

    old_opponent_id = await writer.ensure_deck(
        "Replay Same Name Opponent", p2_cards * 60, db_session
    )
    scheduled_p1_id = await writer.ensure_deck(
        f"Replay P1 {suffix}", p1_cards * 60, db_session
    )
    scheduled_p2_id = uuid.uuid4()
    db_session.add(
        Deck(
            id=scheduled_p2_id,
            name="Replay Same Name Opponent",
            archetype="Replay Same Name Opponent",
            deck_text="",
            card_count=60,
            source="opponent",
        )
    )
    sim = Simulation(
        status="running",
        game_mode="hh",
        deck_mode="full",
        deck_locked=True,
        user_deck_id=scheduled_p1_id,
        matches_per_opponent=1,
        num_rounds=1,
        target_win_rate=60,
    )
    db_session.add(sim)
    await db_session.flush()
    round_row = Round(
        simulation_id=sim.id,
        round_number=1,
        deck_snapshot={
            "cards": [
                {"tcgdex_id": c.tcgdex_id, "name": c.name}
                for c in p1_cards * 60
            ]
        },
        total_matches=0,
    )
    db_session.add(round_row)
    await db_session.flush()
    await db_session.commit()

    assert await _prepare_opponent_checkpoint(
        db_session,
        sim.id,
        round_row.id,
        1,
        scheduled_p2_id,
        "Replay Same Name Opponent",
        1,
    ) == "run"
    await writer.ensure_deck_cards_for_id(
        scheduled_p2_id, "Replay Same Name Opponent", p2_cards * 60, db_session
    )
    await _write_match(
        db_session,
        writer,
        sim.id,
        round_row.id,
        scheduled_p1_id,
        scheduled_p2_id,
        _result("p1"),
    )
    await _complete_opponent_checkpoint(
        db_session, sim.id, 1, scheduled_p2_id, [_result("p1")], "complete"
    )
    await db_session.commit()

    assert old_opponent_id != scheduled_p2_id
    match = (await db_session.execute(
        select(Match).where(Match.simulation_id == sim.id)
    )).scalar_one()
    assert match.opponent_deck_id == scheduled_p2_id

    assert await _prepare_opponent_checkpoint(
        db_session,
        sim.id,
        round_row.id,
        1,
        scheduled_p2_id,
        "Replay Same Name Opponent",
        1,
    ) == "skip"
    await db_session.commit()

    assert (await db_session.execute(
        select(text("count(*)")).select_from(Match).where(Match.simulation_id == sim.id)
    )).scalar_one() == 1


@pytest.mark.asyncio
async def test_fresh_checkpoint_runs_and_completes(db_session):
    _writer, sim_id, round_id, _p1_deck_id, p2_deck_id, _cards = await _seed_simulation(db_session)

    action = await _prepare_opponent_checkpoint(
        db_session, sim_id, round_id, 1, p2_deck_id, "Checkpoint P2", 2
    )
    assert action == "run"

    await _complete_opponent_checkpoint(
        db_session, sim_id, 1, p2_deck_id, [_result("p1"), _result("p2")], "complete"
    )
    await db_session.commit()

    checkpoint = (await db_session.execute(
        select(SimulationOpponentResult).where(
            SimulationOpponentResult.simulation_id == sim_id
        )
    )).scalar_one()
    assert checkpoint.status == "complete"
    assert checkpoint.matches_completed == 2
    assert checkpoint.p1_wins == 1
    assert checkpoint.p2_wins == 1
    assert checkpoint.win_rate == 50
    assert checkpoint.graph_status == "complete"


@pytest.mark.asyncio
async def test_completed_checkpoint_skips_without_duplicate_match_or_card_performance(db_session):
    writer, sim_id, round_id, p1_deck_id, p2_deck_id, cards = await _seed_simulation(db_session)

    assert await _prepare_opponent_checkpoint(
        db_session, sim_id, round_id, 1, p2_deck_id, "Checkpoint P2", 1
    ) == "run"
    await _write_match(db_session, writer, sim_id, round_id, p1_deck_id, p2_deck_id, _result("p1"))
    await _complete_opponent_checkpoint(
        db_session, sim_id, 1, p2_deck_id, [_result("p1")], "complete"
    )
    await db_session.commit()

    before_matches = (await db_session.execute(text("SELECT COUNT(*) FROM matches WHERE simulation_id = :sid"), {"sid": sim_id})).scalar()
    card_ids = {cards[0].tcgdex_id, cards[1].tcgdex_id}
    before_perf = {
        row.card_tcgdex_id: (row.games_included, row.games_won)
        for row in (
            await db_session.execute(
                select(CardPerformance).where(CardPerformance.card_tcgdex_id.in_(card_ids))
            )
        ).scalars().all()
    }

    assert await _prepare_opponent_checkpoint(
        db_session, sim_id, round_id, 1, p2_deck_id, "Checkpoint P2", 1
    ) == "skip"
    await db_session.commit()

    after_matches = (await db_session.execute(text("SELECT COUNT(*) FROM matches WHERE simulation_id = :sid"), {"sid": sim_id})).scalar()
    after_perf = {
        row.card_tcgdex_id: (row.games_included, row.games_won)
        for row in (
            await db_session.execute(
                select(CardPerformance).where(CardPerformance.card_tcgdex_id.in_(card_ids))
            )
        ).scalars().all()
    }
    assert after_matches == before_matches == 1
    assert after_perf == before_perf
    assert set(after_perf) == card_ids


@pytest.mark.asyncio
async def test_completed_checkpoint_count_mismatch_marks_failed(db_session):
    _writer, sim_id, round_id, _p1_deck_id, p2_deck_id, _cards = await _seed_simulation(db_session)
    checkpoint = SimulationOpponentResult(
        simulation_id=sim_id,
        round_id=round_id,
        round_number=1,
        opponent_deck_id=p2_deck_id,
        opponent_deck_name="Checkpoint P2",
        status="complete",
        matches_target=1,
        matches_completed=1,
    )
    db_session.add(checkpoint)
    await db_session.commit()

    with pytest.raises(ValueError, match="Completed opponent checkpoint"):
        await _prepare_opponent_checkpoint(
            db_session, sim_id, round_id, 1, p2_deck_id, "Checkpoint P2", 1
        )
    await db_session.commit()

    assert checkpoint.status == "failed"
    assert "persisted=0" in checkpoint.error_message


@pytest.mark.asyncio
async def test_stale_running_checkpoint_with_zero_matches_reruns(db_session):
    _writer, sim_id, round_id, _p1_deck_id, p2_deck_id, _cards = await _seed_simulation(db_session)
    checkpoint = SimulationOpponentResult(
        simulation_id=sim_id,
        round_id=round_id,
        round_number=1,
        opponent_deck_id=p2_deck_id,
        opponent_deck_name="Checkpoint P2",
        status="running",
        matches_target=2,
    )
    db_session.add(checkpoint)
    await db_session.commit()

    action = await _prepare_opponent_checkpoint(
        db_session, sim_id, round_id, 1, p2_deck_id, "Checkpoint P2", 2
    )
    await db_session.commit()

    assert action == "run"
    assert checkpoint.status == "running"
    assert checkpoint.matches_completed == 0


@pytest.mark.asyncio
async def test_stale_running_checkpoint_with_target_matches_finalizes(db_session):
    writer, sim_id, round_id, p1_deck_id, p2_deck_id, _cards = await _seed_simulation(db_session)
    checkpoint = SimulationOpponentResult(
        simulation_id=sim_id,
        round_id=round_id,
        round_number=1,
        opponent_deck_id=p2_deck_id,
        opponent_deck_name="Checkpoint P2",
        status="running",
        matches_target=2,
    )
    db_session.add(checkpoint)
    await _write_match(db_session, writer, sim_id, round_id, p1_deck_id, p2_deck_id, _result("p1"))
    await _write_match(db_session, writer, sim_id, round_id, p1_deck_id, p2_deck_id, _result("p2"))
    await db_session.commit()

    action = await _prepare_opponent_checkpoint(
        db_session, sim_id, round_id, 1, p2_deck_id, "Checkpoint P2", 2
    )
    await db_session.commit()

    assert action == "skip"
    assert checkpoint.status == "complete"
    assert checkpoint.matches_completed == 2
    assert checkpoint.p1_wins == 1
    assert checkpoint.graph_status == "failed"


@pytest.mark.asyncio
async def test_pending_checkpoint_with_existing_target_matches_finalizes(db_session):
    writer, sim_id, round_id, p1_deck_id, p2_deck_id, _cards = await _seed_simulation(db_session)
    await _write_match(db_session, writer, sim_id, round_id, p1_deck_id, p2_deck_id, _result("p1"))
    await db_session.commit()

    action = await _prepare_opponent_checkpoint(
        db_session, sim_id, round_id, 1, p2_deck_id, "Checkpoint P2", 1
    )
    await db_session.commit()

    checkpoint = (await db_session.execute(
        select(SimulationOpponentResult).where(
            SimulationOpponentResult.simulation_id == sim_id
        )
    )).scalar_one()
    assert action == "skip"
    assert checkpoint.status == "complete"
    assert checkpoint.matches_completed == 1
    assert checkpoint.graph_status == "failed"
    assert "Finalized from persisted matches" in checkpoint.error_message


@pytest.mark.asyncio
async def test_partial_running_checkpoint_fails_without_cleanup(db_session):
    writer, sim_id, round_id, p1_deck_id, p2_deck_id, _cards = await _seed_simulation(db_session)
    checkpoint = SimulationOpponentResult(
        simulation_id=sim_id,
        round_id=round_id,
        round_number=1,
        opponent_deck_id=p2_deck_id,
        opponent_deck_name="Checkpoint P2",
        status="running",
        matches_target=2,
    )
    db_session.add(checkpoint)
    await _write_match(db_session, writer, sim_id, round_id, p1_deck_id, p2_deck_id, _result("p1"))
    await db_session.commit()

    with pytest.raises(ValueError, match="Partial persisted opponent batch"):
        await _prepare_opponent_checkpoint(
            db_session, sim_id, round_id, 1, p2_deck_id, "Checkpoint P2", 2
        )
    await db_session.commit()

    match_count = (await db_session.execute(text("SELECT COUNT(*) FROM matches WHERE simulation_id = :sid"), {"sid": sim_id})).scalar()
    assert match_count == 1
    assert checkpoint.status == "failed"
    assert checkpoint.matches_completed == 1


@pytest.mark.asyncio
async def test_reconstructed_skipped_results_preserve_events(db_session):
    writer, sim_id, round_id, p1_deck_id, p2_deck_id, _cards = await _seed_simulation(db_session)
    event = {"event_type": "attack_damage", "attacker": "Checkpoint A", "final_damage": 120}
    await _write_match(
        db_session,
        writer,
        sim_id,
        round_id,
        p1_deck_id,
        p2_deck_id,
        _result("p1", events=[event]),
    )
    await db_session.commit()

    results = await _load_opponent_match_results(db_session, sim_id, 1, p2_deck_id)

    assert len(results) == 1
    assert results[0].winner == "p1"
    assert results[0].events == [event]


@pytest.mark.asyncio
async def test_persisted_round_mutation_is_detected_for_retry_safety(db_session):
    _writer, sim_id, _round_id, _p1_deck_id, _p2_deck_id, cards = await _seed_simulation(db_session)
    db_session.add(
        DeckMutation(
            simulation_id=sim_id,
            round_number=1,
            card_removed=cards[0].tcgdex_id,
            card_added=cards[1].tcgdex_id,
            reasoning="checkpoint retry safety test",
            evidence={"source": "test"},
        )
    )
    await db_session.commit()

    assert await _round_has_persisted_mutations(db_session, sim_id, 1) is True


def test_checkpoint_model_declares_expected_constraints_and_indexes():
    table = SimulationOpponentResult.__table__
    constraints = {tuple(constraint.columns.keys()) for constraint in table.constraints}
    indexes = {index.name: tuple(index.columns.keys()) for index in table.indexes}

    assert ("simulation_id", "round_number", "opponent_deck_id") in constraints
    assert indexes["idx_sim_opp_results_round_status"] == (
        "simulation_id",
        "round_number",
        "status",
    )
    assert indexes["idx_sim_opp_results_sim_status"] == ("simulation_id", "status")
