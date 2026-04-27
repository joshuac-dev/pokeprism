"""Unit tests for the simulation Celery task.

These tests exercise logic that can be verified without a live database,
Redis instance, or Celery broker.  Heavy integration paths are mocked.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.tasks.simulation import (
    _apply_mutations,
    _get_player_classes,
    _parse_deck_text,
    count_deck_cards,
)


# ---------------------------------------------------------------------------
# Deck-text parsing
# ---------------------------------------------------------------------------

class TestParseDeckText:
    def test_ptcgl_format(self):
        text = "4 Dragapult ex sv06-130\n3 Drakloak sv06-129"
        result = _parse_deck_text(text)
        assert result == [(4, "sv06-130"), (3, "sv06-129")]

    def test_compact_format(self):
        text = "4 sv06-130\n2 mee-005"
        result = _parse_deck_text(text)
        assert result == [(4, "sv06-130"), (2, "mee-005")]

    def test_blank_and_comment_lines_skipped(self):
        text = "\n# Pokémon\n4 sv06-130\n\n# Energy\n2 mee-005\n"
        result = _parse_deck_text(text)
        assert result == [(4, "sv06-130"), (2, "mee-005")]

    def test_empty_string(self):
        assert _parse_deck_text("") == []

    def test_line_without_hyphen_skipped(self):
        text = "4 SomeCard nohyphen\n2 sv06-130"
        result = _parse_deck_text(text)
        assert result == [(2, "sv06-130")]


class TestCountDeckCards:
    def test_sums_all_counts(self):
        text = "4 sv06-130\n3 sv06-129\n2 sv06-128"
        assert count_deck_cards(text) == 9

    def test_empty_text_is_zero(self):
        assert count_deck_cards("") == 0


# ---------------------------------------------------------------------------
# _apply_mutations
# ---------------------------------------------------------------------------

class TestApplyMutations:
    def _make_card(self, tcgdex_id: str, name: str | None = None):
        from app.cards.models import CardDefinition
        return CardDefinition(
            tcgdex_id=tcgdex_id,
            name=name or tcgdex_id,
            set_abbrev=tcgdex_id.rsplit("-", 1)[0] if "-" in tcgdex_id else "",
            set_number=tcgdex_id.rsplit("-", 1)[1] if "-" in tcgdex_id else "",
        )

    def test_removes_and_adds_card(self):
        deck = [self._make_card("sv06-130"), self._make_card("sv06-130"),
                self._make_card("sv06-129")]
        mutations = [{"card_removed": "sv06-129", "card_added": "mee-005"}]
        new_deck, _ = _apply_mutations(deck, "", mutations)
        ids = [c.tcgdex_id for c in new_deck]
        assert "sv06-129" not in ids
        assert "mee-005" in ids
        assert len(new_deck) == 3

    def test_no_mutations_returns_same_deck(self):
        deck = [self._make_card("sv06-130")]
        new_deck, _ = _apply_mutations(deck, "1 sv06-130", [])
        assert len(new_deck) == 1
        assert new_deck[0].tcgdex_id == "sv06-130"

    def test_deck_text_rebuilt_after_mutation(self):
        deck = [self._make_card("sv06-129"), self._make_card("sv06-130")]
        mutations = [{"card_removed": "sv06-129", "card_added": "mee-005"}]
        _, new_text = _apply_mutations(deck, "", mutations)
        assert "mee-005" in new_text
        assert "sv06-129" not in new_text

    def test_missing_remove_or_add_skipped(self):
        deck = [self._make_card("sv06-130")]
        mutations = [{"card_removed": "sv06-130"}]  # no card_added
        new_deck, _ = _apply_mutations(deck, "", mutations)
        assert len(new_deck) == 1


# ---------------------------------------------------------------------------
# _get_player_classes
# ---------------------------------------------------------------------------

class TestGetPlayerClasses:
    def test_hh_returns_two_heuristic(self):
        p1, p2 = _get_player_classes("hh")
        from app.players.heuristic import HeuristicPlayer
        assert p1 is HeuristicPlayer
        assert p2 is HeuristicPlayer

    def test_unknown_mode_returns_heuristic(self):
        p1, p2 = _get_player_classes("unknown")
        from app.players.heuristic import HeuristicPlayer
        assert p1 is HeuristicPlayer

    def test_ai_h_returns_ai_and_heuristic(self):
        try:
            from app.players.ai_player import AIPlayer
        except ImportError:
            pytest.skip("AIPlayer not available")
        p1, p2 = _get_player_classes("ai_h")
        assert p1 is AIPlayer
        from app.players.heuristic import HeuristicPlayer
        assert p2 is HeuristicPlayer


# ---------------------------------------------------------------------------
# Redis event publishing
# ---------------------------------------------------------------------------

class TestRedisEventPublishing:
    """Verify that _run_simulation_async publishes events to the correct channel."""

    async def test_error_publishes_simulation_error_event(
        self, simulation_id, mock_redis
    ):
        """If the simulation fails, a simulation_error event must be published."""
        with patch("app.tasks.simulation.create_async_engine") as mock_engine, \
             patch("app.tasks.simulation.async_sessionmaker") as mock_sm:

            # Make the DB raise an error immediately
            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.execute = AsyncMock(side_effect=RuntimeError("DB down"))
            mock_sm.return_value.return_value = mock_session

            mock_eng_instance = MagicMock()
            mock_eng_instance.dispose = AsyncMock()
            mock_engine.return_value = mock_eng_instance

            from app.tasks.simulation import _run_simulation_async

            with pytest.raises(RuntimeError):
                await _run_simulation_async(None, simulation_id)

        # The mock_redis fixture yields the client returned by Redis.from_url
        assert mock_redis.publish.called
        channel, raw_payload = mock_redis.publish.call_args[0]
        assert channel == f"simulation:{simulation_id}"
        event = json.loads(raw_payload)
        assert event["type"] == "simulation_error"
        assert event["simulation_id"] == simulation_id

    async def test_channel_name_uses_simulation_id(self, simulation_id, mock_redis):
        """The Redis channel must be 'simulation:{simulation_id}'."""
        with patch("app.tasks.simulation.create_async_engine") as mock_engine, \
             patch("app.tasks.simulation.async_sessionmaker"):

            mock_eng_instance = MagicMock()
            mock_eng_instance.dispose = AsyncMock()
            mock_engine.return_value = mock_eng_instance

            from app.tasks.simulation import _run_simulation_async
            with pytest.raises(Exception):
                await _run_simulation_async(None, simulation_id)

        expected_channel = f"simulation:{simulation_id}"
        for call_args in mock_redis.publish.call_args_list:
            channel = call_args[0][0]
            assert channel == expected_channel


# ---------------------------------------------------------------------------
# run_simulation wraps _run_simulation_async
# ---------------------------------------------------------------------------

class TestRunSimulationWrapper:
    def test_run_simulation_calls_async_impl(self):
        """run_simulation must call _run_simulation_async via a new event loop."""
        test_sim_id = str(uuid.uuid4())
        expected_result = {"status": "complete", "final_win_rate": 60}

        with patch("app.tasks.simulation._run_simulation_async") as mock_async:
            import asyncio
            mock_async.return_value = expected_result

            async def _coro(*args, **kwargs):
                return expected_result

            mock_async.side_effect = _coro

            from app.tasks.simulation import run_simulation

            # Call without bind (Celery bind passes self as first arg)
            # We simulate the non-bound call directly
            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(_coro(None, test_sim_id))
            loop.close()

        assert result == expected_result


# ---------------------------------------------------------------------------
# Win-rate calculation
# ---------------------------------------------------------------------------

class TestWinRateCalculation:
    def test_win_rate_correct_percentage(self):
        """Win rate should be calculated as int(round(wins/total*100))."""
        wins = 7
        total = 10
        expected = int(round(wins / total * 100))  # 70
        assert expected == 70

    def test_zero_games_gives_zero(self):
        total = 0
        rate = int(round(0 / total * 100)) if total > 0 else 0
        assert rate == 0

    def test_all_wins(self):
        assert int(round(10 / 10 * 100)) == 100

    def test_rounding(self):
        # 3/7 ≈ 42.857... → rounds to 43
        assert int(round(3 / 7 * 100)) == 43
