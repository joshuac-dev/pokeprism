#!/usr/bin/env python3
"""Seed all cards from test fixtures into the PostgreSQL cards table.

Reads every JSON file in tests/fixtures/cards/, transforms it via
CardListLoader, and upserts to the DB via memory.postgres.ensure_cards().
Run this after capturing new fixtures to make cards available in the UI
without waiting for a simulation to touch them.

Usage:
    cd backend && python3 -m scripts.seed_cards
    # or from project root:
    make seed-cards
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.cards.loader import CardListLoader, SET_CODE_MAP
from app.db.session import AsyncSessionLocal
from app.memory.postgres import MatchMemoryWriter

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

FIXTURE_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "cards"

# Reverse map: tcgdex_set_id → set_abbrev (first match wins)
_REVERSE_SET_MAP: dict[str, str] = {}
for abbrev, tcgdex_id in SET_CODE_MAP.items():
    _REVERSE_SET_MAP.setdefault(tcgdex_id, abbrev)


def _set_abbrev_from_card_id(card_id: str) -> str:
    """Derive the PTCG set abbreviation from a tcgdex_id like 'sv06-130'."""
    parts = card_id.rsplit("-", 1)
    if len(parts) != 2:
        return ""
    set_id = parts[0]
    return _REVERSE_SET_MAP.get(set_id, "")


async def main() -> None:
    if not FIXTURE_DIR.exists():
        logger.error("Fixture directory not found: %s", FIXTURE_DIR)
        sys.exit(1)

    fixture_files = sorted(FIXTURE_DIR.glob("*.json"))
    logger.info("Found %d fixture files in %s", len(fixture_files), FIXTURE_DIR)

    loader = CardListLoader()
    card_defs = []
    skipped = 0

    for fp in fixture_files:
        card_id = fp.stem  # e.g. "sv06-130"
        try:
            raw = json.loads(fp.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("  [ERR] Failed to read %s: %s", fp.name, exc)
            skipped += 1
            continue

        set_abbrev = _set_abbrev_from_card_id(card_id)
        number = card_id.rsplit("-", 1)[-1].lstrip("0") or "0"
        entry = {
            "name": raw.get("name", ""),
            "set_abbrev": set_abbrev,
            "number": number,
        }

        try:
            cdef = loader._transform(raw, entry)
            card_defs.append(cdef)
        except Exception as exc:
            logger.warning("  [ERR] Transform failed for %s: %s", card_id, exc)
            skipped += 1

    logger.info("Transformed %d card definitions (%d skipped)", len(card_defs), skipped)

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
        logger.warning("%d fixtures could not be processed.", skipped)


if __name__ == "__main__":
    asyncio.run(main())
