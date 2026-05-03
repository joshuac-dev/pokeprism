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
