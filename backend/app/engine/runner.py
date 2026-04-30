"""MatchRunner — orchestrates a single game between two PlayerInterface instances.

Follows §6.5 and Appendix A of PROJECT.md.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from typing import Callable, Optional

from app.engine.state import (
    CardInstance,
    EnergyType,
    GameState,
    Phase,
    PlayerState,
    StatusCondition,
    Zone,
)
from app.engine.actions import Action, ActionType, ActionValidator
from app.engine.transitions import StateTransition, TRANSITION_MAP
from app.engine.rules import RuleEngine
from app.cards import registry as card_registry
from app.cards.models import CardDefinition
import app.engine.effects  # noqa: F401 — registers all effect handlers

logger = logging.getLogger(__name__)

PRIZE_COUNT = 6
MAX_BENCH_SIZE = 5


# ──────────────────────────────────────────────────────────────────────────────
# MatchResult
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class MatchResult:
    game_id: str
    winner: str                 # "p1" or "p2"
    win_condition: str          # "prizes", "deck_out", "no_bench", "turn_limit"
    total_turns: int
    p1_prizes_taken: int
    p2_prizes_taken: int
    events: list[dict]
    p1_deck_name: str = ""
    p2_deck_name: str = ""


# ──────────────────────────────────────────────────────────────────────────────
# Deck builder helper — converts CardDefinition list → CardInstance list
# ──────────────────────────────────────────────────────────────────────────────

def build_deck_instances(card_defs: list[CardDefinition]) -> list[CardInstance]:
    """Create a fresh set of CardInstance objects from CardDefinition objects.

    Each call produces a new list with new instance_ids so two players can
    use the same definition list independently.
    """
    instances: list[CardInstance] = []
    for cdef in card_defs:
        stage_map = {
            "basic": 0,
            "stage 1": 1, "stage1": 1,
            "stage 2": 2, "stage2": 2, "mega": 2,
        }
        evolution_stage = stage_map.get(cdef.stage.lower(), 0)

        inst = CardInstance(
            card_def_id=cdef.tcgdex_id,
            card_name=cdef.name,
            card_type=cdef.category,
            card_subtype=cdef.subcategory,
            evolution_stage=evolution_stage,
            energy_provides=list(cdef.energy_provides),
        )
        if cdef.is_pokemon:
            inst.max_hp = cdef.hp or 0
            inst.current_hp = inst.max_hp

        instances.append(inst)
    return instances


# ──────────────────────────────────────────────────────────────────────────────
# MatchRunner
# ──────────────────────────────────────────────────────────────────────────────

class MatchRunner:
    """Orchestrates a single game between two players.

    Players must implement PlayerInterface (see players/base.py).
    The runner does NOT know whether players are heuristic or AI.
    """

    def __init__(
        self,
        p1_player,
        p2_player,
        p1_deck: list[CardDefinition],
        p2_deck: list[CardDefinition],
        p1_deck_name: str = "p1_deck",
        p2_deck_name: str = "p2_deck",
        event_callback: Optional[Callable[[dict], None]] = None,
        max_turns: int = 200,
        rng_seed: Optional[int] = None,
    ) -> None:
        self.p1_player = p1_player
        self.p2_player = p2_player
        self.p1_deck = p1_deck
        self.p2_deck = p2_deck
        self.p1_deck_name = p1_deck_name
        self.p2_deck_name = p2_deck_name
        self.event_callback = event_callback
        self.max_turns = max_turns
        self._rng = random.Random(rng_seed)

    async def run(self) -> MatchResult:
        """Run the game to completion and return a MatchResult."""
        state = self._initialize_game()

        # ── Setup phase ────────────────────────────────────────────────────────
        state = await self._run_setup(state)
        if state.phase == Phase.GAME_OVER:
            return self._build_result(state)
        # ── Main game loop ─────────────────────────────────────────────────────
        while state.phase != Phase.GAME_OVER and state.turn_number < self.max_turns:
            state = await self._run_turn(state)

        if state.phase != Phase.GAME_OVER:
            # Safety valve: turn limit reached
            state.winner = "p1"  # Arbitrary; shouldn't happen in real games
            state.win_condition = "turn_limit"
            state.phase = Phase.GAME_OVER
            state.emit_event("game_over", winner="p1", condition="turn_limit")
            self._emit(state.events[-1])

        return self._build_result(state)

    # ── Setup ──────────────────────────────────────────────────────────────────

    def _initialize_game(self) -> GameState:
        state = GameState()

        p1_instances = build_deck_instances(self.p1_deck)
        p2_instances = build_deck_instances(self.p2_deck)

        # Shuffle decks
        self._rng.shuffle(p1_instances)
        self._rng.shuffle(p2_instances)

        for c in p1_instances:
            c.zone = Zone.DECK
        for c in p2_instances:
            c.zone = Zone.DECK

        state.p1.deck = p1_instances
        state.p2.deck = p2_instances

        state.emit_event("game_start", p1_deck=self.p1_deck_name, p2_deck=self.p2_deck_name)
        self._emit(state.events[-1])
        return state

    def _get_player(self, player_id: str):
        """Return the player object for a given player_id."""
        return self.p1_player if player_id == "p1" else self.p2_player

    async def _run_setup(self, state: GameState) -> GameState:
        """Draw opening hands, handle mulligans, place basics, set prizes."""
        # Draw 7 for each player
        for pid in ("p1", "p2"):
            self._draw_cards(state, pid, 7)

        # Coin flip for first player
        first = self._rng.choice(("p1", "p2"))
        state.first_player = first
        state.active_player = first
        state.emit_event("coin_flip", first_player=first)

        # Handle mulligans (up to 10 iterations to avoid infinite loops)
        for _ in range(10):
            mulligans_needed = []
            for pid in ("p1", "p2"):
                player = state.get_player(pid)
                if not RuleEngine.deck_has_basic(player.hand):
                    mulligans_needed.append(pid)

            if not mulligans_needed:
                break

            for pid in mulligans_needed:
                action = Action(ActionType.MULLIGAN_REDRAW, pid)
                prev_len = len(state.events)
                await StateTransition.apply(state, action, self._get_player)
                self._emit_since(state, prev_len)

        # Both players choose their active and bench
        for pid in ("p1", "p2"):
            player = state.get_player(pid)
            cur_player = self.p1_player if pid == "p1" else self.p2_player
            active_id, bench_ids = await cur_player.choose_setup(state, player.hand)

            action = Action(ActionType.PLACE_ACTIVE, pid, card_instance_id=active_id)
            prev_len = len(state.events)
            await StateTransition.apply(state, action, self._get_player)
            self._emit_since(state, prev_len)

            for bid in bench_ids[:MAX_BENCH_SIZE - 1]:
                action = Action(ActionType.PLACE_BENCH, pid, card_instance_id=bid)
                prev_len = len(state.events)
                await StateTransition.apply(state, action, self._get_player)
                self._emit_since(state, prev_len)

        # Set 6 prize cards for each player
        for pid in ("p1", "p2"):
            player = state.get_player(pid)
            for _ in range(PRIZE_COUNT):
                if player.deck:
                    prize = player.deck.pop(0)
                    prize.zone = Zone.PRIZES
                    player.prizes.append(prize)
            player.prizes_remaining = len(player.prizes)
            state.emit_event("prizes_set", player=pid, count=len(player.prizes))
            self._emit(state.events[-1])

        state.phase = Phase.DRAW
        state.turn_number = 1
        return state

    # ── Turn structure (Appendix A) ────────────────────────────────────────────

    async def _run_turn(self, state: GameState) -> GameState:
        pid = state.active_player
        player_obj = self.p1_player if pid == "p1" else self.p2_player

        # ── DRAW ──────────────────────────────────────────────────────────────
        state.phase = Phase.DRAW
        drawn = self._draw_cards(state, pid, 1)
        if drawn == 0:
            # Cannot draw → opponent wins (deck out)
            opp = state.opponent_id(pid)
            state.winner = opp
            state.win_condition = "deck_out"
            state.phase = Phase.GAME_OVER
            state.emit_event("game_over", winner=opp, condition="deck_out")
            self._emit(state.events[-1])
            return state

        if state.phase == Phase.GAME_OVER:
            return state

        # ── MAIN PHASE ────────────────────────────────────────────────────────
        state.phase = Phase.MAIN
        max_actions = 200  # Safety valve to prevent infinite main-phase loops
        actions_taken = 0

        while state.phase == Phase.MAIN and actions_taken < max_actions:
            legal = ActionValidator.get_legal_actions(state, pid)
            if not legal:
                state.phase = Phase.ATTACK
                break

            action = await player_obj.choose_action(state, legal)
            is_valid, error = ActionValidator.validate(state, action)
            if not is_valid:
                state.emit_event("invalid_action", player=pid, error=error)
                self._emit(state.events[-1])
                # Skip invalid action rather than infinite-looping
                actions_taken += 1
                continue

            prev_len = len(state.events)
            state = await StateTransition.apply(state, action, self._get_player)
            self._emit_since(state, prev_len)

            if state.force_end_turn:
                state.force_end_turn = False
                state = self._end_turn(state)
                return state

            if action.action_type == ActionType.PASS:
                break  # Phase was set to ATTACK by the _pass handler
            elif action.action_type == ActionType.END_TURN:
                state = self._end_turn(state)
                return state

            if state.phase == Phase.GAME_OVER:
                return state

            actions_taken += 1

        # ── ATTACK PHASE ──────────────────────────────────────────────────────
        if state.phase == Phase.ATTACK:
            legal = ActionValidator.get_legal_actions(state, pid)
            if legal:
                action = await player_obj.choose_action(state, legal)
                is_valid, error = ActionValidator.validate(state, action)
                if not is_valid:
                    state.emit_event("invalid_action_attack", player=pid, error=error)
                else:
                    prev_len = len(state.events)
                    state = await StateTransition.apply(state, action, self._get_player)
                    self._emit_since(state, prev_len)

                    # Handle forced switch if KO occurred
                    state = await self._resolve_ko_aftermath(state)

                    if state.phase == Phase.GAME_OVER:
                        return state

        # ── BETWEEN TURNS ─────────────────────────────────────────────────────
        state = self._handle_between_turns(state)
        if state.phase == Phase.GAME_OVER:
            return state

        state = self._end_turn(state)
        return state

    async def _resolve_ko_aftermath(self, state: GameState) -> GameState:
        """If the defending active was KO'd, prompt them to promote a bench Pokémon."""
        for pid in ("p1", "p2"):
            player = state.get_player(pid)
            if player.active is None and player.bench:
                player_obj = self.p1_player if pid == "p1" else self.p2_player
                # Prompt for a switch
                legal = [
                    Action(ActionType.SWITCH_ACTIVE, pid,
                           target_instance_id=b.instance_id)
                    for b in player.bench
                ]
                action = await player_obj.choose_action(state, legal)
                prev_len = len(state.events)
                state = await StateTransition.apply(state, action, self._get_player)
                self._emit_since(state, prev_len)
        return state

    def _handle_between_turns(self, state: GameState) -> GameState:
        """Apply status conditions (Appendix A §Between Turns)."""
        for pid in ("p1", "p2"):
            player = state.get_player(pid)
            active = player.active
            if not active:
                continue

            if StatusCondition.TOXIC in active.status_conditions:
                active.current_hp -= 30
                active.damage_counters += 3
                state.emit_event("toxic_damage", player=pid, card=active.card_name)
                from app.engine.effects.base import check_ko
                check_ko(state, active, pid)
                if state.phase == Phase.GAME_OVER:
                    return state
            elif StatusCondition.POISONED in active.status_conditions:
                poison_damage = 10
                opp_active = state.get_opponent(pid).active
                # Tainted Horn (sv10-119 TR Nidoking ex): heavy_poison flag → 80 damage/turn
                if active.heavy_poison:
                    poison_damage = 80
                elif active.double_poison:
                    poison_damage = 20
                # Toxic Subjugation (Pecharunt svp-149): +50 poison damage while in opponent's Active
                elif opp_active and opp_active.card_def_id == "svp-149":
                    poison_damage += 50
                active.current_hp -= poison_damage
                active.damage_counters += poison_damage // 10
                state.emit_event("poison_damage", player=pid, card=active.card_name)
                from app.engine.effects.base import check_ko
                check_ko(state, active, pid)
                if state.phase == Phase.GAME_OVER:
                    return state

            if StatusCondition.BURNED in active.status_conditions:
                # Magma Surge (sv09-021 Magmortar): +3 more counters on opponent's burned Pokémon
                _magma_opp = state.get_opponent(pid)
                _magma_surge = any(p.card_def_id == "sv09-021"
                                   for p in (([_magma_opp.active] if _magma_opp.active else [])
                                             + list(_magma_opp.bench)))
                flip = self._rng.choice([True, False])
                if flip:  # Heads: take 2 damage counters (standard burn)
                    active.current_hp -= 20
                    active.damage_counters += 2
                    state.emit_event("burn_damage", player=pid, card=active.card_name)
                    from app.engine.effects.base import check_ko
                    check_ko(state, active, pid)
                    if state.phase == Phase.GAME_OVER:
                        return state
                if _magma_surge:  # Extra 3 counters whether or not heads
                    active.current_hp -= 30
                    active.damage_counters += 3
                    state.emit_event("magma_surge_triggered", player=pid, card=active.card_name)
                    from app.engine.effects.base import check_ko
                    check_ko(state, active, pid)
                    if state.phase == Phase.GAME_OVER:
                        return state

            if StatusCondition.ASLEEP in active.status_conditions:
                flip = self._rng.choice([True, False])
                if flip:  # Heads: wake up
                    active.status_conditions.remove(StatusCondition.ASLEEP)
                    state.emit_event("woke_up", player=pid, card=active.card_name)

            if StatusCondition.PARALYZED in active.status_conditions:
                active.status_conditions.remove(StatusCondition.PARALYZED)
                state.emit_event("paralysis_removed", player=pid, card=active.card_name)

        # Freezing Shroud (sv06-053 Froslass): place 1 damage counter on each
        # Pokémon with an Ability (except Froslass itself) during Pokémon Checkup.
        from app.engine.effects.abilities import apply_froslass_shroud
        apply_froslass_shroud(state)
        if state.phase == Phase.GAME_OVER:
            return state

        return state

    def _end_turn(self, state: GameState) -> GameState:
        """Reset per-turn flags and advance to next player."""
        for pid in ("p1", "p2"):
            player = state.get_player(pid)
            player.supporter_played_this_turn = False
            player.energy_attached_this_turn = False
            player.retreat_used_this_turn = False
            player.tr_supporter_played_this_turn = False
            player.items_locked_this_turn = False
            player.tarragon_played_this_turn = False
            if player.active:
                player.active.retreated_this_turn = False
                player.active.ability_used_this_turn = False
                # Reset multi-turn restriction flags
                player.active.cant_attack_next_turn = False
                player.active.cant_retreat_next_turn = False
                player.active.attack_damage_reduction = 0
                player.active.incoming_damage_reduction = 0
                player.active.prevent_damage_one_turn = False
                player.active.resolute_heart_eligible = False
                player.active.moved_from_bench_this_turn = False
                player.active.evolved_this_turn = False
                player.active.prevent_damage_from_basic_noncolorless = False
                player.active.locked_attack_index = None
                player.active.prevent_damage_from_basic = False
                player.active.prevent_damage_threshold = 0
                player.active.no_weakness_one_turn = False
                player.active.attack_requires_flip = False
                player.active.torment_blocked_attack_name = None
                player.active.retaliation_on_damage = False
                # Discard energy cards flagged for end-of-turn removal (Ignition Energy)
                self._discard_expiring_energy(state, player.active)
            for b in player.bench:
                b.ability_used_this_turn = False
                b.attack_damage_reduction = 0
                b.incoming_damage_reduction = 0
                b.prevent_damage_one_turn = False
                b.resolute_heart_eligible = False
                b.moved_from_bench_this_turn = False
                b.evolved_this_turn = False
                b.prevent_damage_from_basic_noncolorless = False
                b.locked_attack_index = None
                b.prevent_damage_from_basic = False
                b.prevent_damage_threshold = 0
                b.no_weakness_one_turn = False
                b.attack_requires_flip = False
                b.torment_blocked_attack_name = None
                b.retaliation_on_damage = False
                self._discard_expiring_energy(state, b)

        state.active_player_damage_bonus = 0
        state.active_player_damage_bonus_vs_ex = 0
        state.briar_active = False
        state.sunny_day_active = False
        state.force_end_turn = False
        # Clear Retaliate window for the player whose turn just ended
        state.get_player(state.active_player).ko_taken_last_turn = False
        state.active_player = state.opponent_id(state.active_player)
        state.turn_number += 1
        state.phase = Phase.DRAW
        state.emit_event("turn_start", player=state.active_player, turn=state.turn_number)

        # Clear Acerola's Mischief protection for the newly-active player's Pokémon
        # (Protection was "during your opponent's next turn" = the turn that just ended)
        new_active = state.get_player(state.active_player)
        for poke in ([new_active.active] if new_active.active else []) + new_active.bench:
            poke.protected_from_ex = False

        return state

    def _discard_expiring_energy(self, state: GameState, pokemon: "CardInstance") -> None:
        """Remove EnergyAttachments flagged discard_at_end_of_turn (Ignition Energy)."""
        to_remove = [att for att in pokemon.energy_attached if att.discard_at_end_of_turn]
        for att in to_remove:
            pokemon.energy_attached.remove(att)
            state.emit_event(
                "energy_discarded",
                card_def_id=att.card_def_id,
                pokemon=pokemon.card_name,
                reason="ignition_energy_expiry",
            )

    # ── Utilities ──────────────────────────────────────────────────────────────

    def _draw_cards(self, state: GameState, pid: str, count: int) -> int:
        player = state.get_player(pid)
        drawn = 0
        for _ in range(count):
            if not player.deck:
                break
            card = player.deck.pop(0)
            card.zone = Zone.HAND
            player.hand.append(card)
            drawn += 1
        if drawn > 0:
            state.emit_event("draw", player=pid, count=drawn,
                             hand_size=len(player.hand))
        return drawn

    def _emit(self, event: dict) -> None:
        if self.event_callback:
            self.event_callback(event)

    def _emit_since(self, state: GameState, prev_len: int) -> None:
        """Emit all events appended to state.events since prev_len."""
        for e in state.events[prev_len:]:
            self._emit(e)

    def _build_result(self, state: GameState) -> MatchResult:
        p1_taken = PRIZE_COUNT - state.p1.prizes_remaining
        p2_taken = PRIZE_COUNT - state.p2.prizes_remaining
        return MatchResult(
            game_id=state.game_id,
            winner=state.winner or "unknown",
            win_condition=state.win_condition or "unknown",
            total_turns=state.turn_number,
            p1_prizes_taken=p1_taken,
            p2_prizes_taken=p2_taken,
            events=list(state.events),
            p1_deck_name=self.p1_deck_name,
            p2_deck_name=self.p2_deck_name,
        )
