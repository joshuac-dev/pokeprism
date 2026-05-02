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

# Role-tagging keyword sets for trainer cards (Phase 1).
_ENERGY_ACCEL_TRAINER_KEYWORDS: frozenset[str] = frozenset({
    "raihan", "energy retrieval", "energy switch", "exp. share",
    "earthen vessel", "superior energy retrieval",
})
_DISRUPTION_TRAINER_KEYWORDS: frozenset[str] = frozenset({
    "boss", "catcher", "lost vacuum", "eject button",
    "iono", "judge",
})
_HEALING_TRAINER_KEYWORDS: frozenset[str] = frozenset({
    "potion", "mela", "miriam",
})
_SETUP_TRAINER_KEYWORDS: frozenset[str] = frozenset({
    "ball", "candy", "research", "colress", "arven", "irida",
    "pal pad", "trekking shoes", "rotom phone", "stretcher",
})

# Draw-Supporter and search-Item detection keywords (Phase 4).
_DRAW_SUPPORTER_KEYWORDS: frozenset[str] = frozenset({
    "iono", "research", "colress", "judge", "magnolia",
    "cress", "lillie", "hau", "hop", "marnie",
})

# Archetype composition templates (Phase 2).
# Each entry specifies inclusive [min, max] card counts for pokemon/trainer/energy.
ARCHETYPE_TEMPLATES: dict[str, dict[str, int]] = {
    "aggro": {
        "pokemon_min": 10, "pokemon_max": 14,
        "trainer_min": 34, "trainer_max": 40,
        "energy_min": 8,  "energy_max": 14,
    },
    "evolution-ramp": {
        "pokemon_min": 16, "pokemon_max": 22,
        "trainer_min": 26, "trainer_max": 34,
        "energy_min": 8,  "energy_max": 12,
    },
    "control": {
        "pokemon_min": 8,  "pokemon_max": 12,
        "trainer_min": 38, "trainer_max": 44,
        "energy_min": 4,  "energy_max": 10,
    },
    "spread": {
        "pokemon_min": 14, "pokemon_max": 18,
        "trainer_min": 28, "trainer_max": 36,
        "energy_min": 8,  "energy_max": 14,
    },
    "stall": {
        "pokemon_min": 12, "pokemon_max": 16,
        "trainer_min": 30, "trainer_max": 38,
        "energy_min": 8,  "energy_max": 12,
    },
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

        self._fill_deck(
            deck, target_size, warnings,
            protected_names=frozenset(c.name for c in partial_deck),
        )
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
        if target_archetype and target_archetype not in ARCHETYPE_TEMPLATES:
            warnings.append(
                f"Unknown archetype '{target_archetype}'; known archetypes: "
                + ", ".join(sorted(ARCHETYPE_TEMPLATES)) + ". Using default composition."
            )

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

        self._fill_deck(deck, target_size, warnings, target_archetype=target_archetype)
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
        # Hard structural constraints
        if len(deck) != target_size:
            errors.append(f"Deck must be exactly {target_size} cards, got {len(deck)}")
        basic_count = sum(1 for c in deck if c.is_basic_pokemon)
        if basic_count == 0:
            errors.append("Deck must contain at least 1 Basic Pokémon")
        elif basic_count < 4:
            errors.append(
                f"Opening hand quality: only {basic_count} Basic Pokémon "
                f"(recommend ≥4 to avoid heavy mulligan odds)"
            )
        by_name = Counter(card.name for card in deck)
        for name, count in sorted(by_name.items()):
            if name not in BASIC_ENERGY_NAMES and count > MAX_COPIES:
                errors.append(f"Too many copies of '{name}': {count} (max {MAX_COPIES})")
        # Stadium copy limit (Phase 4)
        for name, count in by_name.items():
            card = next((c for c in deck if c.name == name), None)
            if card and card.is_trainer and card.subcategory.lower() == "stadium" and count > 2:
                errors.append(
                    f"Too many copies of Stadium '{name}': {count} (recommend ≤2; stadiums replace each other)"
                )
        excluded = sorted({card.tcgdex_id for card in deck if card.tcgdex_id in self._excluded_ids})
        if excluded:
            errors.append("Deck contains excluded cards: " + ", ".join(excluded))
        unknown = sorted({card.tcgdex_id for card in deck if card.tcgdex_id not in self._pool})
        if unknown:
            errors.append("Deck contains cards outside available pool: " + ", ".join(unknown))
        return errors

    def _fill_deck(
        self,
        deck: list[CardDefinition],
        target_size: int,
        warnings: list[str],
        target_archetype: str | None = None,
        protected_names: frozenset[str] | None = None,
    ) -> None:
        desired = self._desired_counts(deck, target_size, target_archetype)
        self._ensure_basic_pokemon(deck)
        self._ensure_staples(deck, target_size, warnings)
        self._fill_category(deck, "pokemon", desired["pokemon"], target_size)
        self._fill_category(deck, "trainer", desired["trainer"], target_size)
        self._fill_category(deck, "energy", desired["energy"], target_size)
        self._fill_any(deck, target_size)
        # Phase 5: replace structurally unplayable cards (orphaned evolutions, wrong-type energy).
        self._replace_dead_cards(deck, target_size, protected_names or frozenset(), warnings)
        if len(deck) < target_size:
            raise DeckBuildError(
                f"Not enough eligible cards to build a {target_size}-card deck "
                f"after exclusions and copy limits; built {len(deck)}."
            )
        if len(deck) > target_size:
            del deck[target_size:]
            warnings.append("Deck was trimmed to target size after preserving required cards.")

    def _desired_counts(
        self,
        deck: list[CardDefinition],
        target_size: int,
        target_archetype: str | None = None,
    ) -> dict[str, int]:
        if target_archetype and target_archetype in ARCHETYPE_TEMPLATES:
            return self._desired_counts_from_archetype(target_archetype, deck, target_size)
        # Conservative baseline composition used only when the project has no
        # archetype-specific rules available.
        if target_size != DECK_SIZE:
            pokemon = max(1, min(target_size, round(target_size * 0.30)))
            energy = max(1, round(target_size * 0.15))
            trainer = target_size - pokemon - energy
            return {"pokemon": pokemon, "trainer": trainer, "energy": energy}
        return {"pokemon": 18, "trainer": 32, "energy": 10}

    def _desired_counts_from_archetype(
        self,
        archetype: str,
        deck: list[CardDefinition],
        target_size: int,
    ) -> dict[str, int]:
        """Return category targets from an archetype template, respecting already-placed cards."""
        t = ARCHETYPE_TEMPLATES[archetype]
        already_pokemon = sum(1 for c in deck if c.is_pokemon)
        already_energy = sum(1 for c in deck if c.is_energy)
        pokemon = max(already_pokemon, (t["pokemon_min"] + t["pokemon_max"]) // 2)
        energy = max(already_energy, (t["energy_min"] + t["energy_max"]) // 2)
        trainer = target_size - pokemon - energy
        # Clamp trainer to template bounds; re-derive pokemon if needed
        trainer = max(t["trainer_min"], min(t["trainer_max"], trainer))
        pokemon = target_size - trainer - energy
        return {"pokemon": pokemon, "trainer": trainer, "energy": energy}

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

    def _ensure_staples(
        self,
        deck: list[CardDefinition],
        target_size: int,
        warnings: list[str],
    ) -> None:
        """Add one draw Supporter and one search Item to the deck if either is absent.

        Called before category filling so that these staples are always present
        unless the pool genuinely has none.
        """
        if len(deck) >= target_size:
            return
        if not any(_is_draw_supporter(c) for c in deck):
            candidate = next(
                (c for c in self._pool.values() if _is_draw_supporter(c) and self._can_add(deck, c)),
                None,
            )
            if candidate:
                self._add_copies(deck, candidate, 1)
            else:
                warnings.append("No draw Supporter available in card pool; opening-hand consistency may be low.")
        if len(deck) >= target_size:
            return
        if not any(_is_search_item(c) for c in deck):
            candidate = next(
                (c for c in self._pool.values() if _is_search_item(c) and self._can_add(deck, c)),
                None,
            )
            if candidate:
                self._add_copies(deck, candidate, 1)
            else:
                warnings.append("No search Item (Ball) available in card pool; setup consistency may be low.")

    def _trainer_role_counts(self, deck: list[CardDefinition]) -> dict[str, int]:
        """Count Trainer cards in the deck by their role tag."""
        counts: dict[str, int] = {}
        for card in deck:
            if not card.is_trainer:
                continue
            role = self._tag_card(card)
            counts[role] = counts.get(role, 0) + 1
        return counts

    def _find_dead_cards(self, deck: list[CardDefinition]) -> list[CardDefinition]:
        """Return cards that are structurally unplayable given deck composition.

        Detected cases:
        - Evolution Pokémon whose immediate pre-evolution is absent from the deck.
        - Energy cards that provide a type no Pokémon in the deck can use.
        """
        pokemon_names = {c.name for c in deck if c.is_pokemon}
        usable_types: set[str] = set()
        for card in deck:
            if card.is_pokemon:
                usable_types.update(card.types)
                for attack in card.attacks:
                    for cost in attack.cost:
                        if cost != "Colorless":
                            usable_types.add(cost)

        dead: list[CardDefinition] = []
        for card in deck:
            if card.is_pokemon and card.evolve_from and card.evolve_from not in pokemon_names:
                dead.append(card)
            elif card.is_energy and card.energy_provides:
                if not any(t in usable_types for t in card.energy_provides):
                    dead.append(card)
        return dead

    def _replace_dead_cards(
        self,
        deck: list[CardDefinition],
        target_size: int,
        protected_names: frozenset[str],
        warnings: list[str],
    ) -> None:
        """Remove structurally dead cards and refill the deck with live alternatives.

        Cards named in protected_names (user-supplied partial deck) are never removed.
        Dead card IDs are temporarily excluded during refill to prevent re-addition.
        Up to 5 passes are made to handle cascading dead-card situations.
        """
        replaced: list[str] = []
        for _ in range(5):
            dead = [c for c in self._find_dead_cards(deck) if c.name not in protected_names]
            if not dead:
                break
            dead_ids = {c.tcgdex_id for c in dead if c.tcgdex_id}
            for dead_card in dead:
                if dead_card in deck:
                    deck.remove(dead_card)
                    replaced.append(dead_card.name)
            orig_excluded = self._excluded_ids
            self._excluded_ids = self._excluded_ids | dead_ids
            self._fill_any(deck, target_size)
            self._excluded_ids = orig_excluded
        if replaced:
            warnings.append(
                "Replaced dead card(s) with better alternatives: "
                + ", ".join(dict.fromkeys(replaced))
            )

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

    def _tag_card(self, card: CardDefinition) -> str:
        """Return the primary role of this card for deck composition purposes.

        Roles:
          attacker     — ≥120 base damage on any attack
          setup        — Stage-1/2 Pokémon; search/draw Trainers
          energy_accel — Trainers/abilities that attach extra energy
          disruption   — Force-switch, hand reset
          healing      — HP recovery
          tech         — Situational counters
          energy       — All energy cards
        """
        if card.is_energy:
            return "energy"
        if card.is_trainer:
            return self._tag_trainer(card)
        # Pokémon: attacker check comes first regardless of stage
        max_damage = max((_damage_value(a.damage) for a in card.attacks), default=0)
        if max_damage >= 120:
            return "attacker"
        # Evolution cards with modest damage → setup
        if card.stage.lower().startswith("stage"):
            return "setup"
        # Check Pokémon abilities for energy acceleration
        for ability in card.abilities:
            if _is_energy_accel_ability(ability):
                return "energy_accel"
        return "tech"

    def _tag_trainer(self, card: CardDefinition) -> str:
        name = card.name.lower()
        if any(kw in name for kw in _ENERGY_ACCEL_TRAINER_KEYWORDS):
            return "energy_accel"
        if any(kw in name for kw in _DISRUPTION_TRAINER_KEYWORDS):
            return "disruption"
        if any(kw in name for kw in _HEALING_TRAINER_KEYWORDS):
            return "healing"
        if any(kw in name for kw in _SETUP_TRAINER_KEYWORDS):
            return "setup"
        if card.subcategory.lower() == "supporter":
            return "setup"
        return "tech"

    def _energy_curve_for_deck(self, deck: list[CardDefinition]) -> Counter[str]:
        """Count non-Colorless attack-cost requirements across all attacker-tagged cards.

        Used to determine which Basic Energy type(s) the deck actually needs.
        """
        counts: Counter[str] = Counter()
        for card in deck:
            if self._tag_card(card) == "attacker":
                for attack in card.attacks:
                    for cost in attack.cost:
                        if cost != "Colorless":
                            counts[cost] += 1
        return counts

    def _deck_energy_preferences(self, deck: list[CardDefinition]) -> Counter[str]:
        prefs: Counter[str] = Counter()
        for card in deck:
            # Weight attacker type/cost preferences 3× over other Pokémon
            weight = 3 if self._tag_card(card) == "attacker" else 1
            for t in card.types:
                prefs[t] += weight
            for attack in card.attacks:
                for cost in attack.cost:
                    if cost != "Colorless":
                        prefs[cost] += weight
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


def _is_draw_supporter(card: CardDefinition) -> bool:
    """Return True if this card is a draw/shuffle Supporter."""
    return (
        card.is_trainer
        and card.subcategory.lower() == "supporter"
        and any(kw in card.name.lower() for kw in _DRAW_SUPPORTER_KEYWORDS)
    )


def _is_search_item(card: CardDefinition) -> bool:
    """Return True if this card is a search Item (i.e. a Ball)."""
    return (
        card.is_trainer
        and card.subcategory.lower() in {"item", ""}
        and "ball" in card.name.lower()
    )


def _is_energy_accel_ability(ability) -> bool:
    """Return True if a Pokémon ability accelerates energy attachment."""
    effect = ability.effect.lower()
    return (
        "attach" in effect
        and "energy" in effect
        and any(kw in effect for kw in (
            "from your hand",
            "from your discard",
            "from your deck",
            "as many",
        ))
    )


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
