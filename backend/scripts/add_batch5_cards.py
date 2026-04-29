#!/usr/bin/env python3
"""Insert Batch 5 card definitions (MEG me01-071..me01-112 + BLK sv10.5b-001..sv10.5b-058)
into the PostgreSQL cards table.

Fetches card data from TCGDex API (or local fixtures if available) and upserts.
Skips cards that are already in the DB (IN_DB list) for efficiency.

Usage:
    cd backend && python3 -m scripts.add_batch5_cards
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
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

# Cards already in DB — skip DB insertion but still process
IN_DB_IDS = {
    "me01-074",  # Lunatone
    "me01-075",  # Solrock
    "me01-086",  # Mega Absol ex
    "me01-088",  # Yveltal
    "me01-104",  # Mega Kangaskhan ex
}

# All batch 5 card IDs to process
MEG_IDS = [f"me01-{n:03d}" for n in range(71, 113)]   # me01-071 .. me01-112
BLK_IDS = [f"sv10.5b-{n:03d}" for n in range(1, 59)]  # sv10.5b-001 .. sv10.5b-058

ALL_IDS = MEG_IDS + BLK_IDS

# Reverse map: tcgdex_set_id → set_abbrev
_REVERSE_SET_MAP: dict[str, str] = {}
for _abbrev, _tcgdex_id in SET_CODE_MAP.items():
    _REVERSE_SET_MAP.setdefault(_tcgdex_id, _abbrev)


async def fetch_card(card_id: str) -> dict | None:
    """Fetch card JSON from TCGDex API."""
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
    loader = CardListLoader()
    card_defs = []
    skipped = 0
    not_found = []

    for card_id in ALL_IDS:
        if card_id in IN_DB_IDS:
            logger.info("  [SKIP-DB] %s already in DB", card_id)
            continue

        # Try local fixture first
        fixture_path = FIXTURE_DIR / f"{card_id}.json"
        raw: dict | None = None
        if fixture_path.exists():
            try:
                raw = json.loads(fixture_path.read_text(encoding="utf-8"))
                logger.info("  [FIXTURE] %s", card_id)
            except Exception as exc:
                logger.warning("  [ERR] Bad fixture %s: %s", card_id, exc)

        if raw is None:
            raw = await fetch_card(card_id)
            if raw:
                # Save fixture for future use
                fixture_path.write_text(
                    json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                logger.info("  [FETCH] %s — saved fixture", card_id)
            else:
                not_found.append(card_id)
                skipped += 1
                continue
            # Small delay to be polite to the API
            await asyncio.sleep(0.15)

            # Determine set_abbrev and number
            parts = card_id.rsplit("-", 1)
            set_id = parts[0]
            local_id = parts[1].lstrip("0") or "0"
            set_abbrev = _REVERSE_SET_MAP.get(set_id, "")

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
        logger.warning("Not found on TCGDex: %s", not_found)

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
