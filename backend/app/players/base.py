"""PlayerInterface — abstract base class all player implementations must satisfy.

Both heuristic bots and AI agents implement this interface.
The runner calls choose_action() and choose_setup().

Phase 2: choose_action() now also handles CHOOSE_CARDS, CHOOSE_TARGET, and
CHOOSE_OPTION action types emitted by effect generators.  The Action object
carries a ``choice_context`` (ChoiceRequest) with full metadata.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Optional


def _parse_damage(damage_str: str) -> int:
    """Extract the base numeric damage from an AttackDef.damage string.

    Examples: "60" → 60, "60+" → 60, "30×" → 30, "" → 0.
    """
    m = re.search(r"\d+", damage_str or "")
    return int(m.group()) if m else 0


class PlayerInterface(ABC):
    """ABC for a Pokémon TCG player (human proxy, heuristic bot, or AI agent)."""

    @abstractmethod
    async def choose_action(self, state, legal_actions: list) -> "Action":  # noqa: F821
        """Return one action from `legal_actions`.

        Args:
            state: The current GameState (read-only from the player's perspective).
            legal_actions: Non-empty list of Action objects the engine deems legal.
                           May include CHOOSE_CARDS / CHOOSE_TARGET / CHOOSE_OPTION
                           actions when an effect handler needs a player decision.

        Returns:
            One of the actions from `legal_actions` (for CHOOSE_TARGET / CHOOSE_OPTION)
            or a new CHOOSE_CARDS Action with ``selected_cards`` populated from the
            available card IDs in ``legal_actions[0].selected_cards``.
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
        from app.engine.actions import ActionType, Action

        if not legal_actions:
            return None

        first = legal_actions[0]

        if first.action_type == ActionType.CHOOSE_CARDS:
            ctx = first.choice_context
            if ctx is None:
                return first
            available = first.selected_cards or []
            count = min(ctx.max_count, len(available))
            count = max(ctx.min_count, count)
            chosen = random.sample(available, count) if available else []
            return Action(ActionType.CHOOSE_CARDS, first.player_id,
                          selected_cards=chosen, choice_context=ctx)

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

    Priority order for normal actions:
      1. ATTACK if possible (in ATTACK phase)
      2. EVOLVE
      3. USE_ABILITY
      4. ATTACH_ENERGY
      5. PLAY_BASIC
      6. PLAY_SUPPORTER
      7. PLAY_ITEM
      8. PASS  (moves to ATTACK phase so #1 can fire next)
      9. END_TURN
      10. RETREAT (last resort — discards energy used for retreat cost)
      11. SWITCH_ACTIVE

    For CHOOSE_* actions (effect handler choices):
      CHOOSE_CARDS: heuristic based on prompt context
      CHOOSE_TARGET: pick highest-priority target
      CHOOSE_OPTION: pick option 0 (first / default)
    """

    from app.engine.actions import ActionType as _AT

    _PRIORITY = [
        "ATTACK",
        "EVOLVE",
        "USE_ABILITY",
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
        from app.engine.actions import ActionType, Action

        if not legal_actions:
            return None

        first = legal_actions[0]

        # ── Effect-driven choice actions ───────────────────────────────────────
        if first.action_type == ActionType.CHOOSE_CARDS:
            return self._choose_cards(state, first)
        if first.action_type == ActionType.CHOOSE_TARGET:
            return self._choose_target(state, legal_actions)
        if first.action_type == ActionType.CHOOSE_OPTION:
            return legal_actions[0]  # default: first/best option

        # ── Normal action priority ─────────────────────────────────────────────
        for preferred in self._PRIORITY:
            matching = [a for a in legal_actions if a.action_type.name == preferred]
            if not matching:
                continue
            if preferred == "ATTACH_ENERGY":
                return self._best_energy_target(state, matching)
            if preferred == "ATTACK":
                return self._best_attack(state, matching)
            if preferred == "PASS":
                # Before passing to ATTACK phase, check whether we'd have any
                # valid attack actions.  If not, retreat to a bench Pokémon
                # that can attack instead of wasting the turn.
                retreat = self._retreat_if_blocked(state, legal_actions)
                if retreat is not None:
                    return retreat
            return matching[0]
        return legal_actions[0]

    def _choose_cards(self, state, action):
        """Heuristic card selection for CHOOSE_CARDS effects."""
        from app.engine.actions import Action, ActionType
        from app.cards import registry as card_registry

        ctx = action.choice_context
        available_iids = list(action.selected_cards or [])

        if not ctx or not available_iids:
            return Action(ActionType.CHOOSE_CARDS, action.player_id,
                          selected_cards=[], choice_context=ctx)

        # Resolve card instances from available IDs
        player = state.get_player(ctx.player_id)
        all_cards = (
            player.hand + player.deck + player.discard
            + ([player.active] if player.active else [])
            + player.bench
        )
        id_to_card = {c.instance_id: c for c in all_cards}
        cards = [id_to_card[iid] for iid in available_iids if iid in id_to_card]

        prompt = (ctx.prompt or "").lower()
        is_search = "search" in prompt or "deck" in prompt
        is_discard = "discard" in prompt
        is_hand = "hand" in prompt

        count = min(ctx.max_count, len(cards))
        count = max(ctx.min_count, min(count, len(cards)))

        if is_search:
            # Searching: pick highest-priority cards
            chosen = self._search_priority(cards, count, state, ctx.player_id)
        elif is_discard or is_hand:
            # Discarding from hand: pick lowest-priority cards
            chosen = self._discard_priority(cards, count, state, ctx.player_id)
        else:
            # Default: pick first N
            chosen = [c.instance_id for c in cards[:count]]

        return Action(ActionType.CHOOSE_CARDS, action.player_id,
                      selected_cards=chosen, choice_context=ctx)

    def _choose_target(self, state, legal_actions):
        """Heuristic target selection for CHOOSE_TARGET effects."""
        if not legal_actions:
            return legal_actions[0]

        ctx = legal_actions[0].choice_context
        prompt = (ctx.prompt if ctx else "").lower()

        # Selecting an opponent target (Boss's Orders, Prime Catcher opp side, etc.)
        if "damage" in prompt or "opponent" in prompt or "opp" in prompt:
            best = min(
                legal_actions,
                key=lambda a: self._target_hp(state, a.target_instance_id),
                default=legal_actions[0],
            )
            return best

        # Self-switch (Prime Catcher, retreat choice, etc.): prefer bench Pokémon
        # with the most energy already attached so we don't lose attack tempo.
        if "switch in" in prompt or ("bench" in prompt and "opponent" not in prompt):
            best = max(
                legal_actions,
                key=lambda a: self._energy_count(state, a.target_instance_id),
                default=legal_actions[0],
            )
            return best

        # Default: first legal target
        return legal_actions[0]

    def _target_hp(self, state, instance_id: str) -> int:
        if not instance_id:
            return 9999
        for player in (state.p1, state.p2):
            for c in ([player.active] if player.active else []) + player.bench:
                if c.instance_id == instance_id:
                    return c.current_hp
        return 9999

    def _energy_count(self, state, instance_id: str) -> int:
        """Return the number of energy cards attached to the Pokémon with this id."""
        if not instance_id:
            return 0
        for player in (state.p1, state.p2):
            for c in ([player.active] if player.active else []) + player.bench:
                if c.instance_id == instance_id:
                    return len(c.energy_attached)
        return 0

    def _best_energy_target(self, state, actions):
        """Pick the ATTACH_ENERGY action that targets the highest-value Pokémon.

        Prefer the in-play Pokémon with the highest max attack damage that is
        furthest from having enough energy to use it.  This pushes energy
        toward the 'finisher' (e.g. Dragapult ex 190 dmg) instead of the
        weak active basic (Dreepy 10 dmg).  Pokémon whose attacks are
        currently blocked by a passive ability (e.g. Power Saver) are
        penalised so energy flows to bench attackers instead.

        Special case: if the active is "trapped" (can't retreat because it
        lacks energy AND has no legal attacks), prioritise attaching to the
        active so it can eventually retreat to a real attacker.
        """
        from app.cards import registry as card_registry
        from app.engine.actions import ActionValidator, _can_pay_retreat
        from app.engine.effects.abilities import power_saver_blocks_attack

        player_id = actions[0].player_id
        player = state.get_player(player_id)

        # Trapped-active check: if active can't retreat AND can't attack,
        # attach energy to active first so it can escape.
        if player and player.active:
            active = player.active
            active_cdef = card_registry.get(active.card_def_id)
            if active_cdef:
                retreat_cost = active_cdef.retreat_cost or 0
                can_retreat = _can_pay_retreat(active, retreat_cost, state, player_id)
                can_attack = bool(ActionValidator._get_attack_actions(state, player, player_id))
                if not can_retreat and not can_attack:
                    active_attach = next(
                        (a for a in actions if a.target_instance_id == active.instance_id),
                        None,
                    )
                    if active_attach:
                        return active_attach

        def target_score(action):
            for player in (state.p1, state.p2):
                for poke in ([player.active] if player.active else []) + player.bench:
                    if poke.instance_id == action.target_instance_id:
                        cdef = card_registry.get(poke.card_def_id)
                        if not cdef:
                            return (0, 0)
                        # Don't feed energy to a Pokémon whose attacks are blocked.
                        if power_saver_blocks_attack(state, poke, player_id):
                            return (-1, 0)
                        max_dmg = max(
                            (_parse_damage(atk.damage) for atk in cdef.attacks),
                            default=0,
                        )
                        # Energy still needed for best attack (lower = closer to ready)
                        best_cost = max(
                            (len(atk.cost) for atk in cdef.attacks if atk.cost),
                            default=1,
                        )
                        already = len(poke.energy_attached)
                        energy_needed = max(0, best_cost - already)
                        # Primary: highest damage. Secondary: most energy still needed
                        # (so we fill up the best attacker first, not one that's already set)
                        return (max_dmg, energy_needed)
            return (0, 0)

        return max(actions, key=target_score)

    def _retreat_if_blocked(self, state, legal_actions):
        """Return a RETREAT action if the active Pokémon cannot attack meaningfully
        and a benched Pokémon with energy can do better.

        'Cannot attack meaningfully' means either:
        - No legal attacks at all (energy missing, Power Saver, etc.)
        - Only 0-damage attacks are available (e.g. Come and Get You)
        """
        from app.engine.actions import ActionType, ActionValidator
        from app.engine.effects.abilities import power_saver_blocks_attack
        from app.cards import registry as card_registry

        retreat_actions = [a for a in legal_actions if a.action_type == ActionType.RETREAT]
        if not retreat_actions:
            return None

        player = state.get_player(retreat_actions[0].player_id)
        player_id = retreat_actions[0].player_id

        # Determine max damage the active Pokémon can deal in ATTACK phase.
        attack_actions = ActionValidator._get_attack_actions(state, player, player_id)
        active_best_dmg = 0
        if attack_actions and player.active:
            active_cdef = card_registry.get(player.active.card_def_id)
            if active_cdef and active_cdef.attacks:
                for atk_action in attack_actions:
                    idx = atk_action.attack_index or 0
                    if idx < len(active_cdef.attacks):
                        active_best_dmg = max(
                            active_best_dmg,
                            _parse_damage(active_cdef.attacks[idx].damage),
                        )
        if active_best_dmg > 0:
            return None  # Active can deal real damage — no retreat needed

        # Active is blocked or only has 0-damage attacks.  Find a better bench option.
        best_action = None
        best_score = -1
        for ret_action in retreat_actions:
            poke = next(
                (b for b in player.bench if b.instance_id == ret_action.target_instance_id),
                None,
            )
            if poke is None:
                continue
            cdef = card_registry.get(poke.card_def_id)
            if not cdef or not cdef.attacks:
                continue
            # Skip bench Pokémon whose attacks are blocked by a passive ability
            # (e.g. TR Mewtwo ex when Power Saver condition is not met).
            if power_saver_blocks_attack(state, poke, player_id):
                continue
            # Score: max attack damage of this bench Pokémon
            dmg = max((_parse_damage(atk.damage) for atk in cdef.attacks), default=0)
            energy_count = len(poke.energy_attached)
            # Only retreat to a bench Pokémon that has energy AND deals strictly
            # more damage than the current active's best available attack.
            if energy_count > 0 and dmg > active_best_dmg and dmg > best_score:
                best_score = dmg
                best_action = ret_action

        return best_action  # None if no better retreat target found

    def _best_attack(self, state, actions):
        """Pick the ATTACK action with the highest base damage."""
        from app.cards import registry as card_registry

        player = state.get_player(actions[0].player_id)
        if not player or not player.active:
            return actions[0]
        cdef = card_registry.get(player.active.card_def_id)
        if not cdef or not cdef.attacks:
            return actions[0]

        def attack_score(action):
            idx = action.attack_index or 0
            if idx < len(cdef.attacks):
                return _parse_damage(cdef.attacks[idx].damage)
            return 0

        return max(actions, key=attack_score)

    def _search_priority(self, cards, count, state, player_id):
        """Pick the most valuable cards when searching."""
        from app.cards import registry as card_registry

        def priority(c):
            ctype = c.card_type.lower()
            if ctype == "pokemon":
                cdef = card_registry.get(c.card_def_id)
                hp = cdef.hp if cdef else 0
                stage = c.evolution_stage
                return (0, -(stage * 100 + (hp or 0)))   # prefer high-stage, high-HP
            elif ctype == "energy":
                return (1, 0)
            elif ctype == "trainer":
                return (2, 0)
            return (3, 0)

        sorted_cards = sorted(cards, key=priority)
        return [c.instance_id for c in sorted_cards[:count]]

    def _discard_priority(self, cards, count, state, player_id):
        """Pick the least valuable cards when forced to discard."""
        from app.cards import registry as card_registry

        def discard_score(c):
            """Lower score = more willing to discard."""
            ctype = c.card_type.lower()
            if ctype == "energy":
                # Energy is precious — keep it to enable attacks. Only discard
                # as a last resort, never to power search cards like Ultra Ball.
                return 20
            elif ctype == "trainer":
                csub = c.card_subtype.lower()
                if csub == "item":
                    return 1  # discard duplicate/excess items first
                elif csub == "stadium":
                    return 2
                elif csub == "supporter":
                    return 3
            elif ctype == "pokemon":
                cdef = card_registry.get(c.card_def_id)
                hp = cdef.hp if cdef else 0
                return 10 + (hp or 0)  # prefer to keep high-HP Pokémon
            return 5

        sorted_cards = sorted(cards, key=discard_score)
        return [c.instance_id for c in sorted_cards[:count]]

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
