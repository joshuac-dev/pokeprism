#!/usr/bin/env python3
"""Insert Batch 17 card definitions into the PostgreSQL cards table.

Cards covered:
  - MEP promos: mep-012..016, mep-018..021, mep-025..026  (11 cards)
  - PR-SV promos (svp): 087..092, 097..098, 105..113, 115..118,
      122..123, 126..129, 133..136, 141, 144..149, 151..159, 162,
      170..172, 177..189, 193, 197..199, 201..203, 205..207, 209..212
      (78 cards; svp-149 already in DB — skipped)

Usage:
    cd backend && python3 -m scripts.add_batch17_cards
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

# Already in DB — skip these
_ALREADY_IN_DB = {
    "svp-149",  # Pecharunt (already in DB)
}

ALL_IDS: list[str] = [
    # MEP promos: mep-012..016, mep-018..021, mep-025..026
    "mep-012", "mep-013", "mep-014", "mep-015", "mep-016",
    "mep-018", "mep-019", "mep-020", "mep-021",
    "mep-025", "mep-026",
    # PR-SV promos: svp-087..092
    "svp-087", "svp-088", "svp-089", "svp-090", "svp-091", "svp-092",
    # svp-097..098
    "svp-097", "svp-098",
    # svp-105..113
    "svp-105", "svp-106", "svp-107", "svp-108", "svp-109",
    "svp-110", "svp-111", "svp-112", "svp-113",
    # svp-115..118
    "svp-115", "svp-116", "svp-117", "svp-118",
    # svp-122..123
    "svp-122", "svp-123",
    # svp-126..129
    "svp-126", "svp-127", "svp-128", "svp-129",
    # svp-133..136
    "svp-133", "svp-134", "svp-135", "svp-136",
    # svp-141
    "svp-141",
    # svp-144..149 (svp-149 already in DB)
    "svp-144", "svp-145", "svp-146", "svp-147", "svp-148", "svp-149",
    # svp-151..159
    "svp-151", "svp-152", "svp-153", "svp-154", "svp-155",
    "svp-156", "svp-157", "svp-158", "svp-159",
    # svp-162
    "svp-162",
    # svp-170..172
    "svp-170", "svp-171", "svp-172",
    # svp-177..189
    "svp-177", "svp-178", "svp-179", "svp-180", "svp-181",
    "svp-182", "svp-183", "svp-184", "svp-185", "svp-186",
    "svp-187", "svp-188", "svp-189",
    # svp-193
    "svp-193",
    # svp-197..199
    "svp-197", "svp-198", "svp-199",
    # svp-201..203
    "svp-201", "svp-202", "svp-203",
    # svp-205..207
    "svp-205", "svp-206", "svp-207",
    # svp-209..212
    "svp-209", "svp-210", "svp-211", "svp-212",
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
