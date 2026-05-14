"""Run-43 engine fix regression tests.

Covers:
  - Hop's Choice Band (sv09-148): pre-W/R damage bonus and Jamming Tower suppression
  - Gravity Gemstone (sv07-137): +1 Retreat Cost for both Active Pokémon
  - Granite Cave (sv10-166): -30 damage for Steven's Pokémon in Active and on Bench
  - Haban Berry (sv08.5-111): Dragon damage reduction + discard, suppressed by Jamming Tower
"""
from __future__ import annotations

import pytest

import app.engine.effects  # noqa: F401
from app.cards import registry as card_registry
from app.cards.models import AttackDef, CardDefinition, WeaknessDef
from app.engine.actions import Action, ActionType, ActionValidator
from app.engine.effects.attacks import _apply_bench_damage, _apply_damage
from app.engine.state import CardInstance, EnergyAttachment, EnergyType, GameState, Phase, Zone


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
    retreat_cost: int = 1,
    weaknesses: list[WeaknessDef] | None = None,
) -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name=name,
        category=category,
        subcategory=subcategory,
        set_abbrev="T43",
        set_number="001",
        hp=hp,
        stage=stage,
        types=types or [],
        attacks=attacks or [],
        weaknesses=weaknesses or [],
        retreat_cost=retreat_cost,
    )


def _inst(cdef: CardDefinition, iid: str, *, zone: Zone = Zone.ACTIVE, hp: int | None = None) -> CardInstance:
    hp = cdef.hp if hp is None else hp
    return CardInstance(
        instance_id=iid,
        card_def_id=cdef.tcgdex_id,
        card_name=cdef.name,
        zone=zone,
        current_hp=hp,
        max_hp=hp,
        card_type=cdef.category.capitalize(),
        card_subtype=cdef.subcategory.capitalize() if cdef.subcategory else "",
        evolution_stage=0 if cdef.stage.lower() == "basic" else 1,
    )


def _state(
    *,
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


def _stadium_inst(tcgdex_id: str, stadium_name: str, iid: str) -> CardInstance:
    return CardInstance(
        instance_id=iid,
        card_def_id=tcgdex_id,
        card_name=stadium_name,
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


def test_hops_choice_band_bonus_applies_before_weakness_and_resistance():
    attacker_def = _make_card(
        "sv09-108",
        "Hop's Corviknight",
        types=["Fighting"],
        attacks=[AttackDef(name="Hit", damage="20", cost=[])],
    )
    defender_def = _make_card(
        "t43-def-001",
        "Defender",
        hp=150,
        types=["Colorless"],
        weaknesses=[WeaknessDef(type="Fighting", value="×2")],
    )
    card_registry.register(attacker_def)
    card_registry.register(defender_def)

    attacker = _inst(attacker_def, "atk")
    attacker.tools_attached = ["sv09-148"]
    defender = _inst(defender_def, "def", hp=150)
    state = _state(p1_active=attacker, p1_bench=[_inst(defender_def, "bench-a", zone=Zone.BENCH)], p2_active=defender)

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 20)

    assert dmg == 100, f"Expected 100 damage ((20+30)×2), got {dmg}"


def test_jamming_tower_disables_hops_choice_band_damage_bonus():
    attacker_def = _make_card(
        "sv09-108",
        "Hop's Corviknight",
        types=["Fighting"],
        attacks=[AttackDef(name="Hit", damage="20", cost=[])],
    )
    defender_def = _make_card(
        "t43-def-002",
        "Defender",
        hp=150,
        types=["Colorless"],
        weaknesses=[WeaknessDef(type="Fighting", value="×2")],
    )
    card_registry.register(attacker_def)
    card_registry.register(defender_def)

    attacker = _inst(attacker_def, "atk")
    attacker.tools_attached = ["sv09-148"]
    defender = _inst(defender_def, "def", hp=150)
    state = _state(p1_active=attacker, p1_bench=[_inst(defender_def, "bench-a", zone=Zone.BENCH)], p2_active=defender)
    state.active_stadium = _stadium_inst("sv06-153", "Jamming Tower", "jam")

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 20)

    assert dmg == 40, f"Expected only weakness damage under Jamming Tower, got {dmg}"


def test_non_hops_pokemon_with_hops_choice_band_gets_no_damage_bonus():
    attacker_def = _make_card(
        "t43-hop-001",
        "Plain Corviknight",
        types=["Fighting"],
        attacks=[AttackDef(name="Hit", damage="20", cost=[])],
    )
    defender_def = _make_card(
        "t43-hop-002",
        "Defender",
        hp=150,
        types=["Colorless"],
        weaknesses=[WeaknessDef(type="Fighting", value="×2")],
    )
    card_registry.register(attacker_def)
    card_registry.register(defender_def)

    attacker = _inst(attacker_def, "atk")
    attacker.tools_attached = ["sv09-148"]
    defender = _inst(defender_def, "def", hp=150)
    state = _state(p1_active=attacker, p1_bench=[_inst(defender_def, "bench-a", zone=Zone.BENCH)], p2_active=defender)

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 20)

    assert dmg == 40


def test_hops_pokemon_without_hops_choice_band_gets_no_damage_bonus():
    attacker_def = _make_card(
        "sv09-108",
        "Hop's Corviknight",
        types=["Fighting"],
        attacks=[AttackDef(name="Hit", damage="20", cost=[])],
    )
    defender_def = _make_card(
        "t43-hop-003",
        "Defender",
        hp=150,
        types=["Colorless"],
        weaknesses=[WeaknessDef(type="Fighting", value="×2")],
    )
    card_registry.register(attacker_def)
    card_registry.register(defender_def)

    attacker = _inst(attacker_def, "atk")
    defender = _inst(defender_def, "def", hp=150)
    state = _state(p1_active=attacker, p1_bench=[_inst(defender_def, "bench-a", zone=Zone.BENCH)], p2_active=defender)

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 20)

    assert dmg == 40


def test_jamming_tower_disables_hops_choice_band_cost_reduction():
    attacker_def = _make_card(
        "sv09-136",
        "Hop's Dubwool",
        attacks=[AttackDef(name="Headbutt", damage="40", cost=["Colorless"])],
    )
    bench_def = _make_card("t43-bench-001", "BenchMon")
    card_registry.register(attacker_def)
    card_registry.register(bench_def)

    attacker = _inst(attacker_def, "atk")
    attacker.tools_attached = ["sv09-148"]
    state = _state(p1_active=attacker, p1_bench=[_inst(bench_def, "bench")], p2_active=_inst(bench_def, "opp"))
    state.phase = Phase.ATTACK

    attack_actions = [a for a in ActionValidator.get_legal_actions(state, "p1") if a.action_type == ActionType.ATTACK]
    assert attack_actions, "Hop's Choice Band should reduce a {C} attack to zero cost"

    state.active_stadium = _stadium_inst("sv06-153", "Jamming Tower", "jam")
    jammed_actions = [a for a in ActionValidator.get_legal_actions(state, "p1") if a.action_type == ActionType.ATTACK]
    assert not jammed_actions, "Jamming Tower should suppress Hop's Choice Band cost reduction"


def test_gravity_gemstone_adds_retreat_cost_for_both_actives():
    active_def = _make_card("t43-ret-001", "Retreater", retreat_cost=1)
    bench_def = _make_card("t43-ret-002", "BenchMon")
    holder_def = _make_card("t43-ret-003", "Holder", retreat_cost=1)
    for cdef in (active_def, bench_def, holder_def):
        card_registry.register(cdef)

    active = _inst(active_def, "active")
    active.energy_attached = [EnergyAttachment(EnergyType.COLORLESS, "e1", "e1", [EnergyType.COLORLESS])]
    holder = _inst(holder_def, "holder")
    holder.tools_attached = ["sv07-137"]
    state = _state(p1_active=active, p1_bench=[_inst(bench_def, "bench")], p2_active=holder, p2_bench=[_inst(bench_def, "opp-bench")])

    retreat_actions = [a for a in ActionValidator.get_legal_actions(state, "p1") if a.action_type == ActionType.RETREAT]
    assert not retreat_actions, "Gravity Gemstone should raise retreat cost from 1 to 2"

    state.active_stadium = _stadium_inst("sv06-153", "Jamming Tower", "jam")
    retreat_actions = [a for a in ActionValidator.get_legal_actions(state, "p1") if a.action_type == ActionType.RETREAT]
    assert retreat_actions, "Jamming Tower should suppress Gravity Gemstone"


def test_gravity_gemstone_holder_active_increases_own_retreat_cost():
    active_def = _make_card("t43-ret-004", "Retreater", retreat_cost=1)
    bench_def = _make_card("t43-ret-005", "BenchMon")
    opp_def = _make_card("t43-ret-006", "Opponent", retreat_cost=1)
    for cdef in (active_def, bench_def, opp_def):
        card_registry.register(cdef)

    active = _inst(active_def, "active")
    active.tools_attached = ["sv07-137"]
    active.energy_attached = [EnergyAttachment(EnergyType.COLORLESS, "e1", "e1", [EnergyType.COLORLESS])]
    state = _state(p1_active=active, p1_bench=[_inst(bench_def, "bench")], p2_active=_inst(opp_def, "opp"), p2_bench=[_inst(bench_def, "opp-bench")])

    retreat_actions = [a for a in ActionValidator.get_legal_actions(state, "p1") if a.action_type == ActionType.RETREAT]

    assert not retreat_actions, "Active holder should also pay +1 retreat cost"


def test_gravity_gemstone_holder_benched_does_not_increase_retreat_cost():
    active_def = _make_card("t43-ret-007", "Retreater", retreat_cost=1)
    bench_def = _make_card("t43-ret-008", "BenchMon")
    holder_def = _make_card("t43-ret-009", "Holder", retreat_cost=1)
    opp_def = _make_card("t43-ret-010", "Opponent", retreat_cost=1)
    for cdef in (active_def, bench_def, holder_def, opp_def):
        card_registry.register(cdef)

    active = _inst(active_def, "active")
    active.energy_attached = [EnergyAttachment(EnergyType.COLORLESS, "e1", "e1", [EnergyType.COLORLESS])]
    benched_holder = _inst(holder_def, "holder", zone=Zone.BENCH)
    benched_holder.tools_attached = ["sv07-137"]
    state = _state(
        p1_active=active,
        p1_bench=[_inst(bench_def, "bench")],
        p2_active=_inst(opp_def, "opp"),
        p2_bench=[benched_holder],
    )

    retreat_actions = [a for a in ActionValidator.get_legal_actions(state, "p1") if a.action_type == ActionType.RETREAT]

    assert retreat_actions, "Benched Gravity Gemstone holder should not tax retreat"


def test_granite_cave_reduces_active_damage_to_stevens_pokemon():
    attacker_def = _make_card("t43-granite-001", "Attacker", attacks=[AttackDef(name="Strike", damage="100", cost=[])])
    defender_def = _make_card("t43-granite-002", "Steven's Metagross", hp=160)
    card_registry.register(attacker_def)
    card_registry.register(defender_def)

    state = _state(
        p1_active=_inst(attacker_def, "atk"),
        p1_bench=[_inst(defender_def, "bench-a", zone=Zone.BENCH)],
        p2_active=_inst(defender_def, "def", hp=160),
    )
    state.active_stadium = _stadium_inst("sv10-166", "Granite Cave", "granite")

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 100)

    assert dmg == 70


def test_granite_cave_does_not_reduce_damage_for_non_stevens_pokemon():
    attacker_def = _make_card("t43-granite-005", "Attacker", attacks=[AttackDef(name="Strike", damage="100", cost=[])])
    defender_def = _make_card("t43-granite-006", "Metagross", hp=160)
    card_registry.register(attacker_def)
    card_registry.register(defender_def)

    state = _state(
        p1_active=_inst(attacker_def, "atk"),
        p1_bench=[_inst(defender_def, "bench-a", zone=Zone.BENCH)],
        p2_active=_inst(defender_def, "def", hp=160),
    )
    state.active_stadium = _stadium_inst("sv10-166", "Granite Cave", "granite")

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 100)

    assert dmg == 100


def test_stevens_pokemon_gets_no_granite_cave_reduction_without_stadium():
    attacker_def = _make_card("t43-granite-007", "Attacker", attacks=[AttackDef(name="Strike", damage="100", cost=[])])
    defender_def = _make_card("t43-granite-008", "Steven's Metagross", hp=160)
    card_registry.register(attacker_def)
    card_registry.register(defender_def)

    state = _state(
        p1_active=_inst(attacker_def, "atk"),
        p1_bench=[_inst(defender_def, "bench-a", zone=Zone.BENCH)],
        p2_active=_inst(defender_def, "def", hp=160),
    )

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 100)

    assert dmg == 100


def test_granite_cave_reduction_clamps_at_zero():
    attacker_def = _make_card("t43-granite-009", "Attacker", attacks=[AttackDef(name="Strike", damage="20", cost=[])])
    defender_def = _make_card("t43-granite-010", "Steven's Beldum", hp=60)
    card_registry.register(attacker_def)
    card_registry.register(defender_def)

    state = _state(
        p1_active=_inst(attacker_def, "atk"),
        p1_bench=[_inst(defender_def, "bench-a", zone=Zone.BENCH)],
        p2_active=_inst(defender_def, "def", hp=60),
    )
    state.active_stadium = _stadium_inst("sv10-166", "Granite Cave", "granite")

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 20)

    assert dmg == 0
    assert state.p2.active.damage_counters == 0


def test_granite_cave_reduces_bench_damage_to_stevens_pokemon():
    bench_def = _make_card("t43-granite-003", "Steven's Beldum", hp=80)
    opp_def = _make_card("t43-granite-004", "Opponent")
    card_registry.register(bench_def)
    card_registry.register(opp_def)

    target = _inst(bench_def, "bench-target", zone=Zone.BENCH, hp=80)
    state = _state(
        p1_active=_inst(opp_def, "atk"),
        p2_active=_inst(opp_def, "opp"),
        p2_bench=[target],
    )
    state.active_stadium = _stadium_inst("sv10-166", "Granite Cave", "granite")

    _apply_bench_damage(state, "p2", target, 50)

    assert target.damage_counters == 2
    assert target.current_hp == 60


def test_haban_berry_reduces_dragon_damage_and_discards_tool():
    attacker_def = _make_card("t43-haban-001", "Dragon Attacker", types=["Dragon"], attacks=[AttackDef(name="Claw", damage="100", cost=[])])
    defender_def = _make_card("t43-haban-002", "Defender", hp=150)
    card_registry.register(attacker_def)
    card_registry.register(defender_def)

    attacker = _inst(attacker_def, "atk")
    defender = _inst(defender_def, "def", hp=150)
    defender.tools_attached = ["sv08.5-111"]
    state = _state(p1_active=attacker, p1_bench=[_inst(defender_def, "bench-a", zone=Zone.BENCH)], p2_active=defender)

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 100)

    assert dmg == 40
    assert "sv08.5-111" not in defender.tools_attached


def test_haban_berry_non_dragon_attack_does_not_reduce_or_discard():
    attacker_def = _make_card("t43-haban-005", "Water Attacker", types=["Water"], attacks=[AttackDef(name="Splash", damage="100", cost=[])])
    defender_def = _make_card("t43-haban-006", "Defender", hp=150)
    card_registry.register(attacker_def)
    card_registry.register(defender_def)

    attacker = _inst(attacker_def, "atk")
    defender = _inst(defender_def, "def", hp=150)
    defender.tools_attached = ["sv08.5-111"]
    state = _state(p1_active=attacker, p1_bench=[_inst(defender_def, "bench-a", zone=Zone.BENCH)], p2_active=defender)

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 100)

    assert dmg == 100
    assert "sv08.5-111" in defender.tools_attached


def test_haban_berry_reduces_dragon_bench_damage_and_discards_tool():
    dragon_def = _make_card("t43-haban-007", "Dragon Attacker", types=["Dragon"], attacks=[AttackDef(name="Claw", damage="100", cost=[])])
    defender_def = _make_card("t43-haban-008", "Defender", hp=150)
    opp_def = _make_card("t43-haban-009", "Opponent", hp=150)
    card_registry.register(dragon_def)
    card_registry.register(defender_def)
    card_registry.register(opp_def)

    benched = _inst(defender_def, "bench-target", zone=Zone.BENCH, hp=150)
    benched.tools_attached = ["sv08.5-111"]
    state = _state(
        p1_active=_inst(dragon_def, "atk"),
        p2_active=_inst(opp_def, "opp"),
        p2_bench=[benched],
    )

    _apply_bench_damage(state, "p2", benched, 100)

    assert benched.damage_counters == 4
    assert benched.current_hp == 110
    assert "sv08.5-111" not in benched.tools_attached


def test_haban_berry_bench_damage_clamps_at_zero_and_discards_tool():
    dragon_def = _make_card("t43-haban-010", "Dragon Attacker", types=["Dragon"], attacks=[AttackDef(name="Claw", damage="50", cost=[])])
    defender_def = _make_card("t43-haban-011", "Defender", hp=150)
    opp_def = _make_card("t43-haban-012", "Opponent", hp=150)
    card_registry.register(dragon_def)
    card_registry.register(defender_def)
    card_registry.register(opp_def)

    benched = _inst(defender_def, "bench-target", zone=Zone.BENCH, hp=150)
    benched.tools_attached = ["sv08.5-111"]
    state = _state(
        p1_active=_inst(dragon_def, "atk"),
        p2_active=_inst(opp_def, "opp"),
        p2_bench=[benched],
    )

    _apply_bench_damage(state, "p2", benched, 50)

    assert benched.damage_counters == 0
    assert benched.current_hp == 150
    assert "sv08.5-111" not in benched.tools_attached


def test_haban_berry_non_dragon_bench_damage_does_not_reduce_or_discard():
    attacker_def = _make_card("t43-haban-013", "Water Attacker", types=["Water"], attacks=[AttackDef(name="Splash", damage="100", cost=[])])
    defender_def = _make_card("t43-haban-014", "Defender", hp=150)
    opp_def = _make_card("t43-haban-015", "Opponent", hp=150)
    card_registry.register(attacker_def)
    card_registry.register(defender_def)
    card_registry.register(opp_def)

    benched = _inst(defender_def, "bench-target", zone=Zone.BENCH, hp=150)
    benched.tools_attached = ["sv08.5-111"]
    state = _state(
        p1_active=_inst(attacker_def, "atk"),
        p2_active=_inst(opp_def, "opp"),
        p2_bench=[benched],
    )

    _apply_bench_damage(state, "p2", benched, 100)

    assert benched.damage_counters == 10
    assert benched.current_hp == 50
    assert "sv08.5-111" in benched.tools_attached


def test_jamming_tower_disables_haban_berry_bench_reduction_and_discard():
    dragon_def = _make_card("t43-haban-016", "Dragon Attacker", types=["Dragon"], attacks=[AttackDef(name="Claw", damage="100", cost=[])])
    defender_def = _make_card("t43-haban-017", "Defender", hp=150)
    opp_def = _make_card("t43-haban-018", "Opponent", hp=150)
    card_registry.register(dragon_def)
    card_registry.register(defender_def)
    card_registry.register(opp_def)

    benched = _inst(defender_def, "bench-target", zone=Zone.BENCH, hp=150)
    benched.tools_attached = ["sv08.5-111"]
    state = _state(
        p1_active=_inst(dragon_def, "atk"),
        p2_active=_inst(opp_def, "opp"),
        p2_bench=[benched],
    )
    state.active_stadium = _stadium_inst("sv06-153", "Jamming Tower", "jam")

    _apply_bench_damage(state, "p2", benched, 100)

    assert benched.damage_counters == 10
    assert benched.current_hp == 50
    assert "sv08.5-111" in benched.tools_attached


def test_jamming_tower_disables_haban_berry_reduction_and_discard():
    attacker_def = _make_card("t43-haban-003", "Dragon Attacker", types=["Dragon"], attacks=[AttackDef(name="Claw", damage="100", cost=[])])
    defender_def = _make_card("t43-haban-004", "Defender", hp=150)
    card_registry.register(attacker_def)
    card_registry.register(defender_def)

    attacker = _inst(attacker_def, "atk")
    defender = _inst(defender_def, "def", hp=150)
    defender.tools_attached = ["sv08.5-111"]
    state = _state(p1_active=attacker, p1_bench=[_inst(defender_def, "bench-a", zone=Zone.BENCH)], p2_active=defender)
    state.active_stadium = _stadium_inst("sv06-153", "Jamming Tower", "jam")

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 100)

    assert dmg == 100
    assert "sv08.5-111" in defender.tools_attached
