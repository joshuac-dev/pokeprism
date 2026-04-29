#!/usr/bin/env python3
"""Insert Batch 8 card definitions into the PostgreSQL cards table.

Cards covered:
  - DRI (sv10): 100–160
  - JTG (sv09): 001–041

Pre-fetched card data is loaded from batch8_cards.json in the project root.
Fixtures are saved to tests/fixtures/cards/ for future use.

Usage:
    cd backend && python3 -m scripts.add_batch8_cards
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
BATCH8_JSON = Path(__file__).parent.parent.parent / "batch8_cards.json"

# Reverse map: tcgdex_set_id → set_abbrev
_REVERSE_SET_MAP: dict[str, str] = {}
for _abbrev, _tcgdex_id in SET_CODE_MAP.items():
    _REVERSE_SET_MAP.setdefault(_tcgdex_id, _abbrev)

# Build full list of card IDs to process
DRI_IDS = [f"sv10-{n:03d}" for n in range(100, 161)]   # sv10-100 .. sv10-160
JTG_IDS = [f"sv09-{n:03d}" for n in range(1, 42)]       # sv09-001 .. sv09-041

ALL_IDS = DRI_IDS + JTG_IDS


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

    # Load pre-fetched data from batch8_cards.json if available
    prefetched: dict[str, dict] = {}
    if BATCH8_JSON.exists():
        try:
            prefetched = json.loads(BATCH8_JSON.read_text(encoding="utf-8"))
            logger.info("Loaded %d pre-fetched cards from batch8_cards.json", len(prefetched))
        except Exception as exc:
            logger.warning("Could not load batch8_cards.json: %s", exc)

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

        # 2. Fall back to pre-fetched batch8_cards.json data
        if raw is None and card_id in prefetched:
            raw = prefetched[card_id]
            fixture_path.write_text(
                json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            logger.info("  [PREFETCH] %s — %s", card_id, raw.get("name", "?"))

        # 3. Fall back to live API fetch
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
