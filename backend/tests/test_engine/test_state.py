"""Tests for GameState, PlayerState, CardInstance data model.

All assertions use real card data loaded from TCGDex fixtures.
"""

from __future__ import annotations

import pytest

from app.engine.state import (
    CardInstance,
    EnergyAttachment,
    EnergyType,
    GameState,
    Phase,
    PlayerState,
    StatusCondition,
    Zone,
)
from app.cards.models import CardDefinition
from app.engine.runner import build_deck_instances


class TestCardInstance:
    def test_default_instance_id_is_unique(self):
        a = CardInstance()
        b = CardInstance()
        assert a.instance_id != b.instance_id

    def test_energy_provides_field_present(self):
        c = CardInstance(energy_provides=["Fire"])
        assert c.energy_provides == ["Fire"]

    def test_card_instance_from_def(self, dragapult_deck_defs):
        """CardInstance built from real CardDefinition has correct HP."""
        from app.cards import registry as reg
        dragapult_def = next(
            d for d in dragapult_deck_defs if "Dragapult" in d.name and d.hp
        )
        inst = CardInstance(
            card_def_id=dragapult_def.tcgdex_id,
            card_name=dragapult_def.name,
            max_hp=dragapult_def.hp,
            current_hp=dragapult_def.hp,
        )
        assert inst.current_hp == dragapult_def.hp
        assert inst.current_hp > 0


class TestPlayerState:
    def test_default_player_state(self):
        p = PlayerState(player_id="p1")
        assert p.player_id == "p1"
        assert p.prizes_remaining == 6
        assert not p.supporter_played_this_turn
        assert p.hand == []

    def test_player_state_reset_flags(self):
        p = PlayerState(player_id="p1")
        p.supporter_played_this_turn = True
        p.energy_attached_this_turn = True
        p.retreat_used_this_turn = True
        # Flags should be settable (they are reset by MatchRunner._end_turn)
        assert p.supporter_played_this_turn
        assert p.energy_attached_this_turn
        assert p.retreat_used_this_turn


class TestGameState:
    def test_initial_game_state(self):
        state = GameState()
        assert state.phase == Phase.SETUP
        assert state.turn_number == 0
        assert state.active_player == "p1"
        assert state.winner is None
        assert state.events == []

    def test_emit_event(self):
        state = GameState()
        event = state.emit_event("test_event", foo="bar")
        assert event["event_type"] == "test_event"
        assert event["foo"] == "bar"
        assert len(state.events) == 1

    def test_get_player_and_opponent(self):
        state = GameState()
        assert state.get_player("p1") is state.p1
        assert state.get_player("p2") is state.p2
        assert state.get_opponent("p1") is state.p2
        assert state.get_opponent("p2") is state.p1

    def test_opponent_id(self):
        state = GameState()
        assert state.opponent_id("p1") == "p2"
        assert state.opponent_id("p2") == "p1"

    def test_active_stadium_starts_none(self):
        state = GameState()
        assert state.active_stadium is None


class TestBuildDeckInstances:
    def test_build_deck_creates_60_instances(self, dragapult_deck_defs):
        instances = build_deck_instances(dragapult_deck_defs)
        assert len(instances) == 60

    def test_build_deck_all_unique_instance_ids(self, dragapult_deck_defs):
        instances = build_deck_instances(dragapult_deck_defs)
        ids = [i.instance_id for i in instances]
        assert len(set(ids)) == 60

    def test_build_deck_pokemon_have_hp(self, dragapult_deck_defs):
        instances = build_deck_instances(dragapult_deck_defs)
        pokemon = [i for i in instances if i.card_type.lower() == "pokemon"]
        assert all(i.current_hp > 0 for i in pokemon), \
            "All Pokémon should have HP > 0"

    def test_build_deck_energy_provides_populated(self, dragapult_deck_defs):
        instances = build_deck_instances(dragapult_deck_defs)
        energies = [i for i in instances
                    if i.card_type.lower() == "energy" and i.card_subtype == "Basic"]
        # Basic energies must have energy_provides set
        assert all(len(i.energy_provides) > 0 for i in energies), \
            "Basic energy cards should have energy_provides populated"

    def test_two_builds_have_independent_instances(self, dragapult_deck_defs):
        """Two builds from the same defs should produce independent instances."""
        deck1 = build_deck_instances(dragapult_deck_defs)
        deck2 = build_deck_instances(dragapult_deck_defs)
        ids1 = {i.instance_id for i in deck1}
        ids2 = {i.instance_id for i in deck2}
        assert ids1.isdisjoint(ids2), "Instance IDs must be unique across builds"
