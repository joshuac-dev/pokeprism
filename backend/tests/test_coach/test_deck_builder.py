from __future__ import annotations

from collections import Counter

import pytest

from app.cards.models import AbilityDef, AttackDef, CardDefinition
from app.coach.deck_builder import (
    ARCHETYPE_TEMPLATES,
    DECK_SIZE,
    DeckBuildError,
    DeckBuilder,
    _is_draw_supporter,
    _is_search_item,
)


def _pokemon(
    tcgdex_id: str,
    name: str,
    *,
    hp: int = 80,
    stage: str = "Basic",
    evolve_from: str | None = None,
    types: list[str] | None = None,
    damage: str = "60",
) -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name=name,
        set_abbrev=tcgdex_id.rsplit("-", 1)[0],
        set_number=tcgdex_id.rsplit("-", 1)[1],
        category="Pokemon",
        stage=stage,
        hp=hp,
        evolve_from=evolve_from,
        types=types or ["Psychic"],
        attacks=[AttackDef(name="Hit", cost=types or ["Psychic"], damage=damage)],
    )


def _trainer(tcgdex_id: str, name: str, subtype: str = "Item") -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name=name,
        set_abbrev=tcgdex_id.rsplit("-", 1)[0],
        set_number=tcgdex_id.rsplit("-", 1)[1],
        category="Trainer",
        subcategory=subtype,
    )


def _energy(tcgdex_id: str, name: str, energy_type: str = "Psychic") -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name=name,
        set_abbrev=tcgdex_id.rsplit("-", 1)[0],
        set_number=tcgdex_id.rsplit("-", 1)[1],
        category="Energy",
        subcategory="Basic",
        energy_provides=[energy_type],
    )


def _pool() -> list[CardDefinition]:
    cards: list[CardDefinition] = [
        _pokemon("tst-001", "Dreepy", hp=70, types=["Psychic"], damage="30"),
        _pokemon("tst-002", "Drakloak", hp=90, stage="Stage 1", evolve_from="Dreepy", damage="70"),
        _pokemon("tst-003", "Dragapult ex", hp=230, stage="ex", evolve_from="Drakloak", damage="200"),
        _pokemon("tst-004", "Munkidori", hp=110, types=["Darkness"], damage="90"),
        _pokemon("tst-005", "Fezandipiti ex", hp=210, stage="ex", damage="160"),
        _energy("mee-005", "Psychic Energy", "Psychic"),
        _energy("mee-007", "Darkness Energy", "Darkness"),
    ]
    for i, name in enumerate(
        [
            "Ultra Ball", "Rare Candy", "Boss's Orders", "Nest Ball",
            "Iono", "Switch", "Energy Search", "Night Stretcher",
            "Buddy-Buddy Poffin", "Prime Catcher", "Professor's Research",
            "Super Rod",
        ],
        start=101,
    ):
        cards.append(_trainer(f"trn-{i}", name, "Supporter" if name in {"Iono", "Boss's Orders", "Professor's Research"} else "Item"))
    return cards


def test_complete_deck_preserves_partial_and_fills_to_legal_size():
    pool = _pool()
    partial = [pool[0]] * 4 + [pool[1]] * 2 + [pool[2]] * 2
    result = DeckBuilder(pool, rng_seed=123).complete_deck(partial)

    assert len(result.deck) == DECK_SIZE
    assert result.metadata["mode"] == "partial"
    assert result.metadata["cards_preserved"] == [c.tcgdex_id for c in partial]
    assert not DeckBuilder(pool).validate_deck(result.deck)


def test_complete_deck_rejects_banned_card():
    pool = _pool()
    builder = DeckBuilder(pool, excluded_ids=["tst-001"])

    with pytest.raises(DeckBuildError, match="excluded cards"):
        builder.complete_deck([pool[0]])


def test_complete_deck_rejects_excess_non_energy_copies():
    pool = _pool()
    partial = [pool[0]] * 5

    with pytest.raises(DeckBuildError, match="Too many copies"):
        DeckBuilder(pool).complete_deck(partial)


def test_complete_deck_rejects_unknown_card():
    pool = _pool()
    unknown = _pokemon("bad-999", "Unknownmon")

    with pytest.raises(DeckBuildError, match="outside available pool"):
        DeckBuilder(pool).complete_deck([unknown])


def test_complete_deck_is_deterministic_with_seed():
    pool = _pool()
    partial = [pool[0]] * 2

    first = DeckBuilder(pool, rng_seed=7).complete_deck(partial).deck_text
    second = DeckBuilder(pool, rng_seed=7).complete_deck(partial).deck_text

    assert first == second


def test_build_from_scratch_creates_valid_deck_with_core_metadata():
    pool = _pool()
    result = DeckBuilder(pool, rng_seed=1).build_from_scratch(build_around_ids=["tst-003"])

    assert len(result.deck) == DECK_SIZE
    assert "tst-003" in result.metadata["core_cards"]
    assert not DeckBuilder(pool).validate_deck(result.deck)


def test_build_from_scratch_fails_without_basic_pokemon():
    pool = [_trainer("trn-200", "Ultra Ball"), _energy("mee-005", "Psychic Energy")]

    with pytest.raises(DeckBuildError, match="no Basic Pokémon"):
        DeckBuilder(pool).build_from_scratch()


def test_build_from_scratch_respects_exclusions():
    pool = _pool()
    result = DeckBuilder(pool, excluded_ids=["tst-003"], rng_seed=2).build_from_scratch()

    assert "tst-003" not in [c.tcgdex_id for c in result.deck]
    assert not DeckBuilder(pool, excluded_ids=["tst-003"]).validate_deck(result.deck)


# ---------------------------------------------------------------------------
# Phase 1 — Role tagging
# ---------------------------------------------------------------------------

def _big_attacker(tcgdex_id: str = "tst-010", name: str = "Attacker ex",
                   stage: str = "ex", evolve_from: str | None = None,
                   types: list[str] | None = None) -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id, name=name,
        set_abbrev="TST", set_number="010",
        category="Pokemon", stage=stage,
        hp=250, types=types or ["Fire"],
        evolve_from=evolve_from,
        attacks=[AttackDef(name="Big Hit", cost=["Fire", "Fire", "Colorless"], damage="200")],
    )


class TestTagCard:
    def _builder(self) -> DeckBuilder:
        return DeckBuilder(_pool())

    def test_high_damage_basic_ex_is_attacker(self):
        assert self._builder()._tag_card(_big_attacker()) == "attacker"

    def test_stage2_ex_with_high_damage_is_attacker(self):
        card = _big_attacker(stage="Stage 2", evolve_from="Drakloak")
        assert self._builder()._tag_card(card) == "attacker"

    def test_stage1_low_damage_is_setup(self):
        card = _pokemon("tst-002", "Drakloak", hp=90, stage="Stage 1",
                        evolve_from="Dreepy", damage="70")
        assert self._builder()._tag_card(card) == "setup"

    def test_stage2_low_damage_is_setup(self):
        card = _pokemon("tst-006", "Dusknoir", hp=130, stage="Stage 2",
                        evolve_from="Dusclops", damage="30")
        assert self._builder()._tag_card(card) == "setup"

    def test_basic_low_damage_is_tech(self):
        card = _pokemon("tst-001", "Dreepy", hp=70, damage="30")
        assert self._builder()._tag_card(card) == "tech"

    def test_basic_120_damage_boundary_is_attacker(self):
        card = _pokemon("tst-007", "Boundary mon", hp=120, damage="120")
        assert self._builder()._tag_card(card) == "attacker"

    def test_ball_item_is_setup(self):
        assert self._builder()._tag_card(_trainer("trn-101", "Ultra Ball")) == "setup"

    def test_nest_ball_is_setup(self):
        assert self._builder()._tag_card(_trainer("trn-104", "Nest Ball")) == "setup"

    def test_rare_candy_is_setup(self):
        assert self._builder()._tag_card(_trainer("trn-102", "Rare Candy")) == "setup"

    def test_boss_orders_is_disruption(self):
        assert self._builder()._tag_card(_trainer("trn-103", "Boss's Orders", "Supporter")) == "disruption"

    def test_iono_is_disruption(self):
        assert self._builder()._tag_card(_trainer("trn-105", "Iono", "Supporter")) == "disruption"

    def test_pokemon_catcher_is_disruption(self):
        assert self._builder()._tag_card(_trainer("trn-106", "Pokémon Catcher")) == "disruption"

    def test_potion_is_healing(self):
        assert self._builder()._tag_card(_trainer("trn-120", "Hyper Potion")) == "healing"

    def test_energy_retrieval_is_energy_accel(self):
        assert self._builder()._tag_card(_trainer("trn-130", "Energy Retrieval")) == "energy_accel"

    def test_raihan_is_energy_accel(self):
        assert self._builder()._tag_card(_trainer("trn-131", "Raihan", "Supporter")) == "energy_accel"

    def test_unknown_supporter_defaults_to_setup(self):
        assert self._builder()._tag_card(_trainer("trn-200", "Mystery Trainer", "Supporter")) == "setup"

    def test_unknown_item_defaults_to_tech(self):
        assert self._builder()._tag_card(_trainer("trn-201", "Mystery Item")) == "tech"

    def test_energy_card_is_energy(self):
        assert self._builder()._tag_card(_energy("mee-005", "Psychic Energy")) == "energy"

    def test_pokemon_energy_accel_ability_tagged(self):
        card = CardDefinition(
            tcgdex_id="tst-emb", name="Emboar", set_abbrev="TST", set_number="emb",
            category="Pokemon", stage="Stage 2", hp=150,
            abilities=[AbilityDef(
                name="Inferno Fandango",
                type="Ability",
                effect="Once during your turn, you may attach as many Fire Energy cards "
                       "from your hand to your Pokémon as you like.",
            )],
            attacks=[AttackDef(name="Flare Blitz", cost=["Fire", "Fire"], damage="100")],
        )
        assert self._builder()._tag_card(card) == "setup"  # Stage 2 low damage → setup wins

    def test_basic_energy_accel_ability_tagged(self):
        """A Basic with <120 damage but an energy-accel ability is tagged energy_accel."""
        card = CardDefinition(
            tcgdex_id="tst-batt", name="Battery Basic", set_abbrev="TST", set_number="batt",
            category="Pokemon", stage="Basic", hp=80,
            abilities=[AbilityDef(
                name="Power Plant",
                type="Ability",
                effect="Once during your turn, you may attach as many Lightning Energy cards "
                       "from your hand to your Pokémon as you like.",
            )],
            attacks=[AttackDef(name="Zap", cost=["Lightning"], damage="30")],
        )
        assert self._builder()._tag_card(card) == "energy_accel"


# ---------------------------------------------------------------------------
# Phase 1 — Energy curve
# ---------------------------------------------------------------------------

class TestEnergyCurve:
    def _builder(self) -> DeckBuilder:
        return DeckBuilder(_pool())

    def test_attacker_costs_counted(self):
        attacker = CardDefinition(
            tcgdex_id="tst-fire", name="Charizard ex",
            set_abbrev="TST", set_number="fire",
            category="Pokemon", stage="ex",
            hp=330, types=["Fire"],
            attacks=[AttackDef(name="Blaze", cost=["Fire", "Fire", "Colorless"], damage="200")],
        )
        curve = self._builder()._energy_curve_for_deck([attacker])
        assert curve["Fire"] == 2
        assert "Colorless" not in curve

    def test_non_attacker_costs_not_counted(self):
        setup_card = _pokemon("tst-002", "Drakloak", hp=90, stage="Stage 1",
                               evolve_from="Dreepy", damage="70")
        assert self._builder()._energy_curve_for_deck([setup_card]) == Counter()

    def test_empty_deck_returns_empty_counter(self):
        assert self._builder()._energy_curve_for_deck([]) == Counter()

    def test_multiple_attackers_summed(self):
        fire_atk = CardDefinition(
            tcgdex_id="tst-f1", name="Fire Mon", set_abbrev="TST", set_number="f1",
            category="Pokemon", stage="Basic", hp=120, types=["Fire"],
            attacks=[AttackDef(name="Hit", cost=["Fire", "Colorless"], damage="120")],
        )
        psychic_atk = CardDefinition(
            tcgdex_id="tst-p1", name="Psychic Mon", set_abbrev="TST", set_number="p1",
            category="Pokemon", stage="Basic", hp=120, types=["Psychic"],
            attacks=[AttackDef(name="Hit", cost=["Psychic", "Psychic"], damage="130")],
        )
        curve = self._builder()._energy_curve_for_deck([fire_atk, psychic_atk])
        assert curve["Fire"] == 1
        assert curve["Psychic"] == 2

    def test_energy_curve_drives_energy_selection(self):
        """build_from_scratch with a Fire attacker should prefer Fire Energy."""
        fire_attacker = CardDefinition(
            tcgdex_id="tst-fire", name="Charizard ex",
            set_abbrev="TST", set_number="fire",
            category="Pokemon", stage="ex",
            hp=330, types=["Fire"],
            attacks=[AttackDef(name="Blaze", cost=["Fire", "Fire", "Colorless"], damage="200")],
        )
        charmander = CardDefinition(
            tcgdex_id="tst-char", name="Charmander",
            set_abbrev="TST", set_number="char",
            category="Pokemon", stage="Basic",
            hp=70, types=["Fire"],
            attacks=[AttackDef(name="Ember", cost=["Fire"], damage="30")],
        )
        pool = [
            fire_attacker,
            charmander,
            _energy("mee-001", "Fire Energy", "Fire"),
            _energy("mee-005", "Psychic Energy", "Psychic"),
        ] + [_trainer(f"trn-{i}", f"Trainer{i}") for i in range(100, 155)]

        result = DeckBuilder(pool, rng_seed=1).build_from_scratch(
            build_around_ids=["tst-fire"]
        )
        energy_cards = [c for c in result.deck if c.is_energy]
        fire_count = sum(1 for c in energy_cards if "Fire" in c.energy_provides)
        psychic_count = sum(1 for c in energy_cards if "Psychic" in c.energy_provides)
        assert fire_count > psychic_count


# ---------------------------------------------------------------------------
# Phase 2 — Archetype templates
# ---------------------------------------------------------------------------

class TestArchetypeTemplates:
    def test_all_known_archetypes_defined(self):
        for name in ("aggro", "evolution-ramp", "control", "spread", "stall"):
            assert name in ARCHETYPE_TEMPLATES

    def test_aggro_builds_fewer_pokemon_than_default(self):
        pool = _pool()
        result = DeckBuilder(pool, rng_seed=1).build_from_scratch(target_archetype="aggro")
        n_pokemon = sum(1 for c in result.deck if c.is_pokemon)
        t = ARCHETYPE_TEMPLATES["aggro"]
        assert t["pokemon_min"] <= n_pokemon <= t["pokemon_max"] + 2  # +2 tolerance for core cards

    def test_evolution_ramp_builds_more_pokemon_than_aggro(self):
        pool = _pool()
        aggro = DeckBuilder(pool, rng_seed=1).build_from_scratch(target_archetype="aggro")
        evo = DeckBuilder(pool, rng_seed=1).build_from_scratch(target_archetype="evolution-ramp")
        n_aggro = sum(1 for c in aggro.deck if c.is_pokemon)
        n_evo = sum(1 for c in evo.deck if c.is_pokemon)
        assert n_evo > n_aggro

    def test_archetype_deck_is_exactly_60_cards(self):
        pool = _pool()
        for archetype in ARCHETYPE_TEMPLATES:
            result = DeckBuilder(pool, rng_seed=1).build_from_scratch(target_archetype=archetype)
            assert len(result.deck) == DECK_SIZE, f"{archetype}: expected 60 cards"

    def test_archetype_deck_passes_validate(self):
        pool = _pool()
        for archetype in ARCHETYPE_TEMPLATES:
            result = DeckBuilder(pool, rng_seed=1).build_from_scratch(target_archetype=archetype)
            errors = DeckBuilder(pool).validate_deck(result.deck)
            assert not errors, f"{archetype} deck failed validation: {errors}"

    def test_unknown_archetype_uses_default_and_warns(self):
        pool = _pool()
        result = DeckBuilder(pool, rng_seed=1).build_from_scratch(target_archetype="banana")
        assert len(result.deck) == DECK_SIZE
        assert any("Unknown archetype" in w for w in result.metadata["warnings"])

    def test_desired_counts_from_archetype_sums_to_60(self):
        builder = DeckBuilder(_pool())
        for archetype in ARCHETYPE_TEMPLATES:
            counts = builder._desired_counts_from_archetype(archetype, [], DECK_SIZE)
            total = counts["pokemon"] + counts["trainer"] + counts["energy"]
            assert total == DECK_SIZE, f"{archetype}: {counts} does not sum to 60"

    def test_control_archetype_more_trainers_than_evolution_ramp(self):
        pool = _pool()
        ctrl = DeckBuilder(pool, rng_seed=1).build_from_scratch(target_archetype="control")
        evo = DeckBuilder(pool, rng_seed=1).build_from_scratch(target_archetype="evolution-ramp")
        n_ctrl_trainers = sum(1 for c in ctrl.deck if c.is_trainer)
        n_evo_trainers = sum(1 for c in evo.deck if c.is_trainer)
        assert n_ctrl_trainers > n_evo_trainers


# ---------------------------------------------------------------------------
# Phase 4 — Opening-hand staple validation
# ---------------------------------------------------------------------------

class TestOpeningHandValidation:
    def _few_basics_pool(self) -> list[CardDefinition]:
        """Pool with only 2 basics — not enough to satisfy ≥4 check."""
        return [
            _pokemon("tst-001", "Dreepy", hp=70, damage="30"),
            _pokemon("tst-002", "Drakloak", hp=90, stage="Stage 1", evolve_from="Dreepy", damage="70"),
            _energy("mee-005", "Psychic Energy"),
        ] + [_trainer(f"trn-{i}", f"Item{i}") for i in range(100, 160)]

    def test_validate_deck_error_on_fewer_than_4_basics(self):
        pool = self._few_basics_pool()
        deck = [pool[0]] * 2 + [pool[1]] * 4 + [pool[2]] * 4  # only 2 basics (Dreepy ×2)
        # Pad to 60 with trainers
        deck += [pool[3]] * (DECK_SIZE - len(deck))
        builder = DeckBuilder(pool)
        errors = builder.validate_deck(deck)
        assert any("Basic Pokémon" in e and "4" in e for e in errors)

    def test_validate_deck_ok_with_4_or_more_basics(self):
        pool = _pool()
        result = DeckBuilder(pool, rng_seed=1).build_from_scratch()
        errors = DeckBuilder(pool).validate_deck(result.deck)
        assert not any("Basic Pokémon" in e and "4" in e for e in errors)

    def test_validate_deck_errors_on_stadium_over_2_copies(self):
        pool = _pool() + [
            _trainer("std-001", "Lost City", "Stadium"),
        ]
        # Build a deck and manually inject 3 stadiums
        result = DeckBuilder(pool, rng_seed=1).build_from_scratch()
        deck = list(result.deck)
        # Replace last 3 non-stadium cards with stadium copies
        stadium_card = next(c for c in pool if c.subcategory.lower() == "stadium")
        replacements = 0
        for i in range(len(deck) - 1, -1, -1):
            if deck[i].subcategory.lower() != "stadium" and replacements < 3:
                deck[i] = stadium_card
                replacements += 1
        errors = DeckBuilder(pool).validate_deck(deck)
        assert any("Stadium" in e for e in errors)

    def test_fill_deck_adds_draw_supporter_when_missing(self):
        """build_from_scratch with a pool that has a draw Supporter includes it."""
        pool = [
            _pokemon("tst-001", "Dreepy", hp=70, damage="30"),
            _trainer("trn-105", "Iono", "Supporter"),
            _energy("mee-005", "Psychic Energy"),
        ] + [_trainer(f"trn-{i}", f"Item{i}") for i in range(200, 255)]

        result = DeckBuilder(pool, rng_seed=1).build_from_scratch()
        draw_supporters = [c for c in result.deck if _is_draw_supporter(c)]
        assert len(draw_supporters) >= 1

    def test_fill_deck_adds_search_item_when_missing(self):
        """build_from_scratch with a pool that has a Ball includes it."""
        pool = [
            _pokemon("tst-001", "Dreepy", hp=70, damage="30"),
            _trainer("trn-101", "Nest Ball"),
            _trainer("trn-106", "Iono", "Supporter"),
            _energy("mee-005", "Psychic Energy"),
        ] + [_trainer(f"trn-{i}", f"Item{i}") for i in range(200, 255)]

        result = DeckBuilder(pool, rng_seed=1).build_from_scratch()
        search_items = [c for c in result.deck if _is_search_item(c)]
        assert len(search_items) >= 1

    def test_fill_deck_warns_when_no_draw_supporter_in_pool(self):
        """If pool has no draw Supporter, a warning is added to metadata."""
        pool = [
            _pokemon("tst-001", "Dreepy", hp=70, damage="30"),
            _energy("mee-005", "Psychic Energy"),
        ] + [_trainer(f"trn-{i}", f"Item{i}") for i in range(200, 255)]

        result = DeckBuilder(pool, rng_seed=1).build_from_scratch()
        assert any("draw Supporter" in w for w in result.metadata["warnings"])

    def test_trainer_role_counts_basic(self):
        pool = _pool()
        result = DeckBuilder(pool, rng_seed=1).build_from_scratch()
        counts = DeckBuilder(pool)._trainer_role_counts(result.deck)
        # The pool has Boss's Orders (disruption), Iono (disruption),
        # Ultra Ball + Nest Ball (setup), Rare Candy (setup), etc.
        assert sum(counts.values()) == sum(1 for c in result.deck if c.is_trainer)
        assert "setup" in counts or "disruption" in counts

    def test_is_draw_supporter_matches_known_cards(self):
        assert _is_draw_supporter(_trainer("trn-105", "Iono", "Supporter"))
        assert _is_draw_supporter(_trainer("trn-111", "Professor's Research", "Supporter"))
        assert not _is_draw_supporter(_trainer("trn-103", "Boss's Orders", "Supporter"))
        assert not _is_draw_supporter(_trainer("trn-101", "Ultra Ball"))  # Item, not Supporter

    def test_is_search_item_matches_known_cards(self):
        assert _is_search_item(_trainer("trn-101", "Ultra Ball"))
        assert _is_search_item(_trainer("trn-104", "Nest Ball"))
        assert not _is_search_item(_trainer("trn-103", "Boss's Orders", "Supporter"))
        assert not _is_search_item(_trainer("trn-105", "Iono", "Supporter"))


# ---------------------------------------------------------------------------
# Phase 5 — Dead-card detection and replacement
# ---------------------------------------------------------------------------

class TestDeadCardDetection:
    def _builder(self) -> DeckBuilder:
        return DeckBuilder(_pool())

    def test_empty_deck_has_no_dead_cards(self):
        assert self._builder()._find_dead_cards([]) == []

    def test_orphaned_stage1_evolution_is_dead(self):
        """A Stage-1 Pokémon whose evolve_from name is absent is dead."""
        haunter = _pokemon("tst-h", "Haunter", hp=80, stage="Stage 1", evolve_from="Gastly")
        dreepy = _pokemon("tst-001", "Dreepy", hp=70, damage="30")
        dead = self._builder()._find_dead_cards([haunter, dreepy])
        assert haunter in dead
        assert dreepy not in dead

    def test_evolution_with_pre_evo_present_not_dead(self):
        dreepy = _pokemon("tst-001", "Dreepy", hp=70, damage="30")
        drakloak = _pokemon("tst-002", "Drakloak", hp=90, stage="Stage 1",
                             evolve_from="Dreepy", damage="70")
        assert self._builder()._find_dead_cards([dreepy, drakloak]) == []

    def test_basic_pokemon_without_evolve_from_never_dead(self):
        dreepy = _pokemon("tst-001", "Dreepy", hp=70, damage="30")  # evolve_from=None
        assert self._builder()._find_dead_cards([dreepy]) == []

    def test_energy_providing_unused_type_is_dead(self):
        fire_mon = _pokemon("tst-f", "Tepig", hp=60, types=["Fire"], damage="30")
        psychic_energy = _energy("mee-p", "Psychic Energy", "Psychic")
        dead = self._builder()._find_dead_cards([fire_mon, psychic_energy])
        assert psychic_energy in dead

    def test_energy_matching_deck_type_not_dead(self):
        psychic_mon = _pokemon("tst-001", "Dreepy", hp=70, types=["Psychic"], damage="30")
        psychic_energy = _energy("mee-005", "Psychic Energy", "Psychic")
        assert self._builder()._find_dead_cards([psychic_mon, psychic_energy]) == []

    def test_energy_usable_via_attack_cost_not_dead(self):
        """Energy is live if any Pokémon's attack costs that type, even if type differs."""
        # Mewtwo-ish: Water type but attack costs Fire
        water_mon = CardDefinition(
            tcgdex_id="tst-wm", name="WaterFire", set_abbrev="TST", set_number="wm",
            category="Pokemon", stage="Basic", hp=80, types=["Water"],
            attacks=[AttackDef(name="Flame", cost=["Fire"], damage="60")],
        )
        fire_energy = _energy("mee-f", "Fire Energy", "Fire")
        assert self._builder()._find_dead_cards([water_mon, fire_energy]) == []

    def test_energy_without_energy_provides_never_dead(self):
        """Special energies with empty energy_provides are never flagged as dead."""
        fire_mon = _pokemon("tst-f", "Tepig", hp=60, types=["Fire"], damage="30")
        special = CardDefinition(
            tcgdex_id="spe-001", name="Double Colorless Energy",
            set_abbrev="SPE", set_number="001",
            category="Energy", subcategory="Special",
            energy_provides=[],
        )
        assert self._builder()._find_dead_cards([fire_mon, special]) == []

    def test_built_deck_has_no_dead_evolutions(self):
        """Every evolution in a built deck must have its pre-evolution present."""
        pool = _pool()
        result = DeckBuilder(pool, rng_seed=1).build_from_scratch()
        dead = DeckBuilder(pool)._find_dead_cards(result.deck)
        dead_evos = [c for c in dead if c.is_pokemon]
        assert not dead_evos, f"Dead evolutions in built deck: {[c.name for c in dead_evos]}"

    def test_replace_dead_cards_removes_orphan_and_warns(self):
        """_replace_dead_cards removes orphaned Stage-1 cards and adds a warning."""
        pool = _pool()
        builder = DeckBuilder(pool, rng_seed=1)
        drakloak = next(c for c in pool if c.name == "Drakloak")
        psychic_energy = next(c for c in pool if c.name == "Psychic Energy")
        # Deck: 4 orphaned Drakloak (no Dreepy) + 56 Psychic Energy
        deck = [drakloak] * 4 + [psychic_energy] * 56
        warnings: list[str] = []
        builder._replace_dead_cards(deck, 60, frozenset(), warnings)
        assert all(c.name != "Drakloak" for c in deck)
        assert any("dead" in w.lower() for w in warnings)
        assert len(deck) == 60

    def test_complete_deck_preserves_partial_evolution_from_dead_removal(self):
        """User-supplied evolution cards in partial deck survive dead-card sweep."""
        pool = _pool()
        # MysteryEvo's pre-evo ("NonExistentBase") is absent from the entire pool.
        mystery_evo = _pokemon(
            "tst-mystery", "MysteryEvo",
            hp=100, stage="Stage 1", evolve_from="NonExistentBase", damage="80",
        )
        extended_pool = pool + [mystery_evo]
        partial = [mystery_evo] * 2

        result = DeckBuilder(extended_pool, rng_seed=1).complete_deck(partial)
        mystery_count = sum(1 for c in result.deck if c.name == "MysteryEvo")
        assert mystery_count >= 2, "User-supplied cards must survive dead-card replacement"
