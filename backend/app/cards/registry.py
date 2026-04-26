"""In-memory card definition registry.

In Phase 1 (no database), this module-level dict serves as the card pool.
Phase 4 replaces the in-memory lookup with async PostgreSQL queries.
"""

from __future__ import annotations

from typing import Optional
from app.cards.models import CardDefinition

# Populated by load_card_pool() or tests/conftest.py
_registry: dict[str, CardDefinition] = {}


def register(card_def: CardDefinition) -> None:
    _registry[card_def.tcgdex_id] = card_def


def register_many(card_defs: dict[str, CardDefinition]) -> None:
    _registry.update(card_defs)


def get(tcgdex_id: str) -> Optional[CardDefinition]:
    return _registry.get(tcgdex_id)


def all_cards() -> dict[str, CardDefinition]:
    return dict(_registry)


def clear() -> None:
    """Clear registry (used between test runs)."""
    _registry.clear()


def size() -> int:
    return len(_registry)
