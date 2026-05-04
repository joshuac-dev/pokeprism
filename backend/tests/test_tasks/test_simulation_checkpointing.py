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
    DeckMutation,
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

    checkpoint = (await db_session.execute(select(SimulationOpponentResult))).scalar_one()
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

    checkpoint = (await db_session.execute(select(SimulationOpponentResult))).scalar_one()
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
