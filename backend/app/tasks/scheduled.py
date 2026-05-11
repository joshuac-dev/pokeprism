"""Periodic Celery tasks.

Scheduled via Celery Beat (see celery_app.py for the crontab definitions).

The nightly H/H task (``pokeprism.run_scheduled_hh``) previously ran the
static Dragapult vs TR-Mewtwo benchmark.  It now selects from prior completed
manual single-round H/H simulations in round-robin order and creates one
queued simulation with fixed multi-round coaching parameters.  The normal
simulation worker processes the generated run.

The static deck constants below are retained for backward compatibility and
in case a direct batch run is ever re-enabled, but they are NOT used by the
nightly scheduler anymore.
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

# Retained for backward compatibility — no longer used by nightly scheduler.
SCHEDULED_HH_P1_NAME = "Dragapult"
SCHEDULED_HH_P2_NAME = "TR-Mewtwo"

SCHEDULED_HH_STALE_HOURS = 1

# Deck lists retained for reference / manual re-use; not used by nightly.
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
    """Nightly H/H round-robin rerun scheduler.

    Selects one completed manual single-round H/H simulation via round-robin
    and creates a new queued simulation with fixed multi-round coaching
    parameters.  The normal simulation worker processes the run.

    The ``num_games`` parameter is kept for backward compatibility but is
    ignored; the rerun service uses RERUN_MATCHES_PER_OPPONENT (25).
    """
    from app.db import graph as _graph_module
    _graph_module._driver = None

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_scheduled_hh_async())
    finally:
        loop.close()
        _graph_module._driver = None


async def _run_scheduled_hh_async() -> dict:
    from app.services.nightly_hh_rerun import create_rerun
    from app.tasks.simulation import run_simulation

    async with AsyncSessionLocal() as db:
        result = await create_rerun(triggered_by="nightly", db=db)

    if result["status"] == "created":
        run_simulation.delay(result["generated_simulation_id"])
        logger.info(
            "Scheduled H/H: queued rerun sim=%s from source=%s cycle=%s",
            result["generated_simulation_id"],
            result["source_simulation_id"],
            result["cycle_number"],
        )
    else:
        logger.info("Scheduled H/H: %s (%s)", result["status"],
                    result.get("reason") or result.get("error", ""))

    return result
