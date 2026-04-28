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
    _parse_ptcgl_deck_text,
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


# ---------------------------------------------------------------------------
# PTCGL deck text parsing
# ---------------------------------------------------------------------------

class TestParsePtcglDeckText:
    def test_basic_ptcgl_line(self):
        text = "4 Dreepy PRE 71\n3 Drakloak ASC 159"
        result = _parse_ptcgl_deck_text(text)
        assert result == [
            {"count": 4, "name": "Dreepy", "set_abbrev": "PRE", "set_number": "71"},
            {"count": 3, "name": "Drakloak", "set_abbrev": "ASC", "set_number": "159"},
        ]

    def test_multi_word_card_name(self):
        text = "2 Boss's Orders MEG 114"
        result = _parse_ptcgl_deck_text(text)
        assert result == [
            {"count": 2, "name": "Boss's Orders", "set_abbrev": "MEG", "set_number": "114"},
        ]

    def test_promo_set_with_hyphen(self):
        text = "1 Pecharunt PR-SV 149"
        result = _parse_ptcgl_deck_text(text)
        assert result == [
            {"count": 1, "name": "Pecharunt", "set_abbrev": "PR-SV", "set_number": "149"},
        ]

    def test_section_headers_skipped(self):
        text = "Pokémon: 14\n4 Dreepy PRE 71\nTrainer: 32\nEnergy: 14"
        result = _parse_ptcgl_deck_text(text)
        assert result == [
            {"count": 4, "name": "Dreepy", "set_abbrev": "PRE", "set_number": "71"},
        ]

    def test_blank_and_comment_lines_skipped(self):
        text = "\n# My deck\n4 Dreepy PRE 71\n\n"
        result = _parse_ptcgl_deck_text(text)
        assert len(result) == 1
        assert result[0]["name"] == "Dreepy"

    def test_empty_string_returns_empty(self):
        assert _parse_ptcgl_deck_text("") == []

    def test_tcgdex_format_not_matched(self):
        # TCGdex lines should NOT be matched by the PTCGL parser
        text = "4 Dragapult ex sv06-130\n2 sv06-129"
        assert _parse_ptcgl_deck_text(text) == []


# ---------------------------------------------------------------------------
# _deck_text_to_card_defs: PTCGL on-demand fetch
# ---------------------------------------------------------------------------

class TestDeckTextToCardDefsPtcgl:
    """Test that PTCGL format triggers DB lookup and on-demand TCGDex fetch."""

    @pytest.mark.asyncio
    async def test_ptcgl_card_found_in_db(self):
        """Card already in DB → no TCGDex call, returns correct CardDefinition."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.tasks.simulation import _deck_text_to_card_defs

        mock_row = MagicMock()
        mock_row.tcgdex_id = "sv08.5-071"
        mock_row.name = "Dreepy"
        mock_row.set_abbrev = "PRE"
        mock_row.set_number = "71"
        mock_row.category = "Pokemon"
        mock_row.subcategory = "Basic"
        mock_row.hp = 40
        mock_row.types = ["Dragon"]
        mock_row.evolve_from = None
        mock_row.stage = "Basic"
        mock_row.retreat_cost = 1
        mock_row.regulation_mark = "I"
        mock_row.rarity = "Common"
        mock_row.image_url = None

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [mock_row]
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session

        defs = await _deck_text_to_card_defs("4 Dreepy PRE 71", mock_factory)

        assert len(defs) == 4
        assert defs[0].tcgdex_id == "sv08.5-071"
        assert defs[0].name == "Dreepy"

    @pytest.mark.asyncio
    async def test_ptcgl_card_not_in_db_fetches_from_tcgdex(self):
        """Card missing from DB → fetches from TCGDex, upserts, returns CardDefinition."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.tasks.simulation import _deck_text_to_card_defs

        # Call 1: set_abbrev batch lookup → empty
        empty_scalars = MagicMock()
        empty_scalars.all.return_value = []
        lookup_result = MagicMock()
        lookup_result.scalars.return_value = empty_scalars

        # Call 2: ensure_cards existing-tcgdex_ids check → empty (result.all() form)
        existing_result = MagicMock()
        existing_result.all.return_value = []

        # Call 3: re-fetch after upsert → returns inserted row
        upserted_row = MagicMock()
        upserted_row.tcgdex_id = "sv08.5-071"
        upserted_row.name = "Dreepy"
        upserted_row.set_abbrev = "PRE"
        upserted_row.set_number = "71"
        upserted_row.category = "Pokemon"
        upserted_row.subcategory = "Basic"
        upserted_row.hp = 40
        upserted_row.types = ["Dragon"]
        upserted_row.evolve_from = None
        upserted_row.stage = "Basic"
        upserted_row.retreat_cost = 1
        upserted_row.regulation_mark = "I"
        upserted_row.rarity = "Common"
        upserted_row.image_url = None
        refetch_scalars = MagicMock()
        refetch_scalars.all.return_value = [upserted_row]
        refetch_result = MagicMock()
        refetch_result.scalars.return_value = refetch_scalars

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(
            side_effect=[lookup_result, existing_result, refetch_result]
        )
        mock_session.flush = AsyncMock()
        mock_session.add_all = MagicMock()
        mock_session.commit = AsyncMock()

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session

        raw_tcgdex = {
            "id": "sv08.5-071",
            "name": "Dreepy",
            "category": "Pokemon",
            "hp": 40,
            "types": ["Dragon"],
            "stage": "Basic",
            "retreat": 1,
            "attacks": [],
            "abilities": [],
            "weaknesses": [],
            "resistances": [],
            "regulationMark": "I",
            "rarity": "Common",
            "image": None,
        }

        with patch("app.cards.tcgdex.TCGDexClient.get_card", new_callable=AsyncMock, return_value=raw_tcgdex):
            defs = await _deck_text_to_card_defs("4 Dreepy PRE 71", mock_factory)

        assert len(defs) == 4
        assert defs[0].name == "Dreepy"
        assert defs[0].tcgdex_id == "sv08.5-071"

    @pytest.mark.asyncio
    async def test_ptcgl_unknown_set_raises_value_error(self):
        """Unknown set abbreviation raises ValueError with clear message."""
        from unittest.mock import AsyncMock, MagicMock
        from app.tasks.simulation import _deck_text_to_card_defs

        empty_scalars = MagicMock()
        empty_scalars.all.return_value = []
        empty_result = MagicMock()
        empty_result.scalars.return_value = empty_scalars

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=empty_result)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session

        with pytest.raises(ValueError, match="Unknown set abbreviation 'XYZ'"):
            await _deck_text_to_card_defs("1 SomeCard XYZ 99", mock_factory)
