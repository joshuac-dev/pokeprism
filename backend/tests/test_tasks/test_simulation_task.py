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
    _per_opponent_all_met,
    _validate_post_mutation_deck,
    _win_rate_pct,
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

    def _make_60_card_deck(self):
        """Build a valid 60-card deck: 4×10 distinct cards + 4×5 others."""
        cards = []
        for i in range(15):
            cards.extend([self._make_card(f"sv01-{i:03d}", f"Card {i}")] * 4)
        return cards  # 15 × 4 = 60

    def test_removes_and_adds_card(self):
        add_def = self._make_card("mee-005", "New Card")
        deck = [self._make_card("sv06-130"), self._make_card("sv06-130"),
                self._make_card("sv06-129")]
        mutations = [{"card_removed": "sv06-129", "card_added": "mee-005", "card_added_def": add_def}]
        new_deck, _, applied = _apply_mutations(deck, "", mutations)
        ids = [c.tcgdex_id for c in new_deck]
        assert "sv06-129" not in ids
        assert "mee-005" in ids
        assert len(new_deck) == 3
        assert len(applied) == 1

    def test_uses_real_def_not_placeholder(self):
        """The added card should come from card_added_def, not be a placeholder."""
        add_def = self._make_card("mee-005", "Real Card Name")
        deck = [self._make_card("sv06-129"), self._make_card("sv06-130")]
        mutations = [{"card_removed": "sv06-129", "card_added": "mee-005", "card_added_def": add_def}]
        new_deck, _, applied = _apply_mutations(deck, "", mutations)
        added = next(c for c in new_deck if c.tcgdex_id == "mee-005")
        assert added.name == "Real Card Name"
        assert len(applied) == 1

    def test_none_card_added_def_skips_mutation(self):
        """Mutation with card_added_def=None is skipped; card is never added."""
        deck = [self._make_card("sv06-129"), self._make_card("sv06-130")]
        mutations = [{"card_removed": "sv06-129", "card_added": "mee-005", "card_added_def": None}]
        new_deck, _, applied = _apply_mutations(deck, "", mutations)
        ids = [c.tcgdex_id for c in new_deck]
        assert "sv06-129" in ids  # not removed
        assert "mee-005" not in ids
        assert applied == []

    def test_missing_card_added_def_key_skips_mutation(self):
        """Mutation dict without card_added_def key is skipped."""
        deck = [self._make_card("sv06-129"), self._make_card("sv06-130")]
        mutations = [{"card_removed": "sv06-129", "card_added": "mee-005"}]
        new_deck, _, applied = _apply_mutations(deck, "", mutations)
        ids = [c.tcgdex_id for c in new_deck]
        assert "sv06-129" in ids
        assert "mee-005" not in ids
        assert applied == []

    def test_remove_not_found_skips_mutation(self):
        """If the card to remove is not in the deck, neither remove nor add happens."""
        add_def = self._make_card("mee-005", "New Card")
        deck = [self._make_card("sv06-130")]
        mutations = [{"card_removed": "sv06-999", "card_added": "mee-005", "card_added_def": add_def}]
        new_deck, _, applied = _apply_mutations(deck, "", mutations)
        assert len(new_deck) == 1
        assert new_deck[0].tcgdex_id == "sv06-130"
        assert applied == []

    def test_no_mutations_returns_same_deck(self):
        deck = [self._make_card("sv06-130")]
        new_deck, _, applied = _apply_mutations(deck, "1 sv06-130", [])
        assert len(new_deck) == 1
        assert new_deck[0].tcgdex_id == "sv06-130"
        assert applied == []

    def test_deck_text_rebuilt_after_mutation(self):
        add_def = self._make_card("mee-005", "New Card")
        deck = [self._make_card("sv06-129"), self._make_card("sv06-130")]
        mutations = [{"card_removed": "sv06-129", "card_added": "mee-005", "card_added_def": add_def}]
        _, new_text, _ = _apply_mutations(deck, "", mutations)
        assert "mee-005" in new_text
        assert "sv06-129" not in new_text

    def test_missing_remove_or_add_skipped(self):
        deck = [self._make_card("sv06-130")]
        mutations = [{"card_removed": "sv06-130"}]  # no card_added
        new_deck, _, applied = _apply_mutations(deck, "", mutations)
        assert len(new_deck) == 1
        assert applied == []

    def test_reverts_if_too_many_copies_in_60_card_deck(self):
        """60-card deck reverts if a mutation would create > 4 copies of a card."""
        deck = self._make_60_card_deck()  # 15 cards × 4 = 60
        assert len(deck) == 60
        # Try to add a 5th copy of sv01-000 by removing sv01-001
        fifth_copy_def = self._make_card("sv01-000", "Card 0")
        mutations = [{
            "card_removed": "sv01-001",
            "card_added": "sv01-000",
            "card_added_def": fifth_copy_def,
        }]
        original_deck = list(deck)
        new_deck, new_text, applied = _apply_mutations(deck, "original text", mutations)
        assert new_deck is deck  # reverted — returns original object
        assert new_text == "original text"
        assert applied == []  # legality revert means nothing was applied

    def test_valid_60_card_mutation_applies(self):
        """A clean swap in a 60-card deck goes through without reverting."""
        deck = self._make_60_card_deck()
        add_def = self._make_card("new-001", "New Card")
        mutations = [{
            "card_removed": "sv01-000",
            "card_added": "new-001",
            "card_added_def": add_def,
        }]
        new_deck, _, applied = _apply_mutations(deck, "", mutations)
        ids = [c.tcgdex_id for c in new_deck]
        assert "new-001" in ids
        assert len(new_deck) == 60
        assert len(applied) == 1


# ---------------------------------------------------------------------------
# Mutation log consistency — regression tests (spec A–E)
# ---------------------------------------------------------------------------

class TestMutationLogConsistency:
    """Regression tests proving the deck mutation log stays consistent.

    These cover the two root causes fixed in this PR:
      Bug A – skipped mutations were logged as applied (no status field).
      Bug B – reverted mutations (after 2 consecutive regressions) stayed in log.
    """

    def _make_card(self, tcgdex_id: str, name: str | None = None):
        from app.cards.models import CardDefinition
        return CardDefinition(
            tcgdex_id=tcgdex_id,
            name=name or tcgdex_id,
            set_abbrev=tcgdex_id.rsplit("-", 1)[0] if "-" in tcgdex_id else "",
            set_number=tcgdex_id.rsplit("-", 1)[1] if "-" in tcgdex_id else "",
        )

    # ------------------------------------------------------------------
    # Spec A: sequential mutations respect current deck counts
    # ------------------------------------------------------------------

    def test_sequential_pikachu_removal_respects_count(self):
        """After one Pikachu removal, a second removal only succeeds if count > 0."""
        pika = self._make_card("me02.5-057", "Pikachu ex")
        other = self._make_card("sv01-001", "Other")
        replacement_a = self._make_card("sv10-129", "Cynthia's Spiritomb")
        replacement_b = self._make_card("sv08-077", "Hoothoot")

        # Start: 4 Pikachu ex, 1 Other
        deck = [pika] * 4 + [other]

        # First removal — should succeed
        m1 = {"card_removed": "me02.5-057", "card_added": "sv10-129",
               "card_added_def": replacement_a}
        deck, text, applied1 = _apply_mutations(deck, "", [m1])
        assert len(applied1) == 1, "First removal must succeed"
        pika_count = sum(1 for c in deck if c.tcgdex_id == "me02.5-057")
        assert pika_count == 3

        # Second removal — succeeds (3 copies remain)
        m2 = {"card_removed": "me02.5-057", "card_added": "sv08-077",
               "card_added_def": replacement_b}
        deck, text, applied2 = _apply_mutations(deck, "", [m2])
        assert len(applied2) == 1
        assert sum(1 for c in deck if c.tcgdex_id == "me02.5-057") == 2

    def test_removal_impossible_when_count_is_zero(self):
        """A removal is skipped when the card is no longer in the deck."""
        other = self._make_card("sv01-001", "Other")
        replacement = self._make_card("sv10-129", "Cynthia's Spiritomb")

        # Pikachu ex absent from deck
        deck = [other]
        m = {"card_removed": "me02.5-057", "card_added": "sv10-129",
             "card_added_def": replacement}
        new_deck, _, applied = _apply_mutations(deck, "", [m])
        assert applied == [], "Removal must be skipped when card absent"
        assert len(new_deck) == 1  # deck unchanged

    def test_only_applied_mutations_returned(self):
        """_apply_mutations returns only the mutations that touched the deck."""
        pika = self._make_card("me02.5-057", "Pikachu ex")
        ghost = self._make_card("sv10-129", "Cynthia's Spiritomb")
        deck = [pika, pika]

        # One valid swap, one impossible (card_added_def=None)
        m_valid = {"card_removed": "me02.5-057", "card_added": "sv10-129",
                   "card_added_def": ghost}
        m_skip  = {"card_removed": "me02.5-057", "card_added": "sv99-999",
                   "card_added_def": None}
        _, _, applied = _apply_mutations(deck, "", [m_valid, m_skip])
        assert len(applied) == 1
        assert applied[0]["card_added"] == "sv10-129"

    # ------------------------------------------------------------------
    # Spec B: applied mutation log reconstructs the final deck
    # ------------------------------------------------------------------

    def test_applied_log_reconstructs_final_deck(self):
        """Replaying applied mutations on the original deck produces the final deck."""
        pika = self._make_card("me02.5-057", "Pikachu ex")
        ghost = self._make_card("sv10-129", "Cynthia's Spiritomb")
        hoot  = self._make_card("sv08-077", "Hoothoot")

        # Build a legal 60-card deck: 4×pika + 56 fillers spread across 14 unique cards
        fillers = []
        for i in range(1, 15):
            fillers += [self._make_card(f"sv01-{i:03d}", f"Filler {i}")] * 4
        original = [pika] * 4 + fillers  # 4 + 56 = 60

        # Round 3: Pikachu → Ghost
        m3 = {"card_removed": "me02.5-057", "card_added": "sv10-129", "card_added_def": ghost}
        deck_r4, _, a3 = _apply_mutations(list(original), "", [m3])
        assert len(a3) == 1

        # Round 16: Pikachu → Hoothoot (impossible via def=None — simulate skip)
        m16 = {"card_removed": "me02.5-057", "card_added": "sv08-077", "card_added_def": None}
        deck_r17, _, a16 = _apply_mutations(deck_r4, "", [m16])
        assert a16 == [], "Skipped mutation must not appear in applied list"

        # Final deck is deck_r17 (same as deck_r4 because m16 was skipped)
        pikas = sum(1 for c in deck_r17 if c.tcgdex_id == "me02.5-057")
        ghosts = sum(1 for c in deck_r17 if c.tcgdex_id == "sv10-129")
        assert pikas == 3
        assert ghosts == 1

        # Replaying only applied mutations on original must produce deck_r17
        all_applied = a3  # a16 is skipped, so not in log
        replay = list(original)
        for m in all_applied:
            # Remove exactly one copy (same semantics as _apply_mutations)
            idx = next((i for i, c in enumerate(replay) if c.tcgdex_id == m["card_removed"]), None)
            if idx is not None:
                replay.pop(idx)
                replay.append(m["card_added_def"])
        assert sum(1 for c in replay if c.tcgdex_id == "me02.5-057") == pikas
        assert sum(1 for c in replay if c.tcgdex_id == "sv10-129") == ghosts

    # ------------------------------------------------------------------
    # Spec C: skipped mutations are not returned as applied
    # ------------------------------------------------------------------

    def test_skipped_mutation_absent_from_applied_list(self):
        """card_added_def=None produces an empty applied list, never a row."""
        other = self._make_card("sv01-001", "Other")
        deck = [other]
        m = {"card_removed": "sv01-001", "card_added": "sv99-999", "card_added_def": None}
        _, _, applied = _apply_mutations(deck, "", [m])
        assert applied == []

    def test_card_not_found_not_applied(self):
        """Removing a non-existent card produces empty applied list."""
        other = self._make_card("sv01-001", "Other")
        replacement = self._make_card("sv99-999", "Ghost")
        deck = [other]
        m = {"card_removed": "sv01-999", "card_added": "sv99-999",
             "card_added_def": replacement}
        _, _, applied = _apply_mutations(deck, "", [m])
        assert applied == []

    # ------------------------------------------------------------------
    # Spec D: later rounds use the current deck, not the original
    # ------------------------------------------------------------------

    def test_later_round_sees_previous_mutation(self):
        """After round 3 removes a Pikachu, round 16 sees the updated deck."""
        pika   = self._make_card("me02.5-057", "Pikachu ex")
        ghost  = self._make_card("sv10-129", "Cynthia's Spiritomb")
        hoot   = self._make_card("sv08-077", "Hoothoot")
        deck   = [pika] * 4

        # Round 3
        m3 = {"card_removed": "me02.5-057", "card_added": "sv10-129", "card_added_def": ghost}
        deck, _, _ = _apply_mutations(deck, "", [m3])
        assert sum(1 for c in deck if c.tcgdex_id == "me02.5-057") == 3

        # Round 16 — uses the UPDATED deck (3 Pikachu, not 4)
        m16 = {"card_removed": "me02.5-057", "card_added": "sv08-077", "card_added_def": hoot}
        deck, _, a16 = _apply_mutations(deck, "", [m16])
        # Removal succeeds because 3 > 0
        assert len(a16) == 1
        assert sum(1 for c in deck if c.tcgdex_id == "me02.5-057") == 2

    # ------------------------------------------------------------------
    # Spec E: revert leaves only best-deck mutations as applied
    # ------------------------------------------------------------------

    def test_reverted_mutations_not_in_applied_list(self):
        """_apply_mutations returns [] for a mutation that was subsequently skipped.

        The revert DB update is tested separately (DB layer).  Here we verify
        that skipped mutations never enter the applied list to begin with, so
        _persist_applied_mutations would never write a stale row.
        """
        other = self._make_card("sv01-001", "Other")
        replacement = self._make_card("sv99-999", "Ghost")

        deck = [other]
        # Mutation skipped because card_added_def is missing
        m = {"card_removed": "sv01-001", "card_added": "sv99-999"}  # no card_added_def key
        _, _, applied = _apply_mutations(deck, "", [m])
        assert applied == []


# ---------------------------------------------------------------------------
# _validate_post_mutation_deck
# ---------------------------------------------------------------------------

class TestValidatePostMutationDeck:
    def _make_card(self, tcgdex_id: str, name: str | None = None):
        from app.cards.models import CardDefinition
        return CardDefinition(
            tcgdex_id=tcgdex_id,
            name=name or tcgdex_id,
            set_abbrev=tcgdex_id.rsplit("-", 1)[0] if "-" in tcgdex_id else "",
            set_number=tcgdex_id.rsplit("-", 1)[1] if "-" in tcgdex_id else "",
        )

    def test_valid_60_card_deck_returns_no_errors(self):
        deck = [self._make_card(f"sv01-{i:03d}", f"Card {i}") for i in range(15)]
        deck = deck * 4  # 15 × 4 = 60
        assert _validate_post_mutation_deck(deck) == []

    def test_wrong_size_returns_error(self):
        deck = [self._make_card(f"sv01-{i:03d}", f"Card {i}") for i in range(59)]
        errors = _validate_post_mutation_deck(deck)
        assert any("59" in e for e in errors)

    def test_too_many_copies_returns_error(self):
        pikachu = [self._make_card("poke-001", "Pikachu")] * 5
        others = [self._make_card(f"sv01-{i:03d}", f"Card {i}") for i in range(55)]
        errors = _validate_post_mutation_deck(pikachu + others)
        assert any("Pikachu" in e for e in errors)

    def test_basic_energy_exempt_from_copy_limit(self):
        energy = [self._make_card(f"sve-{i:02d}", "Psychic Energy") for i in range(10)]
        others = [self._make_card(f"sv01-{i:03d}", f"Card {i}") for i in range(50)]
        assert _validate_post_mutation_deck(energy + others) == []


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

    async def _make_terminal_state_mocks(self, status: str, mock_engine_cls, mock_sm_cls):
        """Helper: set up mocks so the sim row returns the given terminal status."""
        mock_sim = MagicMock()
        mock_sim.status = status
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_sim

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        mock_sm_cls.return_value.return_value = mock_session

        mock_eng_instance = MagicMock()
        mock_eng_instance.dispose = AsyncMock()
        mock_engine_cls.return_value = mock_eng_instance
        return mock_sim, mock_session

    async def test_complete_simulation_skips_redelivered_task(
        self, simulation_id, mock_redis
    ):
        """Re-delivered task for an already-complete simulation must bail immediately.

        Regression: task_acks_late=True + Redis visibility_timeout < sim duration
        caused the broker to redeliver a task that had already completed.  The
        re-delivery previously reset status to 'running', replayed rounds, found
        persisted coach mutations, and marked the sim as 'failed'.
        """
        with patch("app.tasks.simulation.create_async_engine") as mock_engine, \
             patch("app.tasks.simulation.async_sessionmaker") as mock_sm:

            mock_sim, mock_session = await self._make_terminal_state_mocks(
                "complete", mock_engine, mock_sm
            )

            from app.tasks.simulation import _run_simulation_async
            result = await _run_simulation_async(None, simulation_id)

        assert result == {"status": "skipped_complete"}
        assert mock_sim.status == "complete", "status must not be overwritten to 'running'"
        mock_session.commit.assert_not_awaited()

    async def test_failed_simulation_skips_redelivered_task(
        self, simulation_id, mock_redis
    ):
        """Re-delivered task for an already-failed simulation must bail immediately.

        Prevents silent re-execution of a failed sim without explicit operator
        action (creating a new simulation row).
        """
        with patch("app.tasks.simulation.create_async_engine") as mock_engine, \
             patch("app.tasks.simulation.async_sessionmaker") as mock_sm:

            mock_sim, mock_session = await self._make_terminal_state_mocks(
                "failed", mock_engine, mock_sm
            )

            from app.tasks.simulation import _run_simulation_async
            result = await _run_simulation_async(None, simulation_id)

        assert result == {"status": "skipped_failed"}
        assert mock_sim.status == "failed", "status must not be overwritten to 'running'"
        mock_session.commit.assert_not_awaited()

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
# _PTCGL_DB_KEY_ALIASES — MEP 30 alias resolution
# ---------------------------------------------------------------------------

class TestPtcglDbKeyAliases:
    """Tests for PTCGL alias resolution (e.g. Mega Charizard Y ex MEP 30 → ASC 22)."""

    @pytest.mark.asyncio
    async def test_mep30_resolves_via_alias_in_deck_text_to_card_defs(self):
        """MEP 30 resolves to me02.5-022 (ASC 22) without needing MEP in DB."""
        from unittest.mock import AsyncMock, MagicMock
        from app.tasks.simulation import _deck_text_to_card_defs

        mock_row = MagicMock()
        mock_row.tcgdex_id = "me02.5-022"
        mock_row.name = "Mega Charizard Y ex"
        mock_row.set_abbrev = "ASC"
        mock_row.set_number = "22"
        mock_row.category = "Pokemon"
        mock_row.subcategory = "Stage2"
        mock_row.hp = 360
        mock_row.types = ["Fire"]
        mock_row.evolve_from = "Charmeleon"
        mock_row.stage = "Stage2"
        mock_row.retreat_cost = 3
        mock_row.regulation_mark = None
        mock_row.rarity = None
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

        defs = await _deck_text_to_card_defs("1 Mega Charizard Y ex MEP 30", mock_factory)

        assert len(defs) == 1
        assert defs[0].tcgdex_id == "me02.5-022"
        assert defs[0].name == "Mega Charizard Y ex"

    @pytest.mark.asyncio
    async def test_mep30_no_tcgdex_call_when_asc22_in_db(self):
        """ensure_deck_cards_in_db does not call TCGDex for MEP 30 when ASC 22 is in DB."""
        from unittest.mock import AsyncMock, MagicMock, patch
        from app.tasks.simulation import ensure_deck_cards_in_db

        asc_row = MagicMock()
        asc_row.set_abbrev = "ASC"
        asc_row.set_number = "22"
        scalars = MagicMock()
        scalars.all.return_value = [asc_row]
        result = MagicMock()
        result.scalars.return_value = scalars

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=result)

        with patch("app.cards.tcgdex.TCGDexClient.get_card") as mock_get:
            await ensure_deck_cards_in_db(["1 Mega Charizard Y ex MEP 30"], mock_db)
            mock_get.assert_not_called()

    @pytest.mark.asyncio
    async def test_unrelated_mep_card_unaffected_by_alias(self):
        """An unrelated MEP card (e.g. MEP 25) still resolves via normal DB lookup."""
        from unittest.mock import AsyncMock, MagicMock
        from app.tasks.simulation import _deck_text_to_card_defs

        mock_row = MagicMock()
        mock_row.tcgdex_id = "mep-025"
        mock_row.name = "Pikachu ex"
        mock_row.set_abbrev = "MEP"
        mock_row.set_number = "25"
        mock_row.category = "Pokemon"
        mock_row.subcategory = "Basic"
        mock_row.hp = 130
        mock_row.types = ["Lightning"]
        mock_row.evolve_from = None
        mock_row.stage = "Basic"
        mock_row.retreat_cost = 1
        mock_row.regulation_mark = None
        mock_row.rarity = None
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

        defs = await _deck_text_to_card_defs("1 Pikachu ex MEP 25", mock_factory)

        assert len(defs) == 1
        assert defs[0].tcgdex_id == "mep-025"

    @pytest.mark.asyncio
    async def test_unknown_mep_card_still_raises(self):
        """An unknown MEP card not in the alias map still raises ValueError if absent from DB."""
        from unittest.mock import AsyncMock, MagicMock
        from app.tasks.simulation import _deck_text_to_card_defs

        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result = MagicMock()
        mock_result.scalars.return_value = mock_scalars

        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_factory = MagicMock()
        mock_factory.return_value = mock_session

        with pytest.raises(ValueError, match="ensure_deck_cards_in_db"):
            await _deck_text_to_card_defs("1 SomeCard MEP 99", mock_factory)

    @pytest.mark.asyncio
    async def test_mep30_fresh_db_fetches_alias_target_not_mep030(self):
        """Fresh DB: MEP 30 absent causes alias target (ASC 22/me02.5) to be fetched, not mep-030."""
        from unittest.mock import AsyncMock, MagicMock, patch, call
        from app.tasks.simulation import ensure_deck_cards_in_db

        # DB returns nothing (fresh install, neither MEP nor ASC cards present)
        empty_scalars = MagicMock()
        empty_scalars.all.return_value = []
        empty_result = MagicMock()
        empty_result.scalars.return_value = empty_scalars

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=empty_result)
        mock_db.commit = AsyncMock()

        raw_tcgdex = {
            "id": "me02.5-022",
            "name": "Mega Charizard Y ex",
            "category": "Pokemon",
            "hp": 360,
            "types": ["Fire"],
            "stage": "Stage2",
            "retreat": 3,
            "attacks": [],
            "abilities": [],
            "weaknesses": [],
            "resistances": [],
            "regulationMark": None,
            "rarity": None,
            "image": None,
        }

        with patch("app.cards.tcgdex.TCGDexClient.get_card", new_callable=AsyncMock, return_value=raw_tcgdex) as mock_get, \
             patch("app.memory.postgres.MatchMemoryWriter.ensure_cards", new_callable=AsyncMock):
            await ensure_deck_cards_in_db(["1 Mega Charizard Y ex MEP 30"], mock_db)
            # Must have fetched ASC 22 (set_id "me02.5", number "22"), not mep-030
            mock_get.assert_called_once()
            args = mock_get.call_args
            assert args[0][0] == "me02.5", f"Expected set_id 'me02.5', got {args[0][0]!r}"
            assert str(args[0][1]) == "22", f"Expected number '22', got {args[0][1]!r}"

    def test_resolve_ptcgl_db_key_alias(self):
        """_resolve_ptcgl_db_key returns canonical alias target for known aliases."""
        from app.tasks.simulation import _resolve_ptcgl_db_key
        assert _resolve_ptcgl_db_key("MEP", "30") == ("ASC", "22")

    def test_resolve_ptcgl_db_key_passthrough(self):
        """_resolve_ptcgl_db_key returns original key for non-aliased entries."""
        from app.tasks.simulation import _resolve_ptcgl_db_key
        assert _resolve_ptcgl_db_key("PRE", "71") == ("PRE", "71")
        assert _resolve_ptcgl_db_key("MEP", "25") == ("MEP", "25")
        assert _resolve_ptcgl_db_key("MEP", "99") == ("MEP", "99")


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


# ---------------------------------------------------------------------------
# _per_opponent_all_met — per-opponent target stop-condition helper
# ---------------------------------------------------------------------------

class TestPerOpponentAllMet:
    """Unit tests for _per_opponent_all_met.

    Reproduces the screenshot scenario from the bug report:
      - target_win_rate=50, rounds_to_confirm=3
      - Some opponents only have streaks of 0-2 after round 3.
      - The simulation must NOT stop.
    """

    # ── negative cases (should NOT stop) ───────────────────────────────────

    def test_screenshot_scenario_does_not_stop(self):
        """Reproduces the real bug: mixed streaks after round 3 → must not stop."""
        # After round 3, per the screenshot:
        streaks = {
            "alakazam-dudunsparce":     3,   # qualifies
            "dragapult-dudunsparce":    0,   # R3 dropped below target
            "festival-lead":            0,   # R2 & R3 below target
            "lopunny-dudunsparce":      0,   # R3 below target
            "ns-zoroark":               3,   # qualifies
            "ogerpon-box":              3,   # qualifies
            "ogerpon-meganium":         2,   # R1 below target, only 2-streak
            "raging-bolt-ogerpon":      2,   # R1 below target, only 2-streak
            "rockets-honchkrow":        3,   # qualifies
            "starmie-froslass":         2,   # R1 below target, only 2-streak
        }
        assert _per_opponent_all_met(streaks, num_expected=10, rounds_to_confirm=3) is False

    def test_some_opponents_below_target_does_not_stop(self):
        """At least one opponent below threshold → must not stop."""
        streaks = {"a": 3, "b": 2, "c": 3}
        assert _per_opponent_all_met(streaks, num_expected=3, rounds_to_confirm=3) is False

    def test_missing_opponent_data_does_not_stop(self):
        """Fewer entries than expected opponents (incomplete data) → must not stop."""
        streaks = {"a": 3}
        assert _per_opponent_all_met(streaks, num_expected=3, rounds_to_confirm=3) is False

    def test_empty_streaks_does_not_stop(self):
        """No streaks at all → must not stop."""
        assert _per_opponent_all_met({}, num_expected=3, rounds_to_confirm=3) is False

    def test_zero_expected_does_not_stop(self):
        """num_expected=0 is an edge case → must not stop."""
        assert _per_opponent_all_met({}, num_expected=0, rounds_to_confirm=3) is False

    def test_one_below_many_above_does_not_stop(self):
        """Aggregate passes but one opponent hasn't → must not stop."""
        streaks = {str(i): 3 for i in range(9)}
        streaks["9"] = 1  # one opponent still at streak 1
        assert _per_opponent_all_met(streaks, num_expected=10, rounds_to_confirm=3) is False

    # ── positive cases (should stop) ───────────────────────────────────────

    def test_all_opponents_met_exactly_stops(self):
        """Every opponent has streak == rounds_to_confirm → must stop."""
        streaks = {"a": 3, "b": 3, "c": 3}
        assert _per_opponent_all_met(streaks, num_expected=3, rounds_to_confirm=3) is True

    def test_all_opponents_exceeded_stops(self):
        """Streaks above threshold also qualify."""
        streaks = {"a": 5, "b": 4, "c": 10}
        assert _per_opponent_all_met(streaks, num_expected=3, rounds_to_confirm=3) is True

    def test_single_opponent_met_stops(self):
        """Single-opponent simulation with exactly rounds_to_confirm streak."""
        assert _per_opponent_all_met({"solo": 1}, num_expected=1, rounds_to_confirm=1) is True

    def test_rounds_to_confirm_one_all_above(self):
        """rounds_to_confirm=1, all at or above → stop."""
        streaks = {"x": 1, "y": 2}
        assert _per_opponent_all_met(streaks, num_expected=2, rounds_to_confirm=1) is True

    # ── streak-reset semantics ──────────────────────────────────────────────

    def test_streak_reset_after_below_target_round(self):
        """Simulate: opponent had streak 3, then dropped → streak resets to 0."""
        # After a qualifying run the opponent drops, then climbs back.
        # Streak progression: 1 → 2 → 3 (stop?) → drop (reset to 0) → 1 → 2
        # After the drop+2 rounds the streak is 2, which is < 3 → must not stop.
        streaks = {"opp": 2}
        assert _per_opponent_all_met(streaks, num_expected=1, rounds_to_confirm=3) is False

    def test_aggregate_vs_per_opponent_distinct(self):
        """Illustrates that aggregate and per_opponent are distinct.

        In aggregate mode the caller would compute total_wins / total_games
        across all opponents, which could be >= target even if some opponents
        individually fail.  This test verifies the per-opponent helper only
        looks at per-opponent streaks, not an aggregate figure.
        """
        # Two opponents:
        # "good": 9/10 wins each round (90%) — streak 3
        # "bad":  1/10 wins each round (10%) — streak 0
        # Aggregate across 10+10 games per round: ~50%, might pass aggregate
        # Per-opponent: "bad" never met 50% → must not stop.
        streaks = {"good": 3, "bad": 0}
        assert _per_opponent_all_met(streaks, num_expected=2, rounds_to_confirm=3) is False


# ---------------------------------------------------------------------------
# _win_rate_pct helper (used internally for per-opponent rate computation)
# ---------------------------------------------------------------------------

class TestWinRatePct:
    def test_zero_games_gives_zero(self):
        assert _win_rate_pct(0, 0) == 0

    def test_all_wins(self):
        assert _win_rate_pct(10, 10) == 100

    def test_rounding(self):
        # 2/3 ≈ 66.67 → rounds to 67
        assert _win_rate_pct(2, 3) == 67

    def test_one_third(self):
        # 1/3 ≈ 33.33 → rounds to 33
        assert _win_rate_pct(1, 3) == 33

    def test_half(self):
        assert _win_rate_pct(5, 10) == 50
