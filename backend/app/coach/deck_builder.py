"""Deterministic baseline deck builder for partial/no-deck simulation modes.

This builder intentionally does not pretend to be a competitive deck AI. It
uses only CardDefinition objects already loaded from the authoritative card DB,
obeys current project legality rules, and returns metadata explaining what it
preserved or added. Historical memory can improve this later without changing
the API contract.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import random
import re
from typing import Iterable

from app.cards.models import CardDefinition

MINIMUM_MATCHES_RECOMMENDED = 5_000
"""Recommended match count before memory-backed deck building is high quality."""

DECK_SIZE = 60
MAX_COPIES = 4
BASIC_ENERGY_NAMES = {
    "Grass Energy", "Fire Energy", "Water Energy", "Lightning Energy",
    "Psychic Energy", "Fighting Energy", "Darkness Energy", "Metal Energy",
    "Dragon Energy", "Fairy Energy", "Colorless Energy",
}


class DeckBuildError(ValueError):
    """Raised when a deck cannot be built without violating hard rules."""


@dataclass
class DeckBuildResult:
    deck: list[CardDefinition]
    metadata: dict = field(default_factory=dict)

    @property
    def deck_text(self) -> str:
        counts: Counter[str] = Counter(card.tcgdex_id for card in self.deck)
        first_seen: dict[str, CardDefinition] = {}
        for card in self.deck:
            first_seen.setdefault(card.tcgdex_id, card)
        lines = []
        for tcgdex_id, count in sorted(counts.items(), key=lambda item: _sort_key(first_seen[item[0]])):
            card = first_seen[tcgdex_id]
            lines.append(f"{count} {card.name} {card.tcgdex_id}")
        return "\n".join(lines)


class DeckBuilder:
    """Builds or completes decks from an available CardDefinition pool."""

    def __init__(
        self,
        available_cards: Iterable[CardDefinition],
        excluded_ids: Iterable[str] | None = None,
        rng_seed: int | None = 0,
    ) -> None:
        self._excluded_ids = set(excluded_ids or [])
        self._rng = random.Random(rng_seed)
        self._pool = {
            c.tcgdex_id: c
            for c in available_cards
            if c.tcgdex_id and c.tcgdex_id not in self._excluded_ids
        }
        self._by_name: dict[str, list[CardDefinition]] = {}
        for card in self._pool.values():
            self._by_name.setdefault(card.name, []).append(card)
        for cards in self._by_name.values():
            cards.sort(key=_sort_key)

    def complete_deck(
        self,
        partial_deck: list[CardDefinition],
        target_size: int = DECK_SIZE,
        build_around_ids: Iterable[str] | None = None,
    ) -> DeckBuildResult:
        """Fill a legal partial deck to target_size while preserving its cards."""
        self._validate_target_size(target_size)
        warnings: list[str] = [
            "Conservative baseline builder: uses card categories, attack costs, and simple staples; not memory-optimized."
        ]
        rejected = self._find_rejected(partial_deck)
        if rejected:
            raise DeckBuildError("Partial deck contains excluded cards: " + ", ".join(rejected))
        errors = self._validate_partial(partial_deck, target_size)
        if errors:
            raise DeckBuildError("; ".join(errors))

        deck = list(partial_deck)
        preserved = [c.tcgdex_id for c in deck]
        build_around = [self._require_pool_card(cid) for cid in (build_around_ids or [])]
        for card in build_around:
            if not any(c.tcgdex_id == card.tcgdex_id for c in deck):
                self._add_copies(deck, card, 1)

        self._fill_deck(deck, target_size, warnings)
        final_errors = self.validate_deck(deck, target_size)
        if final_errors:
            raise DeckBuildError("Generated deck failed validation: " + "; ".join(final_errors))

        added_counts = Counter(c.tcgdex_id for c in deck) - Counter(c.tcgdex_id for c in partial_deck)
        return DeckBuildResult(
            deck=deck,
            metadata={
                "mode": "partial",
                "cards_preserved": preserved,
                "cards_added": dict(sorted(added_counts.items())),
                "cards_rejected": [],
                "unresolved_cards": [],
                "excluded_cards": sorted(self._excluded_ids),
                "warnings": warnings,
                "confidence": "baseline",
            },
        )

    def build_from_scratch(
        self,
        avoid_meta: bool = True,
        target_size: int = DECK_SIZE,
        build_around_ids: Iterable[str] | None = None,
        target_archetype: str | None = None,
    ) -> DeckBuildResult:
        """Generate a legal baseline 60-card deck from DB-backed cards."""
        self._validate_target_size(target_size)
        if not self._pool:
            raise DeckBuildError("Cannot build a deck: available card pool is empty.")

        warnings = [
            "Conservative baseline builder: no historical memory optimization was applied."
        ]
        if avoid_meta:
            warnings.append("avoid_meta requested, but meta-frequency data is not modeled yet.")
        if target_archetype:
            warnings.append("target_archetype is recorded as a preference only; archetype labels are not modeled yet.")

        deck: list[CardDefinition] = []
        core_cards = [self._require_pool_card(cid) for cid in (build_around_ids or [])]
        if not core_cards:
            core = self._choose_primary_core()
            if core is None:
                raise DeckBuildError("Cannot build a deck: no Basic Pokémon or Pokémon ex found in card pool.")
            core_cards = [core]

        for core in core_cards:
            copies = 3 if core.is_pokemon and not core.is_basic_pokemon else 4
            self._add_evolution_support(deck, core)
            self._add_copies(deck, core, copies)

        self._fill_deck(deck, target_size, warnings)
        final_errors = self.validate_deck(deck, target_size)
        if final_errors:
            raise DeckBuildError("Generated deck failed validation: " + "; ".join(final_errors))

        counts = Counter(c.tcgdex_id for c in deck)
        return DeckBuildResult(
            deck=deck,
            metadata={
                "mode": "none",
                "core_cards": [c.tcgdex_id for c in core_cards],
                "support_cards": {
                    cid: count for cid, count in sorted(counts.items())
                    if self._pool[cid].is_trainer
                },
                "energy_cards": {
                    cid: count for cid, count in sorted(counts.items())
                    if self._pool[cid].is_energy
                },
                "flex_cards": {
                    cid: count for cid, count in sorted(counts.items())
                    if not self._pool[cid].is_trainer and not self._pool[cid].is_energy
                    and cid not in {c.tcgdex_id for c in core_cards}
                },
                "excluded_cards": sorted(self._excluded_ids),
                "warnings": warnings,
                "unresolved_constraints": [],
                "confidence": "baseline",
            },
        )

    def validate_deck(self, deck: list[CardDefinition], target_size: int = DECK_SIZE) -> list[str]:
        errors: list[str] = []
        if len(deck) != target_size:
            errors.append(f"Deck must be exactly {target_size} cards, got {len(deck)}")
        if not any(card.is_basic_pokemon for card in deck):
            errors.append("Deck must contain at least 1 Basic Pokémon")
        by_name = Counter(card.name for card in deck)
        for name, count in sorted(by_name.items()):
            if name not in BASIC_ENERGY_NAMES and count > MAX_COPIES:
                errors.append(f"Too many copies of '{name}': {count} (max {MAX_COPIES})")
        excluded = sorted({card.tcgdex_id for card in deck if card.tcgdex_id in self._excluded_ids})
        if excluded:
            errors.append("Deck contains excluded cards: " + ", ".join(excluded))
        unknown = sorted({card.tcgdex_id for card in deck if card.tcgdex_id not in self._pool})
        if unknown:
            errors.append("Deck contains cards outside available pool: " + ", ".join(unknown))
        return errors

    def _fill_deck(self, deck: list[CardDefinition], target_size: int, warnings: list[str]) -> None:
        desired = self._desired_counts(deck, target_size)
        self._ensure_basic_pokemon(deck)
        self._fill_category(deck, "pokemon", desired["pokemon"], target_size)
        self._fill_category(deck, "trainer", desired["trainer"], target_size)
        self._fill_category(deck, "energy", desired["energy"], target_size)
        self._fill_any(deck, target_size)
        if len(deck) < target_size:
            raise DeckBuildError(
                f"Not enough eligible cards to build a {target_size}-card deck "
                f"after exclusions and copy limits; built {len(deck)}."
            )
        if len(deck) > target_size:
            del deck[target_size:]
            warnings.append("Deck was trimmed to target size after preserving required cards.")

    def _desired_counts(self, deck: list[CardDefinition], target_size: int) -> dict[str, int]:
        # Conservative baseline composition used only when the project has no
        # archetype-specific rules available.
        if target_size != DECK_SIZE:
            pokemon = max(1, min(target_size, round(target_size * 0.30)))
            energy = max(1, round(target_size * 0.15))
            trainer = target_size - pokemon - energy
            return {"pokemon": pokemon, "trainer": trainer, "energy": energy}
        return {"pokemon": 18, "trainer": 32, "energy": 10}

    def _fill_category(self, deck: list[CardDefinition], category: str, desired: int, target_size: int) -> None:
        while len(deck) < target_size and self._category_count(deck, category) < desired:
            candidate = self._next_candidate(deck, category)
            if candidate is None:
                return
            self._add_copies(deck, candidate, 1)

    def _fill_any(self, deck: list[CardDefinition], target_size: int) -> None:
        while len(deck) < target_size:
            candidate = self._next_candidate(deck, None)
            if candidate is None:
                return
            self._add_copies(deck, candidate, 1)

    def _next_candidate(self, deck: list[CardDefinition], category: str | None) -> CardDefinition | None:
        candidates = list(self._pool.values())
        if category == "pokemon":
            candidates = [c for c in candidates if c.is_pokemon]
        elif category == "trainer":
            candidates = [c for c in candidates if c.is_trainer]
        elif category == "energy":
            candidates = [c for c in candidates if c.is_energy]

        type_preferences = self._deck_energy_preferences(deck)
        candidates.sort(key=lambda c: self._candidate_sort_tuple(c, deck, type_preferences))
        for card in candidates:
            if self._can_add(deck, card):
                return card
        return None

    def _candidate_sort_tuple(
        self,
        card: CardDefinition,
        deck: list[CardDefinition],
        type_preferences: Counter[str],
    ) -> tuple:
        type_score = 0
        if card.is_energy and card.energy_provides:
            type_score = max(type_preferences.get(t, 0) for t in card.energy_provides)
        return (-self._score_card(card, type_score), _sort_key(card), self._rng.random())

    def _score_card(self, card: CardDefinition, type_score: int = 0) -> int:
        score = 0
        if card.is_pokemon:
            score += 100
            if card.is_basic_pokemon:
                score += 25
            if card.is_ex:
                score += 35
            score += min(card.hp or 0, 300) // 10
            score += max((_damage_value(a.damage) for a in card.attacks), default=0) // 10
        elif card.is_trainer:
            score += 80 + _trainer_staple_score(card)
        elif card.is_energy:
            score += 50 + type_score * 15
            if card.subcategory.lower() == "basic":
                score += 20
        return score

    def _choose_primary_core(self) -> CardDefinition | None:
        candidates = [c for c in self._pool.values() if c.is_pokemon]
        if not candidates:
            return None
        candidates.sort(key=lambda c: (-self._score_card(c), _sort_key(c)))
        return candidates[0]

    def _add_evolution_support(self, deck: list[CardDefinition], card: CardDefinition) -> None:
        current = card
        while current.evolve_from:
            prior = self._best_by_name(current.evolve_from)
            if prior is None:
                break
            self._add_copies(deck, prior, 3 if prior.is_pokemon and not prior.is_basic_pokemon else 4)
            current = prior

    def _ensure_basic_pokemon(self, deck: list[CardDefinition]) -> None:
        if any(card.is_basic_pokemon for card in deck):
            return
        basic = self._next_candidate([], "pokemon")
        if basic is None or not basic.is_basic_pokemon:
            basics = [c for c in self._pool.values() if c.is_basic_pokemon]
            if not basics:
                raise DeckBuildError("Cannot build a deck: no Basic Pokémon available.")
            basics.sort(key=lambda c: (-self._score_card(c), _sort_key(c)))
            basic = basics[0]
        self._add_copies(deck, basic, 4)

    def _best_by_name(self, name: str) -> CardDefinition | None:
        cards = [c for c in self._by_name.get(name, []) if c.tcgdex_id not in self._excluded_ids]
        if not cards:
            return None
        cards.sort(key=lambda c: (-self._score_card(c), _sort_key(c)))
        return cards[0]

    def _add_copies(self, deck: list[CardDefinition], card: CardDefinition, copies: int) -> int:
        added = 0
        for _ in range(copies):
            if self._can_add(deck, card):
                deck.append(card)
                added += 1
        return added

    def _can_add(self, deck: list[CardDefinition], card: CardDefinition) -> bool:
        if card.tcgdex_id in self._excluded_ids or card.tcgdex_id not in self._pool:
            return False
        if card.name in BASIC_ENERGY_NAMES:
            return True
        return sum(1 for c in deck if c.name == card.name) < MAX_COPIES

    def _category_count(self, deck: list[CardDefinition], category: str) -> int:
        if category == "pokemon":
            return sum(1 for c in deck if c.is_pokemon)
        if category == "trainer":
            return sum(1 for c in deck if c.is_trainer)
        if category == "energy":
            return sum(1 for c in deck if c.is_energy)
        return 0

    def _deck_energy_preferences(self, deck: list[CardDefinition]) -> Counter[str]:
        prefs: Counter[str] = Counter()
        for card in deck:
            for t in card.types:
                prefs[t] += 2
            for attack in card.attacks:
                for cost in attack.cost:
                    if cost != "Colorless":
                        prefs[cost] += 1
        return prefs

    def _validate_target_size(self, target_size: int) -> None:
        if target_size <= 0 or target_size > DECK_SIZE:
            raise DeckBuildError(f"target_size must be between 1 and {DECK_SIZE}")

    def _require_pool_card(self, tcgdex_id: str) -> CardDefinition:
        if tcgdex_id in self._excluded_ids:
            raise DeckBuildError(f"Build-around card is excluded: {tcgdex_id}")
        card = self._pool.get(tcgdex_id)
        if card is None:
            raise DeckBuildError(f"Build-around card is not available: {tcgdex_id}")
        return card

    def _find_rejected(self, cards: list[CardDefinition]) -> list[str]:
        return sorted({c.tcgdex_id for c in cards if c.tcgdex_id in self._excluded_ids})

    def _validate_partial(self, deck: list[CardDefinition], target_size: int) -> list[str]:
        errors: list[str] = []
        if len(deck) >= target_size:
            errors.append(f"Partial deck must contain fewer than {target_size} cards, got {len(deck)}")
        by_name = Counter(card.name for card in deck)
        for name, count in sorted(by_name.items()):
            if name not in BASIC_ENERGY_NAMES and count > MAX_COPIES:
                errors.append(f"Too many copies of '{name}': {count} (max {MAX_COPIES})")
        unknown = sorted({card.tcgdex_id for card in deck if card.tcgdex_id not in self._pool})
        if unknown:
            errors.append("Partial deck contains cards outside available pool: " + ", ".join(unknown))
        return errors


def _sort_key(card: CardDefinition) -> tuple:
    return (card.set_abbrev, _natural_number(card.set_number), card.name, card.tcgdex_id)


def _natural_number(value: str) -> tuple[int, str]:
    try:
        return (int(value), "")
    except (TypeError, ValueError):
        return (10_000, value or "")


def _damage_value(value: str) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else 0


def _trainer_staple_score(card: CardDefinition) -> int:
    name = card.name.lower()
    score = 0
    for keyword, weight in {
        "ball": 30,
        "candy": 25,
        "catcher": 20,
        "orders": 20,
        "switch": 15,
        "stretcher": 15,
        "energy": 10,
        "draw": 10,
    }.items():
        if keyword in name:
            score += weight
    if card.subcategory.lower() == "supporter":
        score += 5
    return score
