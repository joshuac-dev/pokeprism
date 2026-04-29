#!/usr/bin/env python3
"""Insert Batch 13 card definitions into the PostgreSQL cards table.

Cards covered:
  - SCR (sv07): 060–128
  - SFA (sv06.5): 001–034

Usage:
    cd backend && python3 -m scripts.add_batch13_cards
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

ALL_IDS: list[str] = [
    # SCR sv07: 060–128
    "sv07-060", "sv07-061", "sv07-063", "sv07-064", "sv07-065", "sv07-066",
    "sv07-067", "sv07-068", "sv07-069", "sv07-070", "sv07-071", "sv07-072",
    "sv07-073", "sv07-074", "sv07-075", "sv07-076", "sv07-077", "sv07-078",
    "sv07-079", "sv07-080", "sv07-081", "sv07-082", "sv07-083", "sv07-084",
    "sv07-085", "sv07-086", "sv07-087", "sv07-088", "sv07-090", "sv07-091",
    "sv07-092", "sv07-093", "sv07-094", "sv07-095", "sv07-096", "sv07-097",
    "sv07-098", "sv07-099", "sv07-100", "sv07-101", "sv07-102", "sv07-103",
    "sv07-104", "sv07-105", "sv07-106", "sv07-107", "sv07-108", "sv07-109",
    "sv07-110", "sv07-111", "sv07-112", "sv07-113", "sv07-114", "sv07-115",
    "sv07-116", "sv07-117", "sv07-118", "sv07-119", "sv07-120", "sv07-121",
    "sv07-122", "sv07-123", "sv07-124", "sv07-125", "sv07-126", "sv07-127",
    "sv07-128",
    # SFA sv06.5: 001–034
    "sv06.5-001", "sv06.5-002", "sv06.5-003", "sv06.5-004", "sv06.5-005",
    "sv06.5-006", "sv06.5-007", "sv06.5-008", "sv06.5-009", "sv06.5-010",
    "sv06.5-011", "sv06.5-012", "sv06.5-013", "sv06.5-014", "sv06.5-015",
    "sv06.5-016", "sv06.5-017", "sv06.5-018", "sv06.5-019", "sv06.5-020",
    "sv06.5-021", "sv06.5-022", "sv06.5-023", "sv06.5-024", "sv06.5-025",
    "sv06.5-026", "sv06.5-027", "sv06.5-028", "sv06.5-029", "sv06.5-030",
    "sv06.5-031", "sv06.5-032", "sv06.5-033", "sv06.5-034",
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
