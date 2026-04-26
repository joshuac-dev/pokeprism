"""Deck validation rules (§6.3 preamble + standard TCG rules)."""

from __future__ import annotations

from app.engine.state import CardInstance
from app.cards import registry as card_registry


class RuleEngine:
    DECK_SIZE = 60
    MAX_COPIES = 4
    MIN_BASICS = 1
    MAX_BENCH = 5
    PRIZE_COUNT = 6

    # Cards exempt from the 4-copy limit (basic energy)
    UNLIMITED_COPY_NAMES: frozenset[str] = frozenset({
        "Grass Energy", "Fire Energy", "Water Energy", "Lightning Energy",
        "Psychic Energy", "Fighting Energy", "Darkness Energy", "Metal Energy",
        "Dragon Energy", "Fairy Energy", "Colorless Energy",
    })

    @staticmethod
    def validate_deck(deck: list[CardInstance]) -> list[str]:
        """Return a list of rule violations (empty = valid deck)."""
        errors: list[str] = []

        if len(deck) != RuleEngine.DECK_SIZE:
            errors.append(
                f"Deck must be exactly {RuleEngine.DECK_SIZE} cards, "
                f"got {len(deck)}"
            )

        # Count copies
        name_counts: dict[str, int] = {}
        for card in deck:
            name_counts[card.card_name] = name_counts.get(card.card_name, 0) + 1

        for name, count in name_counts.items():
            if name not in RuleEngine.UNLIMITED_COPY_NAMES:
                if count > RuleEngine.MAX_COPIES:
                    errors.append(
                        f"Too many copies of '{name}': {count} "
                        f"(max {RuleEngine.MAX_COPIES})"
                    )

        basics = [
            c for c in deck
            if c.card_type.lower() == "pokemon" and c.evolution_stage == 0
        ]
        if len(basics) < RuleEngine.MIN_BASICS:
            errors.append(
                f"Deck must have at least {RuleEngine.MIN_BASICS} Basic Pokémon"
            )

        return errors

    @staticmethod
    def deck_has_basic(deck: list[CardInstance]) -> bool:
        return any(
            c.card_type.lower() == "pokemon" and c.evolution_stage == 0
            for c in deck
        )
