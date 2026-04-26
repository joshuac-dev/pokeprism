"""PlayerInterface — abstract base class all player implementations must satisfy.

Both heuristic bots and AI agents implement this interface.
The runner only calls choose_action() and choose_setup().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class PlayerInterface(ABC):
    """ABC for a Pokémon TCG player (human proxy, heuristic bot, or AI agent)."""

    @abstractmethod
    async def choose_action(self, state, legal_actions: list) -> "Action":  # noqa: F821
        """Return one action from `legal_actions`.

        Args:
            state: The current GameState (read-only from the player's perspective).
            legal_actions: Non-empty list of Action objects the engine deems legal.

        Returns:
            One of the actions from `legal_actions`.
        """

    @abstractmethod
    async def choose_setup(self, state, hand: list) -> tuple[str, list[str]]:
        """Return (active_instance_id, [bench_instance_ids]) for setup.

        Args:
            state: The current GameState (setup phase).
            hand: The player's current hand as a list of CardInstance objects.

        Returns:
            Tuple of (active card instance_id, list of bench card instance_ids).
            Bench list may be empty but must not exceed MAX_BENCH_SIZE.
        """


class RandomPlayer(PlayerInterface):
    """Simple random player — picks uniformly at random from legal actions.

    Used as a baseline and in Phase 1 integration tests.
    """

    import random as _random

    async def choose_action(self, state, legal_actions: list):
        import random
        return random.choice(legal_actions)

    async def choose_setup(self, state, hand: list) -> tuple[str, list[str]]:
        """Place first basic found as active; put all other basics on bench."""
        from app.cards import registry as card_registry

        basics = [
            c for c in hand
            if card_registry.get(c.card_def_id) and
               card_registry.get(c.card_def_id).is_pokemon and
               card_registry.get(c.card_def_id).stage.lower() == "basic"
        ]
        if not basics:
            # Fallback: just use the first card (shouldn't happen after mulligan)
            basics = [hand[0]] if hand else []

        import random
        random.shuffle(basics)
        active_id = basics[0].instance_id
        bench_ids = [b.instance_id for b in basics[1:5]]  # max 5 bench slots
        return active_id, bench_ids


class GreedyPlayer(PlayerInterface):
    """Greedy heuristic player — used as the stronger baseline in Phase 1 tests.

    Priority order:
      1. ATTACK if possible (in ATTACK phase)
      2. EVOLVE
      3. ATTACH_ENERGY
      4. PLAY_BASIC
      5. PLAY_SUPPORTER
      6. PLAY_ITEM
      7. PASS  (moves to ATTACK phase so #1 can fire next)
      8. END_TURN
      9. RETREAT (last resort — discards energy used for retreat cost)
      10. SWITCH_ACTIVE
    """

    from app.engine.actions import ActionType as _AT

    _PRIORITY = [
        "ATTACK",
        "EVOLVE",
        "ATTACH_ENERGY",
        "PLAY_BASIC",
        "PLAY_SUPPORTER",
        "PLAY_ITEM",
        "PASS",
        "END_TURN",
        "RETREAT",
        "SWITCH_ACTIVE",
    ]

    async def choose_action(self, state, legal_actions: list):
        for preferred in self._PRIORITY:
            for action in legal_actions:
                if action.action_type.name == preferred:
                    return action
        return legal_actions[0]

    async def choose_setup(self, state, hand: list) -> tuple[str, list[str]]:
        from app.cards import registry as card_registry

        basics = [
            c for c in hand
            if card_registry.get(c.card_def_id) and
               card_registry.get(c.card_def_id).is_pokemon and
               card_registry.get(c.card_def_id).stage.lower() == "basic"
        ]
        if not basics:
            basics = [hand[0]] if hand else []

        # Prefer highest-HP basic as active
        def hp_of(c):
            cdef = card_registry.get(c.card_def_id)
            return cdef.hp or 0 if cdef else 0

        basics.sort(key=hp_of, reverse=True)
        active_id = basics[0].instance_id
        bench_ids = [b.instance_id for b in basics[1:5]]
        return active_id, bench_ids
