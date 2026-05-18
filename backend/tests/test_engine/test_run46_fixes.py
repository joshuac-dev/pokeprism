"""Run-46 engine fix regression tests.

Covers all 6 code fixes applied in PR #88 (run-46 audit):

  Fix 1: Bemusing Aroma (sv10.5b-007 Lilligant)
          On tails, Confused was applied to player.active (self) instead of
          opp.active (opponent).  Fixed to target opp.active.

  Fix 2: Fade Out (sv09-068 Lillie's Comfey)
          energy_attached.clear() dropped energy source cards permanently.
          Fixed to return source cards from discard/deck to hand first
          (same bounce pattern as _tuck_tail).

  Fix 3: Magneton svp-153 (Overvolt Discharge)
          Registered via register_passive_ability — no handler wired, ability
          was silently ignored.  Fixed to register_ability with
          _overvolt_discharge + _cond_overvolt_discharge.

  Fix 4: Magneton svp-159 (Overvolt Discharge)
          Same fix as svp-153 (also carried a wrong "# Magnezone" comment).

  Fix 5: Koraidon sv08-116 (Unrelenting Onslaught)
          Bonus 150 fired for *any* benched Pokémon that attacked last turn,
          not just Ancient Pokémon.  Fixed with _is_ancient() filter.

  Fix 6: Alcremie ex sv09-075 (Confectionary Gift)
          caster was always player.active, breaking the ability when Alcremie ex
          was on the bench.  Fixed to _find_in_play(player, action.card_instance_id).
"""
from __future__ import annotations

import pytest

import app.engine.effects  # noqa: F401 — ensures register_all() has run
from app.cards import registry as card_registry
from app.cards.models import AbilityDef, AttackDef, CardDefinition
from app.engine.actions import Action, ActionType
from app.engine.effects.registry import EffectRegistry
from app.engine.state import (
    CardInstance, EnergyAttachment, EnergyType, GameState, Phase, Zone,
    StatusCondition,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _card(tcgdex_id: str, name: str, hp: int = 120,
          attacks: list[AttackDef] | None = None,
          abilities: list[AbilityDef] | None = None,
          stage: str = "Basic") -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id,
        name=name,
        set_abbrev="R46",
        set_number="001",
        category="pokemon",
        stage=stage,
        hp=hp,
        attacks=attacks or [],
        abilities=abilities or [],
    )


def _inst(cdef: CardDefinition, zone: Zone = Zone.ACTIVE,
          hp: int | None = None) -> CardInstance:
    hp = hp if hp is not None else (cdef.hp or 100)
    return CardInstance(
        instance_id="inst-" + cdef.tcgdex_id + "-" + str(id(cdef)),
        card_def_id=cdef.tcgdex_id,
        card_name=cdef.name,
        current_hp=hp,
        max_hp=cdef.hp or hp,
        zone=zone,
    )


def _energy_card(instance_id: str, def_id: str = "basic-energy-r46") -> CardInstance:
    return CardInstance(
        instance_id=instance_id,
        card_def_id=def_id,
        card_name="Basic Energy",
        current_hp=0,
        max_hp=0,
        zone=Zone.DISCARD,
    )


def _attachment(energy_type: EnergyType, source_card_id: str,
                card_def_id: str = "basic-energy-r46") -> EnergyAttachment:
    return EnergyAttachment(
        energy_type=energy_type,
        source_card_id=source_card_id,
        card_def_id=card_def_id,
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


def _attack_action(player_id: str = "p1", attack_index: int = 0,
                   card_instance_id: str | None = None) -> Action:
    return Action(
        player_id=player_id,
        action_type=ActionType.ATTACK,
        attack_index=attack_index,
        card_instance_id=card_instance_id,
    )


def _ability_action(player_id: str = "p1", card_instance_id: str = "") -> Action:
    return Action(
        player_id=player_id,
        action_type=ActionType.USE_ABILITY,
        card_instance_id=card_instance_id,
    )


@pytest.fixture(autouse=True)
def clear_registry():
    yield
    card_registry.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Fix 1 & 2: Bemusing Aroma (sv10.5b-007 Lilligant)
# ──────────────────────────────────────────────────────────────────────────────

def test_bemusing_aroma_tails_confuses_opponent_not_self(monkeypatch):
    """Fix 1 regression: on tails, opp.active gets CONFUSED (not player.active)."""
    from app.engine.effects import attacks as atk_mod

    monkeypatch.setattr(atk_mod._random, "choice", lambda _: False)  # tails

    attacker_def = _card("r46-lilligant", "Lilligant", hp=90,
                         attacks=[AttackDef(name="Bemusing Aroma", damage="30", cost=["Grass"])])
    opp_def = _card("r46-opp-ba", "OppMon", hp=200)
    card_registry.register(attacker_def)
    card_registry.register(opp_def)

    attacker = _inst(attacker_def, zone=Zone.ACTIVE, hp=90)
    opp_active = _inst(opp_def, zone=Zone.ACTIVE, hp=200)
    gs = _state(p1_active=attacker, p2_active=opp_active)

    action = _attack_action(player_id="p1", attack_index=0)

    atk_mod._bemusing_aroma(gs, action)

    # Opponent should be Confused
    assert StatusCondition.CONFUSED in opp_active.status_conditions, (
        "Opponent's active Pokémon must be Confused on tails"
    )
    # Player's own active must NOT be Confused
    assert StatusCondition.CONFUSED not in attacker.status_conditions, (
        "Player's own active Pokémon must NOT be Confused on tails (old bug was applying it here)"
    )


def test_bemusing_aroma_heads_no_confusion(monkeypatch):
    """Fix 1 regression: on heads, Paralyzed+Poisoned (no Confusion anywhere)."""
    from app.engine.effects import attacks as atk_mod

    monkeypatch.setattr(atk_mod._random, "choice", lambda _: True)  # heads

    attacker_def = _card("r46-lilligant-h", "Lilligant", hp=90,
                         attacks=[AttackDef(name="Bemusing Aroma", damage="30", cost=["Grass"])])
    opp_def = _card("r46-opp-ba-h", "OppMon", hp=200)
    card_registry.register(attacker_def)
    card_registry.register(opp_def)

    attacker = _inst(attacker_def, zone=Zone.ACTIVE, hp=90)
    opp_active = _inst(opp_def, zone=Zone.ACTIVE, hp=200)
    gs = _state(p1_active=attacker, p2_active=opp_active)

    action = _attack_action(player_id="p1", attack_index=0)

    atk_mod._bemusing_aroma(gs, action)

    # Heads: Paralyzed + Poisoned on opp, no Confusion anywhere
    assert StatusCondition.PARALYZED in opp_active.status_conditions
    assert StatusCondition.POISONED in opp_active.status_conditions
    assert StatusCondition.CONFUSED not in opp_active.status_conditions
    assert StatusCondition.CONFUSED not in attacker.status_conditions


# ──────────────────────────────────────────────────────────────────────────────
# Fix 3: Fade Out (sv09-068 Lillie's Comfey)
# ──────────────────────────────────────────────────────────────────────────────

def test_fade_out_returns_energy_source_cards_to_hand():
    """Fix 2 regression: energy source cards in discard are returned to hand, not lost."""
    from app.engine.effects import attacks as atk_mod

    comfey_def = _card("r46-comfey", "Lillie's Comfey", hp=60,
                       attacks=[AttackDef(name="Fade Out", damage="30", cost=["Psychic"])])
    opp_def = _card("r46-opp-fo", "OppMon", hp=200)
    card_registry.register(comfey_def)
    card_registry.register(opp_def)

    comfey = _inst(comfey_def, zone=Zone.ACTIVE, hp=60)
    opp_active = _inst(opp_def, zone=Zone.ACTIVE, hp=200)

    # Energy source cards live in discard (normal after being played)
    energy_src1 = _energy_card("e-src-1")
    energy_src2 = _energy_card("e-src-2")
    comfey.energy_attached.append(_attachment(EnergyType.PSYCHIC, "e-src-1"))
    comfey.energy_attached.append(_attachment(EnergyType.COLORLESS, "e-src-2"))

    gs = _state(p1_active=comfey, p2_active=opp_active)
    gs.p1.discard = [energy_src1, energy_src2]

    action = _attack_action(player_id="p1", attack_index=1)

    atk_mod._fade_out(gs, action)

    # Comfey must be in hand (bounced)
    assert comfey in gs.p1.hand, "Lillie's Comfey must bounce to player's hand"
    assert gs.p1.active is None, "Active slot must be empty after Fade Out"

    # Energy source cards must be returned to hand (not in discard)
    assert energy_src1 in gs.p1.hand, "Energy source card 1 must be in hand (not discarded)"
    assert energy_src2 in gs.p1.hand, "Energy source card 2 must be in hand (not discarded)"
    assert energy_src1 not in gs.p1.discard, "Energy source card 1 must leave discard"
    assert energy_src2 not in gs.p1.discard, "Energy source card 2 must leave discard"

    # Comfey must have no attached energy remaining
    assert len(comfey.energy_attached) == 0, "Comfey energy_attached must be cleared after Fade Out"


# ──────────────────────────────────────────────────────────────────────────────
# Fixes 4 & 5: Magneton svp-153 and svp-159 (Overvolt Discharge)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("card_id", ["svp-153", "svp-159"])
def test_magneton_overvolt_discharge_registered_as_active_ability(card_id: str):
    """Fixes 3 & 4: svp-153 and svp-159 Magneton must use register_ability (not passive).

    Previously registered via register_passive_ability, which means the ability
    handler was never wired and the ability silently did nothing. The fix registers
    them with the _overvolt_discharge handler so they can activate.
    """
    reg = EffectRegistry.instance()
    ability_key = f"{card_id}:Overvolt Discharge"

    # Must be in _ability_effects (active, callable)
    assert ability_key in reg._ability_effects, (
        f"{card_id} Overvolt Discharge must be registered as an active ability "
        f"(in _ability_effects). Was previously silently registered as passive-only."
    )
    # Must NOT be passive-only
    assert ability_key not in reg._passive_abilities, (
        f"{card_id} Overvolt Discharge must NOT be in _passive_abilities — "
        "it must have an executable handler."
    )
    # Handler must be callable
    handler = reg._ability_effects[ability_key]
    assert callable(handler), f"Handler for {card_id} Overvolt Discharge must be callable"


# ──────────────────────────────────────────────────────────────────────────────
# Fix 6: Koraidon sv08-116 — Unrelenting Onslaught Ancient filter
# ──────────────────────────────────────────────────────────────────────────────

def test_koraidon_onslaught_bonus_with_ancient_bench():
    """Fix 5 regression: +150 bonus applies when a bench Ancient Pokémon attacked last turn."""
    from app.engine.effects import attacks as atk_mod

    attacker_def = _card("sv08-116", "Koraidon", hp=130,
                         attacks=[AttackDef(name="Unrelenting Onslaught", damage="30", cost=["Fighting"])])
    opp_def = _card("r46-opp-kor", "OppMon", hp=400)
    ancient_bench_def = _card("sv05-119", "Koraidon", hp=130)  # sv05-119 is an Ancient
    card_registry.register(attacker_def)
    card_registry.register(opp_def)
    card_registry.register(ancient_bench_def)

    attacker = _inst(attacker_def, zone=Zone.ACTIVE)
    opp_active = _inst(opp_def, zone=Zone.ACTIVE, hp=400)
    ancient_bench = _inst(ancient_bench_def, zone=Zone.BENCH)
    ancient_bench.last_attack_name = "Primordial Beatdown"  # attacked last turn

    gs = _state(p1_active=attacker, p1_bench=[ancient_bench], p2_active=opp_active)
    action = _attack_action(player_id="p1", attack_index=0)

    atk_mod._koraidon_onslaught_flag(gs, action)

    # 30 base + 150 bonus = 180 total; opp starts at 400 → 220 HP remaining
    expected_hp = 400 - 180
    assert opp_active.current_hp == expected_hp, (
        f"Expected {expected_hp} HP (30 + 150 bonus), got {opp_active.current_hp}. "
        "Ancient bench Pokémon with last_attack_name should grant +150."
    )


def test_koraidon_onslaught_no_bonus_with_non_ancient_bench():
    """Fix 5 regression: no +150 bonus when only non-Ancient bench Pokémon attacked."""
    from app.engine.effects import attacks as atk_mod

    attacker_def = _card("sv08-116", "Koraidon", hp=130,
                         attacks=[AttackDef(name="Unrelenting Onslaught", damage="30", cost=["Fighting"])])
    opp_def = _card("r46-opp-kor2", "OppMon", hp=400)
    # A plain non-Ancient Pokémon
    non_ancient_def = _card("r46-non-ancient", "Pikachu", hp=60)
    card_registry.register(attacker_def)
    card_registry.register(opp_def)
    card_registry.register(non_ancient_def)

    attacker = _inst(attacker_def, zone=Zone.ACTIVE)
    opp_active = _inst(opp_def, zone=Zone.ACTIVE, hp=400)
    non_ancient_bench = _inst(non_ancient_def, zone=Zone.BENCH)
    non_ancient_bench.last_attack_name = "Thunder Shock"  # attacked, but not Ancient

    gs = _state(p1_active=attacker, p1_bench=[non_ancient_bench], p2_active=opp_active)
    action = _attack_action(player_id="p1", attack_index=0)

    atk_mod._koraidon_onslaught_flag(gs, action)

    # 30 base only; no bonus for non-Ancient benched attacker
    expected_hp = 400 - 30
    assert opp_active.current_hp == expected_hp, (
        f"Expected {expected_hp} HP (30 flat, no bonus), got {opp_active.current_hp}. "
        "Non-Ancient bench Pokémon must NOT grant the +150 bonus."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Fix 7: Alcremie ex sv09-075 — Confectionary Gift uses correct caster
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_confectionary_gift_from_bench_heals_target():
    """Fix 6 regression: Confectionary Gift heals when Alcremie ex is on bench.

    Previously used player.active as the caster, so the ability was gated by
    active's ability_used_this_turn flag and identity — breaking when Alcremie ex
    was on the bench.  The fix uses _find_in_play(player, action.card_instance_id).
    """
    alcremie_def = _card(
        "sv09-075", "Alcremie ex", hp=220,
        abilities=[AbilityDef(name="Confectionary Gift", type="Ability")],
    )
    active_def = _card("r46-active-cg", "ActiveMon", hp=120)
    opp_def = _card("r46-opp-cg", "OppMon", hp=200)
    card_registry.register(alcremie_def)
    card_registry.register(active_def)
    card_registry.register(opp_def)

    # Alcremie ex is on the bench
    alcremie = _inst(alcremie_def, zone=Zone.BENCH, hp=220)
    alcremie.ability_used_this_turn = False

    active_mon = _inst(active_def, zone=Zone.ACTIVE, hp=120)
    # Give the active Pokémon 60 damage (6 counters) so it can be healed
    active_mon.current_hp = 60
    active_mon.damage_counters = 6

    opp_active = _inst(opp_def, zone=Zone.ACTIVE, hp=200)

    gs = _state(p1_active=active_mon, p1_bench=[alcremie], p2_active=opp_active)

    action = _ability_action(player_id="p1", card_instance_id=alcremie.instance_id)

    await EffectRegistry.instance().resolve_ability("sv09-075", "Confectionary Gift", gs, action)

    # The active Pokémon should have been healed by 30
    assert active_mon.current_hp == 90, (
        f"ActiveMon should be healed to 90 HP (was 60, healed 30). Got {active_mon.current_hp}."
    )
    assert active_mon.damage_counters == 3, (
        f"damage_counters should drop from 6 to 3. Got {active_mon.damage_counters}."
    )
    # Alcremie ex ability must be marked used
    assert alcremie.ability_used_this_turn is True, (
        "Alcremie ex ability_used_this_turn must be True after activating Confectionary Gift"
    )
