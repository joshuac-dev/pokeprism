"""Section 4B regression tests — status condition mechanics.

Covers:
  - PARALYZED blocks attack actions
  - ASLEEP blocks attack actions
  - PARALYZED blocks retreat actions
  - PARALYZED timing: only removed at end of the paralyzed player's own turn
  - Burn flip direction: tails = 20 damage, heads = no damage
  - CONFUSED coin flip: tails = 30 self-damage + attack fails, heads = resolves
"""
from __future__ import annotations

import random
from unittest.mock import MagicMock, patch

import pytest

import app.engine.effects  # noqa: F401 — register_all via __init__
from app.cards import registry as card_registry
from app.cards.models import AttackDef, CardDefinition
from app.engine.actions import Action, ActionType, ActionValidator
from app.engine.runner import MatchRunner
from app.engine.state import (
    CardInstance, EnergyAttachment, EnergyType, GameState, Phase, StatusCondition, Zone,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers (mirrors test_audit_fixes.py)
# ──────────────────────────────────────────────────────────────────────────────

def _make_card(tcgdex_id: str, name: str, hp: int = 100,
               attacks: list[AttackDef] | None = None) -> CardDefinition:
    return CardDefinition(
        tcgdex_id=tcgdex_id, name=name, set_abbrev="TST", set_number="001",
        category="pokemon", stage="Basic", hp=hp, attacks=attacks or [],
    )


def _make_instance(cdef: CardDefinition, zone: Zone = Zone.ACTIVE,
                   hp: int | None = None) -> CardInstance:
    hp = hp or cdef.hp or 100
    return CardInstance(
        instance_id="inst-" + cdef.tcgdex_id,
        card_def_id=cdef.tcgdex_id, card_name=cdef.name,
        current_hp=hp, max_hp=hp, zone=zone,
    )


def _make_energy(etype: EnergyType) -> EnergyAttachment:
    return EnergyAttachment(energy_type=etype, source_card_id="src", card_def_id="basic")


def _make_state(p1_active=None, p1_bench=None,
                p2_active=None, p2_bench=None,
                active_player: str = "p1") -> GameState:
    state = GameState()
    state.p1.player_id = "p1"
    state.p2.player_id = "p2"
    state.active_player = active_player
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


def _runner(seed: int = 0) -> MatchRunner:
    runner = object.__new__(MatchRunner)
    runner._rng = random.Random(seed)
    return runner


def _runner_mock_rng(return_value: bool) -> MatchRunner:
    runner = object.__new__(MatchRunner)
    runner._rng = MagicMock()
    runner._rng.choice.return_value = return_value
    return runner


@pytest.fixture(autouse=True)
def clear_card_registry():
    yield
    card_registry.clear()


# ──────────────────────────────────────────────────────────────────────────────
# PARALYZED / ASLEEP block attack actions (Section 4B fix #1–2)
# ──────────────────────────────────────────────────────────────────────────────

def _attack_actions(state: GameState, player_id: str) -> list[Action]:
    """Extract ATTACK-type actions from get_legal_actions (state must be ATTACK phase)."""
    state.phase = Phase.ATTACK
    # Bypass the MAIN phase check by calling the private method directly with the player object
    player = state.get_player(player_id)
    return ActionValidator._get_attack_actions(state, player, player_id)


def _retreat_actions(state: GameState, player_id: str) -> list[Action]:
    """Extract RETREAT-type actions (state must be MAIN phase)."""
    state.phase = Phase.MAIN
    player = state.get_player(player_id)
    return ActionValidator._get_retreat_actions(state, player, player_id)


def test_paralyzed_blocks_attack_actions():
    cdef = _make_card("tst-sc-001", "Attacker",
                      attacks=[AttackDef(name="Tackle", damage="10", cost=[])])
    card_registry.register(cdef)
    attacker = _make_instance(cdef)
    attacker.status_conditions.add(StatusCondition.PARALYZED)
    state = _make_state(
        p1_active=attacker,
        p2_active=_make_instance(_make_card("tst-sc-002", "Defender")),
    )
    actions = _attack_actions(state, "p1")
    assert actions == [], "PARALYZED must block all attack actions"


def test_asleep_blocks_attack_actions():
    cdef = _make_card("tst-sc-003", "Sleeper",
                      attacks=[AttackDef(name="Tackle", damage="10", cost=[])])
    card_registry.register(cdef)
    attacker = _make_instance(cdef)
    attacker.status_conditions.add(StatusCondition.ASLEEP)
    state = _make_state(
        p1_active=attacker,
        p2_active=_make_instance(_make_card("tst-sc-004", "Defender")),
    )
    actions = _attack_actions(state, "p1")
    assert actions == [], "ASLEEP must block all attack actions"


def test_paralyzed_blocks_retreat_actions():
    cdef = _make_card("tst-sc-005", "Paralyzed Mon")
    card_registry.register(cdef)
    bench_cdef = _make_card("tst-sc-006", "Bench Mon")
    card_registry.register(bench_cdef)

    attacker = _make_instance(cdef)
    attacker.status_conditions.add(StatusCondition.PARALYZED)
    attacker.energy_attached.append(_make_energy(EnergyType.COLORLESS))
    bench = _make_instance(bench_cdef, zone=Zone.BENCH)

    state = _make_state(
        p1_active=attacker,
        p1_bench=[bench],
        p2_active=_make_instance(_make_card("tst-sc-007", "Opp")),
    )
    actions = _retreat_actions(state, "p1")
    assert actions == [], "PARALYZED must block retreat actions"


def test_confused_or_poisoned_does_not_block_attacks():
    cdef = _make_card("tst-sc-008", "Confused Mon",
                      attacks=[AttackDef(name="Tackle", damage="10", cost=[])])
    card_registry.register(cdef)
    attacker = _make_instance(cdef)
    attacker.status_conditions.add(StatusCondition.CONFUSED)
    attacker.status_conditions.add(StatusCondition.POISONED)
    state = _make_state(
        p1_active=attacker,
        p2_active=_make_instance(_make_card("tst-sc-009", "Defender")),
    )
    actions = _attack_actions(state, "p1")
    assert len(actions) == 1, "CONFUSED/POISONED must NOT block attack actions"


# ──────────────────────────────────────────────────────────────────────────────
# PARALYZED timing fix (Section 4B fix #4)
# ──────────────────────────────────────────────────────────────────────────────

def test_paralyzed_not_removed_for_opponent_at_end_of_current_player_turn():
    """PARALYZED stays on opponent's Pokémon until end of opponent's own turn."""
    p1_cdef = _make_card("tst-pt-001", "P1 Mon")
    p2_cdef = _make_card("tst-pt-002", "P2 Mon")
    card_registry.register(p1_cdef)
    card_registry.register(p2_cdef)

    p1_active = _make_instance(p1_cdef)
    p2_active = _make_instance(p2_cdef)
    p2_active.status_conditions.add(StatusCondition.PARALYZED)

    state = _make_state(p1_active=p1_active, p2_active=p2_active, active_player="p1")
    _runner_mock_rng(True)._handle_between_turns(state)

    assert StatusCondition.PARALYZED in p2_active.status_conditions, (
        "PARALYZED must persist on p2 when p1's turn just ended"
    )


def test_paralyzed_removed_at_end_of_paralyzed_players_own_turn():
    """PARALYZED wears off at the end of the paralyzed player's next turn."""
    p1_cdef = _make_card("tst-pt-003", "P1 Mon")
    p2_cdef = _make_card("tst-pt-004", "P2 Mon")
    card_registry.register(p1_cdef)
    card_registry.register(p2_cdef)

    p2_active = _make_instance(p2_cdef)
    p2_active.status_conditions.add(StatusCondition.PARALYZED)

    state = _make_state(
        p1_active=_make_instance(p1_cdef),
        p2_active=p2_active,
        active_player="p2",  # p2's turn just ended
    )
    _runner_mock_rng(True)._handle_between_turns(state)

    assert StatusCondition.PARALYZED not in p2_active.status_conditions, (
        "PARALYZED must be removed after the paralyzed player's own turn"
    )
    assert any(e["event_type"] == "paralysis_removed" for e in state.events)


# ──────────────────────────────────────────────────────────────────────────────
# Burn flip direction fix (Section 4B fix #6)
# ──────────────────────────────────────────────────────────────────────────────

def test_burn_tails_deals_20_damage():
    """Burn: tails (False) → 20 damage (2 counters) on burned Pokémon."""
    cdef = _make_card("tst-bn-001", "Burned Mon", hp=100)
    opp_cdef = _make_card("tst-bn-002", "Opponent", hp=100)
    card_registry.register(cdef)
    card_registry.register(opp_cdef)

    active = _make_instance(cdef, hp=100)
    active.status_conditions.add(StatusCondition.BURNED)

    state = _make_state(p1_active=active, p2_active=_make_instance(opp_cdef))
    _runner_mock_rng(False)._handle_between_turns(state)  # False = tails

    assert active.damage_counters == 2, "Burn tails must deal 2 damage counters (20 HP)"
    assert active.current_hp == 80
    assert any(e["event_type"] == "burn_damage" for e in state.events)


def test_burn_heads_no_damage():
    """Burn: heads (True) → no damage taken."""
    cdef = _make_card("tst-bn-003", "Burned Mon", hp=100)
    opp_cdef = _make_card("tst-bn-004", "Opponent", hp=100)
    card_registry.register(cdef)
    card_registry.register(opp_cdef)

    active = _make_instance(cdef, hp=100)
    active.status_conditions.add(StatusCondition.BURNED)

    state = _make_state(p1_active=active, p2_active=_make_instance(opp_cdef))
    _runner_mock_rng(True)._handle_between_turns(state)  # True = heads

    assert active.damage_counters == 0, "Burn heads must deal no damage"
    assert active.current_hp == 100
    assert not any(e["event_type"] == "burn_damage" for e in state.events)


# ──────────────────────────────────────────────────────────────────────────────
# CONFUSED coin flip (Section 4B fix #5)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_confused_tails_deals_30_self_damage_and_cancels_attack():
    """Confused: tails → attacker takes 30 damage, attack does NOT resolve."""
    from app.engine.transitions import _attack

    attacker_cdef = _make_card(
        "tst-cf-001", "Confused Attacker", hp=100,
        attacks=[AttackDef(name="Tackle", damage="50", cost=[])],
    )
    defender_cdef = _make_card("tst-cf-002", "Defender", hp=100)
    card_registry.register(attacker_cdef)
    card_registry.register(defender_cdef)

    attacker = _make_instance(attacker_cdef, hp=100)
    attacker.status_conditions.add(StatusCondition.CONFUSED)
    defender = _make_instance(defender_cdef, hp=100)

    state = _make_state(p1_active=attacker, p2_active=defender)
    action = Action(player_id="p1", action_type=ActionType.ATTACK, attack_index=0)

    with patch("random.choice", return_value=False):  # tails
        await _attack(state, action)

    assert attacker.damage_counters == 3, "30 self-damage (3 counters) on confused + tails"
    assert attacker.current_hp == 70
    assert defender.damage_counters == 0, "Attack must NOT hit defender when confused + tails"
    assert any(e["event_type"] == "confusion_damage" for e in state.events)


@pytest.mark.asyncio
async def test_confused_heads_attack_resolves_normally():
    """Confused: heads → attack resolves, defender takes damage."""
    from app.engine.transitions import _attack

    attacker_cdef = _make_card(
        "tst-cf-003", "Confused Attacker", hp=100,
        attacks=[AttackDef(name="Tackle", damage="50", cost=[])],
    )
    defender_cdef = _make_card("tst-cf-004", "Defender", hp=100)
    card_registry.register(attacker_cdef)
    card_registry.register(defender_cdef)

    attacker = _make_instance(attacker_cdef, hp=100)
    attacker.status_conditions.add(StatusCondition.CONFUSED)
    defender = _make_instance(defender_cdef, hp=100)

    state = _make_state(p1_active=attacker, p2_active=defender)
    action = Action(player_id="p1", action_type=ActionType.ATTACK, attack_index=0)

    with patch("random.choice", return_value=True):  # heads
        await _attack(state, action)

    assert attacker.damage_counters == 0, "No self-damage when confused + heads"
    assert defender.damage_counters == 5, "Defender takes 50 damage (5 counters) on heads"
    assert not any(e["event_type"] == "confusion_damage" for e in state.events)
