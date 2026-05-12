"""Run-36 audit gap fixes — unit tests.

Covers:
  - Compound Eyes (sv06.5-002): +50 only when Galvantula attacks defender with ability
  - Primal Knowledge (sv07-038 Carracosta): +30 vs Evolution defender
  - Soft Wool (sv07-125 Dubwool): -30 damage reduction
  - Thicket Body (sv06-002 Tangrowth): -30 damage reduction
  - Solid Shell (sv05-010 Turtwig): -20 damage reduction
  - Impervious Shell (sv07-044 Drednaw): prevent 200+ damage
  - Incandescent Body (sv06-123 Heatran): burn attacker on damage
  - Poison Point (sv05-008 Roselia / sv05-009 Roserade): poison attacker on damage
  - Froslass svp-117 alt print: get_froslass_players / apply_froslass_shroud
  - Psyduck Damp mep-007 / mep-008 alt prints: has_psyduck_damp
  - Sandy Flapping mep-016: registered as active ability handler
"""
from __future__ import annotations

import pytest

import app.engine.effects  # noqa: F401
from app.cards import registry as card_registry
from app.cards.models import AbilityDef, AttackDef, CardDefinition
from app.engine.actions import Action, ActionType
from app.engine.effects.abilities import (
    apply_froslass_shroud,
    get_froslass_players,
    has_psyduck_damp,
)
from app.engine.effects.attacks import _apply_damage
from app.engine.effects.registry import EffectRegistry
from app.engine.state import CardInstance, EnergyType, GameState, Phase, StatusCondition, Zone


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
        set_abbrev="T36",
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


def _action(player_id: str = "p1", attack_index: int = 0) -> Action:
    return Action(action_type=ActionType.ATTACK, player_id=player_id, attack_index=attack_index)


def _deal(state: GameState, base_damage: int, *, player_id: str = "p1") -> int:
    """Call _apply_damage and return the damage dealt (defender HP diff)."""
    opp_id = "p2" if player_id == "p1" else "p1"
    opp = state.get_player(opp_id)
    before = opp.active.current_hp if opp.active else 0
    dmg = _apply_damage(state, Action(ActionType.ATTACK, player_id, attack_index=0), base_damage)
    return dmg


@pytest.fixture(autouse=True)
def clear_registry():
    yield
    card_registry.clear()


# ─── Compound Eyes (sv06.5-002 Galvantula) ──────────────────────────────────


def test_compound_eyes_adds_bonus_when_attacker_is_galvantula_vs_ability_defender():
    galvantula = _make_card("sv06.5-002", "Galvantula", types=["Lightning"],
                            attacks=[AttackDef(name="Electroweb", damage="60", cost=[])])
    defender_with_ability = _make_card("def-1", "Defender With Ability",
                                       abilities=[AbilityDef(name="Some Ability", effect="Does something.")])
    card_registry.register(galvantula)
    card_registry.register(defender_with_ability)

    atk = _inst(galvantula, "galv")
    def_ = _inst(defender_with_ability, "def")
    state = _state(p1_active=atk, p2_active=def_)

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 60)
    assert dmg == 110, f"Expected 110 (60+50), got {dmg}"


def test_compound_eyes_no_bonus_when_defender_has_no_ability():
    galvantula = _make_card("sv06.5-002", "Galvantula", types=["Lightning"],
                            attacks=[AttackDef(name="Electroweb", damage="60", cost=[])])
    plain_defender = _make_card("def-2", "Meowth")
    card_registry.register(galvantula)
    card_registry.register(plain_defender)

    atk = _inst(galvantula, "galv")
    def_ = _inst(plain_defender, "def")
    state = _state(p1_active=atk, p2_active=def_)

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 60)
    assert dmg == 60, f"Expected 60 (no bonus), got {dmg}"


def test_compound_eyes_no_bonus_when_non_galvantula_attacks_ability_defender():
    attacker = _make_card("other-1", "Pikachu", types=["Lightning"],
                          attacks=[AttackDef(name="Thunderbolt", damage="60", cost=[])])
    bench_galvantula = _make_card("sv06.5-002", "Galvantula", types=["Lightning"])
    defender_with_ability = _make_card("def-3", "Defender With Ability",
                                       abilities=[AbilityDef(name="Some Ability", effect="Does something.")])
    card_registry.register(attacker)
    card_registry.register(bench_galvantula)
    card_registry.register(defender_with_ability)

    atk = _inst(attacker, "pika")
    bench_galv = _inst(bench_galvantula, "bench-galv", zone=Zone.BENCH)
    def_ = _inst(defender_with_ability, "def")
    state = _state(p1_active=atk, p1_bench=[bench_galv], p2_active=def_)

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 60)
    assert dmg == 60, f"Expected 60 (bench Galvantula should not grant bonus), got {dmg}"


# ─── Primal Knowledge (sv07-038 Carracosta) ─────────────────────────────────


def test_primal_knowledge_adds_30_vs_evolution_defender():
    attacker = _make_card("atk-1", "Attacker", types=["Water"],
                          attacks=[AttackDef(name="Wave", damage="60", cost=[])])
    carracosta = _make_card("sv07-038", "Carracosta", types=["Water"],
                            abilities=[AbilityDef(name="Primal Knowledge", effect="...")])
    evo_defender = _make_card("def-evo", "Charizard", stage="Stage 2", types=["Fire"])
    card_registry.register(attacker)
    card_registry.register(carracosta)
    card_registry.register(evo_defender)

    atk = _inst(attacker, "atk")
    bench_costa = _inst(carracosta, "costa", zone=Zone.BENCH)
    def_ = _inst(evo_defender, "def")
    state = _state(p1_active=atk, p1_bench=[bench_costa], p2_active=def_)

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 60)
    assert dmg == 90, f"Expected 90 (60+30 Primal Knowledge), got {dmg}"


def test_primal_knowledge_no_bonus_vs_basic_defender():
    attacker = _make_card("atk-1", "Attacker", types=["Water"],
                          attacks=[AttackDef(name="Wave", damage="60", cost=[])])
    carracosta = _make_card("sv07-038", "Carracosta", types=["Water"])
    basic_defender = _make_card("def-basic", "Squirtle", stage="Basic", types=["Water"])
    card_registry.register(attacker)
    card_registry.register(carracosta)
    card_registry.register(basic_defender)

    atk = _inst(attacker, "atk")
    bench_costa = _inst(carracosta, "costa", zone=Zone.BENCH)
    def_ = _inst(basic_defender, "def")
    state = _state(p1_active=atk, p1_bench=[bench_costa], p2_active=def_)

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 60)
    assert dmg == 60, f"Expected 60 (no Primal Knowledge bonus vs Basic), got {dmg}"


# ─── Soft Wool (sv07-125 Dubwool) ───────────────────────────────────────────


def test_soft_wool_reduces_damage_by_30():
    attacker = _make_card("atk-1", "Attacker", types=["Normal"],
                          attacks=[AttackDef(name="Tackle", damage="80", cost=[])])
    dubwool = _make_card("sv07-125", "Dubwool", hp=130,
                         abilities=[AbilityDef(name="Soft Wool", effect="...")])
    card_registry.register(attacker)
    card_registry.register(dubwool)

    atk = _inst(attacker, "atk")
    def_ = _inst(dubwool, "dub")
    state = _state(p1_active=atk, p2_active=def_)

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 80)
    assert dmg == 50, f"Expected 50 (80-30 Soft Wool), got {dmg}"


# ─── Thicket Body (sv06-002 Tangrowth) ──────────────────────────────────────


def test_thicket_body_reduces_damage_by_30():
    attacker = _make_card("atk-1", "Attacker", types=["Fire"],
                          attacks=[AttackDef(name="Flamethrower", damage="100", cost=[])])
    tangrowth = _make_card("sv06-002", "Tangrowth", hp=150,
                           abilities=[AbilityDef(name="Thicket Body", effect="...")])
    card_registry.register(attacker)
    card_registry.register(tangrowth)

    atk = _inst(attacker, "atk")
    def_ = _inst(tangrowth, "tang")
    state = _state(p1_active=atk, p2_active=def_)

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 100)
    assert dmg == 70, f"Expected 70 (100-30 Thicket Body), got {dmg}"


# ─── Solid Shell (sv05-010 Turtwig) ─────────────────────────────────────────


def test_solid_shell_reduces_damage_by_20():
    attacker = _make_card("atk-1", "Attacker", types=["Fire"],
                          attacks=[AttackDef(name="Ember", damage="50", cost=[])])
    turtwig = _make_card("sv05-010", "Turtwig", hp=70,
                         abilities=[AbilityDef(name="Solid Shell", effect="...")])
    card_registry.register(attacker)
    card_registry.register(turtwig)

    atk = _inst(attacker, "atk")
    def_ = _inst(turtwig, "twig")
    state = _state(p1_active=atk, p2_active=def_)

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 50)
    assert dmg == 30, f"Expected 30 (50-20 Solid Shell), got {dmg}"


# ─── Impervious Shell (sv07-044 Drednaw) ────────────────────────────────────


def test_impervious_shell_blocks_damage_200_or_more():
    attacker = _make_card("atk-1", "Attacker", types=["Grass"],
                          attacks=[AttackDef(name="Giant Vine", damage="200", cost=[])])
    drednaw = _make_card("sv07-044", "Drednaw", hp=140,
                         abilities=[AbilityDef(name="Impervious Shell", effect="...")])
    card_registry.register(attacker)
    card_registry.register(drednaw)

    atk = _inst(attacker, "atk")
    def_ = _inst(drednaw, "dred")
    state = _state(p1_active=atk, p2_active=def_)

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 200)
    assert dmg == 0, f"Expected 0 (Impervious Shell blocks 200+), got {dmg}"
    assert def_.current_hp == 140, "HP should not have changed"


def test_impervious_shell_allows_damage_below_200():
    attacker = _make_card("atk-1", "Attacker", types=["Grass"],
                          attacks=[AttackDef(name="Vine Whip", damage="190", cost=[])])
    drednaw = _make_card("sv07-044", "Drednaw", hp=140)
    card_registry.register(attacker)
    card_registry.register(drednaw)

    atk = _inst(attacker, "atk")
    def_ = _inst(drednaw, "dred")
    state = _state(p1_active=atk, p2_active=def_)

    dmg = _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 190)
    assert dmg == 190, f"Expected 190 (below threshold), got {dmg}"


# ─── Incandescent Body (sv06-123 Heatran) ───────────────────────────────────


def test_incandescent_body_heatran_burns_attacker():
    attacker = _make_card("atk-1", "Attacker", types=["Water"],
                          attacks=[AttackDef(name="Surf", damage="60", cost=[])])
    heatran = _make_card("sv06-123", "Heatran", hp=130,
                         abilities=[AbilityDef(name="Incandescent Body", effect="...")])
    card_registry.register(attacker)
    card_registry.register(heatran)

    atk = _inst(attacker, "atk")
    def_ = _inst(heatran, "heatran")
    state = _state(p1_active=atk, p2_active=def_)

    _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 60)
    assert StatusCondition.BURNED in atk.status_conditions, \
        "Attacker should be Burned by Incandescent Body"


# ─── Poison Point (sv05-008 Roselia / sv05-009 Roserade) ────────────────────


@pytest.mark.parametrize("card_id,card_name", [
    ("sv05-008", "Roselia"),
    ("sv05-009", "Roserade"),
])
def test_poison_point_poisons_attacker(card_id, card_name):
    attacker = _make_card("atk-1", "Attacker", types=["Fire"],
                          attacks=[AttackDef(name="Fire Punch", damage="60", cost=[])])
    defender = _make_card(card_id, card_name, hp=80,
                          abilities=[AbilityDef(name="Poison Point", effect="...")])
    card_registry.register(attacker)
    card_registry.register(defender)

    atk = _inst(attacker, "atk")
    def_ = _inst(defender, "def")
    state = _state(p1_active=atk, p2_active=def_)

    _apply_damage(state, Action(ActionType.ATTACK, "p1", attack_index=0), 60)
    assert StatusCondition.POISONED in atk.status_conditions, \
        f"Attacker should be Poisoned by {card_name} Poison Point"


# ─── Froslass svp-117 alt print ─────────────────────────────────────────────


def test_get_froslass_players_recognises_svp117():
    froslass_svp = _make_card("svp-117", "Froslass", hp=90,
                               abilities=[AbilityDef(name="Freezing Shroud", effect="...")])
    card_registry.register(froslass_svp)

    froslass_inst = _inst(froslass_svp, "frost-svp")
    state = _state(p1_active=froslass_inst)

    players = get_froslass_players(state)
    assert "p1" in players, "svp-117 Froslass should be detected by get_froslass_players"


def test_apply_froslass_shroud_damages_ability_pokemon_with_svp117_in_play():
    froslass_svp = _make_card("svp-117", "Froslass", hp=90,
                               abilities=[AbilityDef(name="Freezing Shroud", effect="...")])
    ability_pokemon = _make_card("other-1", "Victim", hp=100,
                                  abilities=[AbilityDef(name="Any Ability", effect="yes")])
    card_registry.register(froslass_svp)
    card_registry.register(ability_pokemon)

    froslass_inst = _inst(froslass_svp, "frost-svp")
    victim = _inst(ability_pokemon, "victim", zone=Zone.BENCH)
    state = _state(p1_active=froslass_inst, p2_bench=[victim])

    apply_froslass_shroud(state)
    assert victim.damage_counters == 1, "Victim with ability should take 1 counter from Freezing Shroud"


def test_apply_froslass_shroud_skips_svp117_froslass_itself():
    froslass_svp = _make_card("svp-117", "Froslass", hp=90,
                               abilities=[AbilityDef(name="Freezing Shroud", effect="...")])
    card_registry.register(froslass_svp)

    froslass_inst = _inst(froslass_svp, "frost-svp")
    state = _state(p1_active=froslass_inst)

    apply_froslass_shroud(state)
    assert froslass_inst.damage_counters == 0, "svp-117 Froslass should not damage itself"


# ─── Psyduck Damp alt prints mep-007 / mep-008 ──────────────────────────────


@pytest.mark.parametrize("card_id,name", [
    ("mep-007", "Psyduck"),
    ("mep-008", "Golduck"),
])
def test_has_psyduck_damp_returns_true_for_alt_prints(card_id, name):
    damp_mon = _make_card(card_id, name,
                          abilities=[AbilityDef(name="Damp", effect="...")])
    card_registry.register(damp_mon)

    inst = _inst(damp_mon, "damp-inst")
    state = _state(p1_active=inst)

    assert has_psyduck_damp(state), \
        f"{name} ({card_id}) should trigger has_psyduck_damp"


# ─── Sandy Flapping mep-016 active registration ─────────────────────────────


def test_sandy_flapping_mep016_registered_as_active_handler():
    reg = EffectRegistry.instance()
    key = "mep-016:Sandy Flapping"
    assert key in reg._ability_effects, \
        "mep-016 Sandy Flapping should be registered as an active ability handler"
    assert key not in reg._passive_abilities, \
        "mep-016 Sandy Flapping should NOT remain in passive abilities set"
