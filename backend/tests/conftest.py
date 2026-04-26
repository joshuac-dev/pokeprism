"""Shared pytest fixtures for PokéPrism Phase 1 tests.

Fixtures load real card data from captured TCGDex responses
(backend/tests/fixtures/cards/*.json) so tests work offline.

Run `python scripts/capture_fixtures.py` from the backend directory to
populate the fixture files before running tests for the first time.

Deck 1: Dragapult ex / Dusknoir — spread-damage Psychic + Dragon
Deck 2: Team Rocket's Mewtwo ex — TR synergy Psychic + Dark
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Generator

import pytest

from app.cards.loader import CardListLoader, SET_CODE_MAP
from app.cards.models import CardDefinition
from app.cards import registry as card_registry

logger = logging.getLogger(__name__)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "cards"

# ──────────────────────────────────────────────────────────────────────────────
# Deck lists — (set_abbrev, card_number, copies)
# All 60 cards must be in CARDLIST.md and have a captured fixture.
# ──────────────────────────────────────────────────────────────────────────────

DRAGAPULT_DECK: list[tuple[str, str, int]] = [
    # Pokémon (22)
    ("TWM", "128", 4),  # Dreepy
    ("TWM", "129", 3),  # Drakloak
    ("TWM", "130", 3),  # Dragapult ex
    ("PRE", "35",  4),  # Duskull
    ("PRE", "36",  2),  # Dusclops
    ("PRE", "37",  2),  # Dusknoir
    ("TWM", "96",  1),  # Fezandipiti
    ("ASC", "142", 1),  # Fezandipiti ex
    ("TWM", "95",  1),  # Munkidori
    ("ASC", "39",  1),  # Psyduck
    # Trainers (30)
    ("TEF", "144", 4),  # Buddy-Buddy Poffin
    ("MEG", "131", 3),  # Ultra Ball
    ("MEG", "125", 3),  # Rare Candy
    ("ASC", "196", 2),  # Night Stretcher
    ("TEF", "157", 2),  # Prime Catcher
    ("MEG", "114", 2),  # Boss's Orders
    ("TEF", "154", 2),  # Maximum Belt
    ("TWM", "167", 2),  # Legacy Energy
    ("TEF", "155", 2),  # Morty's Conviction
    ("TEF", "146", 2),  # Eri
    ("TWM", "163", 2),  # Secret Box
    ("TWM", "143", 1),  # Bug Catching Set
    ("TWM", "148", 1),  # Enhanced Hammer
    ("PRE", "95",  1),  # Binding Mochi
    ("PRE", "112", 1),  # Janine's Secret Art
    # Energy (8)
    ("MEE", "5",   4),  # Psychic Energy
    ("TEF", "161", 2),  # Mist Energy
    ("ASC", "216", 2),  # Prism Energy
]

TEAM_ROCKET_MEWTWO_DECK: list[tuple[str, str, int]] = [
    # Pokémon (18)
    ("DRI", "81",  3),  # Team Rocket's Mewtwo ex
    ("DRI", "87",  3),  # Team Rocket's Mimikyu
    ("DRI", "128", 2),  # Team Rocket's Sneasel
    ("DRI", "51",  2),  # Team Rocket's Articuno
    ("DRI", "10",  2),  # Shaymin
    ("ASC", "39",  2),  # Psyduck
    ("MEG", "88",  2),  # Yveltal
    ("MEG", "86",  1),  # Mega Absol ex
    ("MEG", "74",  1),  # Lunatone
    # Trainers (33)
    ("DRI", "178", 3),  # Team Rocket's Transceiver
    ("DRI", "174", 3),  # Team Rocket's Giovanni
    ("DRI", "173", 3),  # Team Rocket's Factory
    ("DRI", "177", 2),  # Team Rocket's Proton
    ("DRI", "170", 2),  # Team Rocket's Archer
    ("DRI", "171", 2),  # Team Rocket's Ariana
    ("DRI", "176", 2),  # Team Rocket's Petrel
    ("DRI", "180", 2),  # Team Rocket's Watchtower
    ("DRI", "169", 2),  # Spikemuth Gym
    ("DRI", "168", 2),  # Sacred Ash
    ("DRI", "164", 2),  # Energy Recycler
    ("MEG", "131", 2),  # Ultra Ball
    ("MEG", "114", 2),  # Boss's Orders
    ("MEG", "119", 1),  # Lillie's Determination
    ("MEG", "115", 1),  # Energy Switch
    ("SVI", "186", 1),  # Pokégear 3.0
    ("SFA", "57",  1),  # Colress's Tenacity
    # Energy (9)
    ("MEE", "5",   3),  # Psychic Energy
    ("MEE", "7",   3),  # Darkness Energy
    ("DRI", "182", 2),  # Team Rocket's Energy
    ("ASC", "216", 1),  # Prism Energy
]


# ──────────────────────────────────────────────────────────────────────────────
# Fixture loading helpers
# ──────────────────────────────────────────────────────────────────────────────

def _load_fixture(set_abbrev: str, card_number: str) -> dict | None:
    """Load a raw TCGDex JSON fixture from disk."""
    tcgdex_set_id = SET_CODE_MAP.get(set_abbrev)
    if not tcgdex_set_id:
        logger.warning("Unknown set abbrev %s in fixture lookup", set_abbrev)
        return None
    card_id = f"{tcgdex_set_id}-{int(card_number):03d}"
    path = FIXTURE_DIR / f"{card_id}.json"
    if not path.exists():
        logger.warning("Fixture not found: %s (run scripts/capture_fixtures.py)", path)
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _deck_to_defs(deck_list: list[tuple[str, str, int]]) -> list[CardDefinition]:
    """Convert a deck list to a list of CardDefinition objects (with copies)."""
    loader = CardListLoader()
    defs: list[CardDefinition] = []
    for set_abbrev, number, copies in deck_list:
        raw = _load_fixture(set_abbrev, number)
        if raw is None:
            raise RuntimeError(
                f"Missing fixture for {set_abbrev} {number}. "
                "Run: cd backend && python scripts/capture_fixtures.py"
            )
        cdef = loader._transform(
            raw,
            {"set_abbrev": set_abbrev, "number": number, "name": raw.get("name", "")},
        )
        defs.extend([cdef] * copies)
    assert len(defs) == 60, f"Expected 60-card deck, got {len(defs)}"
    return defs


# ──────────────────────────────────────────────────────────────────────────────
# Pytest fixtures
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def all_card_defs() -> dict[str, CardDefinition]:
    """Load all CARDLIST.md cards from fixtures into a dict keyed by tcgdex_id.

    This is the session-scoped registry. Populated once and shared across all
    tests in the session. Tests that add cards to the live registry should use
    the function-scoped `card_registry_populated` fixture instead.
    """
    loader = CardListLoader()
    all_entries: list[tuple[str, str]] = []
    for deck in (DRAGAPULT_DECK, TEAM_ROCKET_MEWTWO_DECK):
        for set_abbrev, number, _ in deck:
            all_entries.append((set_abbrev, number))

    defs: dict[str, CardDefinition] = {}
    for set_abbrev, number in all_entries:
        raw = _load_fixture(set_abbrev, number)
        if raw:
            cdef = loader._transform(
                raw,
                {"set_abbrev": set_abbrev, "number": number, "name": raw.get("name", "")},
            )
            defs[cdef.tcgdex_id] = cdef
    return defs


@pytest.fixture(scope="session")
def dragapult_deck_defs() -> list[CardDefinition]:
    """60 CardDefinition objects for the Dragapult ex / Dusknoir deck."""
    return _deck_to_defs(DRAGAPULT_DECK)


@pytest.fixture(scope="session")
def team_rocket_deck_defs() -> list[CardDefinition]:
    """60 CardDefinition objects for the Team Rocket's Mewtwo ex deck."""
    return _deck_to_defs(TEAM_ROCKET_MEWTWO_DECK)


@pytest.fixture(autouse=True)
def populated_registry(all_card_defs: dict[str, CardDefinition]) -> Generator:
    """Register all test-deck cards into the in-memory registry before each test.

    The registry is cleared and repopulated so tests don't leak state.
    """
    card_registry.clear()
    card_registry.register_many(all_card_defs)
    yield
    card_registry.clear()
