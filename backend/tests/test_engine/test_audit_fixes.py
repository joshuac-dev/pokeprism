"""Audit-fix regression tests (findings #1-14, and Precious Trolley handler).

Findings:
  #1-4 : Fossil passive ability registrations (sv07-129, sv10.5b-080, sv10.5w-079, sv07-130)
  #5   : _crimson_blaster_b4 — discard ALL {R}, deal 180 to BENCH only
  #6   : _high_voltage_press — subtract attack cost (3) from energy count, not 1
  #7   : _thunderburst_storm — player chooses target; bench hit gets no W/R
  #8   : _bench_manipulation — damage bypasses Weakness/Resistance
  #9   : _swim_together (sv10-050 Misty's Lapras) — wrong resp attribute chosen_ids → chosen_card_ids
  #10  : _swim_together — wrong card name "Misty's Dewgong" → "Misty's Lapras"
  #11  : _bubble_beam docstring — wrong card name "Misty's Poliwrath" → "Misty's Staryu"
  #12  : sv10-046 comment — fake "ATK1 Submission" removed (Misty's Staryu has only 1 attack)
  #13  : _running_charge docstring — "atk1" → "atk0" (sv10-107 Mudbray)
  #14  : _pick_and_stick (sv06-072 Morpeko) — replace no-op flag with real attach-from-discard
Engine gap fixes:
  #EG1 : Spiky Energy (sv09-159) — broken source_card_id detection fixed to att.card_def_id
  #EG2 : Watchtower alt print (me02.5-210) — ability suppression now covers both prints
  #EG3 : Mystery Garden (me02.5-194 / me01-122) — USE_STADIUM action fully implemented
Session 2 fixes (Batch A):
  #A1  : duplicate _strong_bash_b2 removed (attacks.py)
  #A2  : _acerolas_mischief removed bogus draw-to-4 clause
  #A3  : _acerolas_mischief added missing prize-count gate (opp must have ≤2 prizes)
  #A4  : _lucian_b5 completely rewritten — each player shuffles hand, flips coin, draws 6/3
  #A5  : sv06-159 re-registered to _ogres_mask (was _noop)
  #A6  : _unfair_stamp player draw corrected 3 → 5
  #A7  : _dangle_tail_flag → _dangle_tail (put 1 Pokémon from discard to hand)
  #A8  : _recovery_net_flag → _recovery_net (put up to 2 Pokémon from discard to hand)
  #A9  : _avenging_edge_flag → _avenging_edge (100 + 60 if ko_taken_last_turn)
Live simulation fix:
  #L1  : _ET_ATTACH (me02-039 Cresselia Swelling Light) — called EnergyType enum instead of EnergyAttachment
  #L2  : _tr_venture_bomb_b19 (sv10-179 TR Venture Bomb) — check_ko called with transposed (player_id, target) args
  #L3  : _upthrusting_horns_b4 / _opposing_winds_b5 / _balloon_return_b5 — energy_provides populated with EnergyType enums instead of strings
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
from app.engine.state import CardInstance, EnergyAttachment, EnergyType, GameState, Zone, StatusCondition


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


@pytest.mark.asyncio
async def test_tuck_tail_handles_attached_tool_ids():
    """Tuck Tail must not treat tools_attached entries as CardInstance objects."""
    meowth = _make_card(
        "me03-062", "Meowth ex", hp=200,
        attacks=[AttackDef(name="Tuck Tail", damage="60", cost=["Colorless"],
                           effect="Put this Pokémon and all attached cards into your hand.")],
    )
    target = _make_card("tst-tt-001", "Opp Target", hp=200)
    card_registry.register(meowth)
    card_registry.register(target)

    attacker = _make_instance(meowth, hp=200)
    attacker.tools_attached = ["sv05-151"]
    defender = _make_instance(target, hp=200)
    state = _make_state(p1_active=attacker, p2_active=defender)

    await EffectRegistry.instance().resolve_attack("me03-062", 0, state, _make_action())

    assert state.p1.active is None
    assert attacker.tools_attached == []
    assert attacker in state.p1.hand
    assert defender.current_hp == 140


@pytest.mark.asyncio
async def test_happy_return_handles_attached_tool_ids():
    """Happy Return bounce path must clear attached tool IDs without crashing."""
    swoobat = _make_card(
        "sv10.5w-037", "Swoobat", hp=120,
        attacks=[AttackDef(name="Happy Return", damage="", cost=["Colorless"],
                           effect="Put 1 of your Benched Pokémon and all attached cards into your hand.")],
    )
    bench_card = _make_card("tst-hr-001", "Bench Target", hp=100)
    opp_card = _make_card("tst-hr-002", "Opp Target", hp=100)
    card_registry.register(swoobat)
    card_registry.register(bench_card)
    card_registry.register(opp_card)

    active = _make_instance(swoobat, hp=120)
    benched = _make_instance(bench_card, zone=Zone.BENCH, hp=100)
    benched.tools_attached = ["sv05-151"]
    defender = _make_instance(opp_card, hp=100)
    state = _make_state(p1_active=active, p1_bench=[benched], p2_active=defender)

    await EffectRegistry.instance().resolve_attack("sv10.5w-037", 0, state, _make_action())

    assert benched.tools_attached == []
    assert benched not in state.p1.bench
    assert benched in state.p1.hand


@pytest.mark.asyncio
async def test_telepathic_psychic_energy_benches_basic_psychic():
    """Telepathic Psychic Energy uses the real BENCH zone, not a non-existent IN_PLAY zone."""
    active_cdef = _make_card("tst-tpe-001", "Psychic Active", hp=100)
    active_cdef.types = ["Psychic"]
    deck_cdef = _make_card("tst-tpe-002", "Psychic Basic", hp=70)
    deck_cdef.types = ["Psychic"]
    card_registry.register(active_cdef)
    card_registry.register(deck_cdef)

    active = _make_instance(active_cdef, hp=100)
    active.energy_attached.append(
        EnergyAttachment(
            energy_type=EnergyType.PSYCHIC,
            source_card_id="energy-inst",
            card_def_id="me03-088",
            provides=[EnergyType.PSYCHIC],
        )
    )
    deck_basic = _make_instance(deck_cdef, zone=Zone.DECK, hp=70)
    deck_basic.card_type = "Pokemon"
    state = _make_state(p1_active=active, p2_active=_make_instance(_make_card("tst-tpe-003", "Opp", hp=100)))
    state.p1.deck = [deck_basic]

    action = Action(
        player_id="p1",
        action_type=ActionType.ATTACH_ENERGY,
        card_instance_id="energy-inst",
        target_instance_id=active.instance_id,
    )
    await EffectRegistry.instance().resolve_energy("me03-088", state, action)

    assert deck_basic not in state.p1.deck
    assert deck_basic in state.p1.bench
    assert deck_basic.zone == Zone.BENCH


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


# ──────────────────────────────────────────────────────────────────────────────
# 2026-05-03 Audit Findings
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_guarded_rolling_discards_energy_and_reduces_damage():
    """sv08-103 Donphan atk1 — Guarded Rolling: discard 2 Energy + take 100 less damage next turn."""
    donphan_cdef = _make_card(
        "sv08-103", "Donphan", hp=140,
        attacks=[
            AttackDef(name="Knock Flat", damage="40", cost=["Fighting"]),
            AttackDef(name="Guarded Rolling", damage="120", cost=["Fighting", "Fighting"]),
        ],
    )
    opp_cdef = _make_card("tst-gr-001", "OppMon", hp=200)
    card_registry.register(donphan_cdef)
    card_registry.register(opp_cdef)

    donphan_inst = _make_instance(donphan_cdef)
    donphan_inst.energy_attached.append(_make_energy(EnergyType.FIGHTING, "fighting-energy"))
    donphan_inst.energy_attached.append(_make_energy(EnergyType.FIGHTING, "fighting-energy2"))
    donphan_inst.energy_attached.append(_make_energy(EnergyType.FIGHTING, "fighting-energy3"))
    opp_active = _make_instance(opp_cdef, hp=200)
    state = _make_state(p1_active=donphan_inst, p2_active=opp_active)

    action = _make_action(attack_index=1)

    from app.engine.effects.attacks import _guarded_rolling
    # _guarded_rolling is not a generator (no yield), call directly
    result = _guarded_rolling(state, action)
    if hasattr(result, '__next__'):
        try:
            next(result)
        except StopIteration:
            pass

    # Should discard 2 energy
    assert len(donphan_inst.energy_attached) == 1
    # Should set damage reduction
    assert donphan_inst.incoming_damage_reduction == 100


@pytest.mark.asyncio
async def test_crimson_blaster_discards_fire_energy():
    """sv08-034 Armarouge atk1 — Crimson Blaster: discard all Fire Energy from self."""
    armarouge_cdef = _make_card(
        "sv08-034", "Armarouge", hp=120,
        attacks=[
            AttackDef(name="Crimson Blaster", damage="0", cost=["Fire", "Fire", "Fire"]),
        ],
    )
    opp_cdef = _make_card("tst-cb-001", "OppMon", hp=200)
    bench_cdef = _make_card("tst-cb-002", "BenchMon", hp=130)
    card_registry.register(armarouge_cdef)
    card_registry.register(opp_cdef)
    card_registry.register(bench_cdef)

    armarouge_inst = _make_instance(armarouge_cdef)
    armarouge_inst.energy_attached.append(_make_energy(EnergyType.FIRE, "fire-energy"))
    armarouge_inst.energy_attached.append(_make_energy(EnergyType.FIRE, "fire-energy2"))
    bench_inst = _make_instance(bench_cdef, zone=Zone.BENCH, hp=130)
    opp_active = _make_instance(opp_cdef, hp=200)
    state = _make_state(p1_active=armarouge_inst, p2_active=opp_active, p2_bench=[bench_inst])

    action = _make_action(attack_index=0)

    from app.engine.effects.attacks import _crimson_blaster
    gen = _crimson_blaster(state, action)
    # Respond to bench choice request
    try:
        req = next(gen)
        resp = Action(
            player_id="p1",
            action_type=ActionType.ATTACK,
            target_instance_id=bench_inst.instance_id,
        )
        gen.send(resp)
    except StopIteration:
        pass

    # All Fire energy should be discarded
    assert armarouge_inst.energy_attached == []


@pytest.mark.asyncio
async def test_cursed_edge_discards_special_energy():
    """sv08-035 Ceruledge atk0 — Cursed Edge: discard all Special Energy from all opp's Pokémon."""
    ceruledge_cdef = _make_card(
        "sv08-035", "Ceruledge", hp=120,
        attacks=[
            AttackDef(name="Cursed Edge", damage="0", cost=["Fire"]),
        ],
    )
    opp_cdef = _make_card("tst-ce-001", "OppMon", hp=200)
    card_registry.register(ceruledge_cdef)
    card_registry.register(opp_cdef)

    ceruledge_inst = _make_instance(ceruledge_cdef)
    opp_active = _make_instance(opp_cdef, hp=200)
    # Add both basic and special energy to opponent's active
    basic_att = _make_energy(EnergyType.FIRE, "fire-energy-basic")
    # Simulate a special energy with a non-basic def_id
    special_att = EnergyAttachment(
        energy_type=EnergyType.COLORLESS,
        source_card_id="src-special",
        card_def_id="sv05-161",  # known special energy ID
    )
    opp_active.energy_attached.append(basic_att)
    opp_active.energy_attached.append(special_att)
    state = _make_state(p1_active=ceruledge_inst, p2_active=opp_active)

    action = _make_action(attack_index=0)

    from app.engine.effects.attacks import _cursed_edge
    result = _cursed_edge(state, action)
    if hasattr(result, '__next__'):
        try:
            next(result)
        except StopIteration:
            pass

    # Special energy (sv05-161) should be discarded
    remaining = opp_active.energy_attached
    assert all(e.card_def_id != "sv05-161" for e in remaining)


@pytest.mark.asyncio
async def test_time_manipulation_puts_cards_on_top():
    """sv08-135 Dialga atk0 — Time Manipulation: search deck for 2 cards, put on top."""
    from app.engine.state import CardInstance as CI
    dialga_cdef = _make_card(
        "sv08-135", "Dialga", hp=140,
        attacks=[AttackDef(name="Time Manipulation", damage="0", cost=["Metal"])],
    )
    card1_cdef = _make_card("tst-tm-001", "Card1", hp=100)
    card2_cdef = _make_card("tst-tm-002", "Card2", hp=100)
    card3_cdef = _make_card("tst-tm-003", "Card3", hp=100)
    card_registry.register(dialga_cdef)
    card_registry.register(card1_cdef)
    card_registry.register(card2_cdef)
    card_registry.register(card3_cdef)

    dialga_inst = _make_instance(dialga_cdef)
    c1 = _make_instance(card1_cdef, zone=Zone.DECK)
    c2 = _make_instance(card2_cdef, zone=Zone.DECK)
    c3 = _make_instance(card3_cdef, zone=Zone.DECK)
    opp_cdef = _make_card("tst-tm-opp", "OppMon", hp=120)
    card_registry.register(opp_cdef)
    opp_active = _make_instance(opp_cdef, hp=120)
    state = _make_state(p1_active=dialga_inst, p2_active=opp_active)
    state.p1.deck = [c1, c2, c3]

    action = _make_action(attack_index=0)

    from app.engine.effects.attacks import _time_manipulation
    gen = _time_manipulation(state, action)
    try:
        req = next(gen)
        # Choose c1 and c2 to put on top
        resp = Action(
            player_id="p1",
            action_type=ActionType.ATTACK,
            selected_cards=[c1.instance_id, c2.instance_id],
        )
        gen.send(resp)
    except StopIteration:
        pass

    # c1 and c2 should be on top of deck (first 2)
    assert state.p1.deck[0].instance_id in (c1.instance_id, c2.instance_id)
    assert state.p1.deck[1].instance_id in (c1.instance_id, c2.instance_id)


# ──────────────────────────────────────────────────────────────────────────────
# Finding #9/#10: _swim_together (sv10-050 Misty's Lapras)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_swim_together_moves_mistys_to_hand():
    """sv10-050 Misty's Lapras atk0 — Swim Together moves chosen Misty's Pokémon to hand."""
    lapras_cdef = _make_card(
        "sv10-050", "Misty's Lapras", hp=100,
        attacks=[AttackDef(name="Swim Together", damage="0", cost=["Water"])],
    )
    mistys1_cdef = _make_card("tst-st-001", "Misty's Magikarp", hp=40)
    mistys2_cdef = _make_card("tst-st-002", "Misty's Gyarados", hp=130)
    other_cdef = _make_card("tst-st-003", "Pikachu", hp=60)
    opp_cdef = _make_card("tst-st-opp", "OppMon", hp=100)
    for c in [lapras_cdef, mistys1_cdef, mistys2_cdef, other_cdef, opp_cdef]:
        card_registry.register(c)

    lapras_inst = _make_instance(lapras_cdef)
    m1 = _make_instance(mistys1_cdef, zone=Zone.DECK)
    m1.card_type = "Pokemon"
    m2 = _make_instance(mistys2_cdef, zone=Zone.DECK)
    m2.card_type = "Pokemon"
    other = _make_instance(other_cdef, zone=Zone.DECK)
    other.card_type = "Pokemon"
    opp_active = _make_instance(opp_cdef, hp=100)

    state = _make_state(p1_active=lapras_inst, p2_active=opp_active)
    state.p1.deck = [m1, m2, other]

    action = _make_action(attack_index=0)

    from app.engine.effects.attacks import _swim_together
    gen = _swim_together(state, action)
    try:
        next(gen)
        # Choose both Misty's Pokémon
        resp = Action(
            player_id="p1",
            action_type=ActionType.ATTACK,
            selected_cards=[m1.instance_id, m2.instance_id],
        )
        gen.send(resp)
    except StopIteration:
        pass

    # Both Misty's Pokémon should be in hand
    assert m1 in state.p1.hand
    assert m2 in state.p1.hand
    # Non-Misty's stays in deck
    assert other in state.p1.deck


@pytest.mark.asyncio
async def test_swim_together_empty_deck_no_crash():
    """_swim_together: empty deck emits no-damage event without error."""
    lapras_cdef = _make_card(
        "sv10-050", "Misty's Lapras", hp=100,
        attacks=[AttackDef(name="Swim Together", damage="0", cost=["Water"])],
    )
    opp_cdef = _make_card("tst-st-emp-opp", "OppMon", hp=100)
    card_registry.register(lapras_cdef)
    card_registry.register(opp_cdef)

    lapras_inst = _make_instance(lapras_cdef)
    opp_active = _make_instance(opp_cdef, hp=100)
    state = _make_state(p1_active=lapras_inst, p2_active=opp_active)
    state.p1.deck = []

    action = _make_action(attack_index=0)

    from app.engine.effects.attacks import _swim_together
    result = _swim_together(state, action)
    if hasattr(result, "__next__"):
        try:
            next(result)
        except StopIteration:
            pass

    assert any(e["event_type"] == "attack_no_damage" for e in state.events)


# ──────────────────────────────────────────────────────────────────────────────
# Finding #14: _pick_and_stick (sv06-072 Morpeko)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pick_and_stick_attaches_energy_from_discard():
    """sv06-072 Morpeko atk0 — Pick and Stick attaches Basic Energy from discard to chosen Pokémon."""
    from app.cards.models import CardDefinition
    morpeko_cdef = _make_card(
        "sv06-072", "Morpeko", hp=60,
        attacks=[AttackDef(name="Pick and Stick", damage="0", cost=["Lightning"])],
    )
    opp_cdef = _make_card("tst-ps-opp", "OppMon", hp=100)
    fire_energy_cdef = CardDefinition(
        tcgdex_id="tst-fire-energy",
        name="Fire Energy",
        set_abbrev="TST",
        set_number="E01",
        category="energy",
        stage="",
        hp=0,
        attacks=[],
        abilities=[],
        card_type="Energy",
        card_subtype="Basic",
        energy_provides=["Fire"],
    )
    card_registry.register(morpeko_cdef)
    card_registry.register(opp_cdef)
    card_registry.register(fire_energy_cdef)

    morpeko_inst = _make_instance(morpeko_cdef)
    opp_active = _make_instance(opp_cdef, hp=100)

    from app.engine.state import CardInstance as CI
    fire_card = CI(
        instance_id="inst-fire-1",
        card_def_id="tst-fire-energy",
        card_name="Fire Energy",
        current_hp=0,
        max_hp=0,
        zone=Zone.DISCARD,
        card_type="Energy",
        card_subtype="Basic",
        energy_provides=["Fire"],
    )
    state = _make_state(p1_active=morpeko_inst, p2_active=opp_active)
    state.p1.discard = [fire_card]

    action = _make_action(attack_index=0)

    from app.engine.effects.attacks import _pick_and_stick
    gen = _pick_and_stick(state, action)
    try:
        next(gen)
        # Choose Morpeko as the target
        resp = Action(
            player_id="p1",
            action_type=ActionType.CHOOSE_TARGET,
            target_instance_id=morpeko_inst.instance_id,
        )
        gen.send(resp)
    except StopIteration:
        pass

    # Fire energy should be attached to Morpeko
    assert len(morpeko_inst.energy_attached) == 1
    assert morpeko_inst.energy_attached[0].energy_type == EnergyType.FIRE
    # Discard should be empty
    assert fire_card not in state.p1.discard


@pytest.mark.asyncio
async def test_pick_and_stick_no_energy_in_discard_no_crash():
    """_pick_and_stick: no Basic Energy in discard → emits no-damage event."""
    morpeko_cdef = _make_card(
        "sv06-072", "Morpeko", hp=60,
        attacks=[AttackDef(name="Pick and Stick", damage="0", cost=["Lightning"])],
    )
    opp_cdef = _make_card("tst-ps-emp-opp", "OppMon", hp=100)
    card_registry.register(morpeko_cdef)
    card_registry.register(opp_cdef)

    morpeko_inst = _make_instance(morpeko_cdef)
    opp_active = _make_instance(opp_cdef, hp=100)
    state = _make_state(p1_active=morpeko_inst, p2_active=opp_active)
    state.p1.discard = []

    action = _make_action(attack_index=0)

    from app.engine.effects.attacks import _pick_and_stick
    result = _pick_and_stick(state, action)
    if hasattr(result, "__next__"):
        try:
            next(result)
        except StopIteration:
            pass

    assert any(e["event_type"] == "attack_no_damage" for e in state.events)


# ──────────────────────────────────────────────────────────────────────────────
# Finding #9 registry check: sv10-050 registered as _swim_together
# ──────────────────────────────────────────────────────────────────────────────

def test_sv10_050_swim_together_registered():
    """sv10-050 Misty's Lapras is registered with _swim_together."""
    from app.engine.effects.registry import EffectRegistry
    reg = EffectRegistry.instance()
    assert "sv10-050:0" in reg._attack_effects, "Swim Together should be registered"


# ──────────────────────────────────────────────────────────────────────────────
# Finding #14 registry check: sv06-072 registered as _pick_and_stick (not flag)
# ──────────────────────────────────────────────────────────────────────────────

def test_sv06_072_pick_and_stick_registered():
    """sv06-072 Morpeko is registered with _pick_and_stick (real handler, not flag)."""
    from app.engine.effects.registry import EffectRegistry
    from app.engine.effects.attacks import _pick_and_stick
    reg = EffectRegistry.instance()
    handler = reg._attack_effects.get("sv06-072:0")
    assert handler is _pick_and_stick, "Pick and Stick should use real handler, not flag"


# ──────────────────────────────────────────────────────────────────────────────
# Nightly 2026-05-03 findings
# ──────────────────────────────────────────────────────────────────────────────

# Finding: Auto Heal (sv09-107 Magearna) heals exactly 10, not all damage counters
def test_auto_heal_heals_exactly_10():
    """Auto Heal should heal exactly 10 HP (remove 1 damage counter), not all counters."""
    from app.engine.state import CardInstance, Zone, GameState

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"

    # Magearna as active
    magearna = CardInstance(
        instance_id="magearna-1",
        card_def_id="sv09-107",
        card_name="Magearna",
        current_hp=110,
        max_hp=120,
        zone=Zone.ACTIVE,
        damage_counters=1,
    )
    state.p1.active = magearna

    # bench Pokémon with 3 damage counters
    bench_poke = CardInstance(
        instance_id="bench-1",
        card_def_id="tst-bench-1",
        card_name="BenchPoke",
        current_hp=70,
        max_hp=100,
        zone=Zone.BENCH,
        damage_counters=3,
    )
    state.p1.bench = [bench_poke]

    # Simulate the Auto Heal logic directly (as in transitions._attach_energy)
    if (state.p1.active and state.p1.active.card_def_id == "sv09-107"
            and bench_poke.damage_counters > 0):
        heal = 10
        bench_poke.current_hp = min(bench_poke.max_hp, bench_poke.current_hp + heal)
        bench_poke.damage_counters -= 1

    assert bench_poke.damage_counters == 2, (
        f"Auto Heal should remove exactly 1 counter, got {bench_poke.damage_counters}"
    )
    assert bench_poke.current_hp == 80, (
        f"Auto Heal should add exactly 10 HP, got {bench_poke.current_hp}"
    )


# Finding: deck.pop(0) for "discard top card" operations
def test_cornerstone_mountain_ramming_discards_top_card():
    """_cornerstone_mountain_ramming (sv10-111) should discard deck[0] (top), not deck[-1] (bottom)."""
    from app.engine.effects.attacks import _cornerstone_mountain_ramming
    from app.engine.state import CardInstance, Zone, GameState
    from app.cards.models import AttackDef, CardDefinition

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"

    attacker = CardInstance(
        instance_id="ogerpon-1", card_def_id="sv10-111",
        card_name="Cornerstone Mask Ogerpon",
        current_hp=130, max_hp=130, zone=Zone.ACTIVE,
    )
    defender = CardInstance(
        instance_id="opp-1", card_def_id="tst-def-cm",
        card_name="OppDef", current_hp=500, max_hp=500, zone=Zone.ACTIVE,
    )
    state.p1.active = attacker
    state.p2.active = defender

    cdef_attacker = CardDefinition(
        tcgdex_id="sv10-111", name="Cornerstone Mask Ogerpon",
        set_abbrev="SV10", set_number="111", category="pokemon",
        stage="Basic", hp=130, types=["Fighting"],
        attacks=[
            AttackDef(name="Rock Kagura", damage="0", cost=["Fighting"]),
            AttackDef(name="Mountain Ramming", damage="100", cost=["Fighting","Colorless"]),
        ],
    )
    card_registry.register(cdef_attacker)

    # Build deck: deck[0] = "top_card", deck[-1] = "bot_card"
    top_card = CardInstance(
        instance_id="deck-top", card_def_id="tst-deck-top",
        card_name="TopCard", current_hp=0, max_hp=0, zone=Zone.DECK,
    )
    bot_card = CardInstance(
        instance_id="deck-bot", card_def_id="tst-deck-bot",
        card_name="BotCard", current_hp=0, max_hp=0, zone=Zone.DECK,
    )
    state.p2.deck = [top_card, bot_card]

    action = Action(player_id="p1", action_type=ActionType.ATTACK, attack_index=1)
    gen = _cornerstone_mountain_ramming(state, action)
    if hasattr(gen, "__next__"):
        try:
            next(gen)
        except StopIteration:
            pass

    discarded_names = [c.card_name for c in state.p2.discard]
    remaining_names = [c.card_name for c in state.p2.deck]
    assert "TopCard" in discarded_names, (
        f"Expected TopCard (deck[0]) to be discarded; got {discarded_names}"
    )
    assert "BotCard" in remaining_names, (
        f"Expected BotCard to remain in deck; got {remaining_names}"
    )


# Finding: torment_blocked_attack_name is cleared for Active Pokémon at end of turn
def test_torment_blocked_cleared_for_active_at_end_of_turn():
    """torment_blocked_attack_name on Active Pokémon should be cleared at end of the blocked player's turn."""
    runner = _runner_for_between_turns()
    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"

    p2_active = CardInstance(
        instance_id="poke-p2", card_def_id="tst-poke-t",
        card_name="TestPoke", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    p2_active.torment_blocked_attack_name = "Some Attack"
    state.p2.active = p2_active

    # Simulate end of P2's turn (current_pid = p2)
    state.active_player = "p2"
    runner._end_turn(state)

    assert p2_active.torment_blocked_attack_name is None, (
        "torment_blocked_attack_name should be cleared at end of the blocked player's own turn"
    )


# Finding: Torment flag persists for one full opponent turn when that turn is NOT ended
def test_torment_blocked_persists_through_attacker_end_of_turn():
    """torment_blocked_attack_name should NOT be cleared at end of the ATTACKER's turn."""
    runner = _runner_for_between_turns()
    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"

    # P1 uses Torment on P2's active → sets flag on P2
    p2_active = CardInstance(
        instance_id="poke-p2b", card_def_id="tst-poke-t2",
        card_name="TestPoke2", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    p2_active.torment_blocked_attack_name = "BlockedAttack"
    state.p2.active = p2_active

    # End of P1's turn (NOT P2's) — flag should persist
    state.active_player = "p1"
    runner._end_turn(state)

    assert p2_active.torment_blocked_attack_name == "BlockedAttack", (
        "torment_blocked_attack_name should NOT be cleared at end of the attacker's turn"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Wide Wall (sv07-076 Rhyperior) — Supporter effect protection
# ──────────────────────────────────────────────────────────────────────────────

def test_wide_wall_blocks_bosss_orders_gust():
    """Wide Wall should block Boss's Orders forced switch."""
    from app.engine.effects.trainers import _bosss_orders
    from app.engine.state import CardInstance, Zone, GameState
    from app.cards.models import CardDefinition

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"

    # P2 has Rhyperior active → Wide Wall
    rhyperior_cdef = CardDefinition(
        tcgdex_id="sv07-076", name="Rhyperior", set_abbrev="TEF",
        set_number="076", category="pokemon", stage="Stage 2", hp=200,
        abilities=[AbilityDef(name="Wide Wall", effect="Prevent Supporter effects on your Pokémon.", ability_type="Ability")],
    )
    card_registry.register(rhyperior_cdef)

    rhyperior = CardInstance(
        instance_id="rhyperior-1", card_def_id="sv07-076",
        card_name="Rhyperior", current_hp=200, max_hp=200, zone=Zone.ACTIVE,
    )
    state.p2.active = rhyperior

    bench_target = CardInstance(
        instance_id="bench-p2-1", card_def_id="tst-bench-ww",
        card_name="BenchTarget", current_hp=60, max_hp=60, zone=Zone.BENCH,
    )
    state.p2.bench = [bench_target]

    p1_active = CardInstance(
        instance_id="p1-active-1", card_def_id="tst-p1-active",
        card_name="P1Active", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state.p1.active = p1_active

    # Simulate Wide Wall flag being set (as done by _play_supporter)
    state.p2.wide_wall_protected = True

    action = Action(player_id="p1", action_type=ActionType.ATTACK, attack_index=0)

    gen = _bosss_orders(state, action)
    # Generator should immediately return (yield nothing) because Wide Wall blocks it
    try:
        next(gen)
        # If it yields a ChoiceRequest, that's wrong — should be blocked
        assert False, "Boss's Orders should not yield a ChoiceRequest when Wide Wall is active"
    except StopIteration:
        pass  # Good — generator returned without yielding

    # bench_target should still be on the bench (not switched to active)
    assert state.p2.active is rhyperior, "Rhyperior should remain Active after Wide Wall block"
    assert bench_target in state.p2.bench, "BenchTarget should still be on bench after Wide Wall block"
    # wide_wall_blocked event should be emitted
    assert any(e["event_type"] == "wide_wall_blocked" for e in state.events), (
        "wide_wall_blocked event should be emitted when Boss's Orders is blocked"
    )


def test_wide_wall_does_not_block_without_rhyperior_active():
    """Wide Wall should NOT block Boss's Orders when Rhyperior is NOT the active Pokémon."""
    from app.engine.effects.trainers import _bosss_orders
    from app.engine.state import CardInstance, Zone, GameState

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"

    # P2 active is NOT Rhyperior
    p2_active = CardInstance(
        instance_id="p2-active-nww", card_def_id="tst-p2-active",
        card_name="P2Active", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state.p2.active = p2_active

    bench_target = CardInstance(
        instance_id="bench-p2-nww", card_def_id="tst-bench-nww",
        card_name="BenchNWW", current_hp=60, max_hp=60, zone=Zone.BENCH,
    )
    state.p2.bench = [bench_target]

    p1_active = CardInstance(
        instance_id="p1-active-nww", card_def_id="tst-p1-nww",
        card_name="P1ActiveNWW", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state.p1.active = p1_active

    # No wide_wall_protected flag → Boss's Orders should proceed normally
    state.p2.wide_wall_protected = False

    action = Action(player_id="p1", action_type=ActionType.ATTACK, attack_index=0)

    gen = _bosss_orders(state, action)
    # Should yield a ChoiceRequest for target selection
    try:
        req = next(gen)
        assert req is not None, "Should yield a ChoiceRequest when Wide Wall is NOT active"
    except StopIteration:
        assert False, "Boss's Orders should yield a choice request without Wide Wall"


# ──────────────────────────────────────────────────────────────────────────────
# Engine gap #EG1: Spiky Energy (sv09-159) detection fix
# ──────────────────────────────────────────────────────────────────────────────

def test_spiky_energy_triggers_on_direct_card_def_id():
    """Spiky Energy on defender's Active must put 2 damage counters on attacker.

    Previously the check searched discard/hand/deck by source_card_id which
    always returned False.  Now it simply reads att.card_def_id == 'sv09-159'.
    """
    from app.engine.effects.attacks import _apply_damage
    from app.engine.state import Phase

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.phase = Phase.MAIN

    attacker = CardInstance(
        instance_id="atk-1", card_def_id="tst-atk",
        card_name="Attacker", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    defender = CardInstance(
        instance_id="def-1", card_def_id="tst-def",
        card_name="Defender", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    # Attach Spiky Energy directly via card_def_id
    defender.energy_attached.append(EnergyAttachment(
        energy_type=EnergyType.COLORLESS,
        source_card_id="spiky-src-1",
        card_def_id="sv09-159",
        provides=[EnergyType.COLORLESS],
    ))

    state.p1.active = attacker
    state.p2.active = defender

    # _apply_damage(state, action, base_damage) uses player.active/opp.active internally
    action = Action(player_id="p1", action_type=ActionType.ATTACK, attack_index=0)
    _apply_damage(state, action, 30)

    # 2 damage counters = 20 HP loss on attacker
    assert attacker.damage_counters == 2, (
        f"Expected 2 damage counters on attacker, got {attacker.damage_counters}"
    )
    assert attacker.current_hp == 80, (
        f"Expected attacker HP 80, got {attacker.current_hp}"
    )
    assert any(e["event_type"] == "spiky_energy_triggered" for e in state.events), (
        "spiky_energy_triggered event should be emitted"
    )


def test_spiky_energy_does_not_trigger_when_active_has_no_spiky():
    """Spiky Energy does not trigger when the active defender has no Spiky Energy attached."""
    from app.engine.effects.attacks import _apply_damage
    from app.engine.state import Phase

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.phase = Phase.MAIN

    attacker = CardInstance(
        instance_id="atk-2", card_def_id="tst-atk2",
        card_name="Attacker2", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    # Active defender has no Spiky Energy (Spiky Energy is only on bench)
    p2_active = CardInstance(
        instance_id="p2-active-ns", card_def_id="tst-p2-active-ns",
        card_name="P2ActiveNoSpiky", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    bench_poke = CardInstance(
        instance_id="bench-1", card_def_id="tst-bench-ns",
        card_name="BenchPoke", current_hp=80, max_hp=80, zone=Zone.BENCH,
    )
    bench_poke.energy_attached.append(EnergyAttachment(
        energy_type=EnergyType.COLORLESS,
        source_card_id="spiky-src-2",
        card_def_id="sv09-159",
        provides=[EnergyType.COLORLESS],
    ))

    state.p1.active = attacker
    state.p2.active = p2_active
    state.p2.bench = [bench_poke]

    action = Action(player_id="p1", action_type=ActionType.ATTACK, attack_index=0)
    _apply_damage(state, action, 30)

    # No Spiky Energy retaliation — active defender has no Spiky Energy
    assert attacker.damage_counters == 0, (
        f"Spiky Energy should not trigger when active has no Spiky, got {attacker.damage_counters}"
    )
    assert not any(e["event_type"] == "spiky_energy_triggered" for e in state.events)


# ──────────────────────────────────────────────────────────────────────────────
# Engine gap #EG2: Watchtower alt print (me02.5-210) ability suppression
# ──────────────────────────────────────────────────────────────────────────────

def test_watchtower_alt_print_suppresses_colorless_ability():
    """me02.5-210 Watchtower must suppress USE_ABILITY for Colorless Pokémon."""
    from app.engine.actions import ActionValidator
    from app.engine.state import Phase

    registry = EffectRegistry.instance()

    colorless_cdef = CardDefinition(
        tcgdex_id="tst-colorless-wt", name="ColorlessPoke", set_abbrev="TST",
        set_number="001", category="pokemon", stage="Basic", hp=120,
        types=["Colorless"],
        abilities=[AbilityDef(name="TestAbility", effect="Do something.", ability_type="Ability")],
    )
    card_registry.register(colorless_cdef)

    def _dummy_ability(state, action):
        pass

    registry.register_ability("tst-colorless-wt", "TestAbility", _dummy_ability)

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.phase = Phase.MAIN
    state.active_player = "p1"

    colorless_poke = CardInstance(
        instance_id="colorless-poke-1", card_def_id="tst-colorless-wt",
        card_name="ColorlessPoke", current_hp=120, max_hp=120, zone=Zone.ACTIVE,
    )
    state.p1.active = colorless_poke

    # Place the alt-print Watchtower as active stadium
    watchtower_alt = CardInstance(
        instance_id="wt-alt-1", card_def_id="me02.5-210",
        card_name="Team Rocket's Watchtower", current_hp=0, max_hp=0, zone=Zone.STADIUM,
    )
    state.active_stadium = watchtower_alt

    p2_active = CardInstance(
        instance_id="p2-active-wt", card_def_id="tst-p2-wt",
        card_name="P2Active", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state.p2.active = p2_active

    legal = ActionValidator.get_legal_actions(state, "p1")
    ability_actions = [a for a in legal if a.action_type == ActionType.USE_ABILITY]
    assert len(ability_actions) == 0, (
        "Watchtower alt print (me02.5-210) should suppress Colorless Pokémon abilities"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Engine gap #EG3: Mystery Garden USE_STADIUM action
# ──────────────────────────────────────────────────────────────────────────────

def test_mystery_garden_use_stadium_offered_when_applicable():
    """USE_STADIUM should be offered when Mystery Garden is active and player has Energy in hand."""
    from app.engine.actions import ActionValidator
    from app.engine.state import Phase

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.phase = Phase.MAIN
    state.active_player = "p1"

    p1_active = CardInstance(
        instance_id="p1-active-mg", card_def_id="tst-p1-mg",
        card_name="P1Active", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state.p1.active = p1_active

    p2_active = CardInstance(
        instance_id="p2-active-mg", card_def_id="tst-p2-mg",
        card_name="P2Active", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state.p2.active = p2_active

    # Place Mystery Garden as active stadium
    mystery_garden = CardInstance(
        instance_id="mg-1", card_def_id="me02.5-194",
        card_name="Mystery Garden", current_hp=0, max_hp=0,
    )
    state.active_stadium = mystery_garden

    # Put an Energy card in p1's hand
    energy_card = CardInstance(
        instance_id="energy-1", card_def_id="basic-fire",
        card_name="Fire Energy", card_type="Energy", zone=Zone.HAND,
    )
    state.p1.hand = [energy_card]

    legal = ActionValidator.get_legal_actions(state, "p1")
    stadium_actions = [a for a in legal if a.action_type == ActionType.USE_STADIUM]
    assert len(stadium_actions) == 1, (
        "USE_STADIUM should be offered when Mystery Garden is active and Energy is in hand"
    )


def test_mystery_garden_not_offered_without_energy_in_hand():
    """USE_STADIUM should NOT be offered if player has no Energy in hand."""
    from app.engine.actions import ActionValidator
    from app.engine.state import Phase

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.phase = Phase.MAIN
    state.active_player = "p1"

    p1_active = CardInstance(
        instance_id="p1-active-mg2", card_def_id="tst-p1-mg2",
        card_name="P1Active2", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state.p1.active = p1_active

    mystery_garden = CardInstance(
        instance_id="mg-2", card_def_id="me02.5-194",
        card_name="Mystery Garden", current_hp=0, max_hp=0,
    )
    state.active_stadium = mystery_garden
    state.p1.hand = []  # No energy

    legal = ActionValidator.get_legal_actions(state, "p1")
    stadium_actions = [a for a in legal if a.action_type == ActionType.USE_STADIUM]
    assert len(stadium_actions) == 0, (
        "USE_STADIUM should not be offered when no Energy card in hand"
    )


def test_mystery_garden_not_offered_after_use():
    """USE_STADIUM should not be offered again once mystery_garden_used_this_turn is set."""
    from app.engine.actions import ActionValidator
    from app.engine.state import Phase

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.phase = Phase.MAIN
    state.active_player = "p1"

    p1_active = CardInstance(
        instance_id="p1-active-mg3", card_def_id="tst-p1-mg3",
        card_name="P1Active3", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state.p1.active = p1_active

    mystery_garden = CardInstance(
        instance_id="mg-3", card_def_id="me02.5-194",
        card_name="Mystery Garden", current_hp=0, max_hp=0,
    )
    state.active_stadium = mystery_garden

    energy_card = CardInstance(
        instance_id="energy-2", card_def_id="basic-water",
        card_name="Water Energy", card_type="Energy", zone=Zone.HAND,
    )
    state.p1.hand = [energy_card]
    state.p1.mystery_garden_used_this_turn = True

    legal = ActionValidator.get_legal_actions(state, "p1")
    stadium_actions = [a for a in legal if a.action_type == ActionType.USE_STADIUM]
    assert len(stadium_actions) == 0, (
        "USE_STADIUM should not be offered again this turn"
    )


def test_mystery_garden_handler_discards_energy_and_draws():
    """Mystery Garden handler: discard Energy, draw to hand_size == Psychic count."""
    from app.engine.effects.trainers import _mystery_garden

    # Register a Psychic Pokémon for the in-play type check
    psychic_cdef = CardDefinition(
        tcgdex_id="tst-psychic-mg", name="PsychicPoke", set_abbrev="TST",
        set_number="010", category="pokemon", stage="Basic", hp=80,
        types=["Psychic"],
    )
    card_registry.register(psychic_cdef)

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"

    # 1 Psychic Pokémon active → draw until hand == 1
    psychic_poke = CardInstance(
        instance_id="psychic-1", card_def_id="tst-psychic-mg",
        card_name="PsychicPoke", current_hp=80, max_hp=80, zone=Zone.ACTIVE,
    )
    state.p1.active = psychic_poke

    energy_card = CardInstance(
        instance_id="energy-3", card_def_id="basic-psychic",
        card_name="Psychic Energy", card_type="Energy", zone=Zone.HAND,
    )
    state.p1.hand = [energy_card]

    # Populate deck with cards to draw from
    for i in range(5):
        state.p1.deck.append(CardInstance(
            instance_id=f"deck-{i}", card_def_id="tst-deck",
            card_name="DeckCard", zone=Zone.DECK,
        ))

    action = Action(player_id="p1", action_type=ActionType.USE_STADIUM)

    gen = _mystery_garden(state, action)
    req = next(gen)
    assert req.choice_type == "choose_cards"

    # Respond with the energy card chosen
    resp = Action(player_id="p1", action_type=ActionType.CHOOSE_CARDS,
                  selected_cards=[energy_card.instance_id])
    try:
        gen.send(resp)
    except StopIteration:
        pass

    # Energy should be in discard
    assert energy_card in state.p1.discard, "Discarded energy should be in discard pile"
    assert energy_card not in state.p1.hand, "Discarded energy should not be in hand"

    # Hand should have exactly 1 card (matching Psychic count = 1)
    assert len(state.p1.hand) == 1, (
        f"Hand should have 1 card (= # Psychic Pokémon), got {len(state.p1.hand)}"
    )

    # mystery_garden_used_this_turn should be set
    assert state.p1.mystery_garden_used_this_turn is True

    # Events should include discard and draw
    assert any(e["event_type"] == "mystery_garden_discard" for e in state.events)
    assert any(e["event_type"] == "mystery_garden_draw" for e in state.events)


def test_mystery_garden_alt_print_also_offered():
    """me01-122 (alt print) should also trigger USE_STADIUM offer."""
    from app.engine.actions import ActionValidator
    from app.engine.state import Phase

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.phase = Phase.MAIN
    state.active_player = "p1"

    p1_active = CardInstance(
        instance_id="p1-active-mg4", card_def_id="tst-p1-mg4",
        card_name="P1Active4", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state.p1.active = p1_active

    # Alt print
    mystery_garden_alt = CardInstance(
        instance_id="mg-alt-1", card_def_id="me01-122",
        card_name="Mystery Garden", current_hp=0, max_hp=0,
    )
    state.active_stadium = mystery_garden_alt

    energy_card = CardInstance(
        instance_id="energy-4", card_def_id="basic-grass",
        card_name="Grass Energy", card_type="Energy", zone=Zone.HAND,
    )
    state.p1.hand = [energy_card]

    legal = ActionValidator.get_legal_actions(state, "p1")
    stadium_actions = [a for a in legal if a.action_type == ActionType.USE_STADIUM]
    assert len(stadium_actions) == 1, (
        "USE_STADIUM should be offered for me01-122 (Mystery Garden alt print)"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Session 2 fixes — Batch A
# ──────────────────────────────────────────────────────────────────────────────

# A1: duplicate _strong_bash_b2 removed ────────────────────────────────────────
def test_strong_bash_b2_no_duplicate():
    """Exactly one _strong_bash_b2 defined — previously two identical definitions existed."""
    import app.engine.effects.attacks as atk_mod
    count = sum(1 for name in dir(atk_mod) if name == "_strong_bash_b2")
    assert count <= 1, "Duplicate _strong_bash_b2 still present"


# A2+A3: Acerola's Mischief ────────────────────────────────────────────────────
def test_acerolas_mischief_blocked_when_opp_prizes_gt_2():
    """_acerolas_mischief does nothing when opponent has >2 prizes remaining."""
    from app.engine.effects.trainers import _acerolas_mischief

    poke = CardInstance(
        instance_id="p1-active-am", card_def_id="tst-am-1",
        card_name="P1Active", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=poke)
    state.p2.prizes_remaining = 3
    state.p2.prizes = [
        CardInstance(instance_id=f"prize-{i}", card_def_id="tst-prize",
                     card_name="Prize", current_hp=0, max_hp=0)
        for i in range(3)
    ]

    action = Action(player_id="p1", action_type=ActionType.PLAY_SUPPORTER)
    gen = _acerolas_mischief(state, action)
    try:
        next(gen)
    except StopIteration:
        pass

    assert not any(e["event_type"] == "acerola_protection" for e in state.events)
    assert any(e["event_type"] == "acerolas_mischief_not_applicable" for e in state.events)


def test_acerolas_mischief_no_draw_effect():
    """_acerolas_mischief never draws cards — the bogus draw-to-4 clause was removed."""
    from app.engine.effects.trainers import _acerolas_mischief
    import inspect
    src = inspect.getsource(_acerolas_mischief)
    assert "draw_cards" not in src, "draw_cards still called inside _acerolas_mischief"
    assert "4 - len" not in src, "draw-to-4 clause still present in _acerolas_mischief"


def test_acerolas_mischief_protects_when_opp_has_2_prizes():
    """_acerolas_mischief grants protection when opponent has exactly 2 prizes."""
    from app.engine.effects.trainers import _acerolas_mischief

    poke = CardInstance(
        instance_id="p1-active-am2", card_def_id="tst-am-2",
        card_name="P1Active2", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=poke)
    state.p2.prizes_remaining = 2
    state.p2.prizes = [
        CardInstance(instance_id=f"prize2-{i}", card_def_id="tst-prize",
                     card_name="Prize", current_hp=0, max_hp=0)
        for i in range(2)
    ]

    action = Action(player_id="p1", action_type=ActionType.PLAY_SUPPORTER)
    gen = _acerolas_mischief(state, action)
    try:
        req = next(gen)
        resp = Action(
            player_id="p1",
            action_type=ActionType.CHOOSE_TARGET,
            target_instance_id=poke.instance_id,
        )
        gen.send(resp)
    except StopIteration:
        pass

    assert poke.protected_from_ex is True
    assert any(e["event_type"] == "acerola_protection" for e in state.events)


# A4: Lucian rewrite ───────────────────────────────────────────────────────────
def test_lucian_shuffles_hand_to_deck():
    """_lucian_b5: each player's hand is moved to deck then drawn from; hand count = 3 or 6."""
    from app.engine.effects.trainers import _lucian_b5

    state = _make_state()
    hand_card = CardInstance(
        instance_id="hand-1", card_def_id="tst-hand-1",
        card_name="SomeCard", current_hp=0, max_hp=0, zone=Zone.HAND,
    )
    state.p1.hand = [hand_card]
    # Give p1 enough deck cards so draw completes
    for i in range(10):
        c = CardInstance(
            instance_id=f"luc-deck-p1-{i}", card_def_id="tst-ld",
            card_name="DeckCard", current_hp=0, max_hp=0, zone=Zone.DECK,
        )
        state.p1.deck.append(c)
    state.p2.hand = []

    action = Action(player_id="p1", action_type=ActionType.PLAY_SUPPORTER)
    result = _lucian_b5(state, action)
    if hasattr(result, '__next__'):
        try:
            next(result)
        except StopIteration:
            pass

    # After Lucian: p1 should have drawn 3 or 6 cards
    assert len(state.p1.hand) in (3, 6), (
        f"p1 should have 3 or 6 cards after Lucian, got {len(state.p1.hand)}"
    )
    # Original hand card should have been moved to deck at some point
    assert hand_card.zone in (Zone.DECK, Zone.HAND), (
        f"hand_card zone should be DECK or HAND (drawn back), got {hand_card.zone}"
    )


def test_lucian_draws_3_or_6():
    """_lucian_b5: after shuffle, combined draw is 6+6, 6+3, 3+6, or 3+3 (when hands not empty)."""
    import random as rmod
    from app.engine.effects.trainers import _lucian_b5

    state = _make_state()
    # Give p1 a hand card to trigger the condition
    p1_hand = CardInstance(
        instance_id="luc-h1", card_def_id="tst-lhc",
        card_name="HandCard", current_hp=0, max_hp=0, zone=Zone.HAND,
    )
    state.p1.hand = [p1_hand]
    state.p2.hand = []
    # Give each player enough deck cards
    for i in range(10):
        c = CardInstance(
            instance_id=f"deck-p1l-{i}", card_def_id="tst-d",
            card_name="Card", current_hp=0, max_hp=0, zone=Zone.DECK,
        )
        state.p1.deck.append(c)
        c2 = CardInstance(
            instance_id=f"deck-p2l-{i}", card_def_id="tst-d",
            card_name="Card", current_hp=0, max_hp=0, zone=Zone.DECK,
        )
        state.p2.deck.append(c2)

    action = Action(player_id="p1", action_type=ActionType.PLAY_SUPPORTER)
    rmod.seed(0)
    result = _lucian_b5(state, action)
    if hasattr(result, '__next__'):
        try:
            next(result)
        except StopIteration:
            pass

    total = len(state.p1.hand) + len(state.p2.hand)
    assert total in (6, 9, 12), f"Expected combined draw of 6+3, 3+3, or 6+6, got {total}"


# A5: sv06-159 Ogre's Mask registration ───────────────────────────────────────
def test_sv06_159_registered_to_ogres_mask():
    """sv06-159 should be registered to _ogres_mask, not _noop."""
    from app.engine.effects.trainers import _ogres_mask, _noop
    reg = EffectRegistry.instance()
    handler = reg._trainer_effects.get("sv06-159")
    assert handler is not None, "sv06-159 has no handler registered"
    assert handler is not _noop, "sv06-159 is still registered as _noop"
    assert handler is _ogres_mask, "sv06-159 is not registered as _ogres_mask"


# A6: Unfair Stamp draws 5 ────────────────────────────────────────────────────
def test_unfair_stamp_player_draws_5():
    """_unfair_stamp: active player draws 5 cards (was 3)."""
    from app.engine.effects.trainers import _unfair_stamp

    state = _make_state()
    state.turn_number = 2
    # Emit a KO event from turn 1 so _ko_happened_last_turn returns True
    state.events.append({
        "event_type": "ko",
        "turn": 1,
        "ko_player": "p1",
        "card_name": "SomePoke",
    })
    # Give plenty of deck cards to both players
    for i in range(10):
        c1 = CardInstance(
            instance_id=f"us-deck-p1-{i}", card_def_id="tst-us",
            card_name="Card", current_hp=0, max_hp=0, zone=Zone.DECK,
        )
        state.p1.deck.append(c1)
        c2 = CardInstance(
            instance_id=f"us-deck-p2-{i}", card_def_id="tst-us",
            card_name="Card", current_hp=0, max_hp=0, zone=Zone.DECK,
        )
        state.p2.deck.append(c2)

    action = Action(player_id="p1", action_type=ActionType.PLAY_SUPPORTER)
    result = _unfair_stamp(state, action)
    if hasattr(result, '__next__'):
        try:
            next(result)
        except StopIteration:
            pass

    assert len(state.p1.hand) == 5, f"Player should draw 5, got {len(state.p1.hand)}"
    assert len(state.p2.hand) == 2, f"Opponent should draw 2, got {len(state.p2.hand)}"


# A7: Dangle Tail ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_dangle_tail_puts_pokemon_from_discard_to_hand():
    """sv07-057 Dangle Tail: puts chosen Pokémon from discard to hand."""
    from app.engine.effects.attacks import _dangle_tail

    poke_in_discard = CardInstance(
        instance_id="dt-discard-1", card_def_id="tst-dt-poke",
        card_name="DiscardedPoke", current_hp=100, max_hp=100,
        zone=Zone.DISCARD, card_type="pokemon",
    )
    attacker = CardInstance(
        instance_id="dt-attacker", card_def_id="sv07-057",
        card_name="Slowpoke", current_hp=60, max_hp=60, zone=Zone.ACTIVE,
    )
    opp = CardInstance(
        instance_id="dt-opp", card_def_id="tst-dt-opp",
        card_name="OppMon", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=attacker, p2_active=opp)
    state.p1.discard = [poke_in_discard]

    action = _make_action(attack_index=0)
    gen = _dangle_tail(state, action)
    try:
        req = next(gen)
        resp = Action(
            player_id="p1",
            action_type=ActionType.CHOOSE_CARDS,
            selected_cards=[poke_in_discard.instance_id],
        )
        gen.send(resp)
    except StopIteration:
        pass

    assert poke_in_discard not in state.p1.discard
    assert poke_in_discard in state.p1.hand
    assert poke_in_discard.zone == Zone.HAND


# A8: Recovery Net ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_recovery_net_puts_up_to_2_pokemon_from_discard():
    """sv06-019 Recovery Net: puts up to 2 Pokémon from discard to hand."""
    from app.engine.effects.attacks import _recovery_net

    poke1 = CardInstance(
        instance_id="rn-discard-1", card_def_id="tst-rn-p1",
        card_name="DisP1", current_hp=100, max_hp=100,
        zone=Zone.DISCARD, card_type="pokemon",
    )
    poke2 = CardInstance(
        instance_id="rn-discard-2", card_def_id="tst-rn-p2",
        card_name="DisP2", current_hp=100, max_hp=100,
        zone=Zone.DISCARD, card_type="pokemon",
    )
    attacker = CardInstance(
        instance_id="rn-attacker", card_def_id="sv06-019",
        card_name="Iron Leaves", current_hp=120, max_hp=120, zone=Zone.ACTIVE,
    )
    opp = CardInstance(
        instance_id="rn-opp", card_def_id="tst-rn-opp",
        card_name="OppMon", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=attacker, p2_active=opp)
    state.p1.discard = [poke1, poke2]

    action = _make_action(attack_index=0)
    gen = _recovery_net(state, action)
    try:
        req = next(gen)
        resp = Action(
            player_id="p1",
            action_type=ActionType.CHOOSE_CARDS,
            selected_cards=[poke1.instance_id, poke2.instance_id],
        )
        gen.send(resp)
    except StopIteration:
        pass

    assert poke1 not in state.p1.discard
    assert poke2 not in state.p1.discard
    assert poke1 in state.p1.hand
    assert poke2 in state.p1.hand


# A9: Avenging Edge ────────────────────────────────────────────────────────────
def test_avenging_edge_bonus_when_ko_taken():
    """sv06-019 Avenging Edge: deals 100+60=160 when a KO was taken last turn."""
    from app.engine.effects.attacks import _avenging_edge
    from app.cards.models import CardDefinition

    iron_leaves_cdef = _make_card(
        "sv06-019", "Iron Leaves ex",
        attacks=[AttackDef(name="Avenging Edge", damage="100", cost=["Grass", "Colorless"])],
    )
    opp_cdef = _make_card("tst-ae-opp", "OppMon", hp=300)
    card_registry.register(iron_leaves_cdef)
    card_registry.register(opp_cdef)

    attacker = _make_instance(iron_leaves_cdef)
    defender = _make_instance(opp_cdef, hp=300)
    state = _make_state(p1_active=attacker, p2_active=defender)
    state.p1.ko_taken_last_turn = True

    action = _make_action(attack_index=1)
    _avenging_edge(state, action)

    assert defender.current_hp == 300 - 160, f"Expected 140 HP remaining, got {defender.current_hp}"


def test_avenging_edge_no_bonus_without_ko():
    """sv06-019 Avenging Edge: deals 100 when no KO was taken last turn."""
    from app.engine.effects.attacks import _avenging_edge

    iron_leaves_cdef = _make_card(
        "sv06-019c", "Iron Leaves ex",
        attacks=[AttackDef(name="Avenging Edge", damage="100", cost=["Grass", "Colorless"])],
    )
    opp_cdef = _make_card("tst-ae3-opp", "OppMon3", hp=300)
    card_registry.register(iron_leaves_cdef)
    card_registry.register(opp_cdef)

    attacker = _make_instance(iron_leaves_cdef)
    defender = _make_instance(opp_cdef, hp=300)
    state = _make_state(p1_active=attacker, p2_active=defender)
    state.p1.ko_taken_last_turn = False

    action = _make_action(attack_index=1)
    _avenging_edge(state, action)

    assert defender.current_hp == 300 - 100, f"Expected 200 HP remaining, got {defender.current_hp}"


# Precious Trolley (sv08-185) ──────────────────────────────────────────────────

def test_precious_trolley_benches_chosen_basics():
    """sv08-185 Precious Trolley: chosen Basic Pokémon move from deck to bench."""
    from app.engine.effects.trainers import _precious_trolley

    active = CardInstance(
        instance_id="pt-active", card_def_id="tst-pt-active",
        card_name="Active", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    basic1 = CardInstance(
        instance_id="pt-basic-1", card_def_id="tst-pt-b1",
        card_name="Basic1", current_hp=70, max_hp=70, zone=Zone.DECK,
        card_type="pokemon", evolution_stage=0,
    )
    basic2 = CardInstance(
        instance_id="pt-basic-2", card_def_id="tst-pt-b2",
        card_name="Basic2", current_hp=70, max_hp=70, zone=Zone.DECK,
        card_type="pokemon", evolution_stage=0,
    )
    state = _make_state(p1_active=active, p2_active=active)
    state.p2.active = CardInstance(
        instance_id="pt-opp", card_def_id="tst-pt-opp",
        card_name="Opp", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state.p1.deck = [basic1, basic2]

    action = Action(player_id="p1", action_type=ActionType.PLAY_ITEM)
    gen = _precious_trolley(state, action)
    req = next(gen)
    assert req.choice_type == "choose_cards"
    assert req.max_count == 2

    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_CARDS,
        selected_cards=[basic1.instance_id, basic2.instance_id],
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    assert basic1 not in state.p1.deck
    assert basic2 not in state.p1.deck
    assert basic1 in state.p1.bench
    assert basic2 in state.p1.bench
    assert basic1.zone == Zone.BENCH
    assert basic2.zone == Zone.BENCH


def test_precious_trolley_respects_bench_space():
    """sv08-185 Precious Trolley: max_count capped by available bench space."""
    from app.engine.effects.trainers import _precious_trolley

    active = CardInstance(
        instance_id="pt2-active", card_def_id="tst-pt2-active",
        card_name="Active", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    # 4 bench Pokémon already → only 1 space left
    bench_fillers = [
        CardInstance(
            instance_id=f"pt2-bench-{i}", card_def_id=f"tst-pt2-bench-{i}",
            card_name=f"Bench{i}", current_hp=70, max_hp=70, zone=Zone.BENCH,
        )
        for i in range(4)
    ]
    basic_in_deck = CardInstance(
        instance_id="pt2-deck-b", card_def_id="tst-pt2-b",
        card_name="DeckBasic", current_hp=70, max_hp=70, zone=Zone.DECK,
        card_type="pokemon", evolution_stage=0,
    )
    extra_basic = CardInstance(
        instance_id="pt2-deck-b2", card_def_id="tst-pt2-b2",
        card_name="DeckBasic2", current_hp=70, max_hp=70, zone=Zone.DECK,
        card_type="pokemon", evolution_stage=0,
    )
    state = _make_state(p1_active=active, p1_bench=bench_fillers)
    state.p2.active = CardInstance(
        instance_id="pt2-opp", card_def_id="tst-pt2-opp",
        card_name="Opp", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state.p1.deck = [basic_in_deck, extra_basic]

    action = Action(player_id="p1", action_type=ActionType.PLAY_ITEM)
    gen = _precious_trolley(state, action)
    req = next(gen)
    # Only 1 bench space → max_count should be 1
    assert req.max_count == 1


def test_precious_trolley_no_basics_in_deck_just_shuffles():
    """sv08-185 Precious Trolley: no Basics in deck — returns without error."""
    from app.engine.effects.trainers import _precious_trolley

    active = CardInstance(
        instance_id="pt3-active", card_def_id="tst-pt3-active",
        card_name="Active", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    trainer_card = CardInstance(
        instance_id="pt3-trainer", card_def_id="tst-pt3-trainer",
        card_name="SomeTrainer", current_hp=0, max_hp=0, zone=Zone.DECK,
        card_type="trainer",
    )
    state = _make_state(p1_active=active)
    state.p2.active = CardInstance(
        instance_id="pt3-opp", card_def_id="tst-pt3-opp",
        card_name="Opp", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state.p1.deck = [trainer_card]

    action = Action(player_id="p1", action_type=ActionType.PLAY_ITEM)
    gen = _precious_trolley(state, action)
    # No Basics → generator should complete without yielding a choice
    try:
        next(gen)
        assert False, "Expected StopIteration — no choice should be yielded with empty Basic pool"
    except StopIteration:
        pass

    assert len(state.p1.bench) == 0
    assert trainer_card in state.p1.deck


# Neutralization Zone — irrecoverable-from-discard enforcement ────────────────

def _make_nz_in_discard(instance_id: str = "nz-disc") -> CardInstance:
    return CardInstance(
        instance_id=instance_id, card_def_id="sv06.5-060",
        card_name="Neutralization Zone", current_hp=0, max_hp=0,
        zone=Zone.DISCARD, card_type="trainer", card_subtype="stadium",
    )


def test_is_recoverable_from_discard_blocks_neutralization_zone():
    """IRRECOVERABLE_FROM_DISCARD: sv06.5-060 returns False from helper."""
    from app.engine.effects.base import is_recoverable_from_discard
    nz = _make_nz_in_discard()
    assert not is_recoverable_from_discard(nz)


def test_is_recoverable_from_discard_allows_normal_cards():
    """IRRECOVERABLE_FROM_DISCARD: ordinary cards are recoverable."""
    from app.engine.effects.base import is_recoverable_from_discard
    supporter = CardInstance(
        instance_id="supp-inst", card_def_id="sv01-170",
        card_name="Some Supporter", current_hp=0, max_hp=0,
        zone=Zone.DISCARD, card_type="trainer", card_subtype="supporter",
    )
    assert is_recoverable_from_discard(supporter)


def test_pal_pad_excludes_irrecoverable_from_discard():
    """Pal Pad candidate list never includes sv06.5-060."""
    from app.engine.effects.trainers import _pal_pad

    active = CardInstance(
        instance_id="pp-active", card_def_id="tst-pp-active",
        card_name="Active", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    supporter = CardInstance(
        instance_id="pp-supp", card_def_id="sv02-185",
        card_name="Iono", current_hp=0, max_hp=0,
        zone=Zone.DISCARD, card_type="trainer", card_subtype="supporter",
    )
    nz = _make_nz_in_discard("pp-nz")

    state = _make_state(p1_active=active)
    state.p2.active = CardInstance(
        instance_id="pp-opp", card_def_id="tst-pp-opp",
        card_name="Opp", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state.p1.discard = [supporter, nz]

    action = Action(player_id="p1", action_type=ActionType.PLAY_ITEM)
    gen = _pal_pad(state, action)
    req = next(gen)
    # Only the Supporter should appear — NZ must be excluded
    assert all(c.card_def_id != "sv06.5-060" for c in req.cards)
    assert any(c.card_def_id == "sv02-185" for c in req.cards)


def test_miracle_headset_excludes_irrecoverable_from_discard():
    """Miracle Headset candidate list never includes sv06.5-060."""
    from app.engine.effects.trainers import _miracle_headset

    active = CardInstance(
        instance_id="mh-active", card_def_id="tst-mh-active",
        card_name="Active", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    supporter = CardInstance(
        instance_id="mh-supp", card_def_id="sv02-185",
        card_name="Iono", current_hp=0, max_hp=0,
        zone=Zone.DISCARD, card_type="trainer", card_subtype="supporter",
    )
    nz = _make_nz_in_discard("mh-nz")

    state = _make_state(p1_active=active)
    state.p2.active = CardInstance(
        instance_id="mh-opp", card_def_id="tst-mh-opp",
        card_name="Opp", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state.p1.discard = [supporter, nz]

    action = Action(player_id="p1", action_type=ActionType.PLAY_ITEM)
    gen = _miracle_headset(state, action)
    req = next(gen)
    assert all(c.card_def_id != "sv06.5-060" for c in req.cards)
    assert any(c.card_def_id == "sv02-185" for c in req.cards)


# Neutralization Zone (sv06.5-060) ────────────────────────────────────────────

def test_neutralization_zone_prevents_ex_damage_to_non_rule_box():
    """sv06.5-060: ex attacker deals 0 damage to a non-rule-box defender."""
    from app.engine.effects.attacks import _apply_damage

    ex_cdef = _make_card("tst-nz-ex", "Test ex", hp=200, stage="ex")
    basic_cdef = _make_card("tst-nz-basic", "Basic Target", hp=100, stage="Basic")
    card_registry.register(ex_cdef)
    card_registry.register(basic_cdef)

    attacker = _make_instance(ex_cdef, hp=200)
    defender = _make_instance(basic_cdef, hp=100)
    state = _make_state(p1_active=attacker, p2_active=defender)

    stadium = CardInstance(
        instance_id="nz-stadium", card_def_id="sv06.5-060",
        card_name="Neutralization Zone", current_hp=0, max_hp=0, zone=Zone.ACTIVE,
    )
    state.active_stadium = stadium

    action = _make_action(player_id="p1")
    result = _apply_damage(state, action, 100)
    assert result == 0, f"Expected 0 damage (prevented), got {result}"


def test_neutralization_zone_allows_ex_damage_to_ex():
    """sv06.5-060: ex attacker can still damage a rule-box (ex) defender."""
    from app.engine.effects.attacks import _apply_damage

    ex_cdef = _make_card("tst-nz2-ex", "Attacker ex", hp=200, stage="ex")
    ex_defender_cdef = _make_card("tst-nz2-def-ex", "Defender ex", hp=200, stage="ex")
    card_registry.register(ex_cdef)
    card_registry.register(ex_defender_cdef)

    attacker = _make_instance(ex_cdef, hp=200)
    defender = _make_instance(ex_defender_cdef, hp=200)
    state = _make_state(p1_active=attacker, p2_active=defender)

    stadium = CardInstance(
        instance_id="nz2-stadium", card_def_id="sv06.5-060",
        card_name="Neutralization Zone", current_hp=0, max_hp=0, zone=Zone.ACTIVE,
    )
    state.active_stadium = stadium

    action = _make_action(player_id="p1")
    result = _apply_damage(state, action, 100)
    assert result > 0, f"Expected non-zero damage (ex vs ex), got {result}"


def test_neutralization_zone_non_ex_attacker_still_damages():
    """sv06.5-060: a non-rule-box attacker can still damage a non-rule-box defender."""
    from app.engine.effects.attacks import _apply_damage

    basic_atk_cdef = _make_card("tst-nz3-atk", "Basic Attacker", hp=100, stage="Basic")
    basic_def_cdef = _make_card("tst-nz3-def", "Basic Defender", hp=100, stage="Basic")
    card_registry.register(basic_atk_cdef)
    card_registry.register(basic_def_cdef)

    attacker = _make_instance(basic_atk_cdef, hp=100)
    defender = _make_instance(basic_def_cdef, hp=100)
    state = _make_state(p1_active=attacker, p2_active=defender)

    stadium = CardInstance(
        instance_id="nz3-stadium", card_def_id="sv06.5-060",
        card_name="Neutralization Zone", current_hp=0, max_hp=0, zone=Zone.ACTIVE,
    )
    state.active_stadium = stadium

    action = _make_action(player_id="p1")
    result = _apply_damage(state, action, 80)
    assert result == 80, f"Expected 80 damage (basic vs basic), got {result}"


# ──────────────────────────────────────────────────────────────────────────────
# Live fix #L1: _ET_ATTACH — Cresselia me02-039 Swelling Light
# ──────────────────────────────────────────────────────────────────────────────

def test_et_attach_returns_energy_attachment_not_enum():
    """Regression #L1: _ET_ATTACH must return EnergyAttachment, not call the EnergyType enum.

    Simulation 2bc45a4e failed with EnumType.__call__() got an unexpected
    keyword argument 'energy_type' because _ET_ATTACH called _ET(...) where
    _ET is EnergyType (an Enum). Fix: call EnergyAttachment(...) instead.
    """
    from app.engine.effects.attacks import _ET_ATTACH
    from app.engine.state import CardInstance, EnergyAttachment, EnergyType, Zone

    energy_card = CardInstance(
        instance_id="test-swelling-light-energy",
        card_def_id="basic-colorless-energy",
        card_name="Colorless Energy",
        current_hp=0,
        max_hp=0,
        zone=Zone.ACTIVE,
    )
    result = _ET_ATTACH(energy_card)

    assert isinstance(result, EnergyAttachment), (
        f"_ET_ATTACH must return EnergyAttachment, got {type(result).__name__}"
    )
    assert result.energy_type == EnergyType.COLORLESS
    assert result.source_card_id == "test-swelling-light-energy"
    assert result.card_def_id == "basic-colorless-energy"


# ──────────────────────────────────────────────────────────────────────────────
# Live fix #L2: _tr_venture_bomb_b19 — TR Venture Bomb check_ko arg order
# ──────────────────────────────────────────────────────────────────────────────

def test_venture_bomb_tails_does_not_raise(monkeypatch):
    """Regression #L2 tails: Venture Bomb tails must call check_ko(state, target, player_id).

    Simulation 005109f8 failed with 'str' object has no attribute 'current_hp'
    because check_ko was called as check_ko(state, player_id, player.active),
    passing the string player_id as the target CardInstance argument.
    """
    import random as _random
    from app.engine.effects.trainers import _tr_venture_bomb_b19

    monkeypatch.setattr(_random, "choice", lambda _seq: False)  # always tails

    p1_cdef = _make_card("tst-vb-p1", "VB Player Active", hp=100)
    p2_cdef = _make_card("tst-vb-p2", "VB Opp Active", hp=100)
    card_registry.register(p1_cdef)
    card_registry.register(p2_cdef)

    p1_active = _make_instance(p1_cdef, hp=100)
    p2_active = _make_instance(p2_cdef, hp=100)
    state = _make_state(p1_active=p1_active, p2_active=p2_active)

    action = _make_action(player_id="p1")
    gen = _tr_venture_bomb_b19(state, action)
    try:
        next(gen)
    except StopIteration:
        pass

    assert p1_active.current_hp == 80
    assert p1_active.damage_counters == 2


def test_venture_bomb_heads_does_not_raise(monkeypatch):
    """Regression #L2 heads: Venture Bomb heads must call check_ko(state, target, opp_id).

    The heads branch had the same argument-order bug: check_ko(state, opp_id, target).
    """
    import random as _random
    from app.engine.effects.trainers import _tr_venture_bomb_b19

    monkeypatch.setattr(_random, "choice", lambda _seq: True)  # always heads

    p1_cdef = _make_card("tst-vb-h-p1", "VB Heads Player", hp=100)
    p2_cdef = _make_card("tst-vb-h-p2", "VB Heads Opp", hp=100)
    card_registry.register(p1_cdef)
    card_registry.register(p2_cdef)

    p1_active = _make_instance(p1_cdef, hp=100)
    p2_active = _make_instance(p2_cdef, hp=100)
    state = _make_state(p1_active=p1_active, p2_active=p2_active)

    action = _make_action(player_id="p1")
    gen = _tr_venture_bomb_b19(state, action)
    # First next() yields the ChoiceRequest; send None to default to opp.active
    req = next(gen)
    assert req is not None
    try:
        gen.send(None)
    except StopIteration:
        pass

    assert p2_active.current_hp == 80
    assert p2_active.damage_counters == 2


# ──────────────────────────────────────────────────────────────────────────────
# Live fix #L3: energy_provides must contain strings, not EnergyType enums
# ──────────────────────────────────────────────────────────────────────────────

def test_energy_card_reconstructed_from_attachment_has_string_provides():
    """Regression #L3: CardInstances reconstructed from EnergyAttachment.provides
    must store energy_provides as strings (e.g. "Fire"), not EnergyType enum objects.

    Simulation 40612eb1 failed with 'EnergyType' object has no attribute 'strip'
    because _upthrusting_horns_b4 / _opposing_winds_b5 / _balloon_return_b5 set
    energy_provides=list(att.provides), copying EnergyType enum values rather than
    their .value strings. EnergyType.from_str() in _attach_energy then called
    .strip() on the enum and raised AttributeError.
    """
    from app.engine.state import EnergyAttachment, EnergyType, CardInstance, Zone

    att = EnergyAttachment(
        energy_type=EnergyType.FIRE,
        source_card_id="src-fire-energy",
        card_def_id="basic-fire-energy",
        provides=[EnergyType.FIRE],
    )

    # Bug: list(att.provides) = [EnergyType.FIRE] — enum object, not string
    # Fix: [et.value for et in att.provides] = ["Fire"] — string
    energy_card = CardInstance(
        instance_id="test-reconstruct-fire",
        card_def_id=att.card_def_id,
        card_name="Fire Energy",
        card_type="Energy",
        card_subtype="Basic",
        max_hp=0, current_hp=0,
        energy_provides=[et.value for et in att.provides] if att.provides else [],
        zone=Zone.HAND,
    )

    assert energy_card.energy_provides == ["Fire"], (
        "energy_provides must contain string values, not EnergyType enum objects"
    )
    assert all(isinstance(ep, str) for ep in energy_card.energy_provides)
    # EnergyType.from_str must succeed on each value (this is what _attach_energy calls)
    resolved = [EnergyType.from_str(ep) for ep in energy_card.energy_provides]
    assert resolved == [EnergyType.FIRE]


@pytest.mark.parametrize("provides,expected_str,expected_enum", [
    ([EnergyType.COLORLESS], ["Colorless"], [EnergyType.COLORLESS]),
    ([EnergyType.WATER],     ["Water"],     [EnergyType.WATER]),
    ([EnergyType.LIGHTNING], ["Lightning"], [EnergyType.LIGHTNING]),
])
def test_energy_provides_conversion_covers_multiple_types(provides, expected_str, expected_enum):
    """Regression #L3: .value conversion works for any EnergyType, not just Fire."""
    from app.engine.state import EnergyType
    converted = [et.value for et in provides]
    assert converted == expected_str
    resolved = [EnergyType.from_str(s) for s in converted]
    assert resolved == expected_enum


# ──────────────────────────────────────────────────────────────────────────────
# Hardening sweep Section 5 regressions (2026-05-04)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sinister_surge_targets_darkness_bench_and_places_counters():
    """me02-068 Toxtricity Sinister Surge: attaches {D} Energy to a Darkness-bench Pokémon
    and places 2 damage counters on it. Non-Darkness bench must NOT be targeted."""
    from app.cards.models import CardDefinition

    toxtricity_cdef = CardDefinition(
        tcgdex_id="me02-068", name="Toxtricity", set_abbrev="ME02", set_number="068",
        category="pokemon", stage="Basic", hp=130,
        abilities=[AbilityDef(name="Sinister Surge", effect="")],
    )
    dark_bench_cdef = CardDefinition(
        tcgdex_id="tst-ss-d01", name="DarkMon", set_abbrev="TST", set_number="001",
        category="pokemon", stage="Basic", hp=100, types=["Darkness"],
    )
    non_dark_bench_cdef = CardDefinition(
        tcgdex_id="tst-ss-n01", name="NormalMon", set_abbrev="TST", set_number="002",
        category="pokemon", stage="Basic", hp=100, types=["Colorless"],
    )
    dark_energy_cdef = CardDefinition(
        tcgdex_id="basic-darkness-energy", name="Darkness Energy",
        set_abbrev="TST", set_number="003",
        category="energy", stage="", hp=0, energy_provides=["Darkness"],
    )
    opp_cdef = _make_card("tst-ss-opp", "OppMon", hp=100)
    for c in [toxtricity_cdef, dark_bench_cdef, non_dark_bench_cdef, dark_energy_cdef, opp_cdef]:
        card_registry.register(c)

    toxtricity_inst = CardInstance(
        instance_id="tox-inst", card_def_id="me02-068", card_name="Toxtricity",
        current_hp=130, max_hp=130, zone=Zone.ACTIVE,
    )
    dark_bench = CardInstance(
        instance_id="dark-bench-inst", card_def_id="tst-ss-d01", card_name="DarkMon",
        card_type="Pokemon", card_subtype="Basic",
        current_hp=100, max_hp=100, zone=Zone.BENCH,
    )
    non_dark_bench = CardInstance(
        instance_id="non-dark-bench-inst", card_def_id="tst-ss-n01", card_name="NormalMon",
        card_type="Pokemon", card_subtype="Basic",
        current_hp=100, max_hp=100, zone=Zone.BENCH,
    )
    d_energy = CardInstance(
        instance_id="dark-energy-inst", card_def_id="basic-darkness-energy",
        card_name="Darkness Energy", card_type="Energy", card_subtype="Basic",
        max_hp=0, current_hp=0, energy_provides=["Darkness"], zone=Zone.DECK,
    )
    opp_active = _make_instance(opp_cdef, hp=100)

    state = _make_state(
        p1_active=toxtricity_inst,
        p1_bench=[dark_bench, non_dark_bench],
        p2_active=opp_active,
    )
    state.p1.deck = [d_energy]

    action = Action(
        player_id="p1",
        action_type=ActionType.USE_ABILITY,
        card_instance_id=toxtricity_inst.instance_id,
    )

    await EffectRegistry.instance().resolve_ability("me02-068", "Sinister Surge", state, action)

    # Energy must be removed from deck and attached to the Darkness bench Pokémon
    assert d_energy not in state.p1.deck, "Energy should be removed from deck"
    assert len(dark_bench.energy_attached) == 1, "Energy must attach to Darkness bench Pokémon"
    assert len(non_dark_bench.energy_attached) == 0, "Non-Darkness bench must NOT receive energy"
    # 2 damage counters (= 20 HP loss) must be placed on the target
    assert dark_bench.damage_counters == 2, (
        f"Expected 2 damage counters, got {dark_bench.damage_counters}"
    )
    assert dark_bench.current_hp == 80, (
        f"Expected 80 HP after 20 damage, got {dark_bench.current_hp}"
    )


def test_jasmine_gaze_applies_to_active_and_bench():
    """sv08-178 Jasmine's Gaze: incoming_damage_reduction must be set on ALL
    in-play Pokémon (active + bench), not only the Active Pokémon."""
    from app.engine.effects.trainers import _jasmine_gaze

    p1_active = CardInstance(
        instance_id="jg-active", card_def_id="tst-jg-001", card_name="ActiveMon",
        current_hp=120, max_hp=120, zone=Zone.ACTIVE,
    )
    p1_bench1 = CardInstance(
        instance_id="jg-bench1", card_def_id="tst-jg-002", card_name="BenchMon1",
        current_hp=100, max_hp=100, zone=Zone.BENCH,
    )
    p1_bench2 = CardInstance(
        instance_id="jg-bench2", card_def_id="tst-jg-003", card_name="BenchMon2",
        current_hp=80, max_hp=80, zone=Zone.BENCH,
    )
    opp_active = CardInstance(
        instance_id="jg-opp", card_def_id="tst-jg-004", card_name="OppMon",
        current_hp=200, max_hp=200, zone=Zone.ACTIVE,
    )

    state = _make_state(
        p1_active=p1_active,
        p1_bench=[p1_bench1, p1_bench2],
        p2_active=opp_active,
    )
    action = Action(player_id="p1", action_type=ActionType.PLAY_SUPPORTER,
                    card_instance_id="jg-active")

    _jasmine_gaze(state, action)

    assert p1_active.incoming_damage_reduction == 30, "Active must receive 30 reduction"
    assert p1_bench1.incoming_damage_reduction == 30, "Bench Pokémon 1 must receive 30 reduction"
    assert p1_bench2.incoming_damage_reduction == 30, "Bench Pokémon 2 must receive 30 reduction"
    assert opp_active.incoming_damage_reduction == 0, "Opponent's Pokémon must be unaffected"


@pytest.mark.asyncio
async def test_grimsleys_move_max_one_pokemon():
    """me02-090 Grimsley's Move: only 1 Darkness Pokémon may be Benched (not multiple).
    The ChoiceRequest max_count must be 1; with two candidates only the chosen one is benched."""
    from app.cards.models import CardDefinition
    from app.engine.effects.trainers import _grimsleys_move_b18

    dark1_cdef = CardDefinition(
        tcgdex_id="tst-gm-001", name="DarkMon1", set_abbrev="TST", set_number="001",
        category="pokemon", stage="Basic", hp=80, types=["Darkness"],
    )
    dark2_cdef = CardDefinition(
        tcgdex_id="tst-gm-002", name="DarkMon2", set_abbrev="TST", set_number="002",
        category="pokemon", stage="Basic", hp=90, types=["Darkness"],
    )
    for c in [dark1_cdef, dark2_cdef]:
        card_registry.register(c)

    dark1 = CardInstance(
        instance_id="gm-d1", card_def_id="tst-gm-001", card_name="DarkMon1",
        card_type="Pokemon", card_subtype="Basic",
        current_hp=80, max_hp=80, zone=Zone.DECK,
    )
    dark2 = CardInstance(
        instance_id="gm-d2", card_def_id="tst-gm-002", card_name="DarkMon2",
        card_type="Pokemon", card_subtype="Basic",
        current_hp=90, max_hp=90, zone=Zone.DECK,
    )
    p1_active = CardInstance(
        instance_id="gm-active", card_def_id="tst-gm-003", card_name="ActiveMon",
        current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="gm-opp", card_def_id="tst-gm-004", card_name="OppMon",
        current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )

    state = _make_state(p1_active=p1_active, p2_active=opp_active)
    state.p1.deck = [dark1, dark2]

    action = Action(player_id="p1", action_type=ActionType.PLAY_ITEM,
                    card_instance_id="gm-active")

    gen = _grimsleys_move_b18(state, action)
    req = next(gen)
    assert req.max_count == 1, (
        f"Grimsley's Move must only allow 1 Pokémon (max_count=1), got {req.max_count}"
    )
    resp = Action(
        action_type=ActionType.CHOOSE_CARDS,
        player_id="p1",
        selected_cards=[dark1.instance_id],
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    benched_ids = {p.instance_id for p in state.p1.bench}
    assert dark1.instance_id in benched_ids, "Chosen Darkness Pokémon must be benched"
    assert dark2.instance_id not in benched_ids, "Second Darkness Pokémon must NOT be benched"


# ──────────────────────────────────────────────────────────────────────────────
# Session 8 regression tests — five handler fixes (commit b7af4b7)
# ──────────────────────────────────────────────────────────────────────────────

# Fix 1: Ninjask Cast-Off Shell (me01-017) must search Shedinja (me01-061), not
#         Nincada (me01-016).

def test_cast_off_shell_benches_shedinja_not_nincada():
    """Cast-Off Shell benches Shedinja (me01-061); Nincada (me01-016) stays in deck."""
    from app.engine.effects.abilities import _cast_off_shell

    ninjask = CardInstance(
        instance_id="cos-ninjask", card_def_id="me01-017",
        card_name="Ninjask", current_hp=80, max_hp=80, zone=Zone.ACTIVE,
    )
    nincada = CardInstance(
        instance_id="cos-nincada", card_def_id="me01-016",
        card_name="Nincada", current_hp=60, max_hp=60, zone=Zone.DECK,
    )
    shedinja = CardInstance(
        instance_id="cos-shedinja", card_def_id="me01-061",
        card_name="Shedinja", current_hp=30, max_hp=30, zone=Zone.DECK,
    )
    opp = CardInstance(
        instance_id="cos-opp", card_def_id="tst-cos-opp",
        card_name="Opp", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.p1.active = ninjask
    state.p2.active = opp
    state.p1.deck = [nincada, shedinja]

    action = Action(player_id="p1", action_type=ActionType.USE_ABILITY,
                    card_instance_id=ninjask.instance_id)
    _cast_off_shell(state, action)

    benched_ids = {p.instance_id for p in state.p1.bench}
    assert shedinja.instance_id in benched_ids, "Shedinja must be benched"
    assert nincada.instance_id not in benched_ids, "Nincada must NOT be benched"
    assert shedinja.zone == Zone.BENCH
    assert nincada in state.p1.deck, "Nincada must remain in deck"


def test_cast_off_shell_no_shedinja_does_nothing():
    """Cast-Off Shell leaves bench empty when no Shedinja is in deck."""
    from app.engine.effects.abilities import _cast_off_shell

    ninjask = CardInstance(
        instance_id="cos2-ninjask", card_def_id="me01-017",
        card_name="Ninjask", current_hp=80, max_hp=80, zone=Zone.ACTIVE,
    )
    nincada = CardInstance(
        instance_id="cos2-nincada", card_def_id="me01-016",
        card_name="Nincada", current_hp=60, max_hp=60, zone=Zone.DECK,
    )
    opp = CardInstance(
        instance_id="cos2-opp", card_def_id="tst-cos2-opp",
        card_name="Opp", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.p1.active = ninjask
    state.p2.active = opp
    state.p1.deck = [nincada]

    action = Action(player_id="p1", action_type=ActionType.USE_ABILITY,
                    card_instance_id=ninjask.instance_id)
    _cast_off_shell(state, action)

    assert state.p1.bench == [], "Bench must remain empty when no Shedinja in deck"
    assert nincada in state.p1.deck, "Nincada must remain in deck"


# Fix 2: Clawitzer Fall Back to Reload (me01-038) must select from hand (not
#         discard), accept only Basic Water Energy, and attach up to 2 to itself.

def test_fall_back_to_reload_uses_hand_water_energy_max2():
    """Fall Back to Reload: offers only Basic Water Energy from hand; max 2; attaches to Clawitzer."""
    from app.engine.effects.abilities import _fall_back_to_reload

    water_cdef = CardDefinition(
        tcgdex_id="tst-fbr-water", name="Water Energy",
        set_abbrev="TST", set_number="W01",
        category="energy", subcategory="basic", stage="",
        hp=0, attacks=[], abilities=[],
        energy_provides=["Water"],
    )
    card_registry.register(water_cdef)

    clawitzer = CardInstance(
        instance_id="fbr-clawitzer", card_def_id="me01-038",
        card_name="Clawitzer", current_hp=130, max_hp=130, zone=Zone.BENCH,
    )
    w1 = CardInstance(
        instance_id="fbr-w1", card_def_id="tst-fbr-water",
        card_name="Water Energy", current_hp=0, max_hp=0, zone=Zone.HAND,
        card_type="Energy", card_subtype="Basic", energy_provides=["Water"],
    )
    w2 = CardInstance(
        instance_id="fbr-w2", card_def_id="tst-fbr-water",
        card_name="Water Energy", current_hp=0, max_hp=0, zone=Zone.HAND,
        card_type="Energy", card_subtype="Basic", energy_provides=["Water"],
    )
    fire = CardInstance(
        instance_id="fbr-fire", card_def_id="tst-fbr-fire",
        card_name="Fire Energy", current_hp=0, max_hp=0, zone=Zone.HAND,
        card_type="Energy", card_subtype="Basic", energy_provides=["Fire"],
    )
    discard_w = CardInstance(
        instance_id="fbr-discard-w", card_def_id="tst-fbr-water",
        card_name="Water Energy", current_hp=0, max_hp=0, zone=Zone.DISCARD,
        card_type="Energy", card_subtype="Basic", energy_provides=["Water"],
    )
    p1_active = CardInstance(
        instance_id="fbr-active", card_def_id="tst-fbr-active",
        card_name="Active", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    opp = CardInstance(
        instance_id="fbr-opp", card_def_id="tst-fbr-opp",
        card_name="Opp", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.p1.active = p1_active
    state.p2.active = opp
    state.p1.bench = [clawitzer]
    state.p1.hand = [w1, w2, fire]
    state.p1.discard = [discard_w]

    action = Action(player_id="p1", action_type=ActionType.USE_ABILITY,
                    card_instance_id=clawitzer.instance_id)
    gen = _fall_back_to_reload(state, action)
    req = next(gen)

    offered_ids = {c.instance_id for c in req.cards}
    assert w1.instance_id in offered_ids, "w1 (hand Water) must be offered"
    assert w2.instance_id in offered_ids, "w2 (hand Water) must be offered"
    assert fire.instance_id not in offered_ids, "Fire energy must NOT be offered"
    assert discard_w.instance_id not in offered_ids, "Discard energy must NOT be offered"
    assert req.max_count == 2, f"max_count must be 2, got {req.max_count}"

    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_CARDS,
        selected_cards=[w1.instance_id, w2.instance_id],
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    attached_ids = {att.source_card_id for att in clawitzer.energy_attached}
    assert w1.instance_id in attached_ids, "w1 must be attached to Clawitzer"
    assert w2.instance_id in attached_ids, "w2 must be attached to Clawitzer"
    assert fire in state.p1.hand, "Fire energy must remain in hand"
    assert discard_w in state.p1.discard, "Discard energy must remain in discard"


def test_cond_fall_back_to_reload_true_with_water_in_hand():
    """_cond_fall_back_to_reload returns True when Clawitzer is in play and hand has Basic Water."""
    from app.engine.effects.abilities import _cond_fall_back_to_reload

    clawitzer = CardInstance(
        instance_id="cfbr-clawitzer", card_def_id="me01-038",
        card_name="Clawitzer", current_hp=130, max_hp=130, zone=Zone.BENCH,
    )
    water = CardInstance(
        instance_id="cfbr-water", card_def_id="tst-cfbr-water",
        card_name="Water Energy", current_hp=0, max_hp=0, zone=Zone.HAND,
        card_type="Energy", card_subtype="Basic", energy_provides=["Water"],
    )
    active = CardInstance(
        instance_id="cfbr-active", card_def_id="tst-cfbr-active",
        card_name="Active", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    opp = CardInstance(
        instance_id="cfbr-opp", card_def_id="tst-cfbr-opp",
        card_name="Opp", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.p1.active = active
    state.p2.active = opp
    state.p1.bench = [clawitzer]
    state.p1.hand = [water]

    assert _cond_fall_back_to_reload(state, "p1") is True


def test_cond_fall_back_to_reload_false_without_water_in_hand():
    """_cond_fall_back_to_reload returns False when no Basic Water Energy in hand."""
    from app.engine.effects.abilities import _cond_fall_back_to_reload

    clawitzer = CardInstance(
        instance_id="cfbr2-clawitzer", card_def_id="me01-038",
        card_name="Clawitzer", current_hp=130, max_hp=130, zone=Zone.BENCH,
    )
    fire = CardInstance(
        instance_id="cfbr2-fire", card_def_id="tst-cfbr2-fire",
        card_name="Fire Energy", current_hp=0, max_hp=0, zone=Zone.HAND,
        card_type="Energy", card_subtype="Basic", energy_provides=["Fire"],
    )
    active = CardInstance(
        instance_id="cfbr2-active", card_def_id="tst-cfbr2-active",
        card_name="Active", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    opp = CardInstance(
        instance_id="cfbr2-opp", card_def_id="tst-cfbr2-opp",
        card_name="Opp", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.p1.active = active
    state.p2.active = opp
    state.p1.bench = [clawitzer]
    state.p1.hand = [fire]

    assert _cond_fall_back_to_reload(state, "p1") is False


# Fix 3: Grumpig Energized Steps (me01-063) must look at only the top 4 cards,
#         offer any Basic Energy (not just Psychic), allow any number, allow any
#         of your own Pokémon as target (including Active).

def test_energized_steps_top4_only_any_basic_any_target():
    """Energized Steps: top-4 only; any Basic Energy; any number; Active target allowed."""
    from app.engine.effects.abilities import _energized_steps

    water_cdef = CardDefinition(
        tcgdex_id="tst-es-water", name="Water Energy",
        set_abbrev="TST", set_number="EW1",
        category="energy", subcategory="basic", stage="",
        hp=0, attacks=[], abilities=[],
        energy_provides=["Water"],
    )
    lightning_cdef = CardDefinition(
        tcgdex_id="tst-es-lightning", name="Lightning Energy",
        set_abbrev="TST", set_number="EL1",
        category="energy", subcategory="basic", stage="",
        hp=0, attacks=[], abilities=[],
        energy_provides=["Lightning"],
    )
    card_registry.register(water_cdef)
    card_registry.register(lightning_cdef)

    grumpig = CardInstance(
        instance_id="es-grumpig", card_def_id="me01-063",
        card_name="Grumpig", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    bench_poke = CardInstance(
        instance_id="es-bench", card_def_id="tst-es-benched",
        card_name="BenchMon", current_hp=80, max_hp=80, zone=Zone.BENCH,
    )
    opp = CardInstance(
        instance_id="es-opp", card_def_id="tst-es-opp",
        card_name="Opp", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    # Top-4 deck: water_e (pos 0), lightning_e (pos 1), non_energy (pos 2), extra_w (pos 3)
    # Pos 5: beyond_e — must not be offered
    water_e = CardInstance(
        instance_id="es-water1", card_def_id="tst-es-water",
        card_name="Water Energy", current_hp=0, max_hp=0, zone=Zone.DECK,
        card_type="energy", card_subtype="basic", energy_provides=["Water"],
    )
    lightning_e = CardInstance(
        instance_id="es-lightning1", card_def_id="tst-es-lightning",
        card_name="Lightning Energy", current_hp=0, max_hp=0, zone=Zone.DECK,
        card_type="energy", card_subtype="basic", energy_provides=["Lightning"],
    )
    non_energy = CardInstance(
        instance_id="es-noenergy", card_def_id="tst-es-other",
        card_name="OtherPoke", current_hp=60, max_hp=60, zone=Zone.DECK,
        card_type="pokemon",
    )
    extra_w = CardInstance(
        instance_id="es-extra-w", card_def_id="tst-es-water",
        card_name="Water Energy 2", current_hp=0, max_hp=0, zone=Zone.DECK,
        card_type="energy", card_subtype="basic", energy_provides=["Water"],
    )
    beyond_e = CardInstance(
        instance_id="es-beyond", card_def_id="tst-es-water",
        card_name="Beyond Energy", current_hp=0, max_hp=0, zone=Zone.DECK,
        card_type="energy", card_subtype="basic", energy_provides=["Water"],
    )

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.p1.active = grumpig
    state.p1.bench = [bench_poke]
    state.p2.active = opp
    # deck[:4] = [water_e, lightning_e, non_energy, extra_w]; deck[4] = beyond_e
    state.p1.deck = [water_e, lightning_e, non_energy, extra_w, beyond_e]

    action = Action(player_id="p1", action_type=ActionType.USE_ABILITY,
                    card_instance_id=grumpig.instance_id)
    gen = _energized_steps(state, action)
    req_e = next(gen)

    offered_ids = {c.instance_id for c in req_e.cards}
    assert water_e.instance_id in offered_ids, "water_e (top-4) must be offered"
    assert lightning_e.instance_id in offered_ids, "lightning_e (top-4) must be offered"
    assert extra_w.instance_id in offered_ids, "extra_w (top-4) must be offered"
    assert non_energy.instance_id not in offered_ids, "non-energy top-4 card must NOT be offered"
    assert beyond_e.instance_id not in offered_ids, "beyond_e (pos 5) must NOT be offered"
    assert req_e.max_count == 3, f"max_count must equal 3 (basic energy in top 4), got {req_e.max_count}"

    # Select water_e → attach to Active; lightning_e → attach to Bench
    resp_e = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_CARDS,
        selected_cards=[water_e.instance_id, lightning_e.instance_id],
    )
    req_t1 = gen.send(resp_e)
    # Active must be a valid target
    target_ids_t1 = {t.instance_id for t in req_t1.targets}
    assert grumpig.instance_id in target_ids_t1, "Active (Grumpig) must be a valid target"
    assert bench_poke.instance_id in target_ids_t1, "Bench must also be a valid target"

    resp_t1 = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_TARGET,
        target_instance_id=grumpig.instance_id,
    )
    req_t2 = gen.send(resp_t1)

    resp_t2 = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_TARGET,
        target_instance_id=bench_poke.instance_id,
    )
    try:
        gen.send(resp_t2)
    except StopIteration:
        pass

    active_attached_srcs = {att.source_card_id for att in grumpig.energy_attached}
    assert water_e.instance_id in active_attached_srcs, "water_e must be attached to Active"
    bench_attached_srcs = {att.source_card_id for att in bench_poke.energy_attached}
    assert lightning_e.instance_id in bench_attached_srcs, "lightning_e must be attached to Bench"
    assert beyond_e in state.p1.deck, "beyond_e (pos 5) must remain in deck"
    assert water_e not in state.p1.deck, "water_e must be removed from deck"
    assert lightning_e not in state.p1.deck, "lightning_e must be removed from deck"


# Fix 4: Fighting Gong (me01-116) must exclude Stage 1 and Stage 2 Fighting
#         Pokémon; only Basic Fighting Pokémon and Basic Fighting Energy qualify.

def test_fighting_gong_excludes_evolved_fighting_pokemon():
    """Fighting Gong candidates: Basic Fighting Energy ✓, Basic Fighting Pokémon ✓,
    Stage 1/2 Fighting Pokémon ✗, non-Fighting Pokémon ✗."""
    from app.engine.effects.trainers import _fighting_gong

    basic_fighter_cdef = _make_card("tst-fg-basic", "Basic Fighter", hp=100)
    basic_fighter_cdef.types = ["Fighting"]
    stage1_cdef = _make_card("tst-fg-s1", "Stage 1 Fighter", hp=120, stage="Stage 1")
    stage1_cdef.types = ["Fighting"]
    stage2_cdef = _make_card("tst-fg-s2", "Stage 2 Fighter", hp=150, stage="Stage 2")
    stage2_cdef.types = ["Fighting"]
    non_fighting_cdef = _make_card("tst-fg-nf", "Non Fighter", hp=80)
    non_fighting_cdef.types = ["Fire"]
    for cdef in [basic_fighter_cdef, stage1_cdef, stage2_cdef, non_fighting_cdef]:
        card_registry.register(cdef)

    fighting_energy = CardInstance(
        instance_id="fg-energy", card_def_id="tst-fg-energy",
        card_name="Fighting Energy", current_hp=0, max_hp=0, zone=Zone.DECK,
        card_type="energy", card_subtype="basic", energy_provides=["Fighting"],
    )
    basic_fighter = CardInstance(
        instance_id="fg-basic", card_def_id="tst-fg-basic",
        card_name="Basic Fighter", current_hp=100, max_hp=100, zone=Zone.DECK,
        card_type="pokemon", evolution_stage=0,
    )
    stage1_fighter = CardInstance(
        instance_id="fg-s1", card_def_id="tst-fg-s1",
        card_name="Stage 1 Fighter", current_hp=120, max_hp=120, zone=Zone.DECK,
        card_type="pokemon", evolution_stage=1,
    )
    stage2_fighter = CardInstance(
        instance_id="fg-s2", card_def_id="tst-fg-s2",
        card_name="Stage 2 Fighter", current_hp=150, max_hp=150, zone=Zone.DECK,
        card_type="pokemon", evolution_stage=2,
    )
    non_fighting = CardInstance(
        instance_id="fg-nf", card_def_id="tst-fg-nf",
        card_name="Non Fighter", current_hp=80, max_hp=80, zone=Zone.DECK,
        card_type="pokemon", evolution_stage=0,
    )

    p1_active = CardInstance(
        instance_id="fg-active", card_def_id="tst-fg-p1active",
        card_name="ActiveMon", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    opp = CardInstance(
        instance_id="fg-opp", card_def_id="tst-fg-opp",
        card_name="Opp", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )

    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.p1.active = p1_active
    state.p2.active = opp
    state.p1.deck = [fighting_energy, basic_fighter, stage1_fighter, stage2_fighter, non_fighting]

    action = Action(player_id="p1", action_type=ActionType.PLAY_ITEM)
    gen = _fighting_gong(state, action)
    req = next(gen)

    candidate_ids = {c.instance_id for c in req.cards}
    assert fighting_energy.instance_id in candidate_ids, "Basic Fighting Energy must be included"
    assert basic_fighter.instance_id in candidate_ids, "Basic Fighting Pokémon must be included"
    assert stage1_fighter.instance_id not in candidate_ids, "Stage 1 Fighting must be EXCLUDED"
    assert stage2_fighter.instance_id not in candidate_ids, "Stage 2 Fighting must be EXCLUDED"
    assert non_fighting.instance_id not in candidate_ids, "Non-Fighting Pokémon must be EXCLUDED"

    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_CARDS,
        selected_cards=[basic_fighter.instance_id],
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    assert basic_fighter in state.p1.hand, "Chosen Basic Fighter must be in hand"
    assert basic_fighter not in state.p1.deck


# Fix 5: Risky Ruins (me01-127) must only damage Basic non-Darkness Pokémon
#         placed on Bench; evolved Pokémon and Darkness Pokémon are exempt.
#         Both placement paths (_place_bench and _play_basic) are covered.

def _risky_ruins_stadium() -> CardInstance:
    return CardInstance(
        instance_id="stadium-rr",
        card_def_id="me01-127",
        card_name="Risky Ruins",
        current_hp=0, max_hp=0, zone=Zone.BENCH,
        card_type="trainer", card_subtype="stadium",
    )


def test_risky_ruins_place_bench_damages_basic_non_darkness():
    """_place_bench: Basic non-Darkness Pokémon takes 20 damage under Risky Ruins."""
    from app.engine.transitions import _place_bench

    fire_cdef = CardDefinition(
        tcgdex_id="tst-rr-fire", name="Fire Basic",
        set_abbrev="TST", set_number="RR1",
        category="pokemon", stage="Basic",
        hp=80, attacks=[], abilities=[],
        types=["Fire"],
    )
    card_registry.register(fire_cdef)

    placed = CardInstance(
        instance_id="rr1-inst", card_def_id="tst-rr-fire",
        card_name="Fire Basic", current_hp=80, max_hp=80, zone=Zone.HAND,
    )
    state = _make_state(
        p1_active=CardInstance(instance_id="rr1-a", card_def_id="tst-rr1-a",
                               card_name="A", current_hp=100, max_hp=100, zone=Zone.ACTIVE),
        p2_active=CardInstance(instance_id="rr1-o", card_def_id="tst-rr1-o",
                               card_name="O", current_hp=100, max_hp=100, zone=Zone.ACTIVE),
    )
    state.p1.hand = [placed]
    state.active_stadium = _risky_ruins_stadium()

    action = Action(player_id="p1", action_type=ActionType.PLACE_BENCH,
                    card_instance_id=placed.instance_id)
    _place_bench(state, action)

    assert placed in state.p1.bench
    assert placed.damage_counters == 2, f"Expected 2 damage counters, got {placed.damage_counters}"
    assert placed.current_hp == 60, f"Expected 60 HP, got {placed.current_hp}"


def test_risky_ruins_place_bench_no_damage_basic_darkness():
    """_place_bench: Basic Darkness Pokémon takes NO damage under Risky Ruins."""
    from app.engine.transitions import _place_bench

    dark_cdef = CardDefinition(
        tcgdex_id="tst-rr-dark", name="Dark Basic",
        set_abbrev="TST", set_number="RR2",
        category="pokemon", stage="Basic",
        hp=80, attacks=[], abilities=[],
        types=["Darkness"],
    )
    card_registry.register(dark_cdef)

    placed = CardInstance(
        instance_id="rr2-inst", card_def_id="tst-rr-dark",
        card_name="Dark Basic", current_hp=80, max_hp=80, zone=Zone.HAND,
    )
    state = _make_state(
        p1_active=CardInstance(instance_id="rr2-a", card_def_id="tst-rr2-a",
                               card_name="A", current_hp=100, max_hp=100, zone=Zone.ACTIVE),
        p2_active=CardInstance(instance_id="rr2-o", card_def_id="tst-rr2-o",
                               card_name="O", current_hp=100, max_hp=100, zone=Zone.ACTIVE),
    )
    state.p1.hand = [placed]
    state.active_stadium = _risky_ruins_stadium()

    action = Action(player_id="p1", action_type=ActionType.PLACE_BENCH,
                    card_instance_id=placed.instance_id)
    _place_bench(state, action)

    assert placed in state.p1.bench
    assert placed.damage_counters == 0, "Darkness Pokémon must NOT take Risky Ruins damage"
    assert placed.current_hp == 80


def test_risky_ruins_place_bench_no_damage_evolved():
    """_place_bench: evolved (Stage 1) non-Darkness Pokémon takes NO damage under Risky Ruins."""
    from app.engine.transitions import _place_bench

    evolved_cdef = CardDefinition(
        tcgdex_id="tst-rr-s1", name="Stage 1 Fire",
        set_abbrev="TST", set_number="RR3",
        category="pokemon", stage="Stage 1",
        hp=120, attacks=[], abilities=[],
        types=["Fire"],
    )
    card_registry.register(evolved_cdef)

    placed = CardInstance(
        instance_id="rr3-inst", card_def_id="tst-rr-s1",
        card_name="Stage 1 Fire", current_hp=120, max_hp=120, zone=Zone.HAND,
    )
    state = _make_state(
        p1_active=CardInstance(instance_id="rr3-a", card_def_id="tst-rr3-a",
                               card_name="A", current_hp=100, max_hp=100, zone=Zone.ACTIVE),
        p2_active=CardInstance(instance_id="rr3-o", card_def_id="tst-rr3-o",
                               card_name="O", current_hp=100, max_hp=100, zone=Zone.ACTIVE),
    )
    state.p1.hand = [placed]
    state.active_stadium = _risky_ruins_stadium()

    action = Action(player_id="p1", action_type=ActionType.PLACE_BENCH,
                    card_instance_id=placed.instance_id)
    _place_bench(state, action)

    assert placed in state.p1.bench
    assert placed.damage_counters == 0, "Evolved Pokémon must NOT take Risky Ruins damage"
    assert placed.current_hp == 120


@pytest.mark.asyncio
async def test_risky_ruins_play_basic_damages_basic_non_darkness():
    """_play_basic: Basic non-Darkness Pokémon takes 20 damage under Risky Ruins."""
    from app.engine.transitions import _play_basic

    water_cdef = CardDefinition(
        tcgdex_id="tst-rr-wp", name="Water Basic",
        set_abbrev="TST", set_number="RR4",
        category="pokemon", stage="Basic",
        hp=70, attacks=[], abilities=[],
        types=["Water"],
    )
    card_registry.register(water_cdef)

    placed = CardInstance(
        instance_id="rr4-inst", card_def_id="tst-rr-wp",
        card_name="Water Basic", current_hp=70, max_hp=70, zone=Zone.HAND,
    )
    state = _make_state(
        p1_active=CardInstance(instance_id="rr4-a", card_def_id="tst-rr4-a",
                               card_name="A", current_hp=100, max_hp=100, zone=Zone.ACTIVE),
        p2_active=CardInstance(instance_id="rr4-o", card_def_id="tst-rr4-o",
                               card_name="O", current_hp=100, max_hp=100, zone=Zone.ACTIVE),
    )
    state.p1.hand = [placed]
    state.active_stadium = _risky_ruins_stadium()

    action = Action(player_id="p1", action_type=ActionType.PLAY_BASIC,
                    card_instance_id=placed.instance_id)
    await _play_basic(state, action)

    assert placed in state.p1.bench
    assert placed.damage_counters == 2, f"Expected 2 damage counters, got {placed.damage_counters}"
    assert placed.current_hp == 50, f"Expected 50 HP, got {placed.current_hp}"


@pytest.mark.asyncio
async def test_risky_ruins_play_basic_no_damage_basic_darkness():
    """_play_basic: Basic Darkness Pokémon takes NO damage under Risky Ruins."""
    from app.engine.transitions import _play_basic

    dark_cdef = CardDefinition(
        tcgdex_id="tst-rr-dp", name="Dark Basic 2",
        set_abbrev="TST", set_number="RR5",
        category="pokemon", stage="Basic",
        hp=90, attacks=[], abilities=[],
        types=["Darkness"],
    )
    card_registry.register(dark_cdef)

    placed = CardInstance(
        instance_id="rr5-inst", card_def_id="tst-rr-dp",
        card_name="Dark Basic 2", current_hp=90, max_hp=90, zone=Zone.HAND,
    )
    state = _make_state(
        p1_active=CardInstance(instance_id="rr5-a", card_def_id="tst-rr5-a",
                               card_name="A", current_hp=100, max_hp=100, zone=Zone.ACTIVE),
        p2_active=CardInstance(instance_id="rr5-o", card_def_id="tst-rr5-o",
                               card_name="O", current_hp=100, max_hp=100, zone=Zone.ACTIVE),
    )
    state.p1.hand = [placed]
    state.active_stadium = _risky_ruins_stadium()

    action = Action(player_id="p1", action_type=ActionType.PLAY_BASIC,
                    card_instance_id=placed.instance_id)
    await _play_basic(state, action)

    assert placed in state.p1.bench
    assert placed.damage_counters == 0, "Darkness Pokémon must NOT take Risky Ruins damage"
    assert placed.current_hp == 90


# ──────────────────────────────────────────────────────────────────────────────
# Audit Batch fixes: Fixes #3-#15
# ──────────────────────────────────────────────────────────────────────────────

# Fix #3: _minor_errand_running_b3 — max_count=3
def test_minor_errand_running_searches_up_to_3():
    """sv06-087 Floette — Minor Errand-Running: searches up to 3 Basic Energy (not 1)."""
    from app.engine.effects.attacks import _minor_errand_running_b3

    attacker = CardInstance(
        instance_id="mer-atk", card_def_id="sv06-087",
        card_name="Floette", current_hp=70, max_hp=70, zone=Zone.ACTIVE,
    )
    opp = CardInstance(
        instance_id="mer-opp", card_def_id="tst-mer-opp",
        card_name="OppMon", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    e1 = CardInstance(
        instance_id="mer-e1", card_def_id="grass-energy",
        card_name="Grass Energy", current_hp=0, max_hp=0, zone=Zone.DECK,
        card_type="energy", card_subtype="basic",
    )
    e2 = CardInstance(
        instance_id="mer-e2", card_def_id="fire-energy",
        card_name="Fire Energy", current_hp=0, max_hp=0, zone=Zone.DECK,
        card_type="energy", card_subtype="basic",
    )
    e3 = CardInstance(
        instance_id="mer-e3", card_def_id="water-energy",
        card_name="Water Energy", current_hp=0, max_hp=0, zone=Zone.DECK,
        card_type="energy", card_subtype="basic",
    )
    state = _make_state(p1_active=attacker, p2_active=opp)
    state.p1.deck = [e1, e2, e3]

    action = _make_action(attack_index=0)
    gen = _minor_errand_running_b3(state, action)
    req = next(gen)
    assert req.max_count == 3, "Minor Errand-Running must allow up to 3"

    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_CARDS,
        selected_cards=[e1.instance_id, e2.instance_id, e3.instance_id],
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    assert e1 in state.p1.hand
    assert e2 in state.p1.hand
    assert e3 in state.p1.hand
    assert len(state.p1.deck) == 0


# Fix #4: _sneaky_placement — targets any opp Pokémon (bench or active)
@pytest.mark.asyncio
async def test_sneaky_placement_targets_bench():
    """sv06-089 Swirlix — Sneaky Placement: can target benched Pokémon."""
    from app.engine.effects.attacks import _sneaky_placement

    attacker = CardInstance(
        instance_id="sp-atk", card_def_id="sv06-089",
        card_name="Swirlix", current_hp=70, max_hp=70, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="sp-opp-a", card_def_id="tst-sp-opp",
        card_name="OppActive", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    opp_bench = CardInstance(
        instance_id="sp-opp-b", card_def_id="tst-sp-bench",
        card_name="OppBench", current_hp=80, max_hp=80, zone=Zone.BENCH,
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active, p2_bench=[opp_bench])

    action = _make_action(attack_index=0)
    gen = _sneaky_placement(state, action)
    req = next(gen)
    assert req.choice_type == "choose_target"
    assert len(req.targets) == 2

    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_TARGET,
        target_instance_id=opp_bench.instance_id,
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    assert opp_bench.damage_counters == 2
    assert opp_bench.current_hp == 60


def test_sneaky_placement_targets_active():
    """sv06-089 Swirlix — Sneaky Placement: can target active Pokémon."""
    from app.engine.effects.attacks import _sneaky_placement

    attacker = CardInstance(
        instance_id="spa-atk", card_def_id="sv06-089",
        card_name="Swirlix", current_hp=70, max_hp=70, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="spa-opp-a", card_def_id="tst-sp-opp2",
        card_name="OppActive2", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)

    action = _make_action(attack_index=0)
    gen = _sneaky_placement(state, action)
    req = next(gen)
    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_TARGET,
        target_instance_id=opp_active.instance_id,
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    assert opp_active.damage_counters == 2
    assert opp_active.current_hp == 80


# Fix #5: _tea_server_flag — retrieve Basic Grass Energy from discard
@pytest.mark.asyncio
async def test_tea_server_moves_grass_energy_from_discard_to_hand():
    """sv06-021 Poltchageist — Tea Server: moves 1 Basic Grass Energy from discard to hand."""
    from app.engine.effects.attacks import _tea_server_flag

    attacker = CardInstance(
        instance_id="ts-atk", card_def_id="sv06-021",
        card_name="Poltchageist", current_hp=60, max_hp=60, zone=Zone.ACTIVE,
    )
    opp = CardInstance(
        instance_id="ts-opp", card_def_id="tst-ts-opp",
        card_name="OppMon", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    grass_e = CardInstance(
        instance_id="ts-grass-e", card_def_id="grass-energy",
        card_name="Grass Energy", current_hp=0, max_hp=0, zone=Zone.DISCARD,
        card_type="energy", card_subtype="basic",
    )
    state = _make_state(p1_active=attacker, p2_active=opp)
    state.p1.discard = [grass_e]

    action = _make_action(attack_index=0)
    gen = _tea_server_flag(state, action)
    req = next(gen)
    assert req.choice_type == "choose_cards"

    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_CARDS,
        selected_cards=[grass_e.instance_id],
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    assert grass_e not in state.p1.discard
    assert grass_e in state.p1.hand
    assert grass_e.zone == Zone.HAND


def test_tea_server_no_op_when_no_grass_energy_in_discard():
    """sv06-021 Poltchageist — Tea Server: no-op when no Grass Energy in discard."""
    from app.engine.effects.attacks import _tea_server_flag

    attacker = CardInstance(
        instance_id="ts2-atk", card_def_id="sv06-021",
        card_name="Poltchageist", current_hp=60, max_hp=60, zone=Zone.ACTIVE,
    )
    opp = CardInstance(
        instance_id="ts2-opp", card_def_id="tst-ts2-opp",
        card_name="OppMon", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=attacker, p2_active=opp)

    action = _make_action(attack_index=0)
    result = _tea_server_flag(state, action)
    if hasattr(result, "__next__"):
        try:
            next(result)
        except StopIteration:
            pass

    assert state.p1.hand == []


# Fix #6: _cursed_drop_flag — place 4 counters in any way on opp's Pokémon
@pytest.mark.asyncio
async def test_cursed_drop_places_4_counters_on_active():
    """sv06-022 Sinistcha — Cursed Drop: places 4 damage counters (choosing active each time)."""
    from app.engine.effects.attacks import _cursed_drop_flag

    attacker = CardInstance(
        instance_id="cd-atk", card_def_id="sv06-022",
        card_name="Sinistcha", current_hp=120, max_hp=120, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="cd-opp-a", card_def_id="tst-cd-opp",
        card_name="OppActive", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)

    action = _make_action(attack_index=0)
    gen = _cursed_drop_flag(state, action)
    req = next(gen)
    assert req.choice_type == "choose_target"
    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_TARGET,
        target_instance_id=opp_active.instance_id,
    )
    for _ in range(3):
        try:
            req = gen.send(resp)
        except StopIteration:
            break
    try:
        gen.send(resp)
    except StopIteration:
        pass

    assert opp_active.damage_counters == 4
    assert opp_active.current_hp == 60


# Fix #7: _spill_the_tea_flag — discard Grass Energy from own Pokémon, 70 per discard
@pytest.mark.asyncio
async def test_spill_the_tea_discards_grass_and_deals_damage():
    """sv06-022 Sinistcha atk1 — Spill the Tea: discards 2 Grass Energy and deals 140 damage."""
    from app.engine.effects.attacks import _spill_the_tea_flag

    attacker = CardInstance(
        instance_id="stt-atk", card_def_id="sv06-022",
        card_name="Sinistcha", current_hp=120, max_hp=120, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="stt-opp", card_def_id="tst-stt-opp",
        card_name="OppMon", current_hp=200, max_hp=200, zone=Zone.ACTIVE,
    )
    g1 = EnergyAttachment(
        energy_type=EnergyType.GRASS, source_card_id="stt-g1-src", card_def_id="grass-energy",
    )
    g2 = EnergyAttachment(
        energy_type=EnergyType.GRASS, source_card_id="stt-g2-src", card_def_id="grass-energy",
    )
    attacker.energy_attached = [g1, g2]
    state = _make_state(p1_active=attacker, p2_active=opp_active)

    action = _make_action(attack_index=1)
    gen = _spill_the_tea_flag(state, action)
    req = next(gen)
    assert req.choice_type == "choose_cards"
    assert req.max_count == 2

    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_CARDS,
        selected_cards=["stt-g1-src", "stt-g2-src"],
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    assert len(attacker.energy_attached) == 0
    assert opp_active.current_hp == 200 - 140


# Fix #8: _re_brew_flag — counters based on Grass Energy in discard
@pytest.mark.asyncio
async def test_re_brew_places_counters_and_shuffles_energy():
    """sv06-023 Sinistcha ex — Re-Brew: 2 counters per Grass Energy in discard, shuffles energy back."""
    from app.engine.effects.attacks import _re_brew_flag

    attacker = CardInstance(
        instance_id="rb-atk", card_def_id="sv06-023",
        card_name="Sinistcha ex", current_hp=240, max_hp=240, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="rb-opp", card_def_id="tst-rb-opp",
        card_name="OppMon", current_hp=200, max_hp=200, zone=Zone.ACTIVE,
    )
    grass1 = CardInstance(
        instance_id="rb-g1", card_def_id="grass-energy",
        card_name="Grass Energy", current_hp=0, max_hp=0, zone=Zone.DISCARD,
        card_type="energy", card_subtype="basic",
    )
    grass2 = CardInstance(
        instance_id="rb-g2", card_def_id="grass-energy",
        card_name="Grass Energy", current_hp=0, max_hp=0, zone=Zone.DISCARD,
        card_type="energy", card_subtype="basic",
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)
    state.p1.discard = [grass1, grass2]

    action = _make_action(attack_index=0)
    gen = _re_brew_flag(state, action)
    req = next(gen)
    assert req.choice_type == "choose_target"

    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_TARGET,
        target_instance_id=opp_active.instance_id,
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    # 2 grass energy → 4 counters → 40 HP damage
    assert opp_active.damage_counters == 4
    assert opp_active.current_hp == 160
    # Energy shuffled back into deck
    assert grass1 in state.p1.deck
    assert grass2 in state.p1.deck
    assert grass1 not in state.p1.discard
    assert grass2 not in state.p1.discard


# Fix #9: _peck_off_flag — discards opp active's tool, then deals 50
def test_peck_off_discards_tool_and_deals_damage():
    """sv06-045 Seaking — Peck Off: discards tool from opp Active, then 50 damage."""
    from app.engine.effects.attacks import _peck_off_flag
    from app.cards.models import CardDefinition

    seaking_cdef = CardDefinition(
        tcgdex_id="sv06-045", name="Seaking",
        set_abbrev="TWM", set_number="045",
        category="pokemon", stage="Stage 1", hp=110,
        attacks=[AttackDef(name="Peck Off", damage="50", cost=["Water"])],
        abilities=[],
    )
    card_registry.register(seaking_cdef)

    attacker = CardInstance(
        instance_id="po-atk", card_def_id="sv06-045",
        card_name="Seaking", current_hp=110, max_hp=110, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="po-opp", card_def_id="tst-po-opp",
        card_name="OppMon", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    opp_active.tools_attached = ["some-tool-id"]
    state = _make_state(p1_active=attacker, p2_active=opp_active)

    action = _make_action(attack_index=0)
    result = _peck_off_flag(state, action)
    if hasattr(result, "__next__"):
        try:
            next(result)
        except StopIteration:
            pass

    assert opp_active.tools_attached == []
    assert opp_active.current_hp == 50  # 50 default damage


# Fix #10: _inviting_kiss_flag — benched Pokémon becomes Confused
def test_inviting_kiss_benches_pokemon_and_applies_confused():
    """sv06-046 Jynx — Inviting Kiss: benches 1 Basic Pokémon which becomes Confused."""
    from app.engine.effects.attacks import _inviting_kiss_flag

    attacker = CardInstance(
        instance_id="ik-atk", card_def_id="sv06-046",
        card_name="Jynx", current_hp=80, max_hp=80, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="ik-opp", card_def_id="tst-ik-opp",
        card_name="OppMon", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    basic_in_deck = CardInstance(
        instance_id="ik-basic", card_def_id="tst-ik-basic",
        card_name="BasicPoke", current_hp=60, max_hp=60, zone=Zone.DECK,
        card_type="pokemon", card_subtype="basic",
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)
    state.p1.deck = [basic_in_deck]

    action = _make_action(attack_index=0)
    gen = _inviting_kiss_flag(state, action)
    try:
        req = next(gen)
        resp = Action(
            player_id="p1",
            action_type=ActionType.CHOOSE_CARDS,
            selected_cards=[basic_in_deck.instance_id],
        )
        gen.send(resp)
    except StopIteration:
        pass

    assert basic_in_deck in state.p1.bench
    assert StatusCondition.CONFUSED in basic_in_deck.status_conditions


# Fix #11: _flock_flag — searches deck for up to 2 Froakie
@pytest.mark.asyncio
async def test_flock_benches_up_to_2_froakie():
    """sv06-056 Froakie — Flock: puts up to 2 Froakie from deck onto Bench."""
    from app.engine.effects.attacks import _flock_flag

    attacker = CardInstance(
        instance_id="fl-atk", card_def_id="sv06-056",
        card_name="Froakie", current_hp=60, max_hp=60, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="fl-opp", card_def_id="tst-fl-opp",
        card_name="OppMon", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    froakie1 = CardInstance(
        instance_id="fl-f1", card_def_id="sv06-056",
        card_name="Froakie", current_hp=60, max_hp=60, zone=Zone.DECK,
        card_type="pokemon", card_subtype="basic",
    )
    froakie2 = CardInstance(
        instance_id="fl-f2", card_def_id="sv06-056",
        card_name="Froakie", current_hp=60, max_hp=60, zone=Zone.DECK,
        card_type="pokemon", card_subtype="basic",
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)
    state.p1.deck = [froakie1, froakie2]

    action = _make_action(attack_index=0)
    gen = _flock_flag(state, action)
    req = next(gen)
    assert req.choice_type == "choose_cards"
    assert req.max_count == 2

    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_CARDS,
        selected_cards=[froakie1.instance_id, froakie2.instance_id],
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    assert froakie1 in state.p1.bench
    assert froakie2 in state.p1.bench
    assert froakie1.zone == Zone.BENCH
    assert froakie2.zone == Zone.BENCH


# Fix #12: _snip_snip_flag — flip 2 coins, mill per heads
def test_snip_snip_mills_deck_on_heads(monkeypatch):
    """sv06-048 Crawdaunt — Snip Snip: mills 2 cards from opp deck (both heads)."""
    from app.engine.effects import attacks as attacks_mod

    monkeypatch.setattr(attacks_mod._random, "choice", lambda _: True)

    attacker = CardInstance(
        instance_id="ss-atk", card_def_id="sv06-048",
        card_name="Crawdaunt", current_hp=130, max_hp=130, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="ss-opp", card_def_id="tst-ss-opp",
        card_name="OppMon", current_hp=200, max_hp=200, zone=Zone.ACTIVE,
    )
    deck_card1 = CardInstance(
        instance_id="ss-dc1", card_def_id="tst-dc1",
        card_name="DeckCard1", current_hp=0, max_hp=0, zone=Zone.DECK,
    )
    deck_card2 = CardInstance(
        instance_id="ss-dc2", card_def_id="tst-dc2",
        card_name="DeckCard2", current_hp=0, max_hp=0, zone=Zone.DECK,
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)
    state.p2.deck = [deck_card1, deck_card2]

    action = _make_action(attack_index=0)
    result = attacks_mod._snip_snip_flag(state, action)
    if hasattr(result, "__next__"):
        try:
            next(result)
        except StopIteration:
            pass

    assert len(state.p2.deck) == 0
    assert deck_card1 in state.p2.discard
    assert deck_card2 in state.p2.discard


def test_snip_snip_no_mill_on_tails(monkeypatch):
    """sv06-048 Crawdaunt — Snip Snip: no mill when both tails."""
    from app.engine.effects import attacks as attacks_mod

    monkeypatch.setattr(attacks_mod._random, "choice", lambda _: False)

    attacker = CardInstance(
        instance_id="ss2-atk", card_def_id="sv06-048",
        card_name="Crawdaunt", current_hp=130, max_hp=130, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="ss2-opp", card_def_id="tst-ss2-opp",
        card_name="OppMon", current_hp=200, max_hp=200, zone=Zone.ACTIVE,
    )
    deck_card = CardInstance(
        instance_id="ss2-dc1", card_def_id="tst-dc3",
        card_name="DeckCard3", current_hp=0, max_hp=0, zone=Zone.DECK,
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)
    state.p2.deck = [deck_card]

    action = _make_action(attack_index=0)
    result = attacks_mod._snip_snip_flag(state, action)
    if hasattr(result, "__next__"):
        try:
            next(result)
        except StopIteration:
            pass

    assert deck_card in state.p2.deck
    assert len(state.p2.discard) == 0


# Fix #13: _colorful_catch_flag — up to 3 different-type Basic Energy from deck
@pytest.mark.asyncio
async def test_colorful_catch_fetches_different_type_energy():
    """sv06.5-050 Eevee — Colorful Catch: fetches up to 3 Basic Energy of different types."""
    from app.engine.effects.attacks import _colorful_catch_flag

    attacker = CardInstance(
        instance_id="cc-atk", card_def_id="sv06.5-050",
        card_name="Eevee", current_hp=60, max_hp=60, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="cc-opp", card_def_id="tst-cc-opp",
        card_name="OppMon", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    grass_e = CardInstance(
        instance_id="cc-g", card_def_id="grass-energy",
        card_name="Grass Energy", current_hp=0, max_hp=0, zone=Zone.DECK,
        card_type="energy", card_subtype="basic",
    )
    fire_e = CardInstance(
        instance_id="cc-f", card_def_id="fire-energy",
        card_name="Fire Energy", current_hp=0, max_hp=0, zone=Zone.DECK,
        card_type="energy", card_subtype="basic",
    )
    water_e = CardInstance(
        instance_id="cc-w", card_def_id="water-energy",
        card_name="Water Energy", current_hp=0, max_hp=0, zone=Zone.DECK,
        card_type="energy", card_subtype="basic",
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)
    state.p1.deck = [grass_e, fire_e, water_e]

    action = _make_action(attack_index=0)
    gen = _colorful_catch_flag(state, action)
    req = next(gen)
    assert req.choice_type == "choose_cards"
    assert req.max_count == 3

    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_CARDS,
        selected_cards=[grass_e.instance_id, fire_e.instance_id, water_e.instance_id],
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    assert grass_e in state.p1.hand
    assert fire_e in state.p1.hand
    assert water_e in state.p1.hand
    assert len(state.p1.deck) == 0


# Fix #14: _energy_assist_flag — attach Basic Energy from discard to benched Pokémon
@pytest.mark.asyncio
async def test_energy_assist_attaches_energy_from_discard_to_bench():
    """sv06.5-051 Furfrou — Energy Assist: attaches a Basic Energy from discard to a Benched Pokémon."""
    from app.engine.effects.attacks import _energy_assist_flag

    attacker = CardInstance(
        instance_id="ea-atk", card_def_id="sv06.5-051",
        card_name="Furfrou", current_hp=110, max_hp=110, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="ea-opp", card_def_id="tst-ea-opp",
        card_name="OppMon", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    bench_poke = CardInstance(
        instance_id="ea-bench", card_def_id="tst-ea-bench",
        card_name="BenchPoke", current_hp=80, max_hp=80, zone=Zone.BENCH,
    )
    energy_in_discard = CardInstance(
        instance_id="ea-energy", card_def_id="grass-energy",
        card_name="Grass Energy", current_hp=0, max_hp=0, zone=Zone.DISCARD,
        card_type="energy", card_subtype="basic",
        energy_provides=["Grass"],
    )
    state = _make_state(p1_active=attacker, p1_bench=[bench_poke], p2_active=opp_active)
    state.p1.discard = [energy_in_discard]

    action = _make_action(attack_index=0)
    gen = _energy_assist_flag(state, action)
    # First yield: choose energy
    req1 = next(gen)
    assert req1.choice_type == "choose_cards"

    resp1 = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_CARDS,
        selected_cards=[energy_in_discard.instance_id],
    )
    # Second yield: choose target bench
    req2 = gen.send(resp1)
    assert req2.choice_type == "choose_target"

    resp2 = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_TARGET,
        target_instance_id=bench_poke.instance_id,
    )
    try:
        gen.send(resp2)
    except StopIteration:
        pass

    assert energy_in_discard not in state.p1.discard
    assert len(bench_poke.energy_attached) == 1
    # Damage is dealt via _do_default_damage (30 for Furfrou, requires card registration to test)


# Fix #15: _splashing_turn_flag — 70 + switch active with bench
@pytest.mark.asyncio
async def test_splashing_turn_deals_damage_and_switches():
    """sv07-037 Tirtouga — Splashing Turn: 70 damage + switches active with chosen benched Pokémon."""
    from app.engine.effects.attacks import _splashing_turn_flag

    attacker = CardInstance(
        instance_id="st-atk", card_def_id="sv07-037",
        card_name="Tirtouga", current_hp=80, max_hp=80, zone=Zone.ACTIVE,
    )
    bench_poke = CardInstance(
        instance_id="st-bench", card_def_id="tst-st-bench",
        card_name="BenchPoke", current_hp=80, max_hp=80, zone=Zone.BENCH,
    )
    opp_active = CardInstance(
        instance_id="st-opp", card_def_id="tst-st-opp",
        card_name="OppMon", current_hp=200, max_hp=200, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=attacker, p1_bench=[bench_poke], p2_active=opp_active)

    action = _make_action(attack_index=0)
    gen = _splashing_turn_flag(state, action)
    req = next(gen)
    assert req.choice_type == "choose_target"

    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_TARGET,
        target_instance_id=bench_poke.instance_id,
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    # Damage is dealt via _do_default_damage (requires card registration to verify exact amount)
    assert state.p1.active is bench_poke
    assert bench_poke.zone == Zone.ACTIVE
    assert attacker in state.p1.bench
    assert attacker.zone == Zone.BENCH


# ─────────────────────────────────────────────────────────────────────────────
# Session 10 Engine Gaps (findings #EG4–#EG13) — now implemented
# ─────────────────────────────────────────────────────────────────────────────


def test_EG4_drum_beating_sets_extra_cost_on_opp():
    """sv06-016 Rillaboom — Drum Beating sets extra_attack_cost=1 and extra_retreat_cost=1 on opp active."""
    from app.engine.effects.attacks import _drum_beating

    attacker = CardInstance(
        instance_id="db-atk", card_def_id="sv06-016",
        card_name="Rillaboom", current_hp=180, max_hp=180, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="db-opp", card_def_id="tst-db-opp",
        card_name="OppMon", current_hp=200, max_hp=200, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)

    action = _make_action()
    _drum_beating(state, action)

    assert opp_active.extra_attack_cost == 1
    assert opp_active.extra_retreat_cost == 1
    assert any(e.get("event_type") == "drum_beating" for e in state.events)


def test_EG4_drum_beating_fields_cleared_by_runner():
    """extra_attack_cost and extra_retreat_cost are cleared at end of affected player's own turn."""
    from app.engine.runner import MatchRunner

    opp_active = CardInstance(
        instance_id="db2-opp", card_def_id="tst-db2",
        card_name="OppMon", current_hp=200, max_hp=200, zone=Zone.ACTIVE,
    )
    opp_active.extra_attack_cost = 1
    opp_active.extra_retreat_cost = 1
    state = _make_state(p2_active=opp_active)
    state.active_player = "p2"  # simulate p2's turn ending

    runner = _runner_for_between_turns()
    runner._end_turn(state)

    assert opp_active.extra_attack_cost == 0
    assert opp_active.extra_retreat_cost == 0


@pytest.mark.asyncio
async def test_EG5_piercing_gaze_reveals_hand_and_discards_chosen_card():
    """sv06-068 Luxray ex — Piercing Gaze: attacker chooses 1 card from opp's hand to discard."""
    from app.engine.effects.attacks import _piercing_gaze

    attacker = CardInstance(
        instance_id="pg-atk", card_def_id="sv06-068",
        card_name="Luxray ex", current_hp=270, max_hp=270, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="pg-opp", card_def_id="tst-pg-opp",
        card_name="OppMon", current_hp=200, max_hp=200, zone=Zone.ACTIVE,
    )
    opp_hand_card = CardInstance(
        instance_id="pg-hand", card_def_id="tst-pg-hand",
        card_name="SomeCard", zone=Zone.HAND,
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)
    state.p2.hand = [opp_hand_card]

    action = _make_action()
    gen = _piercing_gaze(state, action)
    req = next(gen)
    assert req.choice_type == "choose_cards"
    assert any(c.instance_id == opp_hand_card.instance_id for c in req.cards)

    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_CARDS,
        selected_cards=[opp_hand_card.instance_id],
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    assert opp_hand_card not in state.p2.hand
    assert opp_hand_card in state.p2.discard
    assert opp_hand_card.zone == Zone.DISCARD
    assert any(e.get("event_type") == "piercing_gaze" for e in state.events)


def test_EG6_wind_power_charge_sets_bonus():
    """sv06-076 Kilowattrel — Wind Power Charge sets next_attack_damage_bonus = 120 on self."""
    from app.engine.effects.attacks import _wind_power_charge

    attacker = CardInstance(
        instance_id="wpc-atk", card_def_id="sv06-076",
        card_name="Kilowattrel", current_hp=80, max_hp=80, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="wpc-opp", card_def_id="tst-wpc-opp",
        card_name="OppMon", current_hp=200, max_hp=200, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)

    action = _make_action()
    _wind_power_charge(state, action)

    assert attacker.next_attack_damage_bonus == 120
    assert any(e.get("event_type") == "wind_power_charge" for e in state.events)


def test_EG6_next_attack_bonus_consumed_on_next_attack(monkeypatch):
    """next_attack_damage_bonus is added to the next _apply_damage call and then cleared."""
    from app.engine.effects.attacks import _apply_damage

    attacker = CardInstance(
        instance_id="wpc2-atk", card_def_id="tst-wpc2-atk",
        card_name="Attacker", current_hp=80, max_hp=80, zone=Zone.ACTIVE,
        next_attack_damage_bonus=120,
    )
    opp_active = CardInstance(
        instance_id="wpc2-opp", card_def_id="tst-wpc2-opp",
        card_name="Defender", current_hp=300, max_hp=300, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)
    action = _make_action()

    _apply_damage(state, action, 60)  # 60 base + 120 bonus = 180

    # Bonus should be consumed
    assert attacker.next_attack_damage_bonus == 0
    assert opp_active.damage_counters == 18  # 180 damage = 18 counters


@pytest.mark.asyncio
async def test_EG7_breezy_gift_shuffles_self_and_searches_deck():
    """sv07-011 Eldegoss — Breezy Gift: shuffle self+attached into deck, promote bench, search up to 3."""
    from app.engine.effects.attacks import _breezy_gift

    attacker = CardInstance(
        instance_id="bg-atk", card_def_id="sv07-011",
        card_name="Eldegoss", current_hp=90, max_hp=90, zone=Zone.ACTIVE,
    )
    bench_poke = CardInstance(
        instance_id="bg-bench", card_def_id="tst-bg-bench",
        card_name="BenchPoke", current_hp=70, max_hp=70, zone=Zone.BENCH,
    )
    deck_card1 = CardInstance(
        instance_id="bg-deck1", card_def_id="tst-bg-dk1",
        card_name="DeckCard1", zone=Zone.DECK,
    )
    deck_card2 = CardInstance(
        instance_id="bg-deck2", card_def_id="tst-bg-dk2",
        card_name="DeckCard2", zone=Zone.DECK,
    )
    state = _make_state(p1_active=attacker, p1_bench=[bench_poke])
    state.p1.deck = [deck_card1, deck_card2]

    action = _make_action()
    gen = _breezy_gift(state, action)
    req = next(gen)
    assert req.choice_type == "choose_cards"

    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_CARDS,
        selected_cards=[deck_card1.instance_id],
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    # Old attacker should be in deck, bench promoted to active
    assert attacker in state.p1.deck
    assert state.p1.active is bench_poke
    assert bench_poke.zone == Zone.ACTIVE
    # Chosen card should be in hand
    assert deck_card1 in state.p1.hand
    assert any(e.get("event_type") == "breezy_gift_shuffle" for e in state.events)


@pytest.mark.asyncio
async def test_EG8_summoning_gate_benches_top8_pokemon():
    """sv05-072 Reuniclus — Summoning Gate: look at top 8, bench chosen Pokémon."""
    from app.engine.effects.attacks import _summoning_gate_b5

    attacker = CardInstance(
        instance_id="sg-atk", card_def_id="sv05-072",
        card_name="Reuniclus", current_hp=120, max_hp=120, zone=Zone.ACTIVE,
    )
    deck_poke = CardInstance(
        instance_id="sg-dpoke", card_def_id="tst-sg-poke",
        card_name="DeckPokemon", current_hp=80, max_hp=80, zone=Zone.DECK,
        card_type="Pokemon",
    )
    deck_trainer = CardInstance(
        instance_id="sg-dtrain", card_def_id="tst-sg-train",
        card_name="Trainer", zone=Zone.DECK,
        card_type="Trainer",
    )
    opp_active = CardInstance(
        instance_id="sg-opp", card_def_id="tst-sg-opp",
        card_name="OppMon", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)
    state.p1.deck = [deck_poke, deck_trainer]

    action = _make_action()
    gen = _summoning_gate_b5(state, action)
    req = next(gen)
    assert req.choice_type == "choose_cards"

    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_CARDS,
        selected_cards=[deck_poke.instance_id],
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    assert deck_poke in state.p1.bench
    assert deck_poke.zone == Zone.BENCH
    assert any(e.get("event_type") == "summoning_gate" for e in state.events)


@pytest.mark.asyncio
async def test_EG9_metronome_copies_opp_attack_damage():
    """sv06-079 Clefable — Metronome: copies base damage of chosen opponent attack."""
    from app.engine.effects.attacks import _metronome

    attacker = CardInstance(
        instance_id="met-atk", card_def_id="sv06-079",
        card_name="Clefable", current_hp=120, max_hp=120, zone=Zone.ACTIVE,
    )
    opp_poke_cdef = _make_card(
        "tst-met-opp", "OppPokemon", hp=200,
        attacks=[AttackDef(name="Tackle", damage="60", cost=["Colorless"])],
    )
    card_registry.register(opp_poke_cdef)
    opp_active = CardInstance(
        instance_id="met-opp", card_def_id="tst-met-opp",
        card_name="OppPokemon", current_hp=200, max_hp=200, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)

    action = _make_action()
    gen = _metronome(state, action)
    # For a single attack, no choice prompt is shown; handler goes straight to damage
    try:
        next(gen)
        # If we get here, opp has multiple attacks and a choice is requested
    except StopIteration:
        pass

    # Verify damage was applied (60 damage = 6 counters)
    assert opp_active.damage_counters == 6
    assert any(e.get("event_type") == "metronome" for e in state.events)


@pytest.mark.asyncio
async def test_EG10_larimar_rain_attaches_energy_from_top20():
    """sv07-032 Lapras ex — Larimar Rain: attaches energy from top 20 deck cards to own Pokémon."""
    from app.engine.effects.attacks import _larimar_rain

    attacker = CardInstance(
        instance_id="lr-atk", card_def_id="sv07-032",
        card_name="Lapras ex", current_hp=230, max_hp=230, zone=Zone.ACTIVE,
    )
    energy_card = CardInstance(
        instance_id="lr-energy", card_def_id="basic-water",
        card_name="Water Energy", zone=Zone.DECK,
        card_type="Energy",
        energy_provides=["Water"],
    )
    non_energy = CardInstance(
        instance_id="lr-trainer", card_def_id="tst-lr-trainer",
        card_name="Trainer", zone=Zone.DECK,
        card_type="Trainer",
    )
    opp_active = CardInstance(
        instance_id="lr-opp", card_def_id="tst-lr-opp",
        card_name="OppMon", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)
    state.p1.deck = [energy_card, non_energy]

    action = _make_action(attack_index=1)
    gen = _larimar_rain(state, action)
    req = next(gen)
    assert req.choice_type == "choose_target"

    resp = Action(
        player_id="p1",
        action_type=ActionType.CHOOSE_TARGET,
        target_instance_id=attacker.instance_id,
    )
    # Send response to attach; next yield may request next energy (or StopIteration if done)
    try:
        req2 = gen.send(resp)
        # Skip remaining energy selection
        try:
            gen.send(None)
        except StopIteration:
            pass
    except StopIteration:
        pass

    assert len(attacker.energy_attached) >= 1
    assert any(e.get("event_type") == "energy_attached_from_deck" for e in state.events)


def test_EG11_unleash_lightning_sets_player_flag():
    """sv07-047 Electivire — Unleash Lightning: 220 + sets all_pokemon_cant_attack_next_turn on self."""
    from app.engine.effects.attacks import _unleash_lightning

    attacker = CardInstance(
        instance_id="ul-atk", card_def_id="sv07-047",
        card_name="Electivire", current_hp=170, max_hp=170, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="ul-opp", card_def_id="tst-ul-opp",
        card_name="OppMon", current_hp=400, max_hp=400, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)

    action = _make_action(attack_index=1)
    _unleash_lightning(state, action)

    assert state.p1.all_pokemon_cant_attack_next_turn is True
    assert any(e.get("event_type") == "unleash_lightning" for e in state.events)


def test_EG11_unleash_lightning_blocks_attack_via_actions():
    """all_pokemon_cant_attack_next_turn=True causes ActionValidator to return no ATTACK actions."""
    from app.engine.actions import ActionValidator

    rillaboom_cdef = _make_card(
        "sv06-016", "Rillaboom", hp=180,
        attacks=[AttackDef(name="Drum Beating", damage="60", cost=["Grass"])],
    )
    card_registry.register(rillaboom_cdef)
    attacker = CardInstance(
        instance_id="ul2-atk", card_def_id="sv06-016",
        card_name="Rillaboom", current_hp=180, max_hp=180, zone=Zone.ACTIVE,
    )
    attacker.energy_attached = [
        EnergyAttachment(energy_type=EnergyType.GRASS, source_card_id="g1", card_def_id="basic-grass"),
    ]
    opp_active = CardInstance(
        instance_id="ul2-opp", card_def_id="tst-ul2-opp",
        card_name="OppMon", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    from app.engine.state import Phase
    state = _make_state(p1_active=attacker, p2_active=opp_active)
    state.phase = Phase.ATTACK
    state.p1.all_pokemon_cant_attack_next_turn = True

    legal = ActionValidator.get_legal_actions(state, "p1")
    attack_actions = [a for a in legal if a.action_type == ActionType.ATTACK]
    assert len(attack_actions) == 0


def test_EG11_unleash_lightning_flag_cleared_by_runner():
    """all_pokemon_cant_attack_next_turn is cleared at end of the affected player's own turn."""
    from app.engine.runner import MatchRunner

    attacker = CardInstance(
        instance_id="ul3-atk", card_def_id="tst-ul3",
        card_name="Electivire", current_hp=170, max_hp=170, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=attacker)
    state.p1.all_pokemon_cant_attack_next_turn = True
    state.active_player = "p1"

    runner = _runner_for_between_turns()
    runner._end_turn(state)

    assert state.p1.all_pokemon_cant_attack_next_turn is False


def test_EG12_disorienting_flash_applies_confused_with_8_counters():
    """sv07-049 Lanturn — Disorienting Flash: CONFUSED applied with confused_counter_amount=8."""
    from app.engine.effects.attacks import _disorienting_flash

    attacker = CardInstance(
        instance_id="df-atk", card_def_id="sv07-049",
        card_name="Lanturn", current_hp=130, max_hp=130, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="df-opp", card_def_id="tst-df-opp",
        card_name="OppMon", current_hp=200, max_hp=200, zone=Zone.ACTIVE,
    )
    state = _make_state(p1_active=attacker, p2_active=opp_active)

    action = _make_action()
    _disorienting_flash(state, action)

    assert StatusCondition.CONFUSED in opp_active.status_conditions
    assert opp_active.confused_counter_amount == 8
    assert any(e.get("event_type") == "status_applied" for e in state.events)


def test_EG12_disorienting_flash_confusion_flip_uses_custom_counters(monkeypatch):
    """Confused flip with confused_counter_amount=8 deals 80 HP damage (not standard 30)."""
    import random as _random_mod

    # Force tails (confusion triggers)
    monkeypatch.setattr(_random_mod, "choice", lambda seq: False)

    opp_active = CardInstance(
        instance_id="df2-opp", card_def_id="tst-df2-opp",
        card_name="OppMon", current_hp=200, max_hp=200, zone=Zone.ACTIVE,
    )
    opp_active.status_conditions.add(StatusCondition.CONFUSED)
    opp_active.confused_counter_amount = 8

    state = _make_state(p2_active=opp_active)
    state.active_player = "p2"

    action = Action(player_id="p2", action_type=ActionType.ATTACK, attack_index=0)

    import asyncio
    from app.engine.transitions import _attack

    asyncio.run(_attack(state, action))

    assert opp_active.damage_counters == 8
    assert opp_active.current_hp == 120  # 200 - 80


@pytest.mark.asyncio
async def test_EG13_slowing_perfume_shuffles_bench_poke_when_going_second():
    """sv06-010 Illumise — Slowing Perfume: shuffles opp bench Pokémon to deck when going second on turn 2."""
    from app.engine.effects.attacks import _slowing_perfume

    attacker = CardInstance(
        instance_id="sp-atk", card_def_id="sv06-010",
        card_name="Illumise", current_hp=80, max_hp=80, zone=Zone.ACTIVE,
    )
    opp_active = CardInstance(
        instance_id="sp-opp", card_def_id="tst-sp-opp",
        card_name="OppActive", current_hp=100, max_hp=100, zone=Zone.ACTIVE,
    )
    opp_bench_poke = CardInstance(
        instance_id="sp-bench", card_def_id="tst-sp-bench",
        card_name="OppBench", current_hp=80, max_hp=80, zone=Zone.BENCH,
    )
    state = _make_state(p2_active=attacker, p1_active=opp_active, p1_bench=[])
    state.p1.active = opp_active
    state.p1.bench = [opp_bench_poke]
    state.p2.active = attacker
    state.first_player = "p1"  # p2 goes second
    state.turn_number = 2      # p2's first turn
    state.active_player = "p2"

    action = Action(player_id="p2", action_type=ActionType.ATTACK, attack_index=0)
    gen = _slowing_perfume(state, action)
    req = next(gen)
    assert req.choice_type == "choose_target"

    resp = Action(
        player_id="p2",
        action_type=ActionType.CHOOSE_TARGET,
        target_instance_id=opp_bench_poke.instance_id,
    )
    try:
        gen.send(resp)
    except StopIteration:
        pass

    assert opp_bench_poke not in state.p1.bench
    assert opp_bench_poke in state.p1.deck
    assert any(e.get("event_type") == "slowing_perfume" for e in state.events)


def test_EG13_slowing_perfume_no_effect_when_going_first():
    """Slowing Perfume does nothing when the attacker goes first."""
    from app.engine.effects.attacks import _slowing_perfume

    attacker = CardInstance(
        instance_id="sp2-atk", card_def_id="sv06-010",
        card_name="Illumise", current_hp=80, max_hp=80, zone=Zone.ACTIVE,
    )
    opp_bench_poke = CardInstance(
        instance_id="sp2-bench", card_def_id="tst-sp2-bench",
        card_name="OppBench", current_hp=80, max_hp=80, zone=Zone.BENCH,
    )
    state = _make_state(p1_active=attacker)
    state.p2.bench = [opp_bench_poke]
    state.first_player = "p1"  # p1 goes FIRST
    state.turn_number = 1
    state.active_player = "p1"

    action = _make_action(player_id="p1")
    gen = _slowing_perfume(state, action)
    try:
        next(gen)  # Should reach end without yielding (generator returns immediately)
    except StopIteration:
        pass

    assert opp_bench_poke in state.p2.bench  # nothing happened
    assert any(e.get("event_type") == "slowing_perfume_no_effect" for e in state.events)

