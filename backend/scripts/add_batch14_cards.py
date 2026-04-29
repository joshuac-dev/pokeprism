#!/usr/bin/env python3
"""Insert Batch 14 card definitions into the PostgreSQL cards table.

Cards covered:
  - SFA (sv06.5): 035–053  (034, 038, 039 already in DB — skipped)
  - TWM (sv06):  001–081   (025, 039, 053, 057, 064 already in DB — skipped)

Usage:
    cd backend && python3 -m scripts.add_batch14_cards
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
    "sv06.5-034",  # Malamar SFA 34
    "sv06.5-038",  # Fezandipiti ex SFA 38
    "sv06.5-039",  # Pecharunt ex SFA 39
    "sv06-025",    # Teal Mask Ogerpon ex TWM 25
    "sv06-039",    # Chi-Yu TWM 39
    "sv06-053",    # Froslass TWM 53
    "sv06-057",    # Frogadier TWM 57
    "sv06-064",    # Wellspring Mask Ogerpon ex TWM 64
}

ALL_IDS: list[str] = [
    # SFA sv06.5: 035–053 (skip 038, 039)
    "sv06.5-035", "sv06.5-036", "sv06.5-037",
    "sv06.5-040", "sv06.5-041", "sv06.5-042", "sv06.5-043",
    "sv06.5-044", "sv06.5-045", "sv06.5-046", "sv06.5-047",
    "sv06.5-048", "sv06.5-049", "sv06.5-050", "sv06.5-051",
    "sv06.5-052", "sv06.5-053",
    # TWM sv06: 001–081 (skip 025, 039, 053, 057, 064)
    "sv06-001", "sv06-002", "sv06-003", "sv06-004", "sv06-005",
    "sv06-006", "sv06-007", "sv06-008", "sv06-009", "sv06-010",
    "sv06-011", "sv06-012", "sv06-013", "sv06-014", "sv06-015",
    "sv06-016", "sv06-017", "sv06-018", "sv06-019", "sv06-020",
    "sv06-021", "sv06-022", "sv06-023", "sv06-024",
    "sv06-026", "sv06-027", "sv06-028", "sv06-029", "sv06-030",
    "sv06-031", "sv06-032", "sv06-033", "sv06-034", "sv06-035",
    "sv06-036", "sv06-037", "sv06-038",
    "sv06-040", "sv06-041", "sv06-042", "sv06-043", "sv06-044",
    "sv06-045", "sv06-046", "sv06-047", "sv06-048", "sv06-049",
    "sv06-050", "sv06-051", "sv06-052",
    "sv06-054", "sv06-055", "sv06-056",
    "sv06-058", "sv06-059", "sv06-060", "sv06-061", "sv06-062",
    "sv06-063",
    "sv06-065", "sv06-066", "sv06-067", "sv06-068", "sv06-069",
    "sv06-070", "sv06-071", "sv06-072", "sv06-073", "sv06-074",
    "sv06-075", "sv06-076", "sv06-077", "sv06-078", "sv06-079",
    "sv06-080", "sv06-081",
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
