"""Periodic Celery tasks.

Scheduled via Celery Beat (see celery_app.py for the crontab definitions).
The nightly H/H task re-runs the canonical Dragapult vs TR Mewtwo matchup
with persist=True so historical data grows over time.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

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
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_scheduled_hh_async(num_games))
    finally:
        loop.close()


async def _run_scheduled_hh_async(num_games: int) -> dict:
    from pathlib import Path
    import json

    from app.cards.loader import CardListLoader, SET_CODE_MAP
    from app.cards import registry as card_registry
    from app.engine.batch import run_hh_batch

    fixture_dir = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "cards"

    def _load_fixture(set_abbrev: str, number: str) -> dict | None:
        tcgdex_set_id = SET_CODE_MAP.get(set_abbrev.upper())
        if not tcgdex_set_id:
            return None
        card_id = f"{tcgdex_set_id}-{int(number):03d}"
        path = fixture_dir / f"{card_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _load_deck(deck_list: list[tuple[str, str, int]]):
        loader = CardListLoader()
        cards = []
        for set_abbrev, number, copies in deck_list:
            raw = _load_fixture(set_abbrev, number)
            if raw is None:
                logger.warning("Scheduled H/H: fixture missing for %s %s", set_abbrev, number)
                continue
            cdef = loader._transform(
                raw, {"set_abbrev": set_abbrev, "number": number, "name": raw.get("name", "")}
            )
            cards.extend([cdef] * copies)
        return cards

    logger.info("Scheduled H/H: loading decks")
    p1_deck = _load_deck(DRAGAPULT_DECK_LIST)
    p2_deck = _load_deck(TR_MEWTWO_DECK_LIST)

    if not p1_deck or not p2_deck:
        msg = "Scheduled H/H failed: card fixtures missing"
        logger.error(msg)
        return {"status": "error", "error": msg}

    for cdef in {c.tcgdex_id: c for c in p1_deck + p2_deck}.values():
        if not card_registry.get(cdef.tcgdex_id):
            card_registry.register(cdef)

    logger.info("Scheduled H/H: running %d games", num_games)
    batch_result = await run_hh_batch(
        p1_deck=p1_deck,
        p2_deck=p2_deck,
        num_games=num_games,
        p1_deck_name="Dragapult",
        p2_deck_name="TR-Mewtwo",
        persist=True,
        verbose=False,
        simulation_id=uuid.uuid4(),
    )

    logger.info(
        "Scheduled H/H complete: p1_win_rate=%.1f%%, avg_turns=%.1f",
        batch_result.p1_win_rate * 100,
        batch_result.avg_turns,
    )
    return {
        "status": "ok",
        "total_games": batch_result.total_games,
        "p1_win_rate": batch_result.p1_win_rate,
        "avg_turns": batch_result.avg_turns,
    }
