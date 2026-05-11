"""Periodic Celery tasks.

Scheduled via Celery Beat (see celery_app.py for the crontab definitions).
The nightly H/H task re-runs the canonical Dragapult vs TR Mewtwo matchup
with persist=True so historical data grows over time.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from app.db.models import Deck, Simulation, SimulationOpponent
from app.db.session import AsyncSessionLocal
from app.engine.batch import run_hh_batch
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Canonical deck/player names for the scheduled H/H benchmark.
SCHEDULED_HH_P1_NAME = "Dragapult"
SCHEDULED_HH_P2_NAME = "TR-Mewtwo"

# Maximum wall-clock hours a scheduled H/H run may remain in "running" state
# before the next nightly invocation treats it as stale and marks it failed.
SCHEDULED_HH_STALE_HOURS = 1

# Canonical deck lists (mirrors tests/conftest.py & scripts/run_hh.py)
DRAGAPULT_DECK_LIST: list[tuple[str, str, int]] = [
    ("TWM", "128", 4), ("TWM", "129", 3), ("TWM", "130", 3),
    ("PRE", "35",  4), ("PRE", "36",  2), ("PRE", "37",  2),
    ("TWM", "96",  1), ("ASC", "142", 1), ("TWM", "95",  1),
    ("ASC", "39",  1),
    ("TEF", "144", 4), ("MEG", "131", 3), ("MEG", "125", 3),
    ("ASC", "196", 2), ("TEF", "157", 2), ("MEG", "114", 2),
    ("TEF", "154", 2), ("TWM", "167", 2), ("TEF", "155", 2),
    ("TEF", "146", 2), ("TWM", "163", 2), ("TWM", "143", 1),
    ("TWM", "148", 1), ("PRE", "95",  1), ("PRE", "112", 1),
    ("MEE", "5",   4), ("TEF", "161", 2), ("ASC", "216", 2),
]

TR_MEWTWO_DECK_LIST: list[tuple[str, str, int]] = [
    ("DRI", "81",  3), ("DRI", "87",  3), ("DRI", "128", 2),
    ("DRI", "51",  2), ("DRI", "10",  2), ("ASC", "39",  2),
    ("MEG", "88",  2), ("MEG", "86",  1), ("MEG", "74",  1),
    ("DRI", "178", 3), ("DRI", "174", 3), ("DRI", "173", 3),
    ("DRI", "177", 2), ("DRI", "170", 2), ("DRI", "171", 2),
    ("DRI", "176", 2), ("DRI", "180", 2), ("DRI", "169", 2),
    ("DRI", "168", 2), ("DRI", "164", 2), ("MEG", "131", 2),
    ("MEG", "114", 2), ("MEG", "119", 1), ("MEG", "115", 1),
    ("SVI", "186", 1), ("SFA", "57",  1),
    ("MEE", "5",   3), ("MEE", "7",   3), ("DRI", "182", 2),
    ("ASC", "216", 1),
]

_FIXTURE_DIR = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "cards"


def _load_deck_fixture(set_abbrev: str, number: str) -> dict | None:
    """Load a single card fixture JSON, or return None if not present.

    Extracted at module level so tests can patch
    ``app.tasks.scheduled._load_deck_fixture`` to inject fake card data.
    """
    from app.cards.loader import SET_CODE_MAP

    tcgdex_set_id = SET_CODE_MAP.get(set_abbrev.upper())
    if not tcgdex_set_id:
        return None
    card_id = f"{tcgdex_set_id}-{int(number):03d}"
    path = _FIXTURE_DIR / f"{card_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _build_deck_from_list(deck_list: list[tuple[str, str, int]]) -> list:
    """Convert a deck list of (set_abbrev, number, copies) into CardDefinition objects."""
    from app.cards.loader import CardListLoader

    loader = CardListLoader()
    cards = []
    for set_abbrev, number, copies in deck_list:
        raw = _load_deck_fixture(set_abbrev, number)
        if raw is None:
            logger.warning("Scheduled H/H: fixture missing for %s %s", set_abbrev, number)
            continue
        cdef = loader._transform(
            raw, {"set_abbrev": set_abbrev, "number": number, "name": raw.get("name", "")}
        )
        cards.extend([cdef] * copies)
    return cards


@celery_app.task(name="pokeprism.advance_simulation_queue")
def advance_simulation_queue() -> dict:
    """Safety-net Beat task: dispatch the next queued simulation if the worker is idle.

    Runs every 60 seconds. Handles the edge case where the worker restarted or
    crashed before the task-completion dispatch could fire.
    """
    from app.tasks.simulation import _dispatch_next_queued

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_dispatch_next_queued())
    except Exception as exc:
        logger.warning("advance_simulation_queue: dispatch failed: %s", exc)
    finally:
        loop.close()
    return {"status": "ok"}


@celery_app.task(name="pokeprism.run_scheduled_hh")
def run_scheduled_hh(num_games: int = 200) -> dict:
    """Run the nightly H/H benchmark and persist results to the DB.

    Uses the Dragapult ex / Dusknoir deck vs. TR Mewtwo ex (canonical test
    matchup). Results feed into historical card performance data which the
    Coach uses for swap candidate selection.
    """
    # The Neo4j AsyncDriver singleton is bound to whichever loop first called
    # get_driver(). Reusing it across nightly runs (each with a fresh loop)
    # causes stale-connection errors after the first run. Nil it here so it is
    # recreated inside the new loop, matching the pattern in run_simulation.
    from app.db import graph as _graph_module
    _graph_module._driver = None

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_scheduled_hh_async(num_games))
    finally:
        loop.close()
        _graph_module._driver = None


async def _run_scheduled_hh_async(num_games: int) -> dict:
    from app.cards import registry as card_registry

    # ── Non-overlap guard and stale recovery ─────────────────────────────────
    # Scheduled H/H runs are identified by deck_mode="none" + game_mode="hh"
    # + user_deck_name=SCHEDULED_HH_P1_NAME, which distinguishes them from
    # user-created simulations that always have deck_mode="full".
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(hours=SCHEDULED_HH_STALE_HOURS)

    async with AsyncSessionLocal() as db:
        existing_rows = (await db.execute(
            select(Simulation).where(
                Simulation.status.in_(["running", "pending", "queued"]),
                Simulation.game_mode == "hh",
                Simulation.deck_mode == "none",
                Simulation.user_deck_name == SCHEDULED_HH_P1_NAME,
            )
        )).scalars().all()

        for prior_sim in existing_rows:
            reference_ts = prior_sim.started_at or prior_sim.created_at
            if reference_ts is not None and reference_ts < stale_cutoff:
                prior_sim.status = "failed"
                prior_sim.completed_at = now
                prior_sim.error_message = (
                    f"Scheduled H/H run exceeded maximum runtime of "
                    f"{SCHEDULED_HH_STALE_HOURS}h; marked failed by next nightly invocation."
                )
                logger.warning(
                    "Scheduled H/H: marked stale sim %s as failed (started=%s)",
                    prior_sim.id,
                    reference_ts,
                )
            else:
                logger.info(
                    "Scheduled H/H: sim %s is still active (started=%s); skipping.",
                    prior_sim.id,
                    reference_ts,
                )
                return {
                    "status": "skipped",
                    "reason": f"scheduled H/H simulation {prior_sim.id} is already running",
                }

        await db.commit()

    # ── Load decks ────────────────────────────────────────────────────────────
    logger.info("Scheduled H/H: loading decks")
    p1_deck = _build_deck_from_list(DRAGAPULT_DECK_LIST)
    p2_deck = _build_deck_from_list(TR_MEWTWO_DECK_LIST)

    if not p1_deck or not p2_deck:
        msg = "Scheduled H/H failed: card fixtures missing"
        logger.error(msg)
        return {"status": "error", "error": msg}

    for cdef in {c.tcgdex_id: c for c in p1_deck + p2_deck}.values():
        if not card_registry.get(cdef.tcgdex_id):
            card_registry.register(cdef)

    # ── Pre-create simulation row with full metadata ───────────────────────────
    # Written before run_hh_batch so History shows correct deck/params immediately.
    # ensure_simulation() inside batch.py is a no-op when the row already exists.
    simulation_id = uuid.uuid4()
    async with AsyncSessionLocal() as db:
        db.add(Simulation(
            id=simulation_id,
            status="running",
            game_mode="hh",
            deck_mode="none",
            user_deck_name=SCHEDULED_HH_P1_NAME,
            matches_per_opponent=num_games,
            num_rounds=1,
            target_win_rate=60,
            started_at=now,
        ))
        await db.commit()

    # ── Run batch ────────────────────────────────────────────────────────────
    logger.info(
        "Scheduled H/H: running %d games (sim=%s)", num_games, simulation_id
    )
    try:
        batch_result = await run_hh_batch(
            p1_deck=p1_deck,
            p2_deck=p2_deck,
            num_games=num_games,
            p1_deck_name=SCHEDULED_HH_P1_NAME,
            p2_deck_name=SCHEDULED_HH_P2_NAME,
            persist=True,
            verbose=False,
            simulation_id=simulation_id,
        )
    except Exception as exc:
        logger.exception(
            "Scheduled H/H simulation %s failed during batch run", simulation_id
        )
        try:
            async with AsyncSessionLocal() as db:
                row = (await db.execute(
                    select(Simulation).where(Simulation.id == simulation_id)
                )).scalar_one_or_none()
                if row is not None:
                    row.status = "failed"
                    row.completed_at = datetime.now(timezone.utc)
                    row.error_message = str(exc)[:1000]
                    await db.commit()
        except Exception:
            logger.exception(
                "Could not mark scheduled H/H simulation %s as failed", simulation_id
            )
        raise

    # ── Mark complete and record opponent ────────────────────────────────────
    completed_at = datetime.now(timezone.utc)
    p1_win_rate_pct = int(batch_result.p1_win_rate * 100)

    async with AsyncSessionLocal() as db:
        # Create the SimulationOpponent row so History displays the opponent name.
        p2_deck_row = (await db.execute(
            select(Deck).where(Deck.name == SCHEDULED_HH_P2_NAME)
        )).scalars().first()
        if p2_deck_row is not None:
            db.add(SimulationOpponent(
                simulation_id=simulation_id,
                deck_id=p2_deck_row.id,
                deck_name=SCHEDULED_HH_P2_NAME,
            ))

        sim_row = (await db.execute(
            select(Simulation).where(Simulation.id == simulation_id)
        )).scalar_one()
        sim_row.status = "complete"
        sim_row.completed_at = completed_at
        sim_row.total_matches = batch_result.total_games
        sim_row.rounds_completed = 1
        sim_row.final_win_rate = p1_win_rate_pct
        await db.commit()

    logger.info(
        "Scheduled H/H complete: sim=%s p1_win_rate=%d%% avg_turns=%.1f",
        simulation_id,
        p1_win_rate_pct,
        batch_result.avg_turns,
    )
    return {
        "status": "ok",
        "simulation_id": str(simulation_id),
        "total_games": batch_result.total_games,
        "p1_win_rate": batch_result.p1_win_rate,
        "avg_turns": batch_result.avg_turns,
    }
