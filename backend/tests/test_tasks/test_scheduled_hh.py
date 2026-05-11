"""Tests for _run_scheduled_hh_async lifecycle (mock-based, no Postgres required).

Covers:
  - Simulation row pre-created with correct metadata (deck names, matches_per_opponent)
  - Status set to 'complete' after a successful batch run
  - Status set to 'failed' (with error_message) when batch raises
  - Status never left as 'running' after any exception
  - SimulationOpponent row created for History to display opponent name
  - Non-overlap guard: returns 'skipped' when an active scheduled H/H exists
  - Stale recovery: marks old stuck scheduled H/H rows 'failed' then proceeds
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_batch_result(total_games: int = 5, p1_wins: int = 3):
    from app.engine.batch import BatchResult
    return BatchResult(
        total_games=total_games,
        p1_wins=p1_wins,
        p2_wins=total_games - p1_wins,
        p1_win_rate=p1_wins / total_games,
        avg_turns=30.0,
        deck_out_pct=10.0,
        no_bench_pct=5.0,
        turn_limit_pct=0.0,
    )


def _make_card_def(tcgdex_id: str = "twm-001"):
    from app.cards.models import CardDefinition
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name="Test Card",
        set_abbrev="TWM",
        set_number="001",
        category="pokemon",
    )


def _db_context(db_mock):
    """Return an async context manager that yields db_mock."""
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db_mock)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


def _build_db_mock(execute_side_effect):
    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(side_effect=execute_side_effect)
    db_mock.commit = AsyncMock()
    db_mock.add = MagicMock()
    return db_mock


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestScheduledHHLifecycle:
    """Mock-based unit tests for _run_scheduled_hh_async."""

    @pytest.mark.asyncio
    async def test_creates_simulation_with_correct_metadata(self):
        """Pre-created Simulation row has user_deck_name, matches_per_opponent, and started_at."""
        from app.tasks.scheduled import (
            SCHEDULED_HH_P1_NAME,
            SCHEDULED_HH_P2_NAME,
            _run_scheduled_hh_async,
        )

        card = _make_card_def()
        batch_result = _make_batch_result()
        added_objects: list = []
        sim_row = MagicMock()
        p2_deck_mock = MagicMock()
        p2_deck_mock.id = uuid.uuid4()
        call_index = [0]

        async def _execute(stmt):
            result = MagicMock()
            idx = call_index[0]
            call_index[0] += 1
            if idx == 0:
                # non-overlap query — no active scheduled runs
                result.scalars.return_value.all.return_value = []
            elif idx == 1:
                # p2 deck lookup after batch
                result.scalars.return_value.first.return_value = p2_deck_mock
            else:
                # sim row lookup for completion update
                result.scalar_one.return_value = sim_row
            return result

        db_mock = _build_db_mock(_execute)
        db_mock.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        with (
            patch("app.tasks.scheduled.AsyncSessionLocal", side_effect=lambda: _db_context(db_mock)),
            patch("app.tasks.scheduled.run_hh_batch", new=AsyncMock(return_value=batch_result)),
            patch("app.tasks.scheduled._build_deck_from_list", return_value=[card]),
        ):
            result = await _run_scheduled_hh_async(5)

        assert result["status"] == "ok"

        sim_adds = [o for o in added_objects if hasattr(o, "game_mode")]
        assert len(sim_adds) == 1, "Expected exactly one Simulation row to be added"
        added_sim = sim_adds[0]
        assert added_sim.user_deck_name == SCHEDULED_HH_P1_NAME
        assert added_sim.matches_per_opponent == 5
        assert added_sim.started_at is not None
        assert added_sim.status == "running"

        opp_adds = [
            o for o in added_objects
            if hasattr(o, "deck_name") and not hasattr(o, "game_mode")
        ]
        assert len(opp_adds) == 1, "Expected exactly one SimulationOpponent row to be added"
        assert opp_adds[0].deck_name == SCHEDULED_HH_P2_NAME

    @pytest.mark.asyncio
    async def test_marks_simulation_complete_on_success(self):
        """Simulation row receives status=complete, completed_at, total_matches, and win_rate."""
        from app.tasks.scheduled import _run_scheduled_hh_async

        card = _make_card_def()
        batch_result = _make_batch_result(total_games=5, p1_wins=4)
        sim_row = MagicMock()
        p2_deck_mock = MagicMock()
        p2_deck_mock.id = uuid.uuid4()
        call_index = [0]

        async def _execute(stmt):
            result = MagicMock()
            idx = call_index[0]
            call_index[0] += 1
            if idx == 0:
                result.scalars.return_value.all.return_value = []
            elif idx == 1:
                result.scalars.return_value.first.return_value = p2_deck_mock
            else:
                result.scalar_one.return_value = sim_row
            return result

        db_mock = _build_db_mock(_execute)

        with (
            patch("app.tasks.scheduled.AsyncSessionLocal", side_effect=lambda: _db_context(db_mock)),
            patch("app.tasks.scheduled.run_hh_batch", new=AsyncMock(return_value=batch_result)),
            patch("app.tasks.scheduled._build_deck_from_list", return_value=[card]),
        ):
            result = await _run_scheduled_hh_async(5)

        assert result["status"] == "ok"
        assert sim_row.status == "complete"
        assert sim_row.completed_at is not None
        assert sim_row.total_matches == 5
        assert sim_row.rounds_completed == 1
        assert sim_row.final_win_rate == 80  # 4/5 = 80%

    @pytest.mark.asyncio
    async def test_marks_simulation_failed_on_batch_exception(self):
        """Simulation row receives status=failed with error_message when batch raises."""
        from app.tasks.scheduled import _run_scheduled_hh_async

        card = _make_card_def()
        error_msg = "Batch engine exploded"
        sim_row = MagicMock()
        call_index = [0]

        async def _execute(stmt):
            result = MagicMock()
            idx = call_index[0]
            call_index[0] += 1
            if idx == 0:
                result.scalars.return_value.all.return_value = []
            else:
                result.scalar_one_or_none.return_value = sim_row
            return result

        db_mock = _build_db_mock(_execute)

        async def _failing_batch(**kwargs):
            raise RuntimeError(error_msg)

        with (
            patch("app.tasks.scheduled.AsyncSessionLocal", side_effect=lambda: _db_context(db_mock)),
            patch("app.tasks.scheduled.run_hh_batch", new=_failing_batch),
            patch("app.tasks.scheduled._build_deck_from_list", return_value=[card]),
        ):
            with pytest.raises(RuntimeError, match=error_msg):
                await _run_scheduled_hh_async(5)

        assert sim_row.status == "failed"
        assert sim_row.completed_at is not None
        assert error_msg in sim_row.error_message

    @pytest.mark.asyncio
    async def test_does_not_leave_status_running_on_exception(self):
        """Status is never left as 'running' after any exception in the batch."""
        from app.tasks.scheduled import _run_scheduled_hh_async

        card = _make_card_def()
        sim_row = MagicMock()
        sim_row.status = "running"
        call_index = [0]

        async def _execute(stmt):
            result = MagicMock()
            idx = call_index[0]
            call_index[0] += 1
            if idx == 0:
                result.scalars.return_value.all.return_value = []
            else:
                result.scalar_one_or_none.return_value = sim_row
            return result

        db_mock = _build_db_mock(_execute)

        with (
            patch("app.tasks.scheduled.AsyncSessionLocal", side_effect=lambda: _db_context(db_mock)),
            patch(
                "app.tasks.scheduled.run_hh_batch",
                new=AsyncMock(side_effect=RuntimeError("crash")),
            ),
            patch("app.tasks.scheduled._build_deck_from_list", return_value=[card]),
        ):
            with pytest.raises(RuntimeError):
                await _run_scheduled_hh_async(5)

        assert sim_row.status != "running", (
            "Simulation must not remain 'running' after an exception"
        )

    @pytest.mark.asyncio
    async def test_skips_if_active_scheduled_hh_running(self):
        """Returns status='skipped' and does not call run_hh_batch when one is active."""
        from app.tasks.scheduled import _run_scheduled_hh_async

        active_sim = MagicMock()
        active_sim.id = uuid.uuid4()
        active_sim.started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        active_sim.created_at = active_sim.started_at

        async def _execute(stmt):
            result = MagicMock()
            result.scalars.return_value.all.return_value = [active_sim]
            return result

        db_mock = _build_db_mock(_execute)
        mock_batch = AsyncMock()

        with (
            patch("app.tasks.scheduled.AsyncSessionLocal", side_effect=lambda: _db_context(db_mock)),
            patch("app.tasks.scheduled.run_hh_batch", new=mock_batch),
        ):
            result = await _run_scheduled_hh_async(5)

        assert result["status"] == "skipped"
        assert str(active_sim.id) in result["reason"]
        mock_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_marks_stale_scheduled_hh_failed_and_starts_new_run(self):
        """Stale scheduled H/H row is marked 'failed'; a new run then completes normally."""
        from app.tasks.scheduled import SCHEDULED_HH_STALE_HOURS, _run_scheduled_hh_async

        card = _make_card_def()
        batch_result = _make_batch_result()

        stale_sim = MagicMock()
        stale_sim.id = uuid.uuid4()
        stale_sim.started_at = datetime.now(timezone.utc) - timedelta(
            hours=SCHEDULED_HH_STALE_HOURS + 1
        )
        stale_sim.created_at = stale_sim.started_at

        fresh_sim_row = MagicMock()
        p2_deck_mock = MagicMock()
        p2_deck_mock.id = uuid.uuid4()
        call_index = [0]

        async def _execute(stmt):
            result = MagicMock()
            idx = call_index[0]
            call_index[0] += 1
            if idx == 0:
                # non-overlap query returns the stale sim
                result.scalars.return_value.all.return_value = [stale_sim]
            elif idx == 1:
                # p2 deck lookup
                result.scalars.return_value.first.return_value = p2_deck_mock
            else:
                result.scalar_one.return_value = fresh_sim_row
            return result

        db_mock = _build_db_mock(_execute)

        with (
            patch("app.tasks.scheduled.AsyncSessionLocal", side_effect=lambda: _db_context(db_mock)),
            patch("app.tasks.scheduled.run_hh_batch", new=AsyncMock(return_value=batch_result)),
            patch("app.tasks.scheduled._build_deck_from_list", return_value=[card]),
        ):
            result = await _run_scheduled_hh_async(5)

        assert stale_sim.status == "failed"
        assert stale_sim.error_message is not None
        assert result["status"] == "ok"

    @pytest.mark.asyncio
    async def test_creates_simulation_opponent_row_for_history(self):
        """SimulationOpponent row is added so History can display the opponent deck name."""
        from app.db.models import SimulationOpponent
        from app.tasks.scheduled import SCHEDULED_HH_P2_NAME, _run_scheduled_hh_async

        card = _make_card_def()
        batch_result = _make_batch_result()
        p2_deck_id = uuid.uuid4()
        p2_deck_mock = MagicMock()
        p2_deck_mock.id = p2_deck_id
        sim_row = MagicMock()
        added_objects: list = []
        call_index = [0]

        async def _execute(stmt):
            result = MagicMock()
            idx = call_index[0]
            call_index[0] += 1
            if idx == 0:
                result.scalars.return_value.all.return_value = []
            elif idx == 1:
                result.scalars.return_value.first.return_value = p2_deck_mock
            else:
                result.scalar_one.return_value = sim_row
            return result

        db_mock = _build_db_mock(_execute)
        db_mock.add = MagicMock(side_effect=lambda obj: added_objects.append(obj))

        with (
            patch("app.tasks.scheduled.AsyncSessionLocal", side_effect=lambda: _db_context(db_mock)),
            patch("app.tasks.scheduled.run_hh_batch", new=AsyncMock(return_value=batch_result)),
            patch("app.tasks.scheduled._build_deck_from_list", return_value=[card]),
        ):
            await _run_scheduled_hh_async(5)

        opp_rows = [o for o in added_objects if isinstance(o, SimulationOpponent)]
        assert len(opp_rows) == 1, "Expected exactly one SimulationOpponent row"
        assert opp_rows[0].deck_name == SCHEDULED_HH_P2_NAME
        assert opp_rows[0].deck_id == p2_deck_id
