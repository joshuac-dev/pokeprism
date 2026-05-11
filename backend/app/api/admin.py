"""Admin API endpoints for the nightly H/H round-robin rerun system."""

from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.services import nightly_hh_rerun as svc

router = APIRouter()


async def _get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


@router.get("/nightly-hh-rerun/status")
async def get_nightly_hh_rerun_status(db: AsyncSession = Depends(_get_db)):
    """Return current status of the nightly H/H rerun scheduler."""
    return await svc.get_rerun_status(db)


@router.get("/nightly-hh-rerun/preview")
async def preview_nightly_hh_rerun(db: AsyncSession = Depends(_get_db)):
    """Preview the next source that would be selected without creating a run."""
    return await svc.preview_rerun(db)


@router.post("/nightly-hh-rerun/trigger")
async def trigger_nightly_hh_rerun(db: AsyncSession = Depends(_get_db)):
    """Manually trigger the nightly H/H rerun (admin).

    Creates exactly one queued simulation if the queue is free and an eligible
    source simulation exists.  Returns ``status: skipped`` if not.
    """
    from app.tasks.simulation import run_simulation

    result = await svc.create_rerun(triggered_by="manual_admin", db=db)
    if result["status"] == "created":
        run_simulation.delay(result["generated_simulation_id"])
    return result
