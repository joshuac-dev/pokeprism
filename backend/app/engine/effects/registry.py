"""Effect registry singleton.

Phase 1: Only the default flat-damage resolver is active.
Phase 2: All ~120 card effects are registered here.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.engine.state import GameState
    from app.engine.actions import Action

logger = logging.getLogger(__name__)


class EffectRegistry:
    """Singleton registry mapping card IDs to effect handler functions.

    Keys:
      attack  — "{tcgdex_id}:{attack_index}"
      ability — "{tcgdex_id}:{ability_name}"
      trainer — "{tcgdex_id}"
      energy  — "{tcgdex_id}"

    Effect handlers may be either:
    - Regular functions ``(state, action) -> None``: state mutated in place, no choices.
    - Generator functions ``(state, action) -> Generator[ChoiceRequest, Action, None]``:
      yield a :class:`ChoiceRequest`, receive back the Action the player chose.

    The registry's async resolve methods drive generator handlers via
    :func:`_drive_effect`, asking the appropriate player for each choice.
    """

    _instance: "EffectRegistry | None" = None

    def __init__(self) -> None:
        self._attack_effects:  dict[str, Callable] = {}
        self._ability_effects: dict[str, Callable] = {}
        self._ability_conditions: dict[str, Callable] = {}  # optional precondition
        self._trainer_effects: dict[str, Callable] = {}
        self._energy_effects:  dict[str, Callable] = {}
        self._passive_abilities: set[str] = set()  # abilities handled elsewhere in engine

    @classmethod
    def instance(cls) -> "EffectRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Create a fresh registry (used in tests)."""
        cls._instance = cls()

    # ── Registration ──────────────────────────────────────────────────────────

    def register_attack(self, card_id: str, attack_index: int,
                        handler: Callable) -> None:
        key = f"{card_id}:{attack_index}"
        self._attack_effects[key] = handler

    def register_ability(self, card_id: str, ability_name: str,
                         handler: Callable,
                         condition: Optional[Callable] = None) -> None:
        """Register an activatable ability handler.

        Args:
            condition: Optional ``(state, player_id) -> bool`` that returns
                       False when the ability cannot currently activate (e.g.
                       Lunar Cycle without Solrock in play).  When False,
                       USE_ABILITY is not offered as a legal action.
        """
        key = f"{card_id}:{ability_name}"
        self._ability_effects[key] = handler
        if condition is not None:
            self._ability_conditions[key] = condition

    def register_trainer(self, card_id: str, handler: Callable) -> None:
        self._trainer_effects[card_id] = handler

    def register_energy(self, card_id: str, handler: Callable) -> None:
        self._energy_effects[card_id] = handler

    def register_passive_ability(self, card_id: str, ability_name: str) -> None:
        """Mark an ability as passive (logic lives elsewhere in the engine).

        Satisfies coverage checks without exposing a USE_ABILITY action.
        """
        self._passive_abilities.add(f"{card_id}:{ability_name}")

    # ── Resolution (all async — handlers may yield ChoiceRequests) ────────────

    async def resolve_attack(self, card_id: str, attack_index: int,
                             state: "GameState", action: "Action",
                             get_player: Optional[Callable] = None) -> "GameState":
        key = f"{card_id}:{attack_index}"
        handler = self._attack_effects.get(key)
        if handler:
            await _drive_effect(handler, state, action, get_player)
            return state
        # No handler — only fall through to flat-damage if the attack has no
        # effect text.  Non-trivial attacks without a handler are a data error.
        from app.cards import registry as card_registry
        cdef = card_registry.get(card_id)
        if cdef and attack_index < len(cdef.attacks):
            effect_text = (cdef.attacks[attack_index].effect or "").strip()
            if effect_text:
                raise NotImplementedError(
                    f"No handler for '{card_id}' attack[{attack_index}] "
                    f"'{cdef.attacks[attack_index].name}' which has effect text. "
                    "Register a handler before running simulations with this card."
                )
        return self._default_damage(state, action)

    async def resolve_trainer(self, card_id: str,
                              state: "GameState", action: "Action",
                              get_player: Optional[Callable] = None) -> "GameState":
        handler = self._trainer_effects.get(card_id)
        if handler:
            await _drive_effect(handler, state, action, get_player)
            return state
        raise NotImplementedError(
            f"No trainer effect registered for '{card_id}'. "
            "Register a handler before running simulations with this card."
        )

    async def resolve_ability(self, card_id: str, ability_name: str,
                              state: "GameState", action: "Action",
                              get_player: Optional[Callable] = None) -> "GameState":
        key = f"{card_id}:{ability_name}"
        handler = self._ability_effects.get(key)
        if handler:
            await _drive_effect(handler, state, action, get_player)
            return state
        logger.debug("No ability effect registered for %s:%s — no-op",
                     card_id, ability_name)
        return state

    async def resolve_energy(self, card_id: str,
                             state: "GameState", action: "Action",
                             get_player: Optional[Callable] = None) -> "GameState":
        handler = self._energy_effects.get(card_id)
        if handler:
            await _drive_effect(handler, state, action, get_player)
        return state

    # ── Coverage check ────────────────────────────────────────────────────────

    def check_card_coverage(self, card_def: dict) -> list[str]:
        """Return names of missing effect handlers for *card_def*.

        The dict is expected to contain the fields stored in the ``cards`` DB
        table: ``tcgdex_id``, ``category``, ``subcategory``, ``attacks`` (list
        of ``{name, effect, ...}``), and ``abilities`` (list of ``{name, ...}``).

        Returns a list of strings such as::

            ["attack:Phantom Dive", "ability:Phantom Gate", "trainer"]

        An empty list means the card is fully covered.
        Rules:
          - Trainer cards → require a registered trainer handler.
          - Special Energy cards → require a registered energy handler.
          - Pokémon attacks with non-empty effect text → require a handler.
          - Pokémon abilities (any type) → require a registered handler.
          - Basic/colourless flat-damage attacks (empty effect text) are fine.
        """
        missing: list[str] = []
        card_id   = card_def.get("tcgdex_id") or ""
        category  = (card_def.get("category") or "").lower()
        subcat    = (card_def.get("subcategory") or "").lower()

        if category == "trainer":
            if card_id not in self._trainer_effects:
                missing.append("trainer")

        elif category == "energy" and subcat == "special":
            if card_id not in self._energy_effects:
                missing.append("energy")

        elif category == "pokemon":
            for i, atk in enumerate(card_def.get("attacks") or []):
                if (atk.get("effect") or "").strip():
                    if f"{card_id}:{i}" not in self._attack_effects:
                        missing.append(f"attack:{atk.get('name') or str(i)}")
            for abl in card_def.get("abilities") or []:
                name = abl.get("name") or ""
                key = f"{card_id}:{name}"
                if name and key not in self._ability_effects and key not in self._passive_abilities:
                    missing.append(f"ability:{name}")

        return missing

    # ── Introspection ─────────────────────────────────────────────────────────

    def has_effect(self, card_id: str,
                   effect_type: str = "attack", index: int = 0) -> bool:
        if effect_type == "attack":
            return f"{card_id}:{index}" in self._attack_effects
        elif effect_type == "ability":
            return any(k.startswith(f"{card_id}:") for k in self._ability_effects)
        elif effect_type == "trainer":
            return card_id in self._trainer_effects
        elif effect_type == "energy":
            return card_id in self._energy_effects
        return False

    def ability_can_activate(self, card_id: str, ability_name: str,
                             state: "GameState", player_id: str,
                             poke: object = None) -> bool:
        """Return False if a registered condition says the ability cannot fire now.

        Args:
            poke: The specific in-play Pokémon instance being evaluated.
                  Condition functions that accept 3 positional arguments will
                  receive it; 2-argument conditions are called without it.
        """
        key = f"{card_id}:{ability_name}"
        cond = self._ability_conditions.get(key)
        if cond is None:
            return True  # no precondition registered → always offerable
        try:
            sig = inspect.signature(cond)
            if len(sig.parameters) >= 3:
                return bool(cond(state, player_id, poke))
            return bool(cond(state, player_id))
        except Exception:
            return True  # fail open: offer the action if condition check errors

    # ── Default flat-damage resolver ──────────────────────────────────────────

    def _default_damage(self, state: "GameState", action: "Action") -> "GameState":
        """Apply base attack damage with weakness/resistance and tool modifiers.

        Used for every attack that lacks a custom handler.
        Called by Phase 1 engine for all attacks.
        """
        from app.engine.effects.base import (
            apply_weakness_resistance,
            check_ko,
            get_tool_damage_bonus,
            parse_damage,
        )
        from app.cards import registry as card_registry

        player = state.get_player(action.player_id)
        opponent = state.get_opponent(action.player_id)
        opp_id = state.opponent_id(action.player_id)

        if not player.active or not opponent.active:
            return state

        cdef = card_registry.get(player.active.card_def_id)
        if not cdef or action.attack_index is None:
            return state

        if action.attack_index >= len(cdef.attacks):
            return state

        attack = cdef.attacks[action.attack_index]
        base_damage = parse_damage(attack.damage) + state.active_player_damage_bonus
        if state.active_player_damage_bonus_vs_ex:
            opp_cdef = card_registry.get(opponent.active.card_def_id)
            if opp_cdef and opp_cdef.is_ex:
                base_damage += state.active_player_damage_bonus_vs_ex

        # Growl / attack_damage_reduction: defender's attacks do less damage this turn
        base_damage = max(0, base_damage - player.active.attack_damage_reduction)

        # Adrena-Power (sv06-111 Okidogi): +100 damage when {D} energy attached
        from app.engine.effects.abilities import (
            has_adrena_power, has_cornerstone_stance, has_mysterious_rock_inn,
            has_adrena_pheromone,
        )
        if has_adrena_power(player.active):
            base_damage += 100

        if base_damage > 0:
            final_damage = apply_weakness_resistance(
                base_damage, player.active, opponent.active,
                state=state, defender_player_id=opp_id,
            )
            final_damage += get_tool_damage_bonus(
                player.active, opponent.active, action.attack_index, state, action.player_id
            )
            final_damage = max(0, final_damage)

            # Passive ability damage blocks (in priority order)
            if opponent.active.protected_from_ex and cdef.is_ex:
                final_damage = 0
            elif has_cornerstone_stance(opponent.active, player.active):
                final_damage = 0
            elif has_mysterious_rock_inn(opponent.active, player.active):
                final_damage = 0
            elif has_adrena_pheromone(opponent.active):
                import random as _random
                if _random.choice([True, False]):  # Heads = no damage
                    state.emit_event("adrena_pheromone_blocked",
                                     player=opp_id, card=opponent.active.card_name)
                    final_damage = 0

            opponent.active.current_hp -= final_damage
            opponent.active.damage_counters += final_damage // 10

            state.emit_event(
                "attack_damage",
                attacker=player.active.card_name,
                defender=opponent.active.card_name,
                attack_name=attack.name,
                base_damage=base_damage,
                final_damage=final_damage,
            )

            check_ko(state, opponent.active, state.opponent_id(action.player_id))
        else:
            state.emit_event(
                "attack_no_damage",
                attacker=player.active.card_name,
                attack_name=attack.name,
            )

        return state


# ──────────────────────────────────────────────────────────────────────────────
# Generator driver — runs an effect handler, asking players for choices
# ──────────────────────────────────────────────────────────────────────────────

async def _drive_effect(
    handler: Callable,
    state: "GameState",
    action: "Action",
    get_player: Optional[Callable] = None,
) -> None:
    """Run an effect handler, driving any ChoiceRequest yields.

    If ``handler`` is a generator function, it may yield
    :class:`~app.engine.effects.base.ChoiceRequest` objects.  For each yield,
    this function asks the appropriate player for a choice and sends the chosen
    Action back into the generator.

    Regular (non-generator) handlers are called normally.
    """
    result = handler(state, action)

    if not inspect.isgenerator(result):
        # Coroutine support (shouldn't be needed but handle gracefully)
        if asyncio.iscoroutine(result):
            await result
        return

    # Drive the generator
    try:
        request = next(result)
        while request is not None:
            chosen = None
            if get_player is not None:
                player_obj = get_player(request.player_id)
                if player_obj is not None:
                    legal = _choice_to_legal_actions(request)
                    chosen = await player_obj.choose_action(state, legal)

            if chosen is None:
                chosen = _default_choice(request)

            try:
                request = result.send(chosen)
            except StopIteration:
                break
    except StopIteration:
        pass


def _card_choice_id(c) -> str:
    """Return the canonical ID for a card in a ChoiceRequest.

    CardInstance objects use instance_id; EnergyAttachment objects (passed by
    energy-discard handlers) use source_card_id as the unique identifier.
    """
    if isinstance(c, str):
        return c
    if hasattr(c, "instance_id"):
        return c.instance_id
    if hasattr(c, "source_card_id"):
        return c.source_card_id
    return str(id(c))


def _choice_to_legal_actions(request) -> list:
    """Convert a ChoiceRequest into a list of legal Action objects for the player."""
    from app.engine.actions import Action, ActionType

    if request.choice_type == "choose_cards":
        cards = request.cards if request.cards else (request.options or [])
        # Single action carrying the full list; player picks from it
        return [Action(
            action_type=ActionType.CHOOSE_CARDS,
            player_id=request.player_id,
            selected_cards=[_card_choice_id(c) for c in cards],
            choice_context=request,
        )]
    elif request.choice_type == "choose_target":
        return [
            Action(
                action_type=ActionType.CHOOSE_TARGET,
                player_id=request.player_id,
                target_instance_id=t.instance_id,
                choice_context=request,
            )
            for t in request.targets
        ] or [Action(action_type=ActionType.CHOOSE_TARGET, player_id=request.player_id,
                     choice_context=request)]
    elif request.choice_type == "choose_option":
        return [
            Action(
                action_type=ActionType.CHOOSE_OPTION,
                player_id=request.player_id,
                selected_option=i,
                choice_context=request,
            )
            for i in range(len(request.options))
        ] or [Action(action_type=ActionType.CHOOSE_OPTION, player_id=request.player_id,
                     selected_option=0, choice_context=request)]
    return []


def _default_choice(request) -> "Action":
    """Fallback choice when no player object is available (e.g., in unit tests)."""
    from app.engine.actions import Action, ActionType

    if request.choice_type == "choose_cards":
        cards = request.cards if request.cards else (request.options or [])
        chosen = [_card_choice_id(c) for c in cards[:request.max_count]]
        return Action(ActionType.CHOOSE_CARDS, request.player_id, selected_cards=chosen,
                      choice_context=request)
    elif request.choice_type == "choose_target":
        iid = request.targets[0].instance_id if request.targets else None
        return Action(ActionType.CHOOSE_TARGET, request.player_id,
                      target_instance_id=iid, choice_context=request)
    elif request.choice_type == "choose_option":
        return Action(ActionType.CHOOSE_OPTION, request.player_id,
                      selected_option=0, choice_context=request)
    return Action(ActionType.CHOOSE_CARDS, request.player_id)
