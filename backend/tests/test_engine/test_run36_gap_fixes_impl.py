"""Run-36 engine gap fixes — implementation tests.

Covers:
  - Big Net (sv06-005 Ariados): +1 retreat cost for opponent's active Evolution Pokémon
  - Metal Bridge (sv07-107/sv08.5-070 Archaludon): ALL Pokémon with Metal Energy have free retreat
  - Initialization sv06-077 (Iron Thorns ex): rule-box abilities suppressed
  - Boom Boom Groove (sv06-015 Thwackey): search deck for card when Active has Festival Lead
  - Wicked Tail (sv06-138 Ambipom): on-evolve registered with handler
  - ACE Nullifier (sv06.5-040 Genesect): Genesect with tool blocks ACE SPEC cards
  - Massive Body (sv06.5-042 Copperajah): blocks opponent's Stadium plays
  - Storehouse Hideaway (sv06-020 Poltchageist): bench damage blocked
  - Solar Transfer mep-013: registered as active ability
  - Changing Seasons (sv05-017 Sawsbuck): search deck for Stadium
  - Unnerve (sv06.5-045 Fraxure): not targetable by Boss's Orders / Pokémon Catcher
"""
from __future__ import annotations

import pytest

import app.engine.effects  # noqa: F401
from app.cards import registry as card_registry
from app.cards.models import AbilityDef, AttackDef, CardDefinition
from app.engine.actions import Action, ActionType, ActionValidator
from app.engine.effects.abilities import (
    has_metal_bridge,
    has_unnerve_protection,
)
from app.engine.effects.attacks import _apply_bench_damage
from app.engine.effects.base import get_retreat_cost_reduction
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
    is_ex: bool = False,
    retreat_cost: int = 1,
) -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name=name,
        category=category,
        subcategory=subcategory,
        set_abbrev="T36I",
        set_number="001",
        hp=hp,
        stage=stage,
        types=types or [],
        attacks=attacks or [],
        abilities=abilities or [],
        is_ex=is_ex,
        is_tera=False,
        retreat_cost=retreat_cost,
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
    stage = evolution_stage
    if stage is None:
        stage_str = cdef.stage.lower()
        if stage_str == "basic":
            stage = 0
        elif stage_str in ("stage1", "stage 1"):
            stage = 1
        else:
            stage = 2
    return CardInstance(
        instance_id=iid,
        card_def_id=cdef.tcgdex_id,
        card_name=cdef.name,
        zone=zone,
        current_hp=hp,
        max_hp=hp,
        card_type=cdef.category.capitalize(),
        card_subtype=cdef.subcategory.capitalize() if cdef.subcategory else "",
        evolution_stage=stage,
    )


def _trainer_inst(tcgdex_id: str, name: str, subtype: str, iid: str) -> CardInstance:
    return CardInstance(
        instance_id=iid,
        card_def_id=tcgdex_id,
        card_name=name,
        zone=Zone.HAND,
        current_hp=0,
        max_hp=0,
        card_type="Trainer",
        card_subtype=subtype.capitalize(),
        evolution_stage=0,
    )


def _state(
    p1_active: CardInstance | None = None,
    p1_bench: list[CardInstance] | None = None,
    p2_active: CardInstance | None = None,
    p2_bench: list[CardInstance] | None = None,
) -> GameState:
    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.phase = Phase.MAIN
    state.turn_number = 2
    state.active_player = "p1"
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
    return state


# ─── Gap 1: Big Net (sv06-005 Ariados) ──────────────────────────────────────


def test_big_net_blocks_retreat_for_evolution_active_with_insufficient_energy():
    """Ariados in opponent's play → Stage1 active with exactly 1 energy cannot retreat (cost is now 2)."""
    ariados = _make_card("sv06-005", "Ariados",
                         abilities=[AbilityDef(name="Big Net", effect="...")])
    stage1 = _make_card("test-s1-bn", "StageOneActive", stage="Stage1", retreat_cost=1)
    bench_poke = _make_card("test-bench-bn", "BenchPoke")
    card_registry.register(ariados)
    card_registry.register(stage1)
    card_registry.register(bench_poke)

    active = _inst(stage1, "s1-act-bn", evolution_stage=1)
    bench = _inst(bench_poke, "bench-bn1")
    ariados_inst = _inst(ariados, "ari-bn1")

    # p1 retreating; p2 has Ariados as active — gives only 1 energy (not enough for cost 2)
    state = _state(p1_active=active, p1_bench=[bench], p2_active=ariados_inst)
    active.energy_attached = [
        EnergyAttachment(
            energy_type=EnergyType.COLORLESS,
            source_card_id="e-bn1",
            card_def_id="dummy-e",
            provides=[EnergyType.COLORLESS],
        ),
    ]

    retreat_actions = ActionValidator._get_retreat_actions(state, state.p1, "p1")
    assert not retreat_actions, "Stage1 with 1 energy should not retreat when Big Net raises cost to 2"


def test_big_net_allows_retreat_with_sufficient_energy():
    """Stage1 with 2 energy can retreat even with Big Net active (cost 1+1=2, energy=2)."""
    ariados = _make_card("sv06-005b", "Ariados", stage="Basic",
                         abilities=[AbilityDef(name="Big Net", effect="...")])
    stage1 = _make_card("test-s1-bn2", "StageOneActive2", stage="Stage1", retreat_cost=1)
    bench_poke = _make_card("test-bench-bn2", "BenchPoke2")
    card_registry.register(ariados)
    card_registry.register(stage1)
    card_registry.register(bench_poke)

    active = _inst(stage1, "s1-act-bn2", evolution_stage=1)
    bench = _inst(bench_poke, "bench-bn2")
    ariados_inst = _inst(ariados, "ari-bn2")

    state = _state(p1_active=active, p1_bench=[bench], p2_active=ariados_inst)
    active.energy_attached = [
        EnergyAttachment(
            energy_type=EnergyType.COLORLESS,
            source_card_id="e-bn2a",
            card_def_id="dummy-e",
            provides=[EnergyType.COLORLESS],
        ),
        EnergyAttachment(
            energy_type=EnergyType.COLORLESS,
            source_card_id="e-bn2b",
            card_def_id="dummy-e",
            provides=[EnergyType.COLORLESS],
        ),
    ]

    retreat_actions = ActionValidator._get_retreat_actions(state, state.p1, "p1")
    assert retreat_actions, "Stage1 with 2 energy should retreat with Big Net (cost 2)"


def test_big_net_no_effect_on_basic_active():
    """Big Net should NOT add retreat cost if player's active is a Basic (stage 0)."""
    ariados = _make_card("sv06-005c", "Ariados",
                         abilities=[AbilityDef(name="Big Net", effect="...")])
    basic_poke = _make_card("test-basic-bn", "BasicActive", stage="Basic", retreat_cost=1)
    bench_poke = _make_card("test-bench-bn3", "BenchPoke3")
    card_registry.register(ariados)
    card_registry.register(basic_poke)
    card_registry.register(bench_poke)

    active = _inst(basic_poke, "b-act-bn", evolution_stage=0)
    bench = _inst(bench_poke, "bench-bn3")
    ariados_inst = _inst(ariados, "ari-bn3")

    state = _state(p1_active=active, p1_bench=[bench], p2_active=ariados_inst)
    active.energy_attached = [
        EnergyAttachment(
            energy_type=EnergyType.COLORLESS,
            source_card_id="e-bn3",
            card_def_id="dummy-e",
            provides=[EnergyType.COLORLESS],
        ),
    ]

    retreat_actions = ActionValidator._get_retreat_actions(state, state.p1, "p1")
    assert retreat_actions, "Basic active with 1 energy should still be able to retreat (no Big Net effect)"


# ─── Gap 2: Metal Bridge ─────────────────────────────────────────────────────


def test_has_metal_bridge_detects_sv07_107():
    archaludon = _make_card("sv07-107", "Archaludon",
                            abilities=[AbilityDef(name="Metal Bridge", effect="...")])
    card_registry.register(archaludon)
    arch_inst = _inst(archaludon, "arch1")
    state = _state(p1_active=arch_inst)
    assert has_metal_bridge(state, "p1")


def test_has_metal_bridge_detects_sv08_5_070():
    archaludon_ex = _make_card("sv08.5-070", "Archaludon ex",
                               abilities=[AbilityDef(name="Metal Bridge", effect="...")])
    card_registry.register(archaludon_ex)
    arch_inst = _inst(archaludon_ex, "archex1")
    state = _state(p1_active=arch_inst)
    assert has_metal_bridge(state, "p1")


def test_metal_bridge_free_retreat_for_any_pokemon_with_metal_energy():
    """With Metal Bridge, any Pokémon with Metal Energy should get free retreat."""
    archaludon = _make_card("sv07-107", "Archaludon",
                            abilities=[AbilityDef(name="Metal Bridge", effect="...")])
    other_poke = _make_card("test-mp1", "OtherPokemon", retreat_cost=3)
    card_registry.register(archaludon)
    card_registry.register(other_poke)

    arch_inst = _inst(archaludon, "arch-mb")
    other_inst = _inst(other_poke, "other-mb")
    other_inst.energy_attached = [
        EnergyAttachment(
            energy_type=EnergyType.METAL,
            source_card_id="metal1",
            card_def_id="dummy-metal",
            provides=[EnergyType.METAL],
        ),
    ]
    state = _state(p1_active=arch_inst)

    reduction = get_retreat_cost_reduction(other_inst, state, "p1")
    assert reduction == 9999, f"Expected 9999 (free retreat), got {reduction}"


def test_metal_bridge_no_free_retreat_without_metal_energy():
    """Metal Bridge should NOT give free retreat if the Pokémon lacks Metal energy."""
    archaludon = _make_card("sv07-107", "Archaludon",
                            abilities=[AbilityDef(name="Metal Bridge", effect="...")])
    other_poke = _make_card("test-mp2", "OtherPokemon2", retreat_cost=2)
    card_registry.register(archaludon)
    card_registry.register(other_poke)

    arch_inst = _inst(archaludon, "arch-mb2")
    other_inst = _inst(other_poke, "other-mb2")
    state = _state(p1_active=arch_inst)

    reduction = get_retreat_cost_reduction(other_inst, state, "p1")
    assert reduction < 9999, "Should not get free retreat without Metal Energy attached"


# ─── Gap 3: Initialization sv06-077 ─────────────────────────────────────────


def test_initialization_sv06_077_suppresses_rule_box_abilities():
    """sv06-077 Iron Thorns ex active → rule-box Pokémon can't use abilities."""
    iron_thorns_77 = _make_card("sv06-077", "Iron Thorns ex",
                                abilities=[AbilityDef(name="Initialization", effect="...")])
    rule_box_poke = _make_card("test-rb1", "TestPokemon ex", stage="Basic",
                               abilities=[AbilityDef(name="Some Ability", effect="...")])
    card_registry.register(iron_thorns_77)
    card_registry.register(rule_box_poke)

    iron_inst = _inst(iron_thorns_77, "it77")
    rb_inst = _inst(rule_box_poke, "rb1")
    bench_poke = _make_card("test-bench-rb", "BenchPoke")
    card_registry.register(bench_poke)
    bench_inst = _inst(bench_poke, "br1")

    # Register a dummy active handler for the rule-box ability so it would appear otherwise
    reg = EffectRegistry.instance()
    if "test-rb1:Some Ability" not in reg._ability_effects:
        def _dummy_handler(state, action): return None
        reg.register_ability("test-rb1", "Some Ability", _dummy_handler)

    # p1 has rule-box Pokémon; p2 has sv06-077 active
    state = _state(p1_active=rb_inst, p1_bench=[bench_inst], p2_active=iron_inst)

    ability_actions = ActionValidator._get_ability_actions(state, state.p1, "p1")
    target_ids = {a.card_instance_id for a in ability_actions if a.card_instance_id}
    assert rb_inst.instance_id not in target_ids, \
        "Rule-box Pokémon should not be able to use ability when sv06-077 is opponent's active"


# ─── Gap 4: Boom Boom Groove ─────────────────────────────────────────────────


def test_boom_boom_groove_registered_as_active_handler():
    reg = EffectRegistry.instance()
    assert "sv06-015:Boom Boom Groove" in reg._ability_effects, \
        "sv06-015 Boom Boom Groove should be registered as active ability"
    assert "sv06-015:Boom Boom Groove" not in reg._passive_abilities, \
        "sv06-015 Boom Boom Groove should not be in passive abilities"


def test_boom_boom_groove_svp115_registered_as_active_handler():
    reg = EffectRegistry.instance()
    assert "svp-115:Boom Boom Groove" in reg._ability_effects, \
        "svp-115 Boom Boom Groove should be registered as active ability"


def test_boom_boom_groove_condition_requires_festival_lead_on_active():
    """Boom Boom Groove condition requires Active Pokémon to have Festival Lead ability."""
    thwackey = _make_card("sv06-015", "Thwackey",
                          abilities=[AbilityDef(name="Boom Boom Groove", effect="...")])
    festival_lead_poke = _make_card("sv06-018", "Dipplin",
                                    abilities=[AbilityDef(name="Festival Lead", effect="...")])
    non_fl_poke = _make_card("test-nofl", "NormalPoke")
    card_registry.register(thwackey)
    card_registry.register(festival_lead_poke)
    card_registry.register(non_fl_poke)

    thwackey_inst = _inst(thwackey, "tw1")
    fl_inst = _inst(festival_lead_poke, "fl1")
    nofl_inst = _inst(non_fl_poke, "nofl1")

    # With Festival Lead active: condition should be True
    state_with_fl = _state(p1_active=fl_inst, p1_bench=[thwackey_inst])
    from app.engine.effects.abilities import _cond_boom_boom_groove
    assert _cond_boom_boom_groove(state_with_fl, "p1", thwackey_inst), \
        "Condition should be True when active has Festival Lead"

    # Without Festival Lead active: condition should be False
    state_without_fl = _state(p1_active=nofl_inst, p1_bench=[thwackey_inst])
    assert not _cond_boom_boom_groove(state_without_fl, "p1", thwackey_inst), \
        "Condition should be False when active lacks Festival Lead"


# ─── Gap 5: Wicked Tail ──────────────────────────────────────────────────────


def test_wicked_tail_registered_as_active_handler():
    reg = EffectRegistry.instance()
    assert "sv06-138:Wicked Tail" in reg._ability_effects, \
        "sv06-138 Wicked Tail should be registered as active ability"


def test_wicked_tail_in_evolve_trigger_abilities():
    from app.engine.effects.abilities import EVOLVE_TRIGGER_ABILITIES
    assert "Wicked Tail" in EVOLVE_TRIGGER_ABILITIES, \
        "Wicked Tail must be in EVOLVE_TRIGGER_ABILITIES"


# ─── Gap 6: ACE Nullifier ─────────────────────────────────────────────────────


def test_ace_nullifier_blocks_ace_spec_when_genesect_has_tool():
    """Genesect (sv06.5-040) with tool → opponent can't play ACE SPEC cards."""
    genesect = _make_card("sv06.5-040", "Genesect",
                          abilities=[AbilityDef(name="ACE Nullifier", effect="...")])
    card_registry.register(genesect)

    genesect_inst = _inst(genesect, "gen1")
    genesect_inst.tools_attached = ["some-tool"]

    # A bench dummy for p2
    bench_p2 = _make_card("test-bp2", "BenchP2")
    card_registry.register(bench_p2)
    bench_inst = _inst(bench_p2, "bp2-1", zone=Zone.BENCH)

    state = _state(p1_bench=[bench_inst], p2_active=genesect_inst)

    # Add an ACE SPEC item to p1's hand
    ace_card = _trainer_inst("sv06-162", "Scoop Up Cyclone", "item", "ace1")
    state.p1.hand = [ace_card]

    play_actions = ActionValidator._get_play_actions(state, state.p1, "p1")
    played_ids = {a.card_instance_id for a in play_actions}
    assert "ace1" not in played_ids, \
        "ACE SPEC card should be blocked when Genesect with tool is in play"


def test_ace_nullifier_no_block_without_tool():
    """Genesect without a tool should NOT block ACE SPEC cards."""
    genesect = _make_card("sv06.5-040", "Genesect",
                          abilities=[AbilityDef(name="ACE Nullifier", effect="...")])
    card_registry.register(genesect)

    genesect_inst = _inst(genesect, "gen2")
    # No tool attached

    bench_p2 = _make_card("test-bp2b", "BenchP2b")
    card_registry.register(bench_p2)
    bench_inst = _inst(bench_p2, "bp2-2", zone=Zone.BENCH)

    state = _state(p1_bench=[bench_inst], p2_active=genesect_inst)

    ace_card = _trainer_inst("sv06-162", "Scoop Up Cyclone", "item", "ace2")
    state.p1.hand = [ace_card]

    play_actions = ActionValidator._get_play_actions(state, state.p1, "p1")
    played_ids = {a.card_instance_id for a in play_actions}
    assert "ace2" in played_ids, \
        "ACE SPEC should be playable when Genesect has no tool"


# ─── Gap 7: Massive Body ─────────────────────────────────────────────────────


def test_massive_body_blocks_stadium_play():
    """Copperajah (sv06.5-042) as opponent's active → can't play Stadium cards."""
    copperajah = _make_card("sv06.5-042", "Copperajah",
                            abilities=[AbilityDef(name="Massive Body", effect="...")])
    card_registry.register(copperajah)

    copper_inst = _inst(copperajah, "cop1")
    bench_p1 = _make_card("test-bp1-cop", "BenchP1cop")
    card_registry.register(bench_p1)
    bench_inst = _inst(bench_p1, "bp1-cop", zone=Zone.BENCH)

    state = _state(p1_bench=[bench_inst], p2_active=copper_inst)

    stadium_card = _trainer_inst("sv06-153", "Jamming Tower", "stadium", "stad1")
    state.p1.hand = [stadium_card]

    play_actions = ActionValidator._get_play_actions(state, state.p1, "p1")
    played_ids = {a.card_instance_id for a in play_actions}
    assert "stad1" not in played_ids, \
        "Stadium should be blocked when Copperajah is opponent's active"


def test_massive_body_no_block_without_copperajah():
    """Without Copperajah active, stadiums can be played normally."""
    other_active = _make_card("test-other-cop", "OtherActive")
    card_registry.register(other_active)

    other_inst = _inst(other_active, "oth-cop")
    bench_p1 = _make_card("test-bp1-cop2", "BenchP1cop2")
    card_registry.register(bench_p1)
    bench_inst2 = _inst(bench_p1, "bp1-cop2", zone=Zone.BENCH)

    state = _state(p1_bench=[bench_inst2], p2_active=other_inst)

    stadium_card = _trainer_inst("sv06-153", "Jamming Tower", "stadium", "stad2")
    state.p1.hand = [stadium_card]

    play_actions = ActionValidator._get_play_actions(state, state.p1, "p1")
    played_ids = {a.card_instance_id for a in play_actions}
    assert "stad2" in played_ids, \
        "Stadium should be playable when Copperajah is not opponent's active"


# ─── Gap 9: Storehouse Hideaway ──────────────────────────────────────────────


def test_storehouse_hideaway_blocks_bench_damage():
    """sv06-020 Poltchageist on bench takes no damage from bench attacks."""
    poltchageist = _make_card("sv06-020", "Poltchageist", hp=60,
                              abilities=[AbilityDef(name="Storehouse Hideaway", effect="...")])
    card_registry.register(poltchageist)

    poke = _inst(poltchageist, "pot1", zone=Zone.BENCH, hp=60)

    attacker = _make_card("test-atk-sh", "Attacker")
    card_registry.register(attacker)
    atk = _inst(attacker, "atk-sh")
    state = _state(p1_active=atk, p2_bench=[poke])

    _apply_bench_damage(state, "p2", poke, 50)
    assert poke.current_hp == 60, "Poltchageist should take no bench damage (Storehouse Hideaway)"


def test_storehouse_hideaway_only_on_sv06_020():
    """Other bench Pokémon should still take bench damage normally."""
    normal_poke = _make_card("test-bench-sh", "NormalBenchPoke", hp=100)
    card_registry.register(normal_poke)

    bench = _inst(normal_poke, "nb1", zone=Zone.BENCH, hp=100)
    attacker = _make_card("test-atk-sh2", "Attacker2")
    card_registry.register(attacker)
    atk = _inst(attacker, "atk-sh2")
    state = _state(p1_active=atk, p2_bench=[bench])

    _apply_bench_damage(state, "p2", bench, 50)
    assert bench.current_hp == 50, "Normal bench Pokémon should take bench damage"


# ─── Gap 10: Solar Transfer mep-013 ──────────────────────────────────────────


def test_solar_transfer_mep013_registered_as_active_handler():
    reg = EffectRegistry.instance()
    assert "mep-013:Solar Transfer" in reg._ability_effects, \
        "mep-013 Solar Transfer should be registered as active ability handler"
    assert "mep-013:Solar Transfer" not in reg._passive_abilities, \
        "mep-013 Solar Transfer should NOT be in passive abilities"


# ─── Gap 11: Changing Seasons ────────────────────────────────────────────────


def test_changing_seasons_registered_as_active_handler():
    reg = EffectRegistry.instance()
    assert "sv05-017:Changing Seasons" in reg._ability_effects, \
        "sv05-017 Changing Seasons should be registered as active ability"


def test_changing_seasons_condition_requires_stadium_in_deck():
    """Condition should be True only if deck has at least one Stadium card."""
    sawsbuck = _make_card("sv05-017", "Sawsbuck",
                          abilities=[AbilityDef(name="Changing Seasons", effect="...")])
    card_registry.register(sawsbuck)

    sawsbuck_inst = _inst(sawsbuck, "saw1")
    state = _state(p1_active=sawsbuck_inst)

    from app.engine.effects.abilities import _cond_changing_seasons

    # No stadium in deck
    state.p1.deck = []
    assert not _cond_changing_seasons(state, "p1", sawsbuck_inst), \
        "Condition should be False with empty deck"

    # Add a stadium card to deck
    stadium_card = _trainer_inst("sv06-153", "Jamming Tower", "stadium", "stad-cs1")
    state.p1.deck = [stadium_card]
    assert _cond_changing_seasons(state, "p1", sawsbuck_inst), \
        "Condition should be True when deck has a Stadium card"


# ─── Gap 12: Unnerve ─────────────────────────────────────────────────────────


def test_has_unnerve_protection_returns_true_for_sv06_5_045():
    fraxure = _make_card("sv06.5-045", "Fraxure",
                         abilities=[AbilityDef(name="Unnerve", effect="...")])
    card_registry.register(fraxure)
    inst = _inst(fraxure, "frax1")
    assert has_unnerve_protection(inst), "sv06.5-045 should have unnerve protection"


def test_has_unnerve_protection_returns_false_for_others():
    normal = _make_card("test-nonerve", "NormalPoke")
    card_registry.register(normal)
    inst = _inst(normal, "nn1")
    assert not has_unnerve_protection(inst), "Normal Pokémon should not have unnerve protection"
