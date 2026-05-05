"""Tests for setup-phase event emission in MatchRunner.

Verifies that _run_setup emits the full set of structured events needed for
a verbose match transcript: opening hands (with card names), coin flip,
place_active, place_bench, prizes_set (with card names), setup_complete,
and turn_start for turn 1.

Also verifies that turn draws include card names in the 'cards' field.
"""

from __future__ import annotations

import pytest

from app.engine.runner import MatchRunner
from app.players.base import GreedyPlayer, RandomPlayer


# ── helpers ──────────────────────────────────────────────────────────────────


async def _run_match(p1_deck, p2_deck, *, rng_seed: int = 42, max_turns: int = 1):
    """Run a match with GreedyPlayer vs RandomPlayer, collect emitted events."""
    emitted: list[dict] = []

    runner = MatchRunner(
        p1_player=GreedyPlayer(),
        p2_player=RandomPlayer(),
        p1_deck=p1_deck,
        p2_deck=p2_deck,
        p1_deck_name="Deck A",
        p2_deck_name="Deck B",
        max_turns=max_turns,
        rng_seed=rng_seed,
        event_callback=emitted.append,
    )
    await runner.run()
    return emitted


def _events_of(emitted: list[dict], event_type: str) -> list[dict]:
    return [e for e in emitted if e.get("event_type") == event_type]


# ── setup events ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestSetupEvents:

    async def test_setup_start_emitted(self, dragapult_deck_defs, team_rocket_deck_defs):
        """setup_start is emitted before opening hands are drawn."""
        emitted = await _run_match(dragapult_deck_defs, team_rocket_deck_defs)
        setup_starts = _events_of(emitted, "setup_start")
        assert len(setup_starts) == 1
        ev = setup_starts[0]
        assert ev.get("p1_deck") == "Deck A"
        assert ev.get("p2_deck") == "Deck B"

    async def test_opening_hand_drawn_both_players(self, dragapult_deck_defs, team_rocket_deck_defs):
        """opening_hand_drawn emitted once for each player with card names."""
        emitted = await _run_match(dragapult_deck_defs, team_rocket_deck_defs)
        hands = _events_of(emitted, "opening_hand_drawn")
        players = {e.get("player") for e in hands}
        assert "p1" in players
        assert "p2" in players

    async def test_opening_hand_has_card_names(self, dragapult_deck_defs, team_rocket_deck_defs):
        """Each opening_hand_drawn event contains a non-empty cards list of strings."""
        emitted = await _run_match(dragapult_deck_defs, team_rocket_deck_defs)
        hands = _events_of(emitted, "opening_hand_drawn")
        for ev in hands:
            cards = ev.get("cards", [])
            assert isinstance(cards, list)
            assert len(cards) > 0, f"No cards in opening_hand_drawn for {ev.get('player')}"
            for name in cards:
                assert isinstance(name, str) and name, "Card name must be a non-empty string"

    async def test_opening_hand_count_matches_cards(self, dragapult_deck_defs, team_rocket_deck_defs):
        """opening_hand_drawn.count == len(cards)."""
        emitted = await _run_match(dragapult_deck_defs, team_rocket_deck_defs)
        for ev in _events_of(emitted, "opening_hand_drawn"):
            assert ev.get("count") == len(ev.get("cards", []))

    async def test_coin_flip_emitted(self, dragapult_deck_defs, team_rocket_deck_defs):
        """coin_flip event is emitted with first_player field."""
        emitted = await _run_match(dragapult_deck_defs, team_rocket_deck_defs)
        flips = _events_of(emitted, "coin_flip")
        assert len(flips) == 1
        assert flips[0].get("first_player") in ("p1", "p2")

    async def test_place_active_emitted_both_players(self, dragapult_deck_defs, team_rocket_deck_defs):
        """place_active emitted for each player with a card name."""
        emitted = await _run_match(dragapult_deck_defs, team_rocket_deck_defs)
        actives = _events_of(emitted, "place_active")
        players = {e.get("player") for e in actives}
        assert "p1" in players
        assert "p2" in players
        for ev in actives:
            assert ev.get("card"), "place_active must include a card name"

    async def test_prizes_set_emitted_both_players(self, dragapult_deck_defs, team_rocket_deck_defs):
        """prizes_set emitted for each player with count and card names."""
        emitted = await _run_match(dragapult_deck_defs, team_rocket_deck_defs)
        prizes = _events_of(emitted, "prizes_set")
        players = {e.get("player") for e in prizes}
        assert "p1" in players
        assert "p2" in players
        for ev in prizes:
            assert ev.get("count") == 6, "Exactly 6 prizes expected"
            cards = ev.get("cards", [])
            assert isinstance(cards, list)
            assert len(cards) == 6, "prizes_set must include all 6 prize card names"
            for name in cards:
                assert isinstance(name, str) and name

    async def test_setup_complete_emitted(self, dragapult_deck_defs, team_rocket_deck_defs):
        """setup_complete is emitted after prizes are set with active/bench info."""
        emitted = await _run_match(dragapult_deck_defs, team_rocket_deck_defs)
        completes = _events_of(emitted, "setup_complete")
        assert len(completes) == 1
        ev = completes[0]
        assert ev.get("p1_active"), "setup_complete must include p1_active"
        assert ev.get("p2_active"), "setup_complete must include p2_active"
        assert isinstance(ev.get("p1_bench"), list)
        assert isinstance(ev.get("p2_bench"), list)
        assert ev.get("p1_prizes") == 6
        assert ev.get("p2_prizes") == 6

    async def test_turn_start_emitted_for_turn_one(self, dragapult_deck_defs, team_rocket_deck_defs):
        """turn_start is emitted for turn 1 (from setup, before the first draw)."""
        emitted = await _run_match(dragapult_deck_defs, team_rocket_deck_defs)
        turn_starts = _events_of(emitted, "turn_start")
        turns = [e.get("turn") or e.get("data", {}).get("turn") for e in turn_starts]
        assert 1 in turns, f"turn_start for turn 1 not found; found turns: {turns}"

    async def test_setup_order_is_correct(self, dragapult_deck_defs, team_rocket_deck_defs):
        """setup_start → opening_hand_drawn → coin_flip → prizes_set → setup_complete → turn_start."""
        emitted = await _run_match(dragapult_deck_defs, team_rocket_deck_defs)

        def idx(event_type: str, n: int = 0) -> int:
            events = _events_of(emitted, event_type)
            return emitted.index(events[n]) if events else 99999

        assert idx("setup_start") < idx("opening_hand_drawn"), "setup_start before opening_hand_drawn"
        assert idx("opening_hand_drawn") < idx("coin_flip"), "opening_hand_drawn before coin_flip"
        assert idx("coin_flip") < idx("prizes_set"), "coin_flip before prizes_set"
        assert idx("prizes_set") < idx("setup_complete"), "prizes_set before setup_complete"
        assert idx("setup_complete") < idx("turn_start"), "setup_complete before turn_start"


# ── draw events ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestDrawEventCards:

    async def test_turn_draw_includes_card_names(self, dragapult_deck_defs, team_rocket_deck_defs):
        """draw events emitted during the DRAW phase include a non-empty cards list."""
        emitted = await _run_match(dragapult_deck_defs, team_rocket_deck_defs, max_turns=10)
        draws = _events_of(emitted, "draw")
        # Filter to the turn-start draws (DRAW phase), not Supporter/effect draws (MAIN phase)
        turn_draws = [e for e in draws if e.get("phase") == "DRAW" and (e.get("turn") or 0) >= 1]
        assert turn_draws, "No DRAW-phase draw events emitted during turns"
        for ev in turn_draws:
            cards = ev.get("cards", [])
            assert isinstance(cards, list)
            assert len(cards) >= 1
            for name in cards:
                assert isinstance(name, str) and name

    async def test_draw_count_matches_cards_length(self, dragapult_deck_defs, team_rocket_deck_defs):
        """draw.count == len(draw.cards) when cards field is present."""
        emitted = await _run_match(dragapult_deck_defs, team_rocket_deck_defs, max_turns=10)
        for ev in _events_of(emitted, "draw"):
            cards = ev.get("cards")
            if cards is None:
                continue  # draw events from Supporter effects may lack cards field
            count = ev.get("count", 0)
            assert count == len(cards), f"Mismatch: count={count}, len(cards)={len(cards)}"

    async def test_turn_draw_events_are_emitted_live(self, dragapult_deck_defs, team_rocket_deck_defs):
        """draw events appear in the callback stream (not just state.events)."""
        emitted = await _run_match(dragapult_deck_defs, team_rocket_deck_defs, max_turns=5)
        draws = _events_of(emitted, "draw")
        # After setup, each turn should produce a draw
        turn_draws = [e for e in draws if (e.get("turn") or 0) >= 1]
        assert len(turn_draws) >= 1, "At least one turn draw should be in the callback stream"


# ── mulligan event ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestMulliganEvent:

    async def test_mulligan_includes_new_hand(self, dragapult_deck_defs, team_rocket_deck_defs):
        """If a mulligan occurs, the event includes new_hand card names."""
        # Run many seeds to find one with a mulligan
        found_mulligan = False
        for seed in range(50):
            emitted = await _run_match(dragapult_deck_defs, team_rocket_deck_defs, rng_seed=seed)
            mulligans = _events_of(emitted, "mulligan")
            if mulligans:
                found_mulligan = True
                for ev in mulligans:
                    new_hand = ev.get("new_hand", [])
                    assert isinstance(new_hand, list)
                    assert len(new_hand) > 0
                    for name in new_hand:
                        assert isinstance(name, str) and name
                break

        if not found_mulligan:
            pytest.skip("No mulligan occurred in 50 seeds — skipping")
