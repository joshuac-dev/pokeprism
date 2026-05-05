"""Tests for simulation queue safety-net and stale-running recovery.

DB integration tests are skipped when Postgres is unreachable.
Mock-based unit tests always run.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.db.models import Deck, Round, Simulation, SimulationOpponentResult
from app.memory.postgres import MatchMemoryWriter
from app.tasks.simulation import (
    SIMULATION_STALE_RUNNING_MINUTES,
    _classify_stale_simulation,
    _dispatch_next_queued,
    _recover_stale_running_simulations,
)


# ---------------------------------------------------------------------------
# DB connectivity guard
# ---------------------------------------------------------------------------

def _db_reachable() -> bool:
    try:
        from app.config import settings

        async def _check():
            import asyncpg
            url = settings.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")
            conn = await asyncpg.connect(url, timeout=3)
            try:
                await conn.fetchval("SELECT 1 FROM simulations LIMIT 1")
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


pytestmark_db = pytest.mark.skipif(
    not _db_reachable(),
    reason="Postgres not reachable; skipping DB integration tests",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def db_session():
    from app.config import settings
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    async with engine.connect() as conn:
        await conn.begin()
        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            await session.begin_nested()
            yield session
        await conn.rollback()
    await engine.dispose()


async def _seed_stale_sim(db: AsyncSession, *, status: str = "running", minutes_ago: int = 60) -> Simulation:
    """Insert a minimal simulation with started_at in the past."""
    writer = MatchMemoryWriter()
    suffix = uuid.uuid4().hex[:8]
    from app.cards.models import CardDefinition
    cards = [CardDefinition(
        tcgdex_id=f"stale-{suffix}-001",
        name="Stale Card",
        set_abbrev="TST",
        set_number="1",
        category="Pokemon",
    )]
    await writer.ensure_cards(cards, db)
    deck_id = await writer.ensure_deck(f"Stale Deck {suffix}", cards * 60, db)
    sim = Simulation(
        status=status,
        game_mode="hh",
        deck_mode="full",
        deck_locked=True,
        user_deck_id=deck_id,
        matches_per_opponent=2,
        num_rounds=1,
        target_win_rate=60,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )
    db.add(sim)
    await db.flush()
    await db.commit()
    return sim


async def _add_checkpoint(
    db: AsyncSession,
    sim_id: uuid.UUID,
    *,
    status: str = "running",
    matches_completed: int = 0,
    matches_target: int = 2,
    updated_minutes_ago: int = 60,
) -> SimulationOpponentResult:
    """Insert a SimulationOpponentResult for a simulation and backdate its updated_at."""
    writer = MatchMemoryWriter()
    suffix = uuid.uuid4().hex[:8]
    from app.cards.models import CardDefinition
    cards = [CardDefinition(
        tcgdex_id=f"opp-{suffix}-001",
        name="Opp Card",
        set_abbrev="TST",
        set_number="1",
        category="Pokemon",
    )]
    await writer.ensure_cards(cards, db)
    opp_deck_id = await writer.ensure_deck(f"Opp Deck {suffix}", cards * 60, db)

    # We need a round row
    round_row = Round(
        simulation_id=sim_id,
        round_number=1,
        deck_snapshot={"cards": []},
        total_matches=0,
    )
    db.add(round_row)
    await db.flush()

    cp = SimulationOpponentResult(
        simulation_id=sim_id,
        round_id=round_row.id,
        round_number=1,
        opponent_deck_id=opp_deck_id,
        opponent_deck_name="Opp",
        status=status,
        matches_target=matches_target,
        matches_completed=matches_completed,
        p1_wins=0,
        p2_wins=0,
        total_turns=0,
        graph_status="pending",
        started_at=datetime.now(timezone.utc) - timedelta(minutes=updated_minutes_ago),
    )
    db.add(cp)
    await db.flush()
    await db.commit()

    # Backdate updated_at using raw SQL (ORM onupdate would reset to now())
    stale_ts = datetime.now(timezone.utc) - timedelta(minutes=updated_minutes_ago)
    await db.execute(
        text("UPDATE simulation_opponent_results SET updated_at = :ts WHERE id = :id"),
        {"ts": stale_ts, "id": cp.id},
    )
    await db.commit()
    await db.refresh(cp)
    return cp


# ---------------------------------------------------------------------------
# DB integration tests — TestClassifyStaleSimulation
# ---------------------------------------------------------------------------

class TestClassifyStaleSimulation:
    """Test _classify_stale_simulation with real DB rows."""

    @pytestmark_db
    @pytest.mark.asyncio
    async def test_fresh_simulation_is_skipped(self, db_session):
        """A recently started simulation is never classified as stale."""
        sim = await _seed_stale_sim(db_session, status="running", minutes_ago=5)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=45)
        result = await _classify_stale_simulation(db_session, sim, cutoff)
        assert result == "skip"

    @pytestmark_db
    @pytest.mark.asyncio
    async def test_stale_no_checkpoints_requeues(self, db_session):
        """A stale running simulation with no checkpoints is safe to requeue."""
        sim = await _seed_stale_sim(db_session, status="running", minutes_ago=60)
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=45)
        result = await _classify_stale_simulation(db_session, sim, cutoff)
        assert result == "requeue"

    @pytestmark_db
    @pytest.mark.asyncio
    async def test_stale_zero_persisted_running_checkpoint_requeues(self, db_session):
        """Stale sim + running checkpoint with 0 persisted matches → requeue (safe replay)."""
        sim = await _seed_stale_sim(db_session, status="running", minutes_ago=60)
        await _add_checkpoint(
            db_session, sim.id, status="running", matches_completed=0,
            matches_target=2, updated_minutes_ago=60,
        )
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=45)
        result = await _classify_stale_simulation(db_session, sim, cutoff)
        assert result == "requeue"

    @pytestmark_db
    @pytest.mark.asyncio
    async def test_stale_completed_checkpoints_requeues(self, db_session):
        """Stale sim with only complete checkpoints → requeue (completed checkpoints are idempotent)."""
        sim = await _seed_stale_sim(db_session, status="running", minutes_ago=60)
        await _add_checkpoint(
            db_session, sim.id, status="complete", matches_completed=2,
            matches_target=2, updated_minutes_ago=60,
        )
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=45)
        result = await _classify_stale_simulation(db_session, sim, cutoff)
        assert result == "requeue"

    @pytestmark_db
    @pytest.mark.asyncio
    async def test_stale_partial_nonzero_checkpoint_fails(self, db_session):
        """Stale sim + running checkpoint with partial matches → fail (unsafe to replay)."""
        sim = await _seed_stale_sim(db_session, status="running", minutes_ago=60)
        await _add_checkpoint(
            db_session, sim.id, status="running", matches_completed=1,
            matches_target=2, updated_minutes_ago=60,
        )
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=45)
        result = await _classify_stale_simulation(db_session, sim, cutoff)
        assert result == "fail"

    @pytestmark_db
    @pytest.mark.asyncio
    async def test_recent_checkpoint_activity_skips(self, db_session):
        """Stale sim but checkpoint updated recently (worker may still be alive) → skip."""
        sim = await _seed_stale_sim(db_session, status="running", minutes_ago=60)
        # Add a checkpoint that was updated just 5 minutes ago
        await _add_checkpoint(
            db_session, sim.id, status="running", matches_completed=0,
            matches_target=2, updated_minutes_ago=5,
        )
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=45)
        result = await _classify_stale_simulation(db_session, sim, cutoff)
        assert result == "skip"


# ---------------------------------------------------------------------------
# DB integration tests — TestRecoverStaleRunningSimulations
# ---------------------------------------------------------------------------

class TestRecoverStaleRunningSimulations:
    """Test the full _recover_stale_running_simulations helper."""

    @pytestmark_db
    @pytest.mark.asyncio
    async def test_stale_requeue_changes_status(self):
        """A stale running sim with no checkpoints should be reset to 'queued'."""
        from app.config import settings
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = create_async_engine(settings.DATABASE_URL, echo=False)
        SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        try:
            async with SessionFactory() as db:
                sim = await _seed_stale_sim(db, status="running", minutes_ago=60)
                sim_id = sim.id

            recovered = await _recover_stale_running_simulations(SessionFactory, stale_minutes=45)
            assert str(sim_id) in recovered

            async with SessionFactory() as db:
                refreshed = (await db.execute(
                    select(Simulation).where(Simulation.id == sim_id)
                )).scalar_one()
                assert refreshed.status == "queued"
                assert "requeued" in (refreshed.error_message or "")
        finally:
            # Clean up
            async with SessionFactory() as db:
                row = (await db.execute(
                    select(Simulation).where(Simulation.id == sim_id)
                )).scalar_one_or_none()
                if row:
                    await db.delete(row)
                    await db.commit()
            await engine.dispose()

    @pytestmark_db
    @pytest.mark.asyncio
    async def test_fresh_sim_not_recovered(self):
        """A recently started sim is not touched by recovery."""
        from app.config import settings
        from sqlalchemy.ext.asyncio import async_sessionmaker

        engine = create_async_engine(settings.DATABASE_URL, echo=False)
        SessionFactory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        try:
            async with SessionFactory() as db:
                sim = await _seed_stale_sim(db, status="running", minutes_ago=5)
                sim_id = sim.id

            recovered = await _recover_stale_running_simulations(SessionFactory, stale_minutes=45)
            assert str(sim_id) not in recovered

            async with SessionFactory() as db:
                refreshed = (await db.execute(
                    select(Simulation).where(Simulation.id == sim_id)
                )).scalar_one()
                assert refreshed.status == "running"
        finally:
            async with SessionFactory() as db:
                row = (await db.execute(
                    select(Simulation).where(Simulation.id == sim_id)
                )).scalar_one_or_none()
                if row:
                    await db.delete(row)
                    await db.commit()
            await engine.dispose()


# ---------------------------------------------------------------------------
# Mock-based unit tests — no DB required
# ---------------------------------------------------------------------------

class TestDispatchQueuedSimulation:
    """Mock-based tests for dispatch logic."""

    @pytest.mark.asyncio
    async def test_active_running_sim_blocks_dispatch(self):
        """A non-stale running simulation prevents dispatch of queued sims."""
        with (
            patch("app.tasks.simulation._recover_stale_running_simulations", new=AsyncMock(return_value=[])),
            patch("app.tasks.simulation.create_async_engine") as mock_engine,
            patch("app.tasks.simulation.async_sessionmaker") as mock_sf,
            patch("app.tasks.simulation.run_simulation") as mock_task,
        ):
            # Mock DB: active count = 1 (a running sim)
            mock_count_result = MagicMock()
            mock_count_result.scalar.return_value = 1

            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(return_value=mock_count_result)

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_sf.return_value.return_value = mock_ctx
            mock_engine.return_value.dispose = AsyncMock()

            await _dispatch_next_queued()

            mock_task.delay.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_active_sim_dispatches_queued(self):
        """When no active simulation exists, the oldest queued sim is dispatched."""
        queued_id = str(uuid.uuid4())
        mock_row = MagicMock()
        mock_row.status = "queued"
        mock_row.id = uuid.UUID(queued_id)

        call_count = 0

        async def _fake_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # active count query
                result.scalar.return_value = 0
            else:
                # queued sim query
                result.scalar_one_or_none.return_value = mock_row
            return result

        with (
            patch("app.tasks.simulation._recover_stale_running_simulations", new=AsyncMock(return_value=[])),
            patch("app.tasks.simulation.create_async_engine") as mock_engine,
            patch("app.tasks.simulation.async_sessionmaker") as mock_sf,
            patch("app.tasks.simulation.run_simulation") as mock_task,
        ):
            mock_db = AsyncMock()
            mock_db.execute = AsyncMock(side_effect=_fake_execute)
            mock_db.commit = AsyncMock()

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_db)
            mock_ctx.__aexit__ = AsyncMock(return_value=None)
            mock_sf.return_value.return_value = mock_ctx
            mock_engine.return_value.dispose = AsyncMock()

            await _dispatch_next_queued()

            mock_task.delay.assert_called_once_with(queued_id)


class TestStaleThresholdConfigurable:
    """Verify module-level constant and helper accept explicit overrides."""

    def test_default_threshold_is_set(self):
        """SIMULATION_STALE_RUNNING_MINUTES should have a positive default."""
        assert isinstance(SIMULATION_STALE_RUNNING_MINUTES, int)
        assert SIMULATION_STALE_RUNNING_MINUTES > 0

    @pytest.mark.asyncio
    async def test_classify_respects_explicit_cutoff(self):
        """_classify_stale_simulation accepts an explicit cutoff, enabling test overrides."""
        # Build a minimal mock Simulation with a very old started_at
        sim = MagicMock()
        sim.id = uuid.uuid4()
        sim.started_at = datetime.now(timezone.utc) - timedelta(minutes=120)

        # Mock DB session — no checkpoints exist
        mock_result = MagicMock()
        mock_result.scalar.return_value = None  # no latest updated_at
        mock_result.scalars.return_value.all.return_value = []  # no running checkpoints

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        # With a 1-minute cutoff, anything started 120 min ago is stale
        cutoff_tight = datetime.now(timezone.utc) - timedelta(minutes=1)
        result = await _classify_stale_simulation(mock_db, sim, cutoff_tight)
        assert result == "requeue"

        # With a cutoff far in the past (3 hours ago), sim started 120 min ago is NOT stale
        cutoff_loose = datetime.now(timezone.utc) - timedelta(minutes=180)
        result2 = await _classify_stale_simulation(mock_db, sim, cutoff_loose)
        assert result2 == "skip"
