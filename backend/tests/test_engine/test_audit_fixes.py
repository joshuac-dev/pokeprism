"""Audit-fix regression tests (findings #1-8).

Findings:
  #1-4 : Fossil passive ability registrations (sv07-129, sv10.5b-080, sv10.5w-079, sv07-130)
  #5   : _crimson_blaster_b4 — discard ALL {R}, deal 180 to BENCH only
  #6   : _high_voltage_press — subtract attack cost (3) from energy count, not 1
  #7   : _thunderburst_storm — player chooses target; bench hit gets no W/R
  #8   : _bench_manipulation — damage bypasses Weakness/Resistance
"""
from __future__ import annotations

import pytest
import random

import app.engine.effects  # noqa: F401 — triggers register_all via __init__
from app.cards import registry as card_registry
from app.cards.models import AbilityDef, AttackDef, CardDefinition
from app.engine.actions import Action, ActionType
from app.engine.effects.base import ChoiceRequest
from app.engine.effects.registry import _choice_to_legal_actions, _default_choice
from app.engine.effects.registry import EffectRegistry
from app.engine.runner import MatchRunner
from app.engine.state import CardInstance, EnergyAttachment, EnergyType, GameState, Zone


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_card(tcgdex_id: str, name: str, hp: int = 120,
               attacks: list[AttackDef] | None = None,
               abilities: list[AbilityDef] | None = None,
               stage: str = "Basic") -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name=name,
        set_abbrev="TST",
        set_number="001",
        category="pokemon",
        stage=stage,
        hp=hp,
        attacks=attacks or [],
        abilities=abilities or [],
    )


def _make_instance(cdef: CardDefinition, zone: Zone = Zone.ACTIVE,
                   hp: int | None = None) -> CardInstance:
    hp = hp or cdef.hp or 100
    return CardInstance(
        instance_id="inst-" + cdef.tcgdex_id,
        card_def_id=cdef.tcgdex_id,
        card_name=cdef.name,
        current_hp=hp,
        max_hp=hp,
        zone=zone,
    )


def _make_energy(energy_type: EnergyType, card_def_id: str = "basic-energy") -> EnergyAttachment:
    return EnergyAttachment(
        energy_type=energy_type,
        source_card_id="src-" + card_def_id,
        card_def_id=card_def_id,
    )


def _make_state(
    p1_active: CardInstance | None = None,
    p1_bench: list[CardInstance] | None = None,
    p2_active: CardInstance | None = None,
    p2_bench: list[CardInstance] | None = None,
) -> GameState:
    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
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


def _make_action(player_id: str = "p1", attack_index: int = 0) -> Action:
    return Action(
        player_id=player_id,
        action_type=ActionType.ATTACK,
        attack_index=attack_index,
    )


def _runner_for_between_turns() -> MatchRunner:
    runner = object.__new__(MatchRunner)
    runner._rng = random.Random(0)
    return runner


@pytest.fixture(autouse=True)
def clear_card_registry():
    yield
    card_registry.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Findings #1-4: Fossil passive ability registrations
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("card_id,ability_name", [
    ("sv07-129", "Protective Cover"),
    ("sv10.5b-080", "Protective Cover"),
    ("sv10.5w-079", "Plume Protection"),
    ("sv07-130", "Primal Root"),
])
def test_fossil_passive_ability_registered(card_id: str, ability_name: str):
    """Fossil Pokémon passive abilities are registered in the registry."""
    reg = EffectRegistry.instance()
    key = f"{card_id}:{ability_name}"
    assert key in reg._passive_abilities, (
        f"Passive ability '{ability_name}' for {card_id} not registered"
    )


def test_sand_stream_only_active_tyranitar_triggers():
    """Sand Stream fires from Active TR Tyranitar, not benched Tyranitar."""
    tyranitar = _make_card(
        "sv10-096", "Team Rocket's Tyranitar", hp=180,
        abilities=[AbilityDef(name="Sand Stream", effect="")],
    )
    basic = _make_card("tst-ss-001", "Basic Target", hp=100)
    stage1 = _make_card("tst-ss-002", "Stage One Target", hp=100, stage="Stage 1")
    card_registry.register(tyranitar)
    card_registry.register(basic)
    card_registry.register(stage1)

    benched_tyranitar = _make_instance(tyranitar, zone=Zone.BENCH, hp=180)
    p1_active = _make_instance(basic, hp=100)
    p2_active = _make_instance(basic, hp=100)
    p2_stage1 = _make_instance(stage1, zone=Zone.BENCH, hp=100)
    p2_stage1.evolution_stage = 1
    state = _make_state(
        p1_active=p1_active,
        p1_bench=[benched_tyranitar],
        p2_active=p2_active,
        p2_bench=[p2_stage1],
    )

    _runner_for_between_turns()._handle_between_turns(state)

    assert p2_active.damage_counters == 0
    assert p2_stage1.damage_counters == 0

    state.p1.active = benched_tyranitar
    state.p1.active.zone = Zone.ACTIVE
    state.p1.bench = [p1_active]
    p1_active.zone = Zone.BENCH

    _runner_for_between_turns()._handle_between_turns(state)

    assert p2_active.damage_counters == 2
    assert p2_active.current_hp == 80
    assert p2_stage1.damage_counters == 0
    assert any(e["event_type"] == "sand_stream_triggered" and e["player"] == "p1" for e in state.events)


def test_sand_stream_checks_non_turn_player_active():
    """Pokémon Checkup applies Sand Stream regardless of whose turn just ended."""
    tyranitar = _make_card(
        "sv10-096", "Team Rocket's Tyranitar", hp=180,
        abilities=[AbilityDef(name="Sand Stream", effect="")],
    )
    basic = _make_card("tst-ss-003", "Basic Target", hp=100)
    card_registry.register(tyranitar)
    card_registry.register(basic)

    state = _make_state(
        p1_active=_make_instance(basic, hp=100),
        p2_active=_make_instance(tyranitar, hp=180),
    )
    state.active_player = "p1"

    _runner_for_between_turns()._handle_between_turns(state)

    assert state.p1.active.damage_counters == 2
    assert any(e["event_type"] == "sand_stream_triggered" and e["player"] == "p2" for e in state.events)


# ──────────────────────────────────────────────────────────────────────────────
# Finding #5: _crimson_blaster_b4 — sv08-034 Armarouge atk1
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_crimson_blaster_discards_all_fire_energy():
    """Crimson Blaster discards ALL {R} Energy, then deals 180 to first bench target."""
    armarouge = _make_card(
        "sv08-034", "Armarouge", hp=120, stage="Stage 1",
        attacks=[
            AttackDef(name="Combustion", damage="50", cost=["Colorless", "Colorless"]),
            AttackDef(name="Crimson Blaster", damage="180",
                      cost=["Fire", "Fire", "Colorless"],
                      effect="Discard all {R} Energy from this Pokémon. This attack does 180 damage to 1 of your opponent's Benched Pokémon."),
        ],
    )
    card_registry.register(armarouge)

    bench_cdef = _make_card("tst-cb-001", "BenchTarget", hp=250)
    p2_active_cdef = _make_card("tst-cb-002", "OppActive", hp=250)
    card_registry.register(bench_cdef)
    card_registry.register(p2_active_cdef)

    attacker = _make_instance(armarouge)
    for _ in range(4):
        attacker.energy_attached.append(_make_energy(EnergyType.FIRE))
    bench_inst = _make_instance(bench_cdef, zone=Zone.BENCH, hp=250)
    p2_active = _make_instance(p2_active_cdef, hp=250)

    state = _make_state(p1_active=attacker, p2_active=p2_active, p2_bench=[bench_inst])
    action = _make_action("p1", attack_index=1)

    await EffectRegistry.instance().resolve_attack("sv08-034", 1, state, action)

    assert len(attacker.energy_attached) == 0, "Crimson Blaster must discard ALL Fire energy"
    assert bench_inst.damage_counters == 18, (
        f"Bench target should have 18 counters (180 dmg), got {bench_inst.damage_counters}"
    )
    assert p2_active.damage_counters == 0, "Active must NOT be hit by Crimson Blaster"


@pytest.mark.asyncio
async def test_crimson_blaster_no_bench_does_nothing():
    """Crimson Blaster returns early when opponent has no benched Pokémon."""
    armarouge = _make_card(
        "sv08-034", "Armarouge", hp=120, stage="Stage 1",
        attacks=[
            AttackDef(name="Combustion", damage="50", cost=["Colorless", "Colorless"]),
            AttackDef(name="Crimson Blaster", damage="180",
                      cost=["Fire", "Fire", "Colorless"],
                      effect="Discard all {R} Energy from this Pokémon. This attack does 180 damage to 1 of your opponent's Benched Pokémon."),
        ],
    )
    card_registry.register(armarouge)
    p2_active_cdef = _make_card("tst-cb-003", "Defender2", hp=200)
    card_registry.register(p2_active_cdef)

    attacker = _make_instance(armarouge)
    attacker.energy_attached.append(_make_energy(EnergyType.FIRE))
    p2_active = _make_instance(p2_active_cdef, hp=200)

    state = _make_state(p1_active=attacker, p2_active=p2_active)
    action = _make_action("p1", attack_index=1)

    await EffectRegistry.instance().resolve_attack("sv08-034", 1, state, action)

    assert p2_active.damage_counters == 0, "No bench → Active should not be hit"


# ──────────────────────────────────────────────────────────────────────────────
# Finding #6: _high_voltage_press — sv10-069 Electivire ex atk1
# ──────────────────────────────────────────────────────────────────────────────

_ELECTIVIRE_DEF = AttackDef(
    name="High-Voltage Press", damage="180+",
    cost=["Lightning", "Lightning", "Colorless"],
    effect=(
        "If this Pokémon has 2 or more extra Energy attached to it "
        "(in addition to this attack's cost), this attack does 100 more damage."
    ),
)


@pytest.mark.asyncio
async def test_high_voltage_press_no_bonus_with_cost_energy():
    """High-Voltage Press at exactly 3 energy (== cost) → 180 damage, no +100 bonus."""
    electivire = _make_card(
        "sv10-069", "Electivire ex", hp=250,
        attacks=[
            AttackDef(name="Dual Bolt", damage="50", cost=["Lightning", "Colorless"]),
            _ELECTIVIRE_DEF,
        ],
    )
    card_registry.register(electivire)
    defender_cdef = _make_card("tst-hvp-001", "Defender", hp=400)
    card_registry.register(defender_cdef)

    attacker = _make_instance(electivire)
    for _ in range(3):
        attacker.energy_attached.append(_make_energy(EnergyType.LIGHTNING))
    defender = _make_instance(defender_cdef, hp=400)

    state = _make_state(p1_active=attacker, p2_active=defender)
    action = _make_action("p1", attack_index=1)

    await EffectRegistry.instance().resolve_attack("sv10-069", 1, state, action)

    assert defender.damage_counters == 18, (
        f"Expected 18 counters (180 dmg), got {defender.damage_counters}"
    )


@pytest.mark.asyncio
async def test_high_voltage_press_no_bonus_with_4_energy():
    """High-Voltage Press at 4 energy (1 extra, < 2 needed) → 180 damage, no bonus."""
    electivire = _make_card(
        "sv10-069", "Electivire ex", hp=250,
        attacks=[
            AttackDef(name="Dual Bolt", damage="50", cost=["Lightning", "Colorless"]),
            _ELECTIVIRE_DEF,
        ],
    )
    card_registry.register(electivire)
    defender_cdef = _make_card("tst-hvp-002", "Defender2", hp=400)
    card_registry.register(defender_cdef)

    attacker = _make_instance(electivire)
    for _ in range(4):
        attacker.energy_attached.append(_make_energy(EnergyType.LIGHTNING))
    defender = _make_instance(defender_cdef, hp=400)

    state = _make_state(p1_active=attacker, p2_active=defender)
    action = _make_action("p1", attack_index=1)

    await EffectRegistry.instance().resolve_attack("sv10-069", 1, state, action)

    assert defender.damage_counters == 18, (
        f"Expected 18 counters (no bonus with 1 extra), got {defender.damage_counters}"
    )


@pytest.mark.asyncio
async def test_high_voltage_press_bonus_with_5_energy():
    """High-Voltage Press at 5 energy (2 extra) → 280 damage (+100 bonus)."""
    electivire = _make_card(
        "sv10-069", "Electivire ex", hp=250,
        attacks=[
            AttackDef(name="Dual Bolt", damage="50", cost=["Lightning", "Colorless"]),
            _ELECTIVIRE_DEF,
        ],
    )
    card_registry.register(electivire)
    defender_cdef = _make_card("tst-hvp-003", "BigDefender", hp=500)
    card_registry.register(defender_cdef)

    attacker = _make_instance(electivire)
    for _ in range(5):
        attacker.energy_attached.append(_make_energy(EnergyType.LIGHTNING))
    defender = _make_instance(defender_cdef, hp=500)

    state = _make_state(p1_active=attacker, p2_active=defender)
    action = _make_action("p1", attack_index=1)

    await EffectRegistry.instance().resolve_attack("sv10-069", 1, state, action)

    assert defender.damage_counters == 28, (
        f"Expected 28 counters (280 dmg = 180+100 bonus), got {defender.damage_counters}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Finding #7: _thunderburst_storm — sv07-111 Raging Bolt atk0
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_thunderburst_storm_30_per_energy_to_active():
    """Thunderburst Storm deals 30×energy-count to the Active (default choice)."""
    raging_bolt = _make_card(
        "sv07-111", "Raging Bolt", hp=130,
        attacks=[
            AttackDef(name="Thunderburst Storm", damage="0",
                      cost=["Lightning", "Fighting"],
                      effect="This attack does 30 damage for each Energy attached to this Pokémon to 1 of your opponent's Pokémon."),
        ],
    )
    card_registry.register(raging_bolt)
    defender_cdef = _make_card("tst-tbs-001", "OppActive", hp=200)
    card_registry.register(defender_cdef)

    attacker = _make_instance(raging_bolt)
    attacker.energy_attached.append(_make_energy(EnergyType.LIGHTNING))
    attacker.energy_attached.append(_make_energy(EnergyType.FIGHTING))
    attacker.energy_attached.append(_make_energy(EnergyType.COLORLESS))
    defender = _make_instance(defender_cdef, hp=200)

    state = _make_state(p1_active=attacker, p2_active=defender)
    action = _make_action("p1", attack_index=0)

    await EffectRegistry.instance().resolve_attack("sv07-111", 0, state, action)

    # 3 energy → 90 damage
    assert defender.damage_counters == 9, (
        f"Expected 9 counters (90 dmg = 30×3), got {defender.damage_counters}"
    )


@pytest.mark.asyncio
async def test_thunderburst_storm_no_energy_emits_no_damage_event():
    """Thunderburst Storm emits attack_no_damage when no Energy attached."""
    raging_bolt = _make_card(
        "sv07-111", "Raging Bolt", hp=130,
        attacks=[
            AttackDef(name="Thunderburst Storm", damage="0",
                      cost=["Lightning", "Fighting"],
                      effect="This attack does 30 damage for each Energy attached to this Pokémon to 1 of your opponent's Pokémon."),
        ],
    )
    card_registry.register(raging_bolt)
    defender_cdef = _make_card("tst-tbs-002", "Defender", hp=100)
    card_registry.register(defender_cdef)

    attacker = _make_instance(raging_bolt)
    defender = _make_instance(defender_cdef, hp=100)

    state = _make_state(p1_active=attacker, p2_active=defender)
    action = _make_action("p1", attack_index=0)

    await EffectRegistry.instance().resolve_attack("sv07-111", 0, state, action)

    assert defender.damage_counters == 0, "No energy → no damage"
    no_dmg = [e for e in state.events if e["event_type"] == "attack_no_damage"]
    assert no_dmg, "Expected attack_no_damage event when no energy"


# ──────────────────────────────────────────────────────────────────────────────
# Finding #8: _bench_manipulation — sv10-080 TR Hypno atk1
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bench_manipulation_emits_coin_flip_for_each_bench():
    """Bench Manipulation emits coin_flip_result with flips == number of benched Pokémon."""
    hypno = _make_card(
        "sv10-080", "Team Rocket's Hypno", hp=110, stage="Stage 1",
        attacks=[
            AttackDef(name="Psyshot", damage="40", cost=["Psychic"]),
            AttackDef(name="Bench Manipulation", damage="80x",
                      cost=["Psychic", "Psychic", "Psychic"],
                      effect=(
                          "Flip a coin for each of your opponent's Benched Pokémon. "
                          "This attack does 80 damage for each heads. "
                          "This attack's damage isn't affected by Weakness or Resistance."
                      )),
        ],
    )
    card_registry.register(hypno)
    opp_active_cdef = _make_card("tst-bm-001", "OppActive2", hp=200)
    opp_bench1_cdef = _make_card("tst-bm-002", "OppBench2", hp=300)
    opp_bench2_cdef = _make_card("tst-bm-003", "OppBench3", hp=300)
    card_registry.register(opp_active_cdef)
    card_registry.register(opp_bench1_cdef)
    card_registry.register(opp_bench2_cdef)

    attacker = _make_instance(hypno)
    opp_active = _make_instance(opp_active_cdef, hp=200)
    opp_bench1 = _make_instance(opp_bench1_cdef, zone=Zone.BENCH, hp=300)
    opp_bench2 = _make_instance(opp_bench2_cdef, zone=Zone.BENCH, hp=300)
    opp_bench2.instance_id = "inst-tst-bm-003-b"

    state = _make_state(
        p1_active=attacker,
        p2_active=opp_active,
        p2_bench=[opp_bench1, opp_bench2],
    )
    action = _make_action("p1", attack_index=1)

    await EffectRegistry.instance().resolve_attack("sv10-080", 1, state, action)

    flip_events = [e for e in state.events if e["event_type"] == "coin_flip_result"]
    assert flip_events, "Bench Manipulation should emit coin_flip_result"
    # 2 benched Pokémon → 2 flips total
    total_flips = sum(e.get("flips", 0) for e in flip_events)
    assert total_flips == 2, f"Expected 2 total flips for 2 benched Pokémon, got {total_flips}"


def test_choice_request_choose_cards_supports_legacy_options():
    """Legacy choose_cards requests that pass `options=` still map to selected_cards."""
    req = ChoiceRequest(
        "choose_cards",
        player_id="p1",
        options=["c1", "c2", "c3"],
        min_count=1,
        max_count=2,
    )
    legal = _choice_to_legal_actions(req)
    assert len(legal) == 1
    assert legal[0].selected_cards == ["c1", "c2", "c3"]

    default = _default_choice(req)
    assert default.selected_cards == ["c1", "c2"]


def test_choice_request_prompt_defaults_empty_for_legacy_calls():
    """ChoiceRequest prompt defaults to empty string for older keyword-style calls."""
    req = ChoiceRequest("choose_cards", player_id="p1", cards=[])
    assert req.prompt == ""


@pytest.mark.asyncio
async def test_sv06_080_teleporter_switches_active_and_shuffles():
    """sv06-080 Teleporter should replace Active, then shuffle Abra into deck."""
    abra = _make_card(
        "sv06-080", "Abra", hp=50,
        attacks=[AttackDef(name="Beam", damage="10", cost=["Colorless"])],
        abilities=[AbilityDef(name="Teleporter", type="Ability")],
    )
    bench_cdef = _make_card("tst-tel-001", "BenchMon", hp=120)
    opp_cdef = _make_card("tst-tel-002", "OppMon", hp=120)
    card_registry.register(abra)
    card_registry.register(bench_cdef)
    card_registry.register(opp_cdef)

    abra_inst = _make_instance(abra, hp=50)
    abra_inst.energy_attached.append(_make_energy(EnergyType.PSYCHIC))
    bench_inst = _make_instance(bench_cdef, zone=Zone.BENCH, hp=120)
    opp_active = _make_instance(opp_cdef, hp=120)
    state = _make_state(p1_active=abra_inst, p1_bench=[bench_inst], p2_active=opp_active)

    action = Action(
        player_id="p1",
        action_type=ActionType.USE_ABILITY,
        card_instance_id=abra_inst.instance_id,
    )

    await EffectRegistry.instance().resolve_ability("sv06-080", "Teleporter", state, action)

    assert state.p1.active is not None
    assert state.p1.active.instance_id == bench_inst.instance_id
    assert all(p.instance_id != abra_inst.instance_id for p in state.p1.bench)
    assert any(c.instance_id == abra_inst.instance_id for c in state.p1.deck)
    assert abra_inst.energy_attached == []
