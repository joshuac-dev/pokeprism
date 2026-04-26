"""Tests for HeuristicPlayer (Phase 3).

Covers:
- choose_setup: valid active + bench selection
- choose_action: CHOOSE_* interrupts delegated correctly
- choose_action: attack phase picks best (KO-first, then highest damage)
- Full game completes without error (both sides HeuristicPlayer)
- H/G smoke test: HeuristicPlayer wins majority of a small sample
"""

from __future__ import annotations

import asyncio
import pytest

from app.players.heuristic import HeuristicPlayer
from app.players.base import GreedyPlayer
from app.engine.runner import MatchRunner
from app.engine.actions import Action, ActionType
from app.engine.state import GameState, PlayerState, CardInstance, Zone, Phase


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_pokemon(
    card_name: str,
    card_def_id: str,
    max_hp: int = 100,
    current_hp: int = 100,
    evolution_stage: int = 0,
) -> CardInstance:
    inst = CardInstance(
        card_def_id=card_def_id,
        card_name=card_name,
        card_type="pokemon",
        card_subtype="basic",
        evolution_stage=evolution_stage,
    )
    inst.max_hp = max_hp
    inst.current_hp = current_hp
    inst.zone = Zone.ACTIVE
    return inst


def _action(action_type: ActionType, player_id: str = "p1", **kwargs) -> Action:
    return Action(action_type=action_type, player_id=player_id, **kwargs)


# ── choose_setup ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_heuristic_setup_picks_active_and_bench(
    dragapult_deck_defs, team_rocket_deck_defs
):
    """choose_setup should return a valid active + up to 4 bench IDs."""
    player = HeuristicPlayer()
    runner = MatchRunner(
        p1_player=player,
        p2_player=HeuristicPlayer(),
        p1_deck=dragapult_deck_defs,
        p2_deck=team_rocket_deck_defs,
    )
    state = runner._initialize_game()
    runner._draw_cards(state, "p1", 7)

    p1 = state.p1
    active_id, bench_ids = await player.choose_setup(state, p1.hand)

    assert active_id is not None
    all_hand_ids = {c.instance_id for c in p1.hand}
    assert active_id in all_hand_ids
    assert len(bench_ids) <= 4
    assert active_id not in bench_ids
    for bid in bench_ids:
        assert bid in all_hand_ids


# ── CHOOSE_* interrupts ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_heuristic_choose_option_returns_first(dragapult_deck_defs, team_rocket_deck_defs):
    """CHOOSE_OPTION should return the first (default) action."""
    player = HeuristicPlayer()
    # Build minimal state
    state = GameState()
    opt0 = _action(ActionType.CHOOSE_OPTION, selected_option=0)
    opt1 = _action(ActionType.CHOOSE_OPTION, selected_option=1)
    result = await player.choose_action(state, [opt0, opt1])
    assert result is opt0


@pytest.mark.asyncio
async def test_heuristic_choose_target_picks_lowest_hp(
    dragapult_deck_defs, team_rocket_deck_defs
):
    """CHOOSE_TARGET with 'opponent' prompt should pick the lowest-HP target."""
    player = HeuristicPlayer()
    state = GameState()

    # Set up two Pokémon on the board so _target_hp can find them
    weak = _make_pokemon("Dreepy", "twm-128", max_hp=30, current_hp=10)
    strong = _make_pokemon("Dragapult ex", "twm-130", max_hp=310, current_hp=300)
    state.p2.bench = [weak, strong]

    class FakeCtx:
        prompt = "opponent bench"

    ctx = FakeCtx()
    a1 = Action(ActionType.CHOOSE_TARGET, "p1",
                target_instance_id=weak.instance_id, choice_context=ctx)
    a2 = Action(ActionType.CHOOSE_TARGET, "p1",
                target_instance_id=strong.instance_id, choice_context=ctx)

    result = await player.choose_action(state, [a1, a2])
    assert result.target_instance_id == weak.instance_id


# ── Attack phase ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_heuristic_attack_ko_first(dragapult_deck_defs, team_rocket_deck_defs):
    """Should choose the attack that KOs the opponent over a higher-damage one."""
    from app.cards import registry as card_registry
    from app.cards.models import CardDefinition, AttackDef

    player = HeuristicPlayer()
    state = GameState()

    # Active with two attacks: 200 dmg (expensive) and 90 dmg (cheap)
    active = _make_pokemon("Dragapult ex", "test-attacker", max_hp=310, current_hp=310)
    state.p1.active = active

    # Opponent active has 90 HP remaining — attack[1] (90 dmg) should KO it
    opp = _make_pokemon("Dreepy", "test-defender", max_hp=30, current_hp=90)
    state.p2.active = opp

    class FakeAtk:
        def __init__(self, name, damage, cost):
            self.name = name
            self.damage = damage
            self.cost = cost

    class FakeCdef:
        attacks = [FakeAtk("Big Hit", "200", ["R", "R", "R"]),
                   FakeAtk("Small KO", "90", ["R"])]

    card_registry._registry["test-attacker"] = FakeCdef()

    a0 = Action(ActionType.ATTACK, "p1", attack_index=0)
    a1 = Action(ActionType.ATTACK, "p1", attack_index=1)

    result = await player.choose_action(state, [a0, a1])
    # attack_index=1 (90 dmg, cheaper) should KO — prefer it
    assert result.attack_index == 1


# ── Full game integration ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_heuristic_full_game_completes(dragapult_deck_defs, team_rocket_deck_defs):
    """A complete H/H game should finish without raising exceptions."""
    runner = MatchRunner(
        p1_player=HeuristicPlayer(),
        p2_player=HeuristicPlayer(),
        p1_deck=dragapult_deck_defs,
        p2_deck=team_rocket_deck_defs,
        p1_deck_name="Dragapult",
        p2_deck_name="TR-Mewtwo",
    )
    result = await runner.run()

    assert result.winner in ("p1", "p2")
    assert result.win_condition in ("prizes", "deck_out", "no_bench", "turn_limit")
    assert result.total_turns > 0


@pytest.mark.asyncio
async def test_heuristic_batch_no_crashes(dragapult_deck_defs, team_rocket_deck_defs):
    """10-game H/H batch should complete without errors."""
    from app.engine.batch import run_hh_batch

    result = await run_hh_batch(
        p1_deck=dragapult_deck_defs,
        p2_deck=team_rocket_deck_defs,
        num_games=10,
        verbose=False,
    )

    assert result.total_games == 10
    assert result.p1_wins + result.p2_wins == 10
    assert result.avg_turns > 0
    assert 0.0 <= result.deck_out_pct <= 100.0


@pytest.mark.asyncio
async def test_heuristic_vs_greedy_batch(dragapult_deck_defs, team_rocket_deck_defs):
    """HeuristicPlayer (P1) should win at least 40% of 20 H/G games.

    Threshold is intentionally loose to avoid flakiness on small samples.
    The Phase 3 exit criterion (>70%) is verified via the benchmark script.
    """
    from app.engine.batch import run_hh_batch

    result = await run_hh_batch(
        p1_deck=dragapult_deck_defs,
        p2_deck=team_rocket_deck_defs,
        num_games=20,
        p1_player_class=HeuristicPlayer,
        p2_player_class=GreedyPlayer,
        verbose=False,
    )

    assert result.total_games == 20
    assert result.p1_win_rate >= 0.40, (
        f"HeuristicPlayer won only {result.p1_win_rate:.0%} of 20 H/G games — "
        "something may be wrong with the priority chain"
    )
