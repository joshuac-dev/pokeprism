"""Tests for run_scheduled_hh Celery task — round-robin rerun entry point.

The nightly task now delegates entirely to the nightly_hh_rerun service.
These tests verify the Celery task entry point behaviour:
  - passes triggered_by='nightly' to the service
  - dispatches run_simulation.delay when status='created'
  - returns service result unchanged for all status values
  - does NOT dispatch when status='skipped' or 'failed'
"""

from __future__ import annotations

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _db_context(db_mock):
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db_mock)
    ctx.__aexit__ = AsyncMock(return_value=None)
    return ctx


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestScheduledHHLifecycle:
    """Celery task tests for the round-robin rerun entry point."""

    @pytest.mark.asyncio
    async def test_passes_triggered_by_nightly_to_service(self):
        """_run_scheduled_hh_async passes triggered_by='nightly' to create_rerun."""
        from app.tasks.scheduled import _run_scheduled_hh_async

        called_with = {}

        async def fake_create_rerun(triggered_by, db):
            called_with["triggered_by"] = triggered_by
            return {"status": "skipped", "reason": "no eligible source simulations"}

        db_mock = AsyncMock()
        ctx = _db_context(db_mock)

        with patch("app.tasks.scheduled.AsyncSessionLocal", return_value=ctx):
            from app.services import nightly_hh_rerun as svc
            with patch.object(svc, "create_rerun", new=fake_create_rerun):
                result = await _run_scheduled_hh_async()

        assert called_with["triggered_by"] == "nightly"
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_dispatches_run_simulation_when_created(self):
        """run_simulation.delay is called when service returns status='created'."""
        from app.tasks.scheduled import _run_scheduled_hh_async

        gen_id = str(uuid.uuid4())
        dispatch_calls = []

        async def fake_create_rerun(triggered_by, db):
            return {
                "status": "created",
                "source_simulation_id": str(uuid.uuid4()),
                "generated_simulation_id": gen_id,
                "cycle_number": 1,
            }

        db_mock = AsyncMock()
        ctx = _db_context(db_mock)
        mock_run_sim = MagicMock()
        mock_run_sim.delay.side_effect = lambda sid: dispatch_calls.append(sid)

        with patch("app.tasks.scheduled.AsyncSessionLocal", return_value=ctx):
            from app.services import nightly_hh_rerun as svc
            with patch.object(svc, "create_rerun", new=fake_create_rerun), \
                 patch("app.tasks.simulation.run_simulation", mock_run_sim):
                result = await _run_scheduled_hh_async()

        assert result["status"] == "created"
        assert gen_id in dispatch_calls

    @pytest.mark.asyncio
    async def test_does_not_dispatch_when_skipped(self):
        """run_simulation.delay is NOT called when service returns 'skipped'."""
        from app.tasks.scheduled import _run_scheduled_hh_async

        dispatch_calls = []

        async def fake_create_rerun(triggered_by, db):
            return {"status": "skipped", "reason": "simulation queue busy"}

        db_mock = AsyncMock()
        ctx = _db_context(db_mock)
        mock_run_sim = MagicMock()
        mock_run_sim.delay.side_effect = lambda sid: dispatch_calls.append(sid)

        with patch("app.tasks.scheduled.AsyncSessionLocal", return_value=ctx):
            from app.services import nightly_hh_rerun as svc
            with patch.object(svc, "create_rerun", new=fake_create_rerun), \
                 patch("app.tasks.simulation.run_simulation", mock_run_sim):
                result = await _run_scheduled_hh_async()

        assert result["status"] == "skipped"
        assert not dispatch_calls

    @pytest.mark.asyncio
    async def test_returns_failed_result_on_service_error(self):
        """result dict with status='failed' is returned when service returns failed."""
        from app.tasks.scheduled import _run_scheduled_hh_async

        async def fake_create_rerun(triggered_by, db):
            return {"status": "failed", "reason": "DB error"}

        db_mock = AsyncMock()
        ctx = _db_context(db_mock)

        with patch("app.tasks.scheduled.AsyncSessionLocal", return_value=ctx):
            from app.services import nightly_hh_rerun as svc
            with patch.object(svc, "create_rerun", new=fake_create_rerun):
                result = await _run_scheduled_hh_async()

        assert result["status"] == "failed"
