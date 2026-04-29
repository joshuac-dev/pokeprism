#!/usr/bin/env python3
"""Insert Batch 18 card definitions into the PostgreSQL cards table.

Cards covered:
  - svp promos: 216..218            (3 TR Pokémon)
  - POR (me03): 068..083            (16 trainers; 076/081/084/085 already in DB)
  - ASC (me02.5): 180..215          (36 trainers; 183/184/192/194/196/198/207/210/212/213 already registered)
  - PFL (me02): 085..094            (10 trainers; 085/087/091/094 already registered)
  - MEG (me01): 113..132            (20 trainers; 113..117/119/121/125/127/131 already registered)
  - BLK (sv10.5b): 079..084         (6 trainers)
  - WHT (sv10.5w): 079..084         (6 trainers; 080/084 already registered)

Already in DB — skip insert:
  sv10-164, me03-076, me03-081, me03-084, me03-085

Usage:
    cd backend && python3 -m scripts.add_batch18_cards
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

from app.cards.loader import CardListLoader, SET_CODE_MAP
from app.db.session import AsyncSessionLocal
from app.memory.postgres import MatchMemoryWriter

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "cards"
TCGDEX_BASE = "https://api.tcgdex.net/v2/en/cards"

_REVERSE_SET_MAP: dict[str, str] = {}
for _abbrev, _tcgdex_id in SET_CODE_MAP.items():
    _REVERSE_SET_MAP.setdefault(_tcgdex_id, _abbrev)

# Already in DB — skip insert
_ALREADY_IN_DB = {
    "sv10-164",   # Energy Recycler
    "me03-076",   # Judge
    "me03-081",   # Poké Pad
    "me03-084",   # Rosa's Encouragement
    "me03-085",   # Tarragon
}

ALL_IDS: list[str] = [
    # PR-SV promos: svp-216..218 (TR Pokémon)
    "svp-216", "svp-217", "svp-218",

    # POR (me03): 068..083
    "me03-068", "me03-069", "me03-070", "me03-071", "me03-072", "me03-073",
    "me03-074", "me03-075", "me03-076", "me03-077", "me03-078", "me03-079",
    "me03-080", "me03-081", "me03-082", "me03-083",

    # ASC (me02.5): 180..215
    "me02.5-180", "me02.5-181", "me02.5-182", "me02.5-183", "me02.5-184",
    "me02.5-185", "me02.5-186", "me02.5-187", "me02.5-188", "me02.5-189",
    "me02.5-190", "me02.5-191", "me02.5-192", "me02.5-193", "me02.5-194",
    "me02.5-195", "me02.5-196", "me02.5-197", "me02.5-198", "me02.5-199",
    "me02.5-200", "me02.5-201", "me02.5-202", "me02.5-203", "me02.5-204",
    "me02.5-205", "me02.5-206", "me02.5-207", "me02.5-208", "me02.5-209",
    "me02.5-210", "me02.5-211", "me02.5-212", "me02.5-213", "me02.5-214",
    "me02.5-215",

    # PFL (me02): 085..094
    "me02-085", "me02-086", "me02-087", "me02-088", "me02-089",
    "me02-090", "me02-091", "me02-092", "me02-093", "me02-094",

    # MEG (me01): 113..132
    "me01-113", "me01-114", "me01-115", "me01-116", "me01-117", "me01-118",
    "me01-119", "me01-120", "me01-121", "me01-122", "me01-123", "me01-124",
    "me01-125", "me01-126", "me01-127", "me01-128", "me01-129", "me01-130",
    "me01-131", "me01-132",

    # BLK (sv10.5b): 079..084
    "sv10.5b-079", "sv10.5b-080", "sv10.5b-081", "sv10.5b-082",
    "sv10.5b-083", "sv10.5b-084",

    # WHT (sv10.5w): 079..084
    "sv10.5w-079", "sv10.5w-080", "sv10.5w-081", "sv10.5w-082",
    "sv10.5w-083", "sv10.5w-084",
]


async def fetch_card(card_id: str) -> dict | None:
    url = f"{TCGDEX_BASE}/{card_id}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 404:
                logger.warning("  [404] %s not found on TCGDex", card_id)
                return None
            else:
                logger.warning("  [%d] Failed to fetch %s", resp.status_code, card_id)
                return None
    except Exception as exc:
        logger.warning("  [ERR] Fetch error for %s: %s", card_id, exc)
        return None


async def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    loader = CardListLoader()
    card_defs = []
    skipped = 0
    not_found: list[str] = []

    for card_id in ALL_IDS:
        if card_id in _ALREADY_IN_DB:
            logger.info("  [SKIP] %s already in DB", card_id)
            continue

        fixture_path = FIXTURE_DIR / f"{card_id}.json"
        raw: dict | None = None

        if fixture_path.exists():
            try:
                raw = json.loads(fixture_path.read_text(encoding="utf-8"))
                logger.debug("  [FIXTURE] %s", card_id)
            except Exception as exc:
                logger.warning("  [ERR] Bad fixture %s: %s", card_id, exc)

        if raw is None:
            raw = await fetch_card(card_id)
            if raw:
                fixture_path.write_text(
                    json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                logger.info("  [FETCH] %s — %s", card_id, raw.get("name", "?"))
                await asyncio.sleep(0.15)
            else:
                not_found.append(card_id)
                skipped += 1
                continue

        parts = card_id.rsplit("-", 1)
        set_id = parts[0]
        local_id = parts[1].lstrip("0") or "0"
        set_abbrev = _REVERSE_SET_MAP.get(set_id, set_id.upper())

        entry = {
            "name": raw.get("name", ""),
            "set_abbrev": set_abbrev,
            "number": local_id,
        }

        try:
            cdef = loader._transform(raw, entry)
            card_defs.append(cdef)
        except Exception as exc:
            logger.warning("  [ERR] Transform failed for %s: %s", card_id, exc)
            skipped += 1

    logger.info("Transformed %d card definitions (%d skipped)", len(card_defs), skipped)
    if not_found:
        logger.warning("Not found on TCGDex (%d): %s", len(not_found), not_found)

    if not card_defs:
        logger.error("No cards to insert!")
        sys.exit(1)

    async with AsyncSessionLocal() as db:
        writer = MatchMemoryWriter()
        await writer.ensure_cards(card_defs, db)
        await db.commit()

    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT count(*) FROM cards"))
        total = result.scalar()

    logger.info("Done. Cards in DB: %d", total)
    if skipped:
        logger.warning("%d cards could not be processed.", skipped)


if __name__ == "__main__":
    asyncio.run(main())
