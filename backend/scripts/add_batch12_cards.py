#!/usr/bin/env python3
"""Insert Batch 12 card definitions into the PostgreSQL cards table.

Cards covered:
  - SSP (sv08): 118–161
  - SCR (sv07): 002–059 (selected numbers)

Usage:
    cd backend && python3 -m scripts.add_batch12_cards
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

# Reverse map: tcgdex_set_id → set_abbrev
_REVERSE_SET_MAP: dict[str, str] = {}
for _abbrev, _tcgdex_id in SET_CODE_MAP.items():
    _REVERSE_SET_MAP.setdefault(_tcgdex_id, _abbrev)

# Explicit list of all 100 batch-12 cards
ALL_IDS: list[str] = [
    # SSP sv08: 118–161
    "sv08-118", "sv08-119", "sv08-120", "sv08-121", "sv08-122", "sv08-123",
    "sv08-124", "sv08-125", "sv08-126", "sv08-127", "sv08-128", "sv08-129",
    "sv08-130", "sv08-131", "sv08-132", "sv08-133", "sv08-134", "sv08-135",
    "sv08-136", "sv08-137", "sv08-138", "sv08-139", "sv08-140", "sv08-141",
    "sv08-142", "sv08-143", "sv08-144", "sv08-145", "sv08-146", "sv08-147",
    "sv08-148", "sv08-149", "sv08-150", "sv08-151", "sv08-152", "sv08-153",
    "sv08-154", "sv08-155", "sv08-156", "sv08-157", "sv08-158", "sv08-159",
    "sv08-160", "sv08-161",
    # SCR sv07
    "sv07-002", "sv07-003", "sv07-004", "sv07-005", "sv07-006", "sv07-007",
    "sv07-008", "sv07-009", "sv07-010", "sv07-011", "sv07-012", "sv07-013",
    "sv07-014", "sv07-015", "sv07-016", "sv07-017", "sv07-018", "sv07-019",
    "sv07-020", "sv07-022", "sv07-023", "sv07-024", "sv07-025", "sv07-026",
    "sv07-027", "sv07-028", "sv07-029", "sv07-031", "sv07-032", "sv07-033",
    "sv07-034", "sv07-035", "sv07-036", "sv07-037", "sv07-038", "sv07-039",
    "sv07-040", "sv07-041", "sv07-042", "sv07-043", "sv07-044", "sv07-045",
    "sv07-046", "sv07-047", "sv07-048", "sv07-049", "sv07-050", "sv07-051",
    "sv07-052", "sv07-053", "sv07-054", "sv07-055", "sv07-056", "sv07-057",
    "sv07-058", "sv07-059",
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
        fixture_path = FIXTURE_DIR / f"{card_id}.json"
        raw: dict | None = None

        # 1. Try local fixture first
        if fixture_path.exists():
            try:
                raw = json.loads(fixture_path.read_text(encoding="utf-8"))
                logger.debug("  [FIXTURE] %s", card_id)
            except Exception as exc:
                logger.warning("  [ERR] Bad fixture %s: %s", card_id, exc)

        # 2. Fall back to live API fetch
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

        # Determine set_abbrev and number from card_id
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

    # Verify
    from sqlalchemy import text
    async with AsyncSessionLocal() as db:
        result = await db.execute(text("SELECT count(*) FROM cards"))
        total = result.scalar()

    logger.info("Done. Cards in DB: %d", total)
    if skipped:
        logger.warning("%d cards could not be processed.", skipped)


if __name__ == "__main__":
    asyncio.run(main())
