"""HeuristicPlayer — rule-based player for H/H simulation.

Implements the 8-step priority chain from PROJECT.md Appendix I.
Inherits shared helpers from BasePlayer (base.py).

Design philosophy: "average human" level play.  Reasonable decisions,
misses complex multi-turn setups.  Fast (no IO, no inference).

Priority chain (main phase):
  1. Emergency retreat   — low HP or paralysis with free retreat
  2. Draw/search abilities — thin the deck, find pieces
  3. Supporter play      — draw if hand ≤ 3; Boss if good gust target
  4. Evolution           — active attacker > bench attacker > support
  5. Energy attachment   — via inherited _best_energy_target
  6. Bench development   — prefer evolution bases over standalone basics
  7. Item play           — search items > tools on active > other
  8. Pass to attack      — PASS if can attack, else END_TURN
"""

from __future__ import annotations

from typing import Optional

from app.players.base import BasePlayer, _parse_damage


# ── Card-name classification sets (extend as new cards are added) ─────────────

_DRAW_SUPPORTER_NAMES: frozenset[str] = frozenset({
    "Professor's Research",
    "Iono",
    "Colress's Experiment",
    "Morty's Conviction",
    "Eri",
    "Janine's Secret Art",
    "N",
    "Cynthia",
    "Cheren",
    "Lillie",
})

_GUST_SUPPORTER_NAMES: frozenset[str] = frozenset({
    "Boss's Orders",
    "Gust of Wind",
    "Giovanni's Charisma",
})

# Abilities that draw or search — Priority 2 uses these.
_DRAW_ABILITY_NAMES: frozenset[str] = frozenset({
    "Quick Search",     # Pidgeot ex
    "Luminous Sign",    # Lumineon V
    "Stellar Veil",
    "Trade",            # Inteleon
    "Order Pad",        # Bibarel
})

# Item names that search the deck for Pokémon or cards.
_SEARCH_ITEM_NAMES: frozenset[str] = frozenset({
    "Ultra Ball",
    "Nest Ball",
    "Quick Ball",
    "Buddy-Buddy Poffin",
    "Bug Catching Set",
    "Poké Ball",
    "Great Ball",
    "Secret Box",
    "Hisuian Heavy Ball",
    "Wishful Baton",
})


class HeuristicPlayer(BasePlayer):
    """Rule-based player for H/H simulation (Phase 3+).

    Inherits CHOOSE_* handlers, energy/attack helpers, and choose_setup
    from BasePlayer.  Overrides choose_action with the full Appendix I
    priority chain.
    """

    # ── Public interface ───────────────────────────────────────────────────────

    async def choose_action(self, state, legal_actions: list):
        from app.engine.actions import ActionType

        if not legal_actions:
            return None

        first = legal_actions[0]

        # ── Effect-driven interrupts (delegate to BasePlayer helpers) ──────────
        if first.action_type == ActionType.CHOOSE_CARDS:
            return self._choose_cards(state, first)
        if first.action_type == ActionType.CHOOSE_TARGET:
            return self._choose_target(state, legal_actions)
        if first.action_type == ActionType.CHOOSE_OPTION:
            return legal_actions[0]
        if first.action_type == ActionType.DISCARD_ENERGY:
            return legal_actions[0]
        if first.action_type == ActionType.SWITCH_ACTIVE:
            return self._choose_target(state, legal_actions)

        # ── Attack phase ────────────────────────────────────────────────────────
        if any(a.action_type == ActionType.ATTACK for a in legal_actions):
            return self._heuristic_attack(state, legal_actions)

        # ── Main phase: 8-step priority chain ──────────────────────────────────
        for step in (
            self._p1_emergency,
            self._p2_draw_abilities,
            self._p3_supporter,
            self._p4_evolve,
            self._p5_energy,
            self._p6_bench,
            self._p7_items,
            self._p8_pass,
        ):
            action = step(state, legal_actions)
            if action is not None:
                return action

        return legal_actions[0]

    # ── Priority 1 — Emergency retreat ────────────────────────────────────────

    def _p1_emergency(self, state, legal_actions) -> Optional[object]:
        """Retreat when active is critically low HP or paralyzed at zero cost."""
        from app.engine.actions import ActionType
        from app.engine.state import StatusCondition
        from app.cards import registry as card_registry

        retreat_actions = [a for a in legal_actions if a.action_type == ActionType.RETREAT]
        if not retreat_actions:
            return None

        player = state.get_player(retreat_actions[0].player_id)
        if not player or not player.active or not player.bench:
            return None

        active = player.active
        should_retreat = False

        if active.current_hp <= 30:
            should_retreat = True

        if not should_retreat:
            cdef = card_registry.get(active.card_def_id)
            is_paralyzed = StatusCondition.PARALYZED in (active.status_conditions or set())
            free_retreat = cdef and (cdef.retreat_cost or 0) == 0
            if is_paralyzed and free_retreat:
                should_retreat = True

        if should_retreat:
            return max(
                retreat_actions,
                key=lambda a: self._energy_count(state, a.target_instance_id),
            )
        return None

    # ── Priority 2 — Draw/search abilities ────────────────────────────────────

    def _p2_draw_abilities(self, state, legal_actions) -> Optional[object]:
        """Use a draw/search ability before anything else."""
        from app.engine.actions import ActionType
        from app.cards import registry as card_registry

        ability_actions = [a for a in legal_actions if a.action_type == ActionType.USE_ABILITY]
        for action in ability_actions:
            if not action.card_instance_id:
                continue
            player = state.get_player(action.player_id)
            all_poke = ([player.active] if player.active else []) + player.bench
            poke = next((p for p in all_poke if p.instance_id == action.card_instance_id), None)
            if not poke:
                continue
            cdef = card_registry.get(poke.card_def_id)
            if not cdef or not cdef.abilities:
                continue
            for ability in cdef.abilities:
                if ability.name in _DRAW_ABILITY_NAMES:
                    return action
        return None

    # ── Priority 3 — Supporter play ───────────────────────────────────────────

    def _p3_supporter(self, state, legal_actions) -> Optional[object]:
        """Play draw Supporter if hand ≤ 3; play Boss if good gust target exists."""
        from app.engine.actions import ActionType

        supporter_actions = [
            a for a in legal_actions if a.action_type == ActionType.PLAY_SUPPORTER
        ]
        if not supporter_actions:
            return None

        player_id = supporter_actions[0].player_id
        player = state.get_player(player_id)
        opponent = state.get_opponent(player_id)

        gust_actions: list = []
        draw_actions: list = []

        for action in supporter_actions:
            card = next(
                (c for c in player.hand if c.instance_id == action.card_instance_id), None
            )
            if not card:
                continue
            if card.card_name in _GUST_SUPPORTER_NAMES:
                gust_actions.append(action)
            elif card.card_name in _DRAW_SUPPORTER_NAMES:
                draw_actions.append(action)

        # Boss's Orders: gust a low-HP bench target if available
        if gust_actions and opponent and opponent.bench:
            min_hp = min(
                (p.current_hp for p in opponent.bench if p.current_hp > 0),
                default=9999,
            )
            if min_hp <= 100:
                return gust_actions[0]

        # Draw Supporter: only if hand is thin
        if draw_actions and len(player.hand) <= 3:
            # Prefer Professor's Research (full redraw) over others
            for action in draw_actions:
                card = next(
                    (c for c in player.hand if c.instance_id == action.card_instance_id), None
                )
                if card and card.card_name == "Professor's Research":
                    return action
            return draw_actions[0]

        return None

    # ── Priority 4 — Evolution ────────────────────────────────────────────────

    def _p4_evolve(self, state, legal_actions) -> Optional[object]:
        """Evolve: active attacker > bench attacker > support Pokémon."""
        from app.engine.actions import ActionType
        from app.cards import registry as card_registry

        evolve_actions = [a for a in legal_actions if a.action_type == ActionType.EVOLVE]
        if not evolve_actions:
            return None

        player_id = evolve_actions[0].player_id
        player = state.get_player(player_id)
        active_iid = player.active.instance_id if player.active else None

        def evolve_score(action) -> tuple:
            # action.card_instance_id  = evolution card in hand
            # action.target_instance_id = Pokémon on board being evolved
            is_active = action.target_instance_id == active_iid
            evo_card = next(
                (c for c in player.hand if c.instance_id == action.card_instance_id), None
            )
            if evo_card:
                cdef = card_registry.get(evo_card.card_def_id)
                hp = cdef.hp or 0 if cdef else 0
                stage = evo_card.evolution_stage
            else:
                hp = 0
                stage = 0
            # Prefer active, then higher stage, then higher HP
            return (int(is_active), stage, hp)

        return max(evolve_actions, key=evolve_score)

    # ── Priority 5 — Energy attachment ────────────────────────────────────────

    def _p5_energy(self, state, legal_actions) -> Optional[object]:
        from app.engine.actions import ActionType

        energy_actions = [a for a in legal_actions if a.action_type == ActionType.ATTACH_ENERGY]
        if not energy_actions:
            return None
        return self._best_energy_target(state, energy_actions)

    # ── Priority 6 — Bench development ───────────────────────────────────────

    def _p6_bench(self, state, legal_actions) -> Optional[object]:
        """Play a Basic to bench; prefer evolution bases over standalone basics."""
        from app.engine.actions import ActionType
        from app.cards import registry as card_registry

        bench_actions = [a for a in legal_actions if a.action_type == ActionType.PLAY_BASIC]
        if not bench_actions:
            return None

        player = state.get_player(bench_actions[0].player_id)

        def bench_score(action) -> int:
            card = next(
                (c for c in player.hand if c.instance_id == action.card_instance_id), None
            )
            if not card:
                return 0
            cdef = card_registry.get(card.card_def_id)
            return cdef.hp or 0 if cdef else 0

        return max(bench_actions, key=bench_score)

    # ── Priority 7 — Item play ────────────────────────────────────────────────

    def _p7_items(self, state, legal_actions) -> Optional[object]:
        """Items: search items first, then tools on active, then others."""
        from app.engine.actions import ActionType

        item_actions = [
            a for a in legal_actions
            if a.action_type in (ActionType.PLAY_ITEM, ActionType.PLAY_TOOL,
                                  ActionType.PLAY_STADIUM)
        ]
        if not item_actions:
            return None

        player = state.get_player(item_actions[0].player_id)
        active_iid = player.active.instance_id if player.active else None

        # 1. Search items
        for action in item_actions:
            if action.action_type != ActionType.PLAY_ITEM:
                continue
            card = next(
                (c for c in player.hand if c.instance_id == action.card_instance_id), None
            )
            if card and card.card_name in _SEARCH_ITEM_NAMES:
                return action

        # 2. Tools on the active Pokémon
        for action in item_actions:
            if action.action_type == ActionType.PLAY_TOOL:
                if action.target_instance_id == active_iid:
                    return action

        # 3. Any remaining item
        return item_actions[0]

    # ── Priority 8 — Pass to attack phase ────────────────────────────────────

    def _p8_pass(self, state, legal_actions) -> Optional[object]:
        """PASS to attack phase if worthwhile; END_TURN if blocked."""
        from app.engine.actions import ActionType

        # Retreat if active is stuck and a better option is on bench
        retreat = self._retreat_if_blocked(state, legal_actions)
        if retreat is not None:
            return retreat

        pass_action = self._find_action(legal_actions, ActionType.PASS)
        if pass_action:
            return pass_action

        return self._find_action(legal_actions, ActionType.END_TURN)

    # ── Attack phase ──────────────────────────────────────────────────────────

    def _heuristic_attack(self, state, legal_actions) -> object:
        """KO the opponent's active if possible; otherwise deal maximum damage."""
        from app.engine.actions import ActionType
        from app.cards import registry as card_registry

        attack_actions = [a for a in legal_actions if a.action_type == ActionType.ATTACK]
        if not attack_actions:
            return self._find_action(legal_actions, ActionType.END_TURN) or legal_actions[0]

        player_id = attack_actions[0].player_id
        player = state.get_player(player_id)
        opponent = state.get_opponent(player_id)

        if not player or not player.active or not opponent or not opponent.active:
            return self._best_attack(state, attack_actions)

        cdef = card_registry.get(player.active.card_def_id)
        opp_hp = opponent.active.current_hp

        ko_actions = []
        for action in attack_actions:
            idx = action.attack_index or 0
            if cdef and idx < len(cdef.attacks):
                dmg = _parse_damage(cdef.attacks[idx].damage)
                if dmg >= opp_hp:
                    ko_actions.append(action)

        if ko_actions:
            # Among KO moves, prefer the cheapest energy cost
            def energy_cost(action) -> int:
                idx = action.attack_index or 0
                if cdef and idx < len(cdef.attacks):
                    return len(cdef.attacks[idx].cost or [])
                return 99

            return min(ko_actions, key=energy_cost)

        return self._best_attack(state, attack_actions)
