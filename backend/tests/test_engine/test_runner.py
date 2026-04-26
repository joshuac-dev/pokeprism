"""Phase 1 exit criteria: MatchRunner must play a complete game to GAME_OVER.

This is the integration test that proves Phase 1 is done:
  1. Load real card data from fixtures
  2. Build two 60-card decks
  3. Run a full game using GreedyPlayer vs RandomPlayer
  4. Assert the game ended properly (GAME_OVER, valid winner, valid win_condition)

No mocks. No fake data. Real card definitions from TCGDex fixtures.
"""

from __future__ import annotations

import asyncio
import pytest

from app.engine.runner import MatchResult, MatchRunner
from app.engine.state import GameState, Phase
from app.players.base import GreedyPlayer, RandomPlayer


@pytest.mark.asyncio
class TestMatchRunnerPhase1:
    async def test_game_reaches_game_over(
        self,
        dragapult_deck_defs,
        team_rocket_deck_defs,
    ):
        """A full game must terminate with a winner."""
        runner = MatchRunner(
            p1_player=GreedyPlayer(),
            p2_player=RandomPlayer(),
            p1_deck=dragapult_deck_defs,
            p2_deck=team_rocket_deck_defs,
            p1_deck_name="Dragapult ex / Dusknoir",
            p2_deck_name="Team Rocket's Mewtwo ex",
            max_turns=200,
            rng_seed=42,
        )
        result = await runner.run()

        assert isinstance(result, MatchResult)
        assert result.winner in ("p1", "p2")
        assert result.win_condition in ("prizes", "deck_out", "no_bench", "turn_limit")
        assert result.total_turns >= 1
        assert result.p1_prizes_taken >= 0
        assert result.p2_prizes_taken >= 0

    async def test_game_produces_event_log(
        self,
        dragapult_deck_defs,
        team_rocket_deck_defs,
    ):
        """The event log must contain at least game_start and game_over events."""
        runner = MatchRunner(
            p1_player=GreedyPlayer(),
            p2_player=RandomPlayer(),
            p1_deck=dragapult_deck_defs,
            p2_deck=team_rocket_deck_defs,
            max_turns=200,
            rng_seed=0,
        )
        result = await runner.run()

        event_types = {e["event_type"] for e in result.events}
        assert "game_start" in event_types
        assert "game_over" in event_types

    async def test_greedy_vs_greedy(
        self,
        dragapult_deck_defs,
        team_rocket_deck_defs,
    ):
        """Two greedy players should also produce a complete game."""
        runner = MatchRunner(
            p1_player=GreedyPlayer(),
            p2_player=GreedyPlayer(),
            p1_deck=dragapult_deck_defs,
            p2_deck=team_rocket_deck_defs,
            max_turns=200,
            rng_seed=99,
        )
        result = await runner.run()
        assert result.winner in ("p1", "p2")

    async def test_prizes_taken_consistent(
        self,
        dragapult_deck_defs,
        team_rocket_deck_defs,
    ):
        """When won by prizes, the winner should have taken exactly 6 prizes."""
        runner = MatchRunner(
            p1_player=GreedyPlayer(),
            p2_player=RandomPlayer(),
            p1_deck=dragapult_deck_defs,
            p2_deck=team_rocket_deck_defs,
            max_turns=200,
            rng_seed=7,
        )
        result = await runner.run()

        if result.win_condition == "prizes":
            if result.winner == "p1":
                assert result.p1_prizes_taken == 6
            else:
                assert result.p2_prizes_taken == 6

    async def test_deck_names_in_result(
        self,
        dragapult_deck_defs,
        team_rocket_deck_defs,
    ):
        runner = MatchRunner(
            p1_player=GreedyPlayer(),
            p2_player=RandomPlayer(),
            p1_deck=dragapult_deck_defs,
            p2_deck=team_rocket_deck_defs,
            p1_deck_name="DragDusk",
            p2_deck_name="TRMewtwo",
            max_turns=200,
            rng_seed=1,
        )
        result = await runner.run()
        assert result.p1_deck_name == "DragDusk"
        assert result.p2_deck_name == "TRMewtwo"
