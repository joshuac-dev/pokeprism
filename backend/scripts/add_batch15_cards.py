#!/usr/bin/env python3
"""Insert Batch 15 card definitions into the PostgreSQL cards table.

Cards covered:
  - TWM (sv06): 082–141  (093, 095, 096, 106, 111, 112, 118, 128, 129, 130, 141 already in DB — skipped)
  - TEF (sv05): 001–048  (023, 024, 025 already in DB — skipped)

Usage:
    cd backend && python3 -m scripts.add_batch15_cards
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
    "sv06-093",  # Scream Tail TWM 93 (already in DB)
    "sv06-095",  # Iron Bundle TWM 95
    "sv06-096",  # Iron Hands ex TWM 96
    "sv06-106",  # Dusclops TWM 106
    "sv06-111",  # Sandile TWM 111
    "sv06-112",  # Krokorok TWM 112
    "sv06-118",  # Aron TWM 118
    "sv06-128",  # Varoom TWM 128
    "sv06-129",  # Revavroom TWM 129
    "sv06-130",  # Revavroom ex TWM 130
    "sv06-141",  # Lumineon V TWM 141
    "sv05-023",  # Charizard ex TEF 23
    "sv05-024",  # Rotom V TEF 24
    "sv05-025",  # Pidgeot ex TEF 25
}

ALL_IDS: list[str] = [
    # TWM sv06: 082–141 (skip 093, 095, 096, 106, 111, 112, 118, 128, 129, 130, 141)
    "sv06-082", "sv06-083", "sv06-084", "sv06-085", "sv06-086",
    "sv06-087", "sv06-088", "sv06-089", "sv06-090", "sv06-091",
    "sv06-092",
    "sv06-094",
    "sv06-097", "sv06-098", "sv06-099", "sv06-100",
    "sv06-101", "sv06-102", "sv06-103", "sv06-104", "sv06-105",
    "sv06-107", "sv06-108", "sv06-109", "sv06-110",
    "sv06-113", "sv06-114", "sv06-115", "sv06-116", "sv06-117",
    "sv06-119", "sv06-120", "sv06-121", "sv06-122", "sv06-123",
    "sv06-124", "sv06-125", "sv06-126", "sv06-127",
    "sv06-131", "sv06-132", "sv06-133", "sv06-134", "sv06-135",
    "sv06-136", "sv06-137", "sv06-138", "sv06-139", "sv06-140",
    # TEF sv05: 001–048 (skip 023, 024, 025)
    "sv05-001", "sv05-002", "sv05-003", "sv05-004", "sv05-005",
    "sv05-006", "sv05-007", "sv05-008", "sv05-009", "sv05-010",
    "sv05-011", "sv05-012", "sv05-013", "sv05-014", "sv05-015",
    "sv05-016", "sv05-017", "sv05-018", "sv05-019", "sv05-020",
    "sv05-021", "sv05-022",
    "sv05-026", "sv05-027", "sv05-028", "sv05-029", "sv05-030",
    "sv05-031", "sv05-032", "sv05-033", "sv05-034", "sv05-035",
    "sv05-036", "sv05-037", "sv05-038", "sv05-039", "sv05-040",
    "sv05-041", "sv05-042", "sv05-043", "sv05-044", "sv05-045",
    "sv05-046", "sv05-047", "sv05-048",
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
