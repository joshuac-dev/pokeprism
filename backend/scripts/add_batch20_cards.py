#!/usr/bin/env python3
"""Insert Batch 20 card definitions into the PostgreSQL cards table.

Cards covered (52 new inserts from 78 Batch 20 cards — final batch):
  - SPA/TWM (sv06): 142,144..147,149..151,156..160,166
  - TEF (sv05): 142,143,147,148,150,151,156,159,160
  - MEP Promos (mep): 028
  - PR-SV Promos (svp): 114,150,224
  - POR (me03): 087
  - ASC (me02.5): 217
  - MEE (mee): 008
  - BLK (sv10.5b): 086
  - JTG (sv09): 159
  - SVE energies (sve): 001..016,019,020,022,024

Already in DB — skip insert:
  sv05-144, sv05-145, sv05-146, sv05-155, sv05-161,
  sv06-143, sv06-148, sv06-153, sv06-154, sv06-155,
  sv10-182, sv10.5w-086,
  me02.5-216,
  me03-086, me03-088,
  mee-001..007,
  sve-017, sve-018, sve-021, sve-023

Usage:
    cd backend && python3 -m scripts.add_batch20_cards
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

# Already in DB — skip insert
_ALREADY_IN_DB = {
    # TEF (sv05) — registered in earlier batches
    "sv05-144",   # Buddy-Buddy Poffin
    "sv05-145",   # Counter Catcher
    "sv05-146",   # Earthen Vessel
    "sv05-155",   # Iono
    "sv05-161",   # Mist Energy
    # SPA/TWM (sv06) — registered in earlier batches
    "sv06-143",   # Boss's Orders (Ghetsis)
    "sv06-148",   # Iono (TWM alt art)
    "sv06-153",   # Briar (TWM alt art)
    "sv06-154",   # Carmine
    "sv06-155",   # Crispin
    # DRI (sv10) / WHT (sv10.5w) — registered in earlier batches
    "sv10-182",   # Team Rocket's Energy
    "sv10.5w-086", # Ignition Energy
    # ASC (me02.5) — registered in earlier batches
    "me02.5-216", # Prism Energy
    # POR (me03) — registered in earlier batches
    "me03-086",   # Growing Grass Energy
    "me03-088",   # Telepathic Psychic Energy
    # MEE — registered in earlier batches
    "mee-001",    # Basic Grass Energy (MEE)
    "mee-002",    # Basic Fire Energy (MEE)
    "mee-003",    # Basic Water Energy (MEE)
    "mee-004",    # Basic Lightning Energy (MEE)
    "mee-005",    # Basic Psychic Energy (MEE)
    "mee-006",    # Basic Fighting Energy (MEE)
    "mee-007",    # Basic Darkness Energy (MEE)
    # SVE — registered in earlier batches
    "sve-017",    # Basic Grass Energy variant
    "sve-018",    # Basic Fire Energy variant
    "sve-021",    # Basic Psychic Energy variant
    "sve-023",    # Basic Metal Energy variant
}

ALL_IDS: list[str] = [
    # SPA/TWM (sv06): trainers + special energies
    "sv06-142",  # Accompanying Flute
    "sv06-143",  # Boss's Orders (Ghetsis) [already in DB]
    "sv06-144",  # Caretaker
    "sv06-145",  # Carmine (alt art)
    "sv06-146",  # Community Center
    "sv06-147",  # Cook
    "sv06-148",  # Iono (alt art) [already in DB]
    "sv06-149",  # Galactic Card
    "sv06-150",  # Handheld Fan
    "sv06-151",  # Hassel
    "sv06-153",  # Briar (alt art) [already in DB]
    "sv06-154",  # Carmine [already in DB]
    "sv06-155",  # Crispin [already in DB]
    "sv06-156",  # Love Ball
    "sv06-157",  # Lucian
    "sv06-158",  # Lucky Helmet
    "sv06-159",  # Penny
    "sv06-160",  # Perrin
    "sv06-166",  # Boomerang Energy

    # TEF (sv05): trainers
    "sv05-142",  # Bianca's Devotion
    "sv05-143",  # Boxed Order
    "sv05-144",  # Buddy-Buddy Poffin [already in DB]
    "sv05-145",  # Counter Catcher [already in DB]
    "sv05-146",  # Earthen Vessel [already in DB]
    "sv05-147",  # Explorer's Guidance
    "sv05-148",  # Full Metal Lab
    "sv05-150",  # Hand Trimmer
    "sv05-151",  # Heavy Baton
    "sv05-155",  # Iono [already in DB]
    "sv05-156",  # Perilous Jungle
    "sv05-159",  # Rescue Board
    "sv05-160",  # Salvatore
    "sv05-161",  # Mist Energy [already in DB]

    # MEP Black Star Promos (mep)
    "mep-028",   # Celebratory Fanfare

    # PR-SV Promos (svp)
    "svp-114",   # Picnicker
    "svp-150",   # Paradise Resort
    "svp-224",   # Paradise Resort (alt art)

    # POR — Perfect Order (me03)
    "me03-086",  # Growing Grass Energy [already in DB]
    "me03-087",  # Rocky Fighting Energy
    "me03-088",  # Telepathic Psychic Energy [already in DB]

    # ASC — Ascended Heroes (me02.5)
    "me02.5-216", # Prism Energy [already in DB]
    "me02.5-217", # Team Rocket's Energy (alt art)

    # MEE — Mega Evolution Energy (mee)
    "mee-001", "mee-002", "mee-003", "mee-004",  # already in DB
    "mee-005", "mee-006", "mee-007",              # already in DB
    "mee-008",   # Basic Grass Energy (MEE) variant

    # BLK — Black Bolt (sv10.5b)
    "sv10.5b-086", # Prism Energy (alt art)

    # JTG — Journey Together (sv09)
    "sv09-159",  # Spiky Energy

    # SVE — Scarlet & Violet Energy
    "sve-001", "sve-002", "sve-003", "sve-004", "sve-005",
    "sve-006", "sve-007", "sve-008",
    "sve-009", "sve-010", "sve-011", "sve-012", "sve-013",
    "sve-014", "sve-015", "sve-016",
    "sve-017", "sve-018",  # already in DB
    "sve-019", "sve-020",
    "sve-021",  # already in DB
    "sve-022",
    "sve-023",  # already in DB
    "sve-024",
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
