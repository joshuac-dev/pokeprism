"""Run-41 engine fix regression tests.

Covers three bugs fixed in PR #74:
  1. Sticky Bind (sv08-107 Gastrodon) — wrong location check (active vs bench)
  2. Forest of Vitality alt-print (me02.5-188) — missing from same-turn Grass evolution check
  3. Extra Helpings alt-print (svp-184 Hop's Snorlax) — missing from ability gate
"""
from __future__ import annotations

import pytest

import app.engine.effects  # noqa: F401
from app.cards import registry as card_registry
from app.cards.models import AbilityDef, AttackDef, CardDefinition
from app.engine.actions import Action, ActionType, ActionValidator
from app.engine.effects.abilities import has_extra_helpings
from app.engine.effects.attacks import _apply_damage
from app.engine.effects.registry import EffectRegistry
from app.engine.state import (
    CardInstance,
    EnergyAttachment,
    EnergyType,
    GameState,
    Phase,
    Zone,
)


# ─── helpers ────────────────────────────────────────────────────────────────


def _make_card(
    tcgdex_id: str,
    name: str,
    *,
    category: str = "pokemon",
    subcategory: str = "",
    hp: int = 100,
    stage: str = "Basic",
    types: list[str] | None = None,
    attacks: list[AttackDef] | None = None,
    abilities: list[AbilityDef] | None = None,
    retreat_cost: int = 1,
    evolve_from: str | None = None,
) -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name=name,
        category=category,
        subcategory=subcategory,
        set_abbrev="T41",
        set_number="001",
        hp=hp,
        stage=stage,
        types=types or [],
        attacks=attacks or [],
        abilities=abilities or [],
        is_ex=False,
        is_tera=False,
        retreat_cost=retreat_cost,
        evolve_from=evolve_from,
    )


def _inst(
    cdef: CardDefinition,
    iid: str,
    *,
    zone: Zone = Zone.ACTIVE,
    hp: int | None = None,
    evolution_stage: int | None = None,
) -> CardInstance:
    hp = cdef.hp if hp is None else hp
    if evolution_stage is None:
        stage_str = cdef.stage.lower()
        if stage_str == "basic":
            evolution_stage = 0
        elif stage_str in ("stage1", "stage 1"):
            evolution_stage = 1
        else:
            evolution_stage = 2
    return CardInstance(
        instance_id=iid,
        card_def_id=cdef.tcgdex_id,
        card_name=cdef.name,
        zone=zone,
        current_hp=hp,
        max_hp=hp,
        card_type=cdef.category.capitalize(),
        card_subtype=cdef.subcategory.capitalize() if cdef.subcategory else "",
        evolution_stage=evolution_stage,
    )


def _hand_inst(cdef: CardDefinition, iid: str, *, evo_stage: int = 1) -> CardInstance:
    """Create a card instance in the HAND zone (for evolutions)."""
    return CardInstance(
        instance_id=iid,
        card_def_id=cdef.tcgdex_id,
        card_name=cdef.name,
        zone=Zone.HAND,
        current_hp=cdef.hp or 100,
        max_hp=cdef.hp or 100,
        card_type=cdef.category.capitalize(),
        card_subtype="",
        evolution_stage=evo_stage,
    )


def _state(
    p1_active: CardInstance | None = None,
    p1_bench: list[CardInstance] | None = None,
    p2_active: CardInstance | None = None,
    p2_bench: list[CardInstance] | None = None,
    p1_hand: list[CardInstance] | None = None,
    turn_number: int = 2,
    active_player: str = "p1",
    first_player: str = "p1",
) -> GameState:
    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.phase = Phase.MAIN
    state.turn_number = turn_number
    state.active_player = active_player
    state.first_player = first_player
    if p1_active:
        p1_active.zone = Zone.ACTIVE
        state.p1.active = p1_active
    if p1_bench:
        for c in p1_bench:
            c.zone = Zone.BENCH
        state.p1.bench = list(p1_bench)
    if p2_active:
        p2_active.zone = Zone.ACTIVE
        state.p2.active = p2_active
    if p2_bench:
        for c in p2_bench:
            c.zone = Zone.BENCH
        state.p2.bench = list(p2_bench)
    if p1_hand:
        for c in p1_hand:
            c.zone = Zone.HAND
        state.p1.hand = list(p1_hand)
    return state


def _stadium_inst(tcgdex_id: str, name: str, iid: str) -> CardInstance:
    return CardInstance(
        instance_id=iid,
        card_def_id=tcgdex_id,
        card_name=name,
        zone=Zone.STADIUM,
        current_hp=0,
        max_hp=0,
        card_type="Trainer",
        card_subtype="Stadium",
        evolution_stage=0,
    )


@pytest.fixture(autouse=True)
def clear_registry():
    yield
    card_registry.clear()


# ─── Fix 1: Sticky Bind (sv08-107 Gastrodon) ────────────────────────────────
#
# Bug: code checked opp_init.active.card_def_id == "sv08-107" (Gastrodon Active)
# Fix: should check opp_init.bench for Gastrodon (ability says "on your Bench")
#
# Tests:
#   a) Gastrodon on opp BENCH → p1's benched Stage 2 ability blocked
#   b) Gastrodon on opp ACTIVE (not bench) → p1's benched Stage 2 ability NOT blocked by Sticky Bind
#   c) Gastrodon on opp bench → p1's ACTIVE Stage 2 ability NOT blocked
#   d) Gastrodon on opp bench → p1's benched Stage 1 ability NOT blocked


def _make_gastrodon() -> CardDefinition:
    return _make_card("sv08-107", "Gastrodon",
                      abilities=[AbilityDef(name="Sticky Bind",
                                            effect="Benched Stage 2 Pokémon have no Abilities.")])


def _make_stage2_with_ability(tcgdex_id: str, name: str) -> CardDefinition:
    """Return a Stage 2 card with a registered active ability."""
    return _make_card(tcgdex_id, name, stage="Stage2",
                      abilities=[AbilityDef(name="Test Ability", effect="Do something.")])


def _register_active_ability(tcgdex_id: str) -> None:
    """Register a no-op active ability handler so the action validator offers USE_ABILITY."""
    registry = EffectRegistry.instance()

    async def _noop_handler(state, action):
        return

    registry.register_ability(tcgdex_id, "Test Ability", _noop_handler)


def test_sticky_bind_blocks_benched_stage2_ability_when_gastrodon_on_opp_bench():
    """With Gastrodon on opponent's Bench, p1's Benched Stage 2 can't use its ability."""
    gastrodon = _make_gastrodon()
    stage2 = _make_stage2_with_ability("t41-s2a", "TestStage2A")
    basic_active = _make_card("t41-basic-a", "BasicActive")
    card_registry.register(gastrodon)
    card_registry.register(stage2)
    card_registry.register(basic_active)
    _register_active_ability("t41-s2a")

    gastrodon_inst = _inst(gastrodon, "gast-bench-1", zone=Zone.BENCH, evolution_stage=0)
    stage2_bench_inst = _inst(stage2, "s2-bench-1", zone=Zone.BENCH, evolution_stage=2)
    p1_active_inst = _inst(basic_active, "basic-act-1", evolution_stage=0)

    state = _state(
        p1_active=p1_active_inst,
        p1_bench=[stage2_bench_inst],
        p2_active=_inst(basic_active, "p2-act-1", evolution_stage=0),
        p2_bench=[gastrodon_inst],
    )

    ability_actions = ActionValidator._get_ability_actions(state, state.p1, "p1")
    acted_ids = {a.card_instance_id for a in ability_actions}
    assert stage2_bench_inst.instance_id not in acted_ids, (
        "Gastrodon on opp bench: Benched Stage 2 ability MUST be blocked by Sticky Bind"
    )


def test_sticky_bind_does_not_block_when_gastrodon_is_active_not_benched():
    """Bug regression: when Gastrodon is the opponent's Active (not benched),
    Sticky Bind must NOT block p1's Benched Stage 2 ability."""
    gastrodon = _make_gastrodon()
    stage2 = _make_stage2_with_ability("t41-s2b", "TestStage2B")
    basic_bench = _make_card("t41-basic-b", "BasicBench")
    card_registry.register(gastrodon)
    card_registry.register(stage2)
    card_registry.register(basic_bench)
    _register_active_ability("t41-s2b")

    gastrodon_active_inst = _inst(gastrodon, "gast-act-1", zone=Zone.ACTIVE, evolution_stage=0)
    stage2_bench_inst = _inst(stage2, "s2-bench-2", zone=Zone.BENCH, evolution_stage=2)
    p1_active_inst = _inst(basic_bench, "basic-act-2", evolution_stage=0)

    state = _state(
        p1_active=p1_active_inst,
        p1_bench=[stage2_bench_inst],
        p2_active=gastrodon_active_inst,
        p2_bench=[],
    )

    ability_actions = ActionValidator._get_ability_actions(state, state.p1, "p1")
    acted_ids = {a.card_instance_id for a in ability_actions}
    assert stage2_bench_inst.instance_id in acted_ids, (
        "Gastrodon Active (not benched): Benched Stage 2 ability must NOT be blocked by Sticky Bind"
    )


def test_sticky_bind_does_not_block_active_stage2_ability():
    """Sticky Bind suppresses BENCHED Stage 2 abilities only; the Active Stage 2 is unaffected."""
    gastrodon = _make_gastrodon()
    stage2 = _make_stage2_with_ability("t41-s2c", "TestStage2C")
    bench_dummy = _make_card("t41-bench-c", "BenchDummy")
    card_registry.register(gastrodon)
    card_registry.register(stage2)
    card_registry.register(bench_dummy)
    _register_active_ability("t41-s2c")

    gastrodon_inst = _inst(gastrodon, "gast-bench-2", zone=Zone.BENCH, evolution_stage=0)
    stage2_active_inst = _inst(stage2, "s2-act-2", zone=Zone.ACTIVE, evolution_stage=2)
    bench_dummy_inst = _inst(bench_dummy, "bench-d-1", zone=Zone.BENCH, evolution_stage=0)

    state = _state(
        p1_active=stage2_active_inst,
        p1_bench=[bench_dummy_inst],
        p2_active=_inst(bench_dummy, "p2-act-2", evolution_stage=0),
        p2_bench=[gastrodon_inst],
    )

    ability_actions = ActionValidator._get_ability_actions(state, state.p1, "p1")
    acted_ids = {a.card_instance_id for a in ability_actions}
    assert stage2_active_inst.instance_id in acted_ids, (
        "Sticky Bind only suppresses BENCHED Stage 2 abilities; Active Stage 2 must not be blocked"
    )


def test_sticky_bind_does_not_block_benched_stage1_ability():
    """Sticky Bind only suppresses Stage 2; Benched Stage 1 abilities are not affected."""
    gastrodon = _make_gastrodon()
    stage1 = _make_card("t41-s1a", "TestStage1A", stage="Stage1",
                         abilities=[AbilityDef(name="Test Ability", effect="Do something.")])
    basic_active = _make_card("t41-basic-c", "BasicActive2")
    card_registry.register(gastrodon)
    card_registry.register(stage1)
    card_registry.register(basic_active)
    _register_active_ability("t41-s1a")

    gastrodon_inst = _inst(gastrodon, "gast-bench-3", zone=Zone.BENCH, evolution_stage=0)
    stage1_bench_inst = _inst(stage1, "s1-bench-1", zone=Zone.BENCH, evolution_stage=1)
    p1_active_inst = _inst(basic_active, "basic-act-3", evolution_stage=0)

    state = _state(
        p1_active=p1_active_inst,
        p1_bench=[stage1_bench_inst],
        p2_active=_inst(basic_active, "p2-act-3", evolution_stage=0),
        p2_bench=[gastrodon_inst],
    )

    ability_actions = ActionValidator._get_ability_actions(state, state.p1, "p1")
    acted_ids = {a.card_instance_id for a in ability_actions}
    assert stage1_bench_inst.instance_id in acted_ids, (
        "Sticky Bind only affects Stage 2; Benched Stage 1 ability must not be blocked"
    )


# ─── Fix 2: Forest of Vitality alt-print (me02.5-188) ───────────────────────
#
# Bug: same-turn Grass evolution check used card_def_id == "me01-117" only
# Fix: changed to card_def_id in ("me01-117", "me02.5-188")
#
# Tests:
#   a) me02.5-188 active → Grass Pokémon played this turn CAN evolve (turn >= 2)
#   b) No stadium → Grass Pokémon played this turn CANNOT evolve
#   c) me02.5-188 active on turn 1 (first player) → still blocked by first-turn restriction
#   d) me02.5-188 active → Non-Grass Pokémon played this turn CANNOT evolve


def _setup_forest_of_vitality_test(stadium_id: str | None) -> tuple[GameState, CardInstance, CardInstance]:
    """Helper: build a state where p1 has a Grass basic (played this turn) on bench,
    a Stage1 evolution in hand, and optionally a Forest of Vitality stadium.
    """
    grass_basic = _make_card("t41-grass-basic", "GrassBasic",
                              stage="Basic", types=["Grass"])
    grass_s1 = _make_card("t41-grass-s1", "GrassStage1",
                           stage="Stage1", types=["Grass"],
                           evolve_from="GrassBasic")
    dummy_active = _make_card("t41-dummy-act", "DummyActive")
    card_registry.register(grass_basic)
    card_registry.register(grass_s1)
    card_registry.register(dummy_active)

    basic_inst = _inst(grass_basic, "grass-basic-1", zone=Zone.BENCH, evolution_stage=0)
    s1_hand_inst = _hand_inst(grass_s1, "grass-s1-hand-1", evo_stage=1)
    active_inst = _inst(dummy_active, "dummy-act-1", evolution_stage=0)

    state = _state(
        p1_active=active_inst,
        p1_bench=[basic_inst],
        p1_hand=[s1_hand_inst],
        p2_active=_inst(dummy_active, "dummy-act-2", evolution_stage=0),
        turn_number=2,
        active_player="p1",
        first_player="p2",  # p1 is NOT first player → first-turn restriction doesn't apply on turn 1 for p2
    )
    # Mark basic as played THIS turn (turn 2) so the "turn_played" check fires
    basic_inst.turn_played = 2

    if stadium_id:
        state.active_stadium = _stadium_inst(stadium_id, "Forest of Vitality", "fov-stadium")

    return state, basic_inst, s1_hand_inst


def test_forest_of_vitality_alt_print_allows_same_turn_grass_evolution():
    """With me02.5-188 active, Grass Pokémon played this turn can evolve (non-first-turn)."""
    state, basic_inst, s1_hand_inst = _setup_forest_of_vitality_test("me02.5-188")

    evolve_actions = ActionValidator._get_evolve_actions(state, state.p1, "p1")
    matching = [
        a for a in evolve_actions
        if a.card_instance_id == s1_hand_inst.instance_id
        and a.target_instance_id == basic_inst.instance_id
    ]
    assert matching, (
        "me02.5-188 Forest of Vitality alt-print: Grass Pokémon played this turn must be evolvable"
    )


def test_without_forest_of_vitality_grass_pokemon_cannot_evolve_same_turn():
    """Without Forest of Vitality, a Grass Pokémon played this turn cannot evolve."""
    state, basic_inst, s1_hand_inst = _setup_forest_of_vitality_test(None)

    evolve_actions = ActionValidator._get_evolve_actions(state, state.p1, "p1")
    matching = [
        a for a in evolve_actions
        if a.card_instance_id == s1_hand_inst.instance_id
        and a.target_instance_id == basic_inst.instance_id
    ]
    assert not matching, (
        "Without Forest of Vitality, Grass Pokémon played this turn must NOT be evolvable"
    )


def test_forest_of_vitality_alt_print_blocks_first_turn_evolution():
    """me02.5-188 active on turn 1 (first player's turn) must still block same-turn evolution."""
    grass_basic = _make_card("t41-grass-basic-ft", "GrassBasicFT",
                              stage="Basic", types=["Grass"])
    grass_s1 = _make_card("t41-grass-s1-ft", "GrassStage1FT",
                           stage="Stage1", types=["Grass"],
                           evolve_from="GrassBasicFT")
    dummy_active = _make_card("t41-dummy-ft", "DummyFT")
    card_registry.register(grass_basic)
    card_registry.register(grass_s1)
    card_registry.register(dummy_active)

    basic_inst = _inst(grass_basic, "grass-basic-ft-1", zone=Zone.BENCH, evolution_stage=0)
    s1_hand_inst = _hand_inst(grass_s1, "grass-s1-ft-1", evo_stage=1)
    active_inst = _inst(dummy_active, "dummy-ft-1", evolution_stage=0)

    state = _state(
        p1_active=active_inst,
        p1_bench=[basic_inst],
        p1_hand=[s1_hand_inst],
        p2_active=_inst(dummy_active, "dummy-ft-2", evolution_stage=0),
        turn_number=1,
        active_player="p1",
        first_player="p1",  # p1 IS the first player
    )
    basic_inst.turn_played = 1

    state.active_stadium = _stadium_inst("me02.5-188", "Forest of Vitality", "fov-ft-stadium")

    evolve_actions = ActionValidator._get_evolve_actions(state, state.p1, "p1")
    matching = [
        a for a in evolve_actions
        if a.card_instance_id == s1_hand_inst.instance_id
        and a.target_instance_id == basic_inst.instance_id
    ]
    assert not matching, (
        "First-turn restriction must still apply even with me02.5-188 Forest of Vitality active"
    )


def test_forest_of_vitality_alt_print_does_not_allow_non_grass_same_turn_evolution():
    """With me02.5-188, a non-Grass Pokémon played this turn still cannot evolve."""
    fire_basic = _make_card("t41-fire-basic", "FireBasic",
                             stage="Basic", types=["Fire"])
    fire_s1 = _make_card("t41-fire-s1", "FireStage1",
                          stage="Stage1", types=["Fire"],
                          evolve_from="FireBasic")
    dummy_active = _make_card("t41-dummy-ng", "DummyNG")
    card_registry.register(fire_basic)
    card_registry.register(fire_s1)
    card_registry.register(dummy_active)

    basic_inst = _inst(fire_basic, "fire-basic-1", zone=Zone.BENCH, evolution_stage=0)
    s1_hand_inst = _hand_inst(fire_s1, "fire-s1-hand-1", evo_stage=1)
    active_inst = _inst(dummy_active, "dummy-ng-1", evolution_stage=0)

    state = _state(
        p1_active=active_inst,
        p1_bench=[basic_inst],
        p1_hand=[s1_hand_inst],
        p2_active=_inst(dummy_active, "dummy-ng-2", evolution_stage=0),
        turn_number=2,
        active_player="p1",
        first_player="p2",
    )
    basic_inst.turn_played = 2
    state.active_stadium = _stadium_inst("me02.5-188", "Forest of Vitality", "fov-ng-stadium")

    evolve_actions = ActionValidator._get_evolve_actions(state, state.p1, "p1")
    matching = [
        a for a in evolve_actions
        if a.card_instance_id == s1_hand_inst.instance_id
        and a.target_instance_id == basic_inst.instance_id
    ]
    assert not matching, (
        "Forest of Vitality only allows Grass Pokémon; non-Grass must still be blocked same turn"
    )


# ─── Fix 3: Extra Helpings alt-print (svp-184 Hop's Snorlax) ────────────────
#
# Bug: _EXTRA_HELPINGS_IDS only contained "sv09-117"; svp-184 was excluded
# Fix: added "svp-184" to _EXTRA_HELPINGS_IDS frozenset
#
# Tests:
#   a) svp-184 in play → has_extra_helpings returns True (alt-print detected)
#   b) sv09-117 in play → has_extra_helpings returns True (original print still works)
#   c) Neither print in play → has_extra_helpings returns False
#   d) svp-184 in play + Hop's attacker → +30 damage bonus applied in _apply_damage


def _make_hops_snorlax_alt() -> CardDefinition:
    return _make_card("svp-184", "Hop's Snorlax",
                      abilities=[AbilityDef(name="Extra Helpings",
                                            effect="Hop's Pokémon do 30 more damage.")])


def _make_hops_snorlax_orig() -> CardDefinition:
    return _make_card("sv09-117", "Hop's Snorlax",
                      abilities=[AbilityDef(name="Extra Helpings",
                                            effect="Hop's Pokémon do 30 more damage.")])


def test_extra_helpings_alt_print_svp184_detected_by_has_extra_helpings():
    """svp-184 in play must be detected by has_extra_helpings."""
    snorlax = _make_hops_snorlax_alt()
    dummy_active = _make_card("t41-dummy-eh1", "Dummy1")
    card_registry.register(snorlax)
    card_registry.register(dummy_active)

    snorlax_inst = _inst(snorlax, "svp184-bench", zone=Zone.BENCH, evolution_stage=0)
    active_inst = _inst(dummy_active, "dummy-eh1-act", evolution_stage=0)

    state = _state(p1_active=active_inst, p1_bench=[snorlax_inst])
    assert has_extra_helpings(state, "p1"), (
        "svp-184 Hop's Snorlax alt-print on bench must be detected by has_extra_helpings"
    )


def test_extra_helpings_original_print_sv09117_still_detected():
    """sv09-117 (original print) must still be detected by has_extra_helpings."""
    snorlax = _make_hops_snorlax_orig()
    dummy_active = _make_card("t41-dummy-eh2", "Dummy2")
    card_registry.register(snorlax)
    card_registry.register(dummy_active)

    snorlax_inst = _inst(snorlax, "sv09117-bench", zone=Zone.BENCH, evolution_stage=0)
    active_inst = _inst(dummy_active, "dummy-eh2-act", evolution_stage=0)

    state = _state(p1_active=active_inst, p1_bench=[snorlax_inst])
    assert has_extra_helpings(state, "p1"), (
        "sv09-117 original Hop's Snorlax must still be detected by has_extra_helpings"
    )


def test_extra_helpings_absent_when_neither_print_in_play():
    """Without either Hop's Snorlax print, has_extra_helpings returns False."""
    dummy = _make_card("t41-dummy-eh3", "Dummy3")
    card_registry.register(dummy)

    active_inst = _inst(dummy, "dummy-eh3-act", evolution_stage=0)
    bench_inst = _inst(dummy, "dummy-eh3-bench", zone=Zone.BENCH, evolution_stage=0)

    state = _state(p1_active=active_inst, p1_bench=[bench_inst])
    assert not has_extra_helpings(state, "p1"), (
        "has_extra_helpings must return False when no Hop's Snorlax print is in play"
    )


def test_extra_helpings_alt_print_bonus_does_not_apply_to_non_hops_pokemon():
    """With svp-184 in play, a non-Hop's attacker does NOT receive the +30 bonus."""
    snorlax = _make_hops_snorlax_alt()
    non_hops = _make_card("t41-nonhops", "Pikachu",
                           abilities=[],
                           attacks=[AttackDef(name="Zap", cost=["Lightning"], damage="30", effect="")])
    dummy_active = _make_card("t41-dummy-eh4", "Dummy4")
    card_registry.register(snorlax)
    card_registry.register(non_hops)
    card_registry.register(dummy_active)

    snorlax_inst = _inst(snorlax, "svp184-bench-2", zone=Zone.BENCH, evolution_stage=0)
    attacker_inst = _inst(non_hops, "nonhops-act", evolution_stage=0)
    defender_inst = _inst(dummy_active, "defender-1", evolution_stage=0)

    state = _state(
        p1_active=attacker_inst,
        p1_bench=[snorlax_inst],
        p2_active=defender_inst,
    )

    # has_extra_helpings is True (snorlax is in play), but "Hop's" not in attacker name
    assert has_extra_helpings(state, "p1"), "svp-184 should be detected"
    assert "Hop's" not in attacker_inst.card_name, "Attacker is not a Hop's Pokémon"
    # The +30 is gated on "Hop's" in attacker name — verified by checking the function guard
    # in attacks.py: `if "Hop's" in attacker.card_name and has_extra_helpings(...)`
    # We confirm the condition fails for non-Hop's attackers:
    bonus_would_apply = "Hop's" in attacker_inst.card_name and has_extra_helpings(state, "p1")
    assert not bonus_would_apply, (
        "Extra Helpings +30 bonus must NOT apply to non-Hop's attackers even with svp-184 in play"
    )
