"""Unit tests for MatchRunner._annotate_action_events_with_ai_reasoning.

These tests verify that AI reasoning is injected directly into visible events
instead of relying on hidden ai_decision correlation events.
"""

from __future__ import annotations

import types
import pytest

from app.engine.actions import Action, ActionType
from app.engine.runner import MatchRunner


def _make_runner() -> MatchRunner:
    """Build a minimal MatchRunner without full game infrastructure."""
    return MatchRunner.__new__(MatchRunner)


def _make_state(events: list[dict]) -> types.SimpleNamespace:
    """Build a minimal fake state with an events list."""
    state = types.SimpleNamespace()
    state.events = events
    return state


def _make_action(
    action_type: ActionType,
    *,
    reasoning: str | None = None,
    card_instance_id: str | None = None,
    target_instance_id: str | None = None,
    attack_index: int | None = None,
) -> Action:
    return Action(
        action_type=action_type,
        player_id="p1",
        card_instance_id=card_instance_id,
        target_instance_id=target_instance_id,
        attack_index=attack_index,
        reasoning=reasoning,
    )


class TestAnnotateActionEventsWithAiReasoning:
    """_annotate_action_events_with_ai_reasoning injects ai_reasoning into events."""

    def test_attach_energy_annotates_energy_attached(self):
        action = _make_action(
            ActionType.ATTACH_ENERGY,
            reasoning="Attach to build toward Stone Axe",
            card_instance_id="spiky-energy-1",
            target_instance_id="ogerpon-1",
        )
        events = [{"event_type": "energy_attached", "turn": 8, "player": "p1"}]
        state = _make_state(events)
        runner = _make_runner()
        prev_len = 0

        runner._annotate_action_events_with_ai_reasoning(state, prev_len, action)

        assert events[0]["ai_reasoning"] == "Attach to build toward Stone Axe"
        assert events[0]["ai_action_type"] == "ATTACH_ENERGY"
        assert events[0]["ai_card_played"] == "spiky-energy-1"
        assert events[0]["ai_target"] == "ogerpon-1"

    def test_evolve_annotates_evolved_event(self):
        action = _make_action(
            ActionType.EVOLVE,
            reasoning="Evolve now for extra HP",
            card_instance_id="dusclops-1",
            target_instance_id="duskull-1",
        )
        events = [{"event_type": "evolved", "turn": 6, "player": "p2"}]
        state = _make_state(events)
        runner = _make_runner()

        runner._annotate_action_events_with_ai_reasoning(state, 0, action)

        assert events[0]["ai_reasoning"] == "Evolve now for extra HP"
        assert events[0]["ai_action_type"] == "EVOLVE"

    def test_attack_annotates_attack_damage_event(self):
        action = _make_action(
            ActionType.ATTACK,
            reasoning="KO the active for 2 prizes",
            attack_index=0,
        )
        events = [
            {"event_type": "attack_declared", "turn": 12, "player": "p1"},
            {"event_type": "attack_damage", "turn": 12, "player": "p1", "final_damage": 200},
        ]
        state = _make_state(events)
        runner = _make_runner()

        runner._annotate_action_events_with_ai_reasoning(state, 0, action)

        for e in events:
            assert e["ai_reasoning"] == "KO the active for 2 prizes"
            assert e["ai_action_type"] == "ATTACK"
            assert e["ai_attack_index"] == 0

    def test_pass_annotates_pass_event(self):
        action = _make_action(ActionType.PASS, reasoning="No good attacks yet")
        events = [{"event_type": "pass", "turn": 3, "player": "p1"}]
        state = _make_state(events)
        runner = _make_runner()

        runner._annotate_action_events_with_ai_reasoning(state, 0, action)

        assert events[0]["ai_reasoning"] == "No good attacks yet"
        assert events[0]["ai_action_type"] == "PASS"

    def test_end_turn_annotates_end_turn_event(self):
        action = _make_action(ActionType.END_TURN, reasoning="Conserve resources")
        events = [{"event_type": "end_turn", "turn": 5, "player": "p2"}]
        state = _make_state(events)
        runner = _make_runner()

        runner._annotate_action_events_with_ai_reasoning(state, 0, action)

        assert events[0]["ai_reasoning"] == "Conserve resources"
        assert events[0]["ai_action_type"] == "END_TURN"

    def test_no_reasoning_does_not_annotate(self):
        """Heuristic/greedy players: reasoning is None → no annotation."""
        action = _make_action(ActionType.ATTACH_ENERGY, reasoning=None)
        events = [{"event_type": "energy_attached", "turn": 7, "player": "p1"}]
        state = _make_state(events)
        runner = _make_runner()

        runner._annotate_action_events_with_ai_reasoning(state, 0, action)

        assert "ai_reasoning" not in events[0]
        assert "ai_action_type" not in events[0]

    def test_only_events_after_prev_len_are_annotated(self):
        """Events before prev_len (pre-existing) are not mutated."""
        action = _make_action(ActionType.ATTACK, reasoning="Go for KO")
        pre_event = {"event_type": "draw", "turn": 3, "player": "p1"}
        new_event = {"event_type": "attack_damage", "turn": 3, "player": "p1"}
        events = [pre_event, new_event]
        state = _make_state(events)
        runner = _make_runner()

        runner._annotate_action_events_with_ai_reasoning(state, prev_len=1, action=action)

        assert "ai_reasoning" not in pre_event
        assert new_event["ai_reasoning"] == "Go for KO"

    def test_optional_fields_not_set_when_absent(self):
        """card_instance_id and target_instance_id absent → no ai_card_played/ai_target."""
        action = _make_action(ActionType.PASS, reasoning="Pass turn")
        events = [{"event_type": "pass", "turn": 2, "player": "p2"}]
        state = _make_state(events)
        runner = _make_runner()

        runner._annotate_action_events_with_ai_reasoning(state, 0, action)

        assert "ai_card_played" not in events[0]
        assert "ai_target" not in events[0]
        assert "ai_attack_index" not in events[0]
        assert events[0]["ai_reasoning"] == "Pass turn"
