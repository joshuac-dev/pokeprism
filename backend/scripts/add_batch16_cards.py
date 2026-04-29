#!/usr/bin/env python3
"""Insert Batch 16 card definitions into the PostgreSQL cards table.

Cards covered:
  - TEF (sv05): 049–139  (082, 123, 129 excluded — 082 not in master list, 123/129 already in DB)
  - MEP promos: mep-001..009, mep-011  (mep-010 excluded — not in master list)

Usage:
    cd backend && python3 -m scripts.add_batch16_cards
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
    "sv05-123",  # Raging Bolt ex TEF 123 (already in DB)
    "sv05-129",  # Dudunsparce TEF 129 (already in DB)
}

ALL_IDS: list[str] = [
    # TEF sv05: 049–139 (skip 082 not in master list, skip 123/129 already in DB)
    "sv05-049", "sv05-050", "sv05-051", "sv05-052", "sv05-053",
    "sv05-054", "sv05-055", "sv05-056", "sv05-057", "sv05-058",
    "sv05-059", "sv05-060", "sv05-061", "sv05-062", "sv05-063",
    "sv05-064", "sv05-065", "sv05-066", "sv05-067", "sv05-068",
    "sv05-069", "sv05-070", "sv05-071", "sv05-072", "sv05-073",
    "sv05-074", "sv05-075", "sv05-076", "sv05-077", "sv05-078",
    "sv05-079", "sv05-080", "sv05-081",
    # skip sv05-082
    "sv05-083", "sv05-084", "sv05-085", "sv05-086", "sv05-087",
    "sv05-088", "sv05-089", "sv05-090", "sv05-091", "sv05-092",
    "sv05-093", "sv05-094", "sv05-095", "sv05-096", "sv05-097",
    "sv05-098", "sv05-099", "sv05-100", "sv05-101", "sv05-102",
    "sv05-103", "sv05-104", "sv05-105", "sv05-106", "sv05-107",
    "sv05-108", "sv05-109", "sv05-110", "sv05-111", "sv05-112",
    "sv05-113", "sv05-114", "sv05-115", "sv05-116", "sv05-117",
    "sv05-118", "sv05-119", "sv05-120", "sv05-121", "sv05-122",
    # skip sv05-123
    "sv05-124", "sv05-125", "sv05-126", "sv05-127", "sv05-128",
    # skip sv05-129
    "sv05-130", "sv05-131", "sv05-132", "sv05-133", "sv05-134",
    "sv05-135", "sv05-136", "sv05-137", "sv05-138", "sv05-139",
    # MEP promos: mep-001..009, mep-011 (skip mep-010)
    "mep-001", "mep-002", "mep-003", "mep-004", "mep-005",
    "mep-006", "mep-007", "mep-008", "mep-009",
    # skip mep-010
    "mep-011",
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
