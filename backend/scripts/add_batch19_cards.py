#!/usr/bin/env python3
"""Insert Batch 19 card definitions into the PostgreSQL cards table.

Cards covered (69 new inserts from 100 Batch 19 cards):
  - WHT (sv10.5w): 085               (1 trainer)
  - DRI (sv10): 161..181             (18 trainers; 168..171/173/174/176..178/180 already in DB)
  - JTG (sv09): 142..158             (14 trainers; 143/146/151..153 already in DB)
  - PRE (sv08.5): 093..127           (18 trainers; 095/102/105/112/115 already in DB)
  - SSP (sv08): 163..190             (22 trainers; 170/177/180 already in DB)
  - SCR (sv07): 129..141             (8 trainers; 131..133/135/141 already in DB)
  - SFA (sv06.5): 054..064           (7 trainers; 057/061/064 already in DB)

Already in DB — skip insert:
  sv10-168, sv10-169, sv10-170, sv10-171, sv10-173, sv10-174,
  sv10-176, sv10-177, sv10-178, sv10-180,
  sv09-143, sv09-146, sv09-151, sv09-152, sv09-153,
  sv08.5-095, sv08.5-102, sv08.5-105, sv08.5-112, sv08.5-115,
  sv08-170, sv08-177, sv08-180,
  sv07-131, sv07-132, sv07-133, sv07-135, sv07-141,
  sv06.5-057, sv06.5-061, sv06.5-064

Usage:
    cd backend && python3 -m scripts.add_batch19_cards
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
    # DRI (sv10) — registered in earlier batches
    "sv10-168",   # Sacred Ash
    "sv10-169",   # Spikemuth Gym
    "sv10-170",   # Cyrano
    "sv10-171",   # Team Rocket's Ariana
    "sv10-173",   # Team Rocket's Factory
    "sv10-174",   # Team Rocket's Giovanni
    "sv10-176",   # Team Rocket's Petrel
    "sv10-177",   # Team Rocket's Proton
    "sv10-178",   # Team Rocket's Transceiver
    "sv10-180",   # Team Rocket's Watchtower
    # JTG (sv09) — registered in earlier batches
    "sv09-143",   # Black Belt's Training
    "sv09-146",   # Brock's Scouting
    "sv09-151",   # Lillie's Pearl
    "sv09-152",   # N's Castle
    "sv09-153",   # N's PP Up
    # PRE (sv08.5) — registered in earlier batches
    "sv08.5-095",  # Binding Mochi
    "sv08.5-102",  # Bug Catching Set
    "sv08.5-105",  # Crispin
    "sv08.5-112",  # Janine's Secret Art
    "sv08.5-115",  # Larry's Skill
    # SSP (sv08) — registered in earlier batches
    "sv08-170",   # Cyrano
    "sv08-177",   # Gravity Mountain
    "sv08-180",   # Lively Stadium
    # SCR (sv07) — registered in earlier batches
    "sv07-131",   # Area Zero Underdepths
    "sv07-132",   # Briar
    "sv07-133",   # Crispin
    "sv07-135",   # Glass Trumpet
    "sv07-141",   # Payapa Berry
    # SFA (sv06.5) — registered in earlier batches
    "sv06.5-057",  # Colress's Tenacity
    "sv06.5-061",  # Night Stretcher
    "sv06.5-064",  # Xerosic's Machinations
}

ALL_IDS: list[str] = [
    # WHT (sv10.5w): 085
    "sv10.5w-085",

    # DRI (sv10): 161..181
    "sv10-161", "sv10-162", "sv10-163", "sv10-165", "sv10-166",
    "sv10-168", "sv10-169", "sv10-170", "sv10-171", "sv10-172",
    "sv10-173", "sv10-174", "sv10-175", "sv10-176", "sv10-177",
    "sv10-178", "sv10-179", "sv10-180", "sv10-181",

    # JTG (sv09): 142..158
    "sv09-142", "sv09-143", "sv09-144", "sv09-145", "sv09-146",
    "sv09-147", "sv09-148", "sv09-149", "sv09-150", "sv09-151",
    "sv09-152", "sv09-153", "sv09-154", "sv09-156", "sv09-157",
    "sv09-158",

    # PRE (sv08.5): 093..127
    "sv08.5-093", "sv08.5-094", "sv08.5-095", "sv08.5-096",
    "sv08.5-100", "sv08.5-101", "sv08.5-102", "sv08.5-103",
    "sv08.5-104", "sv08.5-105", "sv08.5-107", "sv08.5-108",
    "sv08.5-109", "sv08.5-110", "sv08.5-111", "sv08.5-112",
    "sv08.5-113", "sv08.5-114", "sv08.5-115", "sv08.5-116",
    "sv08.5-118", "sv08.5-126", "sv08.5-127",

    # SSP (sv08): 163..190
    "sv08-163", "sv08-165", "sv08-166", "sv08-167", "sv08-168",
    "sv08-169", "sv08-170", "sv08-171", "sv08-172", "sv08-173",
    "sv08-174", "sv08-175", "sv08-177", "sv08-178", "sv08-179",
    "sv08-180", "sv08-181", "sv08-184", "sv08-187", "sv08-188",
    "sv08-189", "sv08-190",

    # SCR (sv07): 129..141
    "sv07-129", "sv07-130", "sv07-131", "sv07-132", "sv07-133",
    "sv07-135", "sv07-137", "sv07-138", "sv07-139", "sv07-140",
    "sv07-141",

    # SFA (sv06.5): 054..064
    "sv06.5-054", "sv06.5-055", "sv06.5-056", "sv06.5-057",
    "sv06.5-059", "sv06.5-061", "sv06.5-063", "sv06.5-064",
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
