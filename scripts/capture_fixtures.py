#!/usr/bin/env python3
"""Capture live TCGDex API responses for test fixtures.

Run this script once to populate backend/tests/fixtures/cards/*.json.
The test suite uses these files so tests pass without live network access.

Usage:
    cd backend && python scripts/capture_fixtures.py
    # or from project root:
    make capture-fixtures
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

# Add backend to path when running directly
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.cards.loader import CardListLoader, SET_CODE_MAP
from app.cards.tcgdex import TCGDexClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).parent.parent
FIXTURE_DIR = ROOT_DIR / "backend" / "tests" / "fixtures" / "cards"
CARDLIST_PATH = ROOT_DIR / "docs" / "POKEMON_MASTER_LIST.md"
_KNOWN_EXCLUDED_SETS = {"M4"}


async def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    async with TCGDexClient() as client:
        loader = CardListLoader()
        entries = loader.parse_cardlist(CARDLIST_PATH)

        logger.info("Parsed %d card entries from %s", len(entries), CARDLIST_PATH)

        success = 0
        failed = 0
        skipped = 0

        for entry in entries:
            abbrev = entry["set_abbrev"]
            number = entry["number"]
            name = entry.get("name", "?")

            if abbrev in _KNOWN_EXCLUDED_SETS:
                logger.info("  [SKIP] %s %s %s — excluded set", name, abbrev, number)
                skipped += 1
                continue

            tcgdex_set_id = SET_CODE_MAP.get(abbrev)
            if tcgdex_set_id is None:
                logger.warning("  [SKIP] %s %s %s — unknown set", name, abbrev, number)
                skipped += 1
                continue

            card_id = f"{tcgdex_set_id}-{int(number):03d}"
            fixture_path = FIXTURE_DIR / f"{card_id}.json"

            if fixture_path.exists():
                logger.debug("  [CACHED] %s", card_id)
                success += 1
                continue

            try:
                raw = await client.get_card_raw(tcgdex_set_id, number)
                if raw is None:
                    logger.warning("  [MISS] %s (%s)", card_id, name)
                    failed += 1
                    continue

                fixture_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False))
                logger.info("  [OK] %s — %s", card_id, name)
                success += 1

            except Exception as exc:
                logger.warning("  [ERR] %s: %s", card_id, exc)
                failed += 1

        print(f"\n{'='*50}")
        print(f"Captured : {success}")
        print(f"Failed   : {failed}")
        print(f"Skipped  : {skipped} (M4/unknown sets)")
        print(f"Fixtures : {FIXTURE_DIR}")


if __name__ == "__main__":
    asyncio.run(main())
