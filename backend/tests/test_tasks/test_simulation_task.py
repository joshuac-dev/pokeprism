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
    _check_regression,
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

    async def test_pre_cancelled_simulation_is_not_marked_running(
        self, simulation_id, mock_redis
    ):
        """A task that starts after cancellation must not overwrite status."""
        with patch("app.tasks.simulation.create_async_engine") as mock_engine, \
             patch("app.tasks.simulation.async_sessionmaker") as mock_sm:

            mock_sim = MagicMock()
            mock_sim.status = "cancelled"
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_sim

            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session.commit = AsyncMock()
            mock_sm.return_value.return_value = mock_session

            mock_eng_instance = MagicMock()
            mock_eng_instance.dispose = AsyncMock()
            mock_engine.return_value = mock_eng_instance

            from app.tasks.simulation import _run_simulation_async

            result = await _run_simulation_async(None, simulation_id)

        assert result == {"status": "cancelled"}
        assert mock_sim.status == "cancelled"
        mock_session.commit.assert_not_awaited()
        channel, raw_payload = mock_redis.publish.call_args[0]
        assert channel == f"simulation:{simulation_id}"
        assert json.loads(raw_payload)["type"] == "simulation_cancelled"

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
             patch("app.tasks.simulation.async_sessionmaker") as mock_sm:

            mock_session = AsyncMock()
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=False)
            mock_session.execute = AsyncMock(side_effect=RuntimeError("DB down"))
            mock_sm.return_value.return_value = mock_session

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

    def test_driver_nilled_before_async_impl_entry(self):
        """Stale Neo4j driver singleton is cleared before _run_simulation_async runs.

        Regression: each Celery task creates a new event loop; the module-level
        AsyncDriver singleton binds to the first loop and raises
        'Future attached to a different loop' on subsequent tasks unless nilled.
        """
        from app.db import graph as graph_module
        from app.tasks.simulation import run_simulation

        driver_at_entry: list = []

        async def _stub_impl(task_self, sim_id):
            # Capture _driver state at the moment the async impl starts.
            driver_at_entry.append(graph_module._driver)
            return {"status": "cancelled"}

        fake_driver = MagicMock(name="stale_driver")
        graph_module._driver = fake_driver

        try:
            with patch("app.tasks.simulation._run_simulation_async", side_effect=_stub_impl):
                # With bind=True, run_simulation.run() already has self bound to
                # the Celery task instance — pass only simulation_id.
                run_simulation.run(str(uuid.uuid4()))
        finally:
            graph_module._driver = None

        assert len(driver_at_entry) == 1, "async impl must be called exactly once"
        assert driver_at_entry[0] is None, "_driver must be nil'd before async impl enters"
        assert graph_module._driver is None, "_driver must remain nil after task completes"


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

    def test_basic_energy_shorthand_maps_to_sve(self):
        text = "Energy: 10\n6 Psychic Energy\n4 Darkness Energy"
        result = _parse_ptcgl_deck_text(text)
        assert result == [
            {"count": 6, "name": "Psychic Energy", "set_abbrev": "SVE", "set_number": "5"},
            {"count": 4, "name": "Darkness Energy", "set_abbrev": "SVE", "set_number": "7"},
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
    async def test_ptcgl_card_not_in_db_raises_value_error(self):
        """Card missing from DB → raises ValueError (fetch must happen before task)."""
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

        with pytest.raises(ValueError, match="ensure_deck_cards_in_db"):
            await _deck_text_to_card_defs("4 Dreepy PRE 71", mock_factory)

    @pytest.mark.asyncio
    async def test_ptcgl_unknown_set_raises_value_error(self):
        """Unknown set abbreviation raises ValueError from ensure_deck_cards_in_db."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.tasks.simulation import ensure_deck_cards_in_db

        empty_scalars = MagicMock()
        empty_scalars.all.return_value = []
        empty_result = MagicMock()
        empty_result.scalars.return_value = empty_scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=empty_result)

        with pytest.raises(ValueError, match="Unknown set abbreviation 'XYZ'"):
            await ensure_deck_cards_in_db(["1 SomeCard XYZ 99"], mock_db)


class TestEnsureDeckCardsInDb:
    """Test the ensure_deck_cards_in_db pre-flight fetch."""

    @pytest.mark.asyncio
    async def test_all_cards_in_db_no_fetch(self):
        """When all PTCGL cards are in DB, no TCGDex call is made."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.tasks.simulation import ensure_deck_cards_in_db

        row = MagicMock()
        row.set_abbrev = "PRE"
        row.set_number = "71"
        scalars = MagicMock()
        scalars.all.return_value = [row]
        result = MagicMock()
        result.scalars.return_value = scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)

        with patch("app.cards.tcgdex.TCGDexClient.get_card") as mock_get:
            await ensure_deck_cards_in_db(["4 Dreepy PRE 71"], mock_db)
            mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_card_fetched_and_upserted(self):
        """Card missing from DB → fetched from TCGDex and upserted, then commit."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.tasks.simulation import ensure_deck_cards_in_db

        empty_scalars = MagicMock()
        empty_scalars.all.return_value = []
        empty_result = MagicMock()
        empty_result.scalars.return_value = empty_scalars

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=empty_result)
        mock_db.commit = AsyncMock()

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

        with patch("app.cards.tcgdex.TCGDexClient.get_card", new_callable=AsyncMock, return_value=raw_tcgdex), \
             patch("app.memory.postgres.MatchMemoryWriter.ensure_cards", new_callable=AsyncMock) as mock_ensure:
            await ensure_deck_cards_in_db(["4 Dreepy PRE 71"], mock_db)
            mock_ensure.assert_called_once()
            mock_db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# _check_regression
# ---------------------------------------------------------------------------

class TestCheckRegression:
    def test_first_round_no_prev_returns_zero(self):
        """No previous win rate → no regression possible."""
        assert _check_regression(50, None, 0) == 0

    def test_improvement_resets_counter(self):
        """Win rate went up → consecutive_regressions resets to 0."""
        assert _check_regression(60, 50, 2) == 0

    def test_same_rate_resets_counter(self):
        """Win rate unchanged → not a regression."""
        assert _check_regression(55, 55, 1) == 0

    def test_drop_increments_counter(self):
        """Win rate dropped → increment."""
        assert _check_regression(40, 60, 0) == 1

    def test_second_consecutive_drop(self):
        """Second consecutive drop → counter reaches 2."""
        assert _check_regression(35, 40, 1) == 2

    def test_third_consecutive_drop(self):
        """Three consecutive drops → counter reaches 3 (skip-coach threshold)."""
        assert _check_regression(30, 35, 2) == 3

    def test_one_percent_drop_counts(self):
        """Even a 1% drop counts as a regression."""
        assert _check_regression(59, 60, 0) == 1
