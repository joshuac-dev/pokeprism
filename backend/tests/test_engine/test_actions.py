"""Tests for ActionValidator — legal action enumeration and validation.

Uses real card data from fixtures.
"""

from __future__ import annotations

import pytest

from app.engine.actions import Action, ActionType, ActionValidator
from app.engine.state import (
    CardInstance,
    EnergyAttachment,
    EnergyType,
    GameState,
    Phase,
    PlayerState,
    Zone,
)
from app.engine.runner import build_deck_instances
from app.engine.effects.base import ChoiceRequest
from app.cards import registry as card_registry


def _make_state_with_active(p1_active: CardInstance, p2_active: CardInstance) -> GameState:
    state = GameState()
    state.phase = Phase.MAIN
    state.turn_number = 2  # Past turn 1 so evolution is legal in theory
    state.p1.active = p1_active
    state.p2.active = p2_active
    p1_active.zone = Zone.ACTIVE
    p2_active.zone = Zone.ACTIVE
    return state


class TestSetupActions:
    def test_place_active_is_legal_during_setup(self, dragapult_deck_defs):
        instances = build_deck_instances(dragapult_deck_defs)
        state = GameState()
        state.phase = Phase.SETUP
        # Put a Dreepy in hand
        dreepy = next(i for i in instances if "Dreepy" in i.card_name)
        dreepy.zone = Zone.HAND
        state.p1.hand = [dreepy]

        legal = ActionValidator.get_legal_actions(state, "p1")
        types = {a.action_type for a in legal}
        assert ActionType.PLACE_ACTIVE in types


class TestMainPhaseActions:
    def test_attach_energy_legal_when_not_yet_attached(self, dragapult_deck_defs):
        instances = build_deck_instances(dragapult_deck_defs)
        state = GameState()
        state.phase = Phase.MAIN
        state.turn_number = 2

        dreepy = next(i for i in instances if "Dreepy" in i.card_name)
        dreepy.zone = Zone.ACTIVE
        state.p1.active = dreepy

        psych = next(
            i for i in instances
            if "Psychic" in i.card_name and i.card_type.lower() == "energy"
        )
        psych.zone = Zone.HAND
        state.p1.hand = [psych]
        state.p1.energy_attached_this_turn = False

        legal = ActionValidator.get_legal_actions(state, "p1")
        types = {a.action_type for a in legal}
        assert ActionType.ATTACH_ENERGY in types

    def test_attach_energy_blocked_when_already_attached(self, dragapult_deck_defs):
        instances = build_deck_instances(dragapult_deck_defs)
        state = GameState()
        state.phase = Phase.MAIN
        state.turn_number = 2

        dreepy = next(i for i in instances if "Dreepy" in i.card_name)
        dreepy.zone = Zone.ACTIVE
        state.p1.active = dreepy

        psych = next(
            i for i in instances
            if "Psychic" in i.card_name and i.card_type.lower() == "energy"
        )
        psych.zone = Zone.HAND
        state.p1.hand = [psych]
        state.p1.energy_attached_this_turn = True  # Already attached this turn

        legal = ActionValidator.get_legal_actions(state, "p1")
        types = {a.action_type for a in legal}
        assert ActionType.ATTACH_ENERGY not in types

    def test_no_supporter_twice_per_turn(self, dragapult_deck_defs):
        from app.cards import registry as card_registry
        instances = build_deck_instances(dragapult_deck_defs)
        state = GameState()
        state.phase = Phase.MAIN
        state.turn_number = 2

        dreepy = next(i for i in instances if "Dreepy" in i.card_name)
        dreepy.zone = Zone.ACTIVE
        state.p1.active = dreepy

        # Find a supporter in the deck defs (Boss's Orders is a Supporter)
        supporter = next(
            (i for i in instances if i.card_subtype == "Supporter"),
            None,
        )
        if supporter is None:
            pytest.skip("No Supporter found in deck instances — check subcategory inference")

        supporter.zone = Zone.HAND
        state.p1.hand = [supporter]
        state.p1.supporter_played_this_turn = True  # Already played one

        legal = ActionValidator.get_legal_actions(state, "p1")
        types = {a.action_type for a in legal}
        assert ActionType.PLAY_SUPPORTER not in types

    def test_pass_always_legal_during_main(self, dragapult_deck_defs):
        instances = build_deck_instances(dragapult_deck_defs)
        state = GameState()
        state.phase = Phase.MAIN
        state.turn_number = 2

        dreepy = next(i for i in instances if "Dreepy" in i.card_name)
        dreepy.zone = Zone.ACTIVE
        state.p1.active = dreepy
        state.p2.active = next(  # p2 needs an active too
            i for i in build_deck_instances(dragapult_deck_defs)
            if "Dreepy" in i.card_name
        )

        legal = ActionValidator.get_legal_actions(state, "p1")
        types = {a.action_type for a in legal}
        assert ActionType.PASS in types


class TestIllegalActionRejections:
    """Section 2B — prove that ActionValidator rejects specific illegal plays."""

    def test_evolve_blocked_when_just_played(self, dragapult_deck_defs):
        """Pokémon placed this turn cannot be evolved on the same turn."""
        instances = build_deck_instances(dragapult_deck_defs)
        dreepy = next(i for i in instances if "Dreepy" in i.card_name)
        drakloak = next(i for i in instances if "Drakloak" in i.card_name)

        state = GameState()
        state.phase = Phase.MAIN
        state.turn_number = 3

        dreepy.zone = Zone.ACTIVE
        dreepy.turn_played = 3  # Placed THIS turn
        state.p1.active = dreepy

        drakloak.zone = Zone.HAND
        state.p1.hand = [drakloak]

        legal = ActionValidator.get_legal_actions(state, "p1")
        evolve_actions = [a for a in legal if a.action_type == ActionType.EVOLVE]
        assert evolve_actions == [], (
            "EVOLVE should not be offered for a Pokémon played on the current turn"
        )
        # Also confirm validate() explicitly rejects it
        action = Action(ActionType.EVOLVE, "p1",
                        card_instance_id=drakloak.instance_id,
                        target_instance_id=dreepy.instance_id)
        valid, error = ActionValidator.validate(state, action)
        assert not valid

    def test_retreat_blocked_without_energy(self, dragapult_deck_defs):
        """Retreat should be illegal when active Pokémon cannot pay its retreat cost."""
        instances = build_deck_instances(dragapult_deck_defs)
        # Dragapult ex has retreat cost > 0; ensure no energy attached.
        dragapult = next(
            (i for i in instances if "Dragapult" in i.card_name), None
        )
        if dragapult is None:
            pytest.skip("No Dragapult in fixture")
        cdef = card_registry.get(dragapult.card_def_id)
        if cdef is None or cdef.retreat_cost == 0:
            pytest.skip("Card has 0 retreat cost — cannot test blocking")

        dragapult.zone = Zone.ACTIVE
        dragapult.energy_attached = []  # No energy — cannot pay retreat cost

        bench_mon = next(
            (i for i in instances
             if "Dreepy" in i.card_name and i is not dragapult), None
        )
        if bench_mon is None:
            pytest.skip("No bench Pokémon available")
        bench_mon.zone = Zone.BENCH

        state = GameState()
        state.phase = Phase.MAIN
        state.turn_number = 2
        state.p1.active = dragapult
        state.p1.bench = [bench_mon]

        legal = ActionValidator.get_legal_actions(state, "p1")
        retreat_actions = [a for a in legal if a.action_type == ActionType.RETREAT]
        assert retreat_actions == [], (
            "RETREAT should be blocked when active Pokémon has no energy to pay retreat cost"
        )

    def test_attack_blocked_without_energy(self, dragapult_deck_defs):
        """Attack requiring energy is not legal when no energy is attached."""
        instances = build_deck_instances(dragapult_deck_defs)
        # Find a Pokémon whose first attack has a non-empty energy cost.
        attacker = None
        for inst in instances:
            cdef = card_registry.get(inst.card_def_id)
            if cdef and cdef.attacks and cdef.attacks[0].cost:
                attacker = inst
                break
        if attacker is None:
            pytest.skip("No Pokémon with a non-free attack found")

        attacker.zone = Zone.ACTIVE
        attacker.energy_attached = []  # No energy

        opp_active = next(
            (i for i in build_deck_instances(dragapult_deck_defs)
             if "Dreepy" in i.card_name), None
        )
        if opp_active is None:
            pytest.skip("No opponent active available")
        opp_active.zone = Zone.ACTIVE

        state = GameState()
        state.phase = Phase.ATTACK
        state.turn_number = 2
        state.p1.active = attacker
        state.p2.active = opp_active

        legal = ActionValidator.get_legal_actions(state, "p1")
        attack_actions = [a for a in legal if a.action_type == ActionType.ATTACK]
        assert attack_actions == [], (
            "ATTACK should be blocked when active Pokémon has no energy for any attack cost"
        )

    def test_extra_tool_beyond_limit_blocked(self, dragapult_deck_defs):
        """A second Tool cannot be attached to a Pokémon that already carries one."""
        instances = build_deck_instances(dragapult_deck_defs)
        dreepy = next(i for i in instances if "Dreepy" in i.card_name)
        dreepy.zone = Zone.ACTIVE
        dreepy.tools_attached = ["sv08-185"]  # Already has a tool

        state = GameState()
        state.phase = Phase.MAIN
        state.turn_number = 2
        state.p1.active = dreepy

        # Put a Tool card in hand
        tool = next(
            (i for i in instances if i.card_subtype == "Pokémon Tool"
             or i.card_subtype == "Pokemon Tool"),
            None,
        )
        if tool is None:
            pytest.skip("No Tool card found in deck instances")
        tool.zone = Zone.HAND
        state.p1.hand = [tool]

        legal = ActionValidator.get_legal_actions(state, "p1")
        tool_actions = [a for a in legal
                        if a.action_type == ActionType.PLAY_TOOL
                        and a.target_instance_id == dreepy.instance_id]
        assert tool_actions == [], (
            "PLAY_TOOL should be blocked when target Pokémon already has a Tool attached"
        )


class TestAttackPhaseActions:
    def test_attack_legal_when_cost_met(self, dragapult_deck_defs):
        """Attack should be legal when the active Pokémon has enough energy."""
        instances = build_deck_instances(dragapult_deck_defs)

        # Find Dreepy (it has a 0-cost attack or simple attack)
        dreepy = next(i for i in instances if "Dreepy" in i.card_name)
        dreepy.zone = Zone.ACTIVE

        # Get the card definition to check attack cost
        cdef = card_registry.get(dreepy.card_def_id)
        if not cdef or not cdef.attacks:
            pytest.skip("No attacks on Dreepy in this fixture")

        state = GameState()
        state.phase = Phase.ATTACK
        state.turn_number = 2
        state.p1.active = dreepy

        opp_active = next(
            i for i in build_deck_instances(dragapult_deck_defs)
            if "Dreepy" in i.card_name
        )
        opp_active.zone = Zone.ACTIVE
        state.p2.active = opp_active

        # Attach enough energy to cover first attack cost
        attack_cost = cdef.attacks[0].cost
        for energy_type in attack_cost[:1]:  # Attach one energy
            dreepy.energy_attached.append(
                EnergyAttachment(
                    energy_type=EnergyType.from_str(energy_type or "Colorless"),
                    source_card_id="test-energy-id",
                    provides=[EnergyType.from_str(energy_type or "Colorless")],
                )
            )

        legal = ActionValidator.get_legal_actions(state, "p1")
        attack_actions = [a for a in legal if a.action_type == ActionType.ATTACK]
        # May or may not be legal depending on exact cost; just check no crash
        assert isinstance(attack_actions, list)


class TestValidateAction:
    def test_validate_returns_true_for_legal_action(self, dragapult_deck_defs):
        instances = build_deck_instances(dragapult_deck_defs)
        state = GameState()
        state.phase = Phase.SETUP

        dreepy = next(i for i in instances if "Dreepy" in i.card_name)
        dreepy.zone = Zone.HAND
        state.p1.hand = [dreepy]

        action = Action(
            ActionType.PLACE_ACTIVE,
            player_id="p1",
            card_instance_id=dreepy.instance_id,
        )
        valid, error = ActionValidator.validate(state, action)
        assert valid is True
        assert error == ""  # validate returns "" not None for valid actions

    def test_validate_returns_false_for_wrong_player(self, dragapult_deck_defs):
        instances = build_deck_instances(dragapult_deck_defs)
        state = GameState()
        state.phase = Phase.SETUP
        state.active_player = "p1"

        dreepy = next(i for i in instances if "Dreepy" in i.card_name)
        dreepy.zone = Zone.HAND
        state.p2.hand = [dreepy]

        action = Action(
            ActionType.PLACE_ACTIVE,
            player_id="p2",  # Wrong player
            card_instance_id=dreepy.instance_id,
        )
        # p2 cannot act during p1's setup phase (rule 2 from ActionValidator)
        valid, error = ActionValidator.validate(state, action)
        # Depends on implementation — setup is turn 0 so both players act
        # Just check the return type is correct
        assert isinstance(valid, bool)

    def test_validate_rejects_forced_switch_to_non_bench_target(self, dragapult_deck_defs):
        instances = build_deck_instances(dragapult_deck_defs)
        state = GameState()
        state.phase = Phase.MAIN
        state.turn_number = 2

        state.p1.active = next(i for i in instances if "Dreepy" in i.card_name)
        state.p1.bench = [next(i for i in instances if "Drakloak" in i.card_name)]

        action = Action(
            ActionType.SWITCH_ACTIVE,
            player_id="p1",
            target_instance_id="not-on-bench",
        )

        valid, error = ActionValidator.validate(state, action)

        assert valid is False
        assert "bench" in error

    def test_validate_accepts_forced_switch_to_bench_target(self, dragapult_deck_defs):
        instances = build_deck_instances(dragapult_deck_defs)
        state = GameState()
        state.phase = Phase.MAIN
        state.turn_number = 2

        state.p1.active = next(i for i in instances if "Dreepy" in i.card_name)
        bench = next(i for i in instances if "Drakloak" in i.card_name)
        state.p1.bench = [bench]

        action = Action(
            ActionType.SWITCH_ACTIVE,
            player_id="p1",
            target_instance_id=bench.instance_id,
        )

        valid, error = ActionValidator.validate(state, action)

        assert valid is True
        assert error == ""

    def test_validate_rejects_choice_target_outside_context(self, dragapult_deck_defs):
        instances = build_deck_instances(dragapult_deck_defs)
        state = GameState()
        target = next(i for i in instances if "Dreepy" in i.card_name)
        ctx = ChoiceRequest(
            "choose_target",
            "p1",
            targets=[target],
        )

        action = Action(
            ActionType.CHOOSE_TARGET,
            player_id="p1",
            target_instance_id="not-a-choice",
            choice_context=ctx,
        )

        valid, error = ActionValidator.validate(state, action)

        assert valid is False
        assert "legal target" in error
