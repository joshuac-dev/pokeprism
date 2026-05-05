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

def _find_deferred_target(player, instance_id):
    """Find a Pokémon by instance_id among active/bench for deferred effect targeting."""
    if player.active and player.active.instance_id == instance_id:
        return player.active
    return next((p for p in player.bench if p.instance_id == instance_id), None)


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
        state.emit_event("setup_start", p1_deck=self.p1_deck_name, p2_deck=self.p2_deck_name)
        self._emit(state.events[-1])

        # Draw 7 for each player; emit opening_hand_drawn showing the full initial hand.
        for pid in ("p1", "p2"):
            self._draw_cards(state, pid, 7)
            player = state.get_player(pid)
            state.emit_event(
                "opening_hand_drawn",
                player=pid,
                count=len(player.hand),
                cards=[c.card_name for c in player.hand],
            )
            self._emit(state.events[-1])

        # Coin flip for first player
        first = self._rng.choice(("p1", "p2"))
        state.first_player = first
        state.active_player = first
        state.emit_event("coin_flip", first_player=first)
        self._emit(state.events[-1])

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

        # Set 6 prize cards for each player (cards included for audit visibility)
        for pid in ("p1", "p2"):
            player = state.get_player(pid)
            prize_names: list[str] = []
            for _ in range(PRIZE_COUNT):
                if player.deck:
                    prize = player.deck.pop(0)
                    prize.zone = Zone.PRIZES
                    player.prizes.append(prize)
                    prize_names.append(prize.card_name)
            player.prizes_remaining = len(player.prizes)
            state.emit_event("prizes_set", player=pid, count=len(player.prizes), cards=prize_names)
            self._emit(state.events[-1])

        state.phase = Phase.DRAW
        state.turn_number = 1

        # Emit setup_complete summary and the first turn_start before entering the turn loop
        state.emit_event(
            "setup_complete",
            p1_active=state.p1.active.card_name if state.p1.active else None,
            p2_active=state.p2.active.card_name if state.p2.active else None,
            p1_bench=[c.card_name for c in state.p1.bench],
            p2_bench=[c.card_name for c in state.p2.bench],
            p1_prizes=state.p1.prizes_remaining,
            p2_prizes=state.p2.prizes_remaining,
        )
        self._emit(state.events[-1])

        state.emit_event("turn_start", player=state.active_player, turn=state.turn_number)
        self._emit(state.events[-1])

        return state

    # ── Turn structure (Appendix A) ────────────────────────────────────────────

    async def _run_turn(self, state: GameState) -> GameState:
        pid = state.active_player
        player_obj = self.p1_player if pid == "p1" else self.p2_player

        # ── DRAW ──────────────────────────────────────────────────────────────
        state.phase = Phase.DRAW
        prev_draw_len = len(state.events)
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
        self._emit_since(state, prev_draw_len)

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
            self._annotate_action_events_with_ai_reasoning(state, prev_len, action)
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
                    self._annotate_action_events_with_ai_reasoning(state, prev_len, action)
                    self._emit_since(state, prev_len)

                    # Handle forced switch if KO occurred
                    state = await self._resolve_ko_aftermath(state)

                    if state.phase == Phase.GAME_OVER:
                        return state

                    # Festival Lead: second attack if flag was set
                    fl_player = state.get_player(pid)
                    if fl_player.festival_lead_pending and state.phase != Phase.GAME_OVER:
                        fl_player.festival_lead_pending = False
                        if fl_player.active is not None and fl_player.active.current_hp > 0:
                            legal2 = [a for a in ActionValidator.get_legal_actions(state, pid)
                                      if a.action_type == ActionType.ATTACK]
                            if legal2:
                                action2 = await player_obj.choose_action(state, legal2)
                                is_valid2, _ = ActionValidator.validate(state, action2)
                                if is_valid2:
                                    prev_len2 = len(state.events)
                                    state = await StateTransition.apply(state, action2, self._get_player)
                                    self._annotate_action_events_with_ai_reasoning(state, prev_len2, action2)
                                    self._emit_since(state, prev_len2)
                                    state.get_player(pid).festival_lead_pending = False
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
                is_valid, error = ActionValidator.validate(state, action)
                if not is_valid:
                    state.emit_event("invalid_forced_switch", player=pid, error=error)
                    self._emit(state.events[-1])
                    action = legal[0]
                prev_len = len(state.events)
                state = await StateTransition.apply(state, action, self._get_player)
                self._emit_since(state, prev_len)
        return state

    def _annotate_action_events_with_ai_reasoning(
        self,
        state: "GameState",
        prev_len: int,
        action: "Action",
    ) -> None:
        """Inject AI reasoning metadata directly into visible events emitted by the action.

        Called after StateTransition.apply() but before _emit_since(), so that every event
        published downstream already carries ai_reasoning. EventDetail can then show reasoning
        by reading event.data.ai_reasoning directly — no hidden-event correlation needed.

        Only injects when action.reasoning is set (AIPlayer sets this; heuristic/greedy
        players leave it None), so this naturally restricts to AI players.
        """
        reasoning = getattr(action, "reasoning", None)
        if not reasoning:
            return
        fields = {
            "ai_reasoning": reasoning,
            "ai_action_type": action.action_type.name,
        }
        if action.card_instance_id:
            fields["ai_card_played"] = action.card_instance_id
        if action.target_instance_id:
            fields["ai_target"] = action.target_instance_id
        if action.attack_index is not None:
            fields["ai_attack_index"] = action.attack_index
        for event in state.events[prev_len:]:
            event.update(fields)

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
                if not flip:  # Tails: take 2 damage counters (standard burn)
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

            if (StatusCondition.PARALYZED in active.status_conditions
                    and pid == state.active_player):
                active.status_conditions.remove(StatusCondition.PARALYZED)
                state.emit_event("paralysis_removed", player=pid, card=active.card_name)

        # Freezing Shroud (sv06-053 Froslass): place 1 damage counter on each
        # Pokémon with an Ability (except Froslass itself) during Pokémon Checkup.
        from app.engine.effects.abilities import apply_froslass_shroud
        apply_froslass_shroud(state)
        if state.phase == Phase.GAME_OVER:
            return state

        # Sand Stream (sv10-096 TR Tyranitar): during Pokémon Checkup, if this
        # Pokémon is Active, place 2 damage counters on each opposing Basic.
        # Check both players because Pokémon Checkup is not tied to turn player.
        for tr_player_id in ("p1", "p2"):
            tr_player = state.get_player(tr_player_id)
            if not tr_player.active or tr_player.active.card_def_id != "sv10-096":
                continue
            opp_ss_id = state.opponent_id(tr_player_id)
            opp_ss = state.get_player(opp_ss_id)
            basic_opp = [
                p for p in ([opp_ss.active] if opp_ss.active else []) + list(opp_ss.bench)
                if p.evolution_stage == 0
            ]
            if not basic_opp:
                continue
            for poke in basic_opp:
                poke.current_hp -= 20
                poke.damage_counters += 2
            state.emit_event("sand_stream_triggered", player=tr_player_id)
            from app.engine.effects.base import check_ko
            for poke in list(basic_opp):
                check_ko(state, poke, opp_ss_id)
                if state.phase == Phase.GAME_OVER:
                    return state

        # Perilous Jungle (sv05-156): during Pokémon Checkup, put 2 more counters on each Poisoned non-{D} Pokémon
        if (state.active_stadium
                and state.active_stadium.card_def_id == "sv05-156"):
            for _pj_pid in ("p1", "p2"):
                _pj_player = state.get_player(_pj_pid)
                _pj_all = (([_pj_player.active] if _pj_player.active else [])
                           + list(_pj_player.bench))
                for _pj_poke in _pj_all:
                    if StatusCondition.POISONED in _pj_poke.status_conditions:
                        _pj_cdef = card_registry.get(_pj_poke.card_def_id)
                        _is_dark = _pj_cdef and "Darkness" in (_pj_cdef.types or [])
                        if not _is_dark:
                            _pj_poke.current_hp -= 20
                            _pj_poke.damage_counters += 2
                            state.emit_event("perilous_jungle_triggered",
                                             player=_pj_pid,
                                             card=_pj_poke.card_name)
                            from app.engine.effects.base import check_ko
                            check_ko(state, _pj_poke, _pj_pid)
                            if state.phase == Phase.GAME_OVER:
                                return state

        return state

    def _end_turn(self, state: GameState) -> GameState:
        """Reset per-turn flags and advance to next player."""
        current_pid = state.active_player
        for pid in ("p1", "p2"):
            player = state.get_player(pid)
            player.supporter_played_this_turn = False
            player.energy_attached_this_turn = False
            player.retreat_used_this_turn = False
            player.tr_supporter_played_this_turn = False
            player.tarragon_played_this_turn = False
            player.janines_sa_used_this_turn = False
            player.future_supporter_played_this_turn = False
            player.xerosics_machinations_played_this_turn = False
            player.daydream_active = False
            player.mystery_garden_used_this_turn = False
            # items_locked_this_turn is set by the opponent on this player for the upcoming
            # turn. Only clear it at the end of THIS player's own turn so the effect persists
            # through the opponent's (next) turn as intended.
            if pid == current_pid:
                player.items_locked_this_turn = False
                player.evolution_blocked_next_turn = False
                player.ancient_supporter_played_this_turn = False
                player.supporters_locked_next_turn = False
                # Unleash Lightning (sv07-047): clear player-wide attack block at end of affected player's own turn
                player.all_pokemon_cant_attack_next_turn = False
                # Premium Power Pro (me01-124): Fighting bonus only lasts this turn
                player.fighting_pokemon_damage_bonus = 0
            if pid != current_pid:
                # Iron Defender / Jasmine's Gaze: opponent-next-turn protection expires after opponent attacks
                player.metal_type_damage_reduction = 0
                player.opponent_next_turn_all_reduction = 0
            if player.active:
                player.active.retreated_this_turn = False
                player.active.ability_used_this_turn = False
                # Reset multi-turn restriction flags.
                # attack_damage_reduction and cant_retreat_next_turn are set on the
                # opponent's Pokémon by the current player's attacks; only clear them
                # at the end of THIS player's own turn so they apply during the
                # opponent's upcoming turn.
                # incoming_damage_reduction is set on YOUR OWN Pokémon by your own
                # effects to protect against opponent's NEXT turn attacks; clear it
                # at the end of the OPPONENT's turn (pid != current_pid) so it stays
                # active while the opponent attacks.
                if pid == current_pid:
                    player.active.cant_retreat_next_turn = False
                    player.active.attack_damage_reduction = 0
                    player.active.torment_blocked_attack_name = None
                    # Drum Beating (sv06-016): clear extra cost modifiers at end of affected player's own turn
                    player.active.extra_attack_cost = 0
                    player.active.extra_retreat_cost = 0
                if pid != current_pid:
                    player.active.incoming_damage_reduction = 0
                player.active.cant_attack_next_turn = False
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
                player.active.energy_attach_punish_counters = 0
                player.active.retaliation_on_damage = False
                player.active.repulsor_axe_active = False
                player.active.ready_to_ram_active = False
                player.active.prevent_damage_from_ancient = False
                player.active.attack_damage_bonus = 0
                # Discard energy cards flagged for end-of-turn removal (Ignition Energy)
                self._discard_expiring_energy(state, player.active)
            for b in player.bench:
                b.ability_used_this_turn = False
                if pid == current_pid:
                    b.attack_damage_reduction = 0
                if pid != current_pid:
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
                b.repulsor_axe_active = False
                b.ready_to_ram_active = False
                b.prevent_damage_from_ancient = False
                b.attack_damage_bonus = 0
                self._discard_expiring_energy(state, b)

        state.active_player_damage_bonus = 0
        state.active_player_damage_bonus_vs_ex = 0
        state.briar_active = False
        state.sunny_day_active = False
        state.force_end_turn = False
        # Reset festival_lead_pending for all players
        for pid in ("p1", "p2"):
            state.get_player(pid).festival_lead_pending = False
        # Clear Retaliate window for the player whose turn just ended
        state.get_player(state.active_player).ko_taken_last_turn = False
        state.get_player(state.active_player).ethans_pokemon_ko_last_turn = False

        # Levincia (sv09-150): once during each player's turn, retrieve up to 2 Basic Lightning from discard to hand
        if (state.active_stadium
                and state.active_stadium.card_def_id == "sv09-150"):
            _lev_player = state.get_player(state.active_player)
            _lev_disc = [c for c in _lev_player.discard
                         if c.card_type.lower() == "energy"
                         and c.card_subtype.lower() == "basic"
                         and any("Lightning" in (ep or "") for ep in (c.energy_provides or []))]
            for _lev_card in _lev_disc[:2]:
                _lev_player.discard.remove(_lev_card)
                _lev_card.zone = Zone.HAND
                _lev_player.hand.append(_lev_card)
                state.emit_event("levincia_recovery",
                                 player=state.active_player,
                                 card=_lev_card.card_name)

        # Community Center (sv06-146): if supporter was played this turn, heal 10 from each of your Pokémon
        if (state.active_stadium
                and state.active_stadium.card_def_id == "sv06-146"):
            _cc_player = state.get_player(state.active_player)
            if _cc_player.supporter_played_this_turn:
                _cc_all = ([_cc_player.active] if _cc_player.active else []) + list(_cc_player.bench)
                for _cc_poke in _cc_all:
                    if _cc_poke.damage_counters > 0:
                        _cc_poke.damage_counters = max(0, _cc_poke.damage_counters - 1)
                        _cc_poke.current_hp = min(_cc_poke.max_hp, _cc_poke.current_hp + 10)
                state.emit_event("community_center_heal",
                                 player=state.active_player)

        # Process deferred effects (Permeating Chill, Corrosive Sludge) that fire after current player's turn
        for pe in list(state.pending_effects):
            if pe.get("fires_after_player") == state.active_player:
                state.pending_effects.remove(pe)
                if pe["type"] == "deferred_counters":
                    pe_player = state.get_player(pe["target_pid"])
                    pe_target = _find_deferred_target(pe_player, pe["target_instance_id"])
                    if pe_target and pe_target.current_hp > 0:
                        counters = pe.get("counters", 1)
                        pe_target.current_hp -= counters * 10
                        pe_target.damage_counters += counters
                        state.emit_event("deferred_counters_applied",
                                         player=pe["target_pid"],
                                         card=pe_target.card_name,
                                         counters=counters)
                        from app.engine.effects.base import check_ko
                        check_ko(state, pe_target, pe["target_pid"])
                        if state.phase == Phase.GAME_OVER:
                            return state
                elif pe["type"] == "deferred_ko":
                    pe_player = state.get_player(pe["target_pid"])
                    pe_target = _find_deferred_target(pe_player, pe["target_instance_id"])
                    if pe_target and pe_target.current_hp > 0:
                        pe_target.current_hp = 0
                        pe_target.damage_counters = pe_target.max_hp // 10
                        state.emit_event("deferred_ko_applied",
                                         player=pe["target_pid"],
                                         card=pe_target.card_name)
                        from app.engine.effects.base import check_ko
                        check_ko(state, pe_target, pe["target_pid"])
                        if state.phase == Phase.GAME_OVER:
                            return state

        # Amarys: if pending, discard hand if 5+ cards
        _amarys_player = state.get_player(state.active_player)
        if _amarys_player.amarys_pending:
            _amarys_player.amarys_pending = False
            if len(_amarys_player.hand) >= 5:
                for _hcard in list(_amarys_player.hand):
                    _hcard.zone = Zone.DISCARD
                    _amarys_player.discard.append(_hcard)
                _amarys_player.hand.clear()
                state.emit_event("amarys_discard", player=state.active_player)

        # Powerglass (sv06.5-063): end of your turn, if active has Powerglass, attach Basic Energy from discard
        _pg_player = state.get_player(state.active_player)
        if (_pg_player.active
                and "sv06.5-063" in _pg_player.active.tools_attached):
            from app.engine.effects.trainers import _is_basic_energy_card, _make_energy_attachment
            _pg_basic = [c for c in _pg_player.discard if _is_basic_energy_card(c)]
            if _pg_basic:
                _pg_ec = _pg_basic[0]
                _pg_att = _make_energy_attachment(_pg_ec)
                _pg_player.discard.remove(_pg_ec)
                _pg_ec.zone = _pg_player.active.zone
                _pg_player.active.energy_attached.append(_pg_att)
                state.emit_event("powerglass_triggered", player=state.active_player,
                                 energy=_pg_ec.card_name)

        # Celebratory Fanfare (mep-028): heal 10 from each of current player's Pokémon
        if (state.active_stadium
                and state.active_stadium.card_def_id == "mep-028"):
            _cf_player = state.get_player(state.active_player)
            _cf_all = (([_cf_player.active] if _cf_player.active else [])
                       + list(_cf_player.bench))
            _cf_healed = False
            for _cf_poke in _cf_all:
                if _cf_poke.damage_counters > 0:
                    _cf_poke.damage_counters = max(0, _cf_poke.damage_counters - 1)
                    _cf_poke.current_hp = min(_cf_poke.max_hp, _cf_poke.current_hp + 10)
                    _cf_healed = True
            if _cf_healed:
                state.emit_event("celebratory_fanfare_heal", player=state.active_player)

        # Discard TM tools at end of owner's turn
        _TM_DISCARD_TOOL_IDS = {"sv08-188"}
        _ep = state.get_player(state.active_player)
        for _poke in ([_ep.active] if _ep.active else []) + list(_ep.bench):
            _poke.tools_attached = [t for t in _poke.tools_attached
                                     if t not in _TM_DISCARD_TOOL_IDS]

        state.active_player = state.opponent_id(state.active_player)
        state.turn_number += 1
        state.phase = Phase.DRAW
        state.emit_event("turn_start", player=state.active_player, turn=state.turn_number)
        self._emit(state.events[-1])

        # Clear C.O.D.E.: Protect immunity for the newly-active player
        # (immunity was set for "during your opponent's next turn")
        state.get_player(state.active_player).future_effect_immunity = False

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
        drawn_cards: list[str] = []
        for _ in range(count):
            if not player.deck:
                break
            card = player.deck.pop(0)
            card.zone = Zone.HAND
            player.hand.append(card)
            drawn_cards.append(card.card_name)
            drawn += 1
        if drawn > 0:
            state.emit_event("draw", player=pid, count=drawn,
                             hand_size=len(player.hand), cards=drawn_cards)
        return drawn

    def _emit(self, event: dict) -> None:
        cb = getattr(self, "event_callback", None)
        if cb:
            cb(event)

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
