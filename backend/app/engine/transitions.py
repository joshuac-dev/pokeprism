"""State transition handlers for every ActionType.

State is mutated in place for performance (§6.4 of PROJECT.md).
Every transition emits at least one event so the event log provides
a complete audit trail.

Phase 2 note: handlers that call the EffectRegistry are async and accept a
``get_player`` callable so the registry can ask either player for choices
when an effect yields a ChoiceRequest.  All other handlers are synchronous
but accept ``get_player=None`` so StateTransition.apply can call them
uniformly.
"""

from __future__ import annotations

import asyncio
import random
import logging
from typing import Callable, Optional

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
from app.engine.actions import Action, ActionType
from app.engine.effects.registry import EffectRegistry
from app.cards import registry as card_registry

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _find(cards: list[CardInstance], iid: str) -> Optional[CardInstance]:
    for c in cards:
        if c.instance_id == iid:
            return c
    return None


def _find_in_hand(player: PlayerState, iid: str) -> Optional[CardInstance]:
    return _find(player.hand, iid)


def _find_in_play(player: PlayerState, iid: str) -> Optional[CardInstance]:
    if player.active and player.active.instance_id == iid:
        return player.active
    return _find(player.bench, iid)


# ──────────────────────────────────────────────────────────────────────────────
# Setup transitions
# ──────────────────────────────────────────────────────────────────────────────

def _place_active(state: GameState, action: Action, get_player=None) -> GameState:
    player = state.get_player(action.player_id)
    card = _find_in_hand(player, action.card_instance_id)
    if card is None:
        raise ValueError(f"Card {action.card_instance_id} not in hand")
    player.hand.remove(card)
    card.zone = Zone.ACTIVE
    card.turn_played = state.turn_number
    player.active = card
    state.emit_event("place_active", player=action.player_id, card=card.card_name)
    return state


def _place_bench(state: GameState, action: Action, get_player=None) -> GameState:
    player = state.get_player(action.player_id)
    card = _find_in_hand(player, action.card_instance_id)
    if card is None:
        raise ValueError(f"Card {action.card_instance_id} not in hand")
    player.hand.remove(card)
    card.zone = Zone.BENCH
    card.turn_played = state.turn_number
    player.bench.append(card)
    state.emit_event("place_bench", player=action.player_id, card=card.card_name)
    # Risky Ruins (me01-127): non-Darkness Pokémon placed on bench take 20 damage
    if state.active_stadium and state.active_stadium.card_def_id == "me01-127":
        cdef_rr = card_registry.get(card.card_def_id)
        if cdef_rr and "Darkness" not in (cdef_rr.types or []):
            card.current_hp = max(0, card.current_hp - 20)
            card.damage_counters += 2
    return state


def _mulligan_redraw(state: GameState, action: Action, get_player=None) -> GameState:
    """Player has no basics → shuffle hand back, draw 7 again.
    Opponent draws 1 bonus card per mulligan.
    """
    player = state.get_player(action.player_id)
    opponent = state.get_opponent(action.player_id)

    # Shuffle hand back
    player.deck.extend(player.hand)
    player.hand.clear()
    random.shuffle(player.deck)

    # Opponent draws 1 bonus card
    if opponent.deck:
        bonus = opponent.deck.pop(0)
        bonus.zone = Zone.HAND
        opponent.hand.append(bonus)

    # Player draws 7 new cards
    for _ in range(7):
        if player.deck:
            card = player.deck.pop(0)
            card.zone = Zone.HAND
            player.hand.append(card)

    state.emit_event(
        "mulligan",
        player=action.player_id,
        new_hand_size=len(player.hand),
    )
    return state


# ──────────────────────────────────────────────────────────────────────────────
# Main phase transitions
# ──────────────────────────────────────────────────────────────────────────────

async def _play_basic(state: GameState, action: Action, get_player=None) -> GameState:
    """Play a Basic Pokémon from hand to bench."""
    player = state.get_player(action.player_id)
    card = _find_in_hand(player, action.card_instance_id)
    if card is None:
        raise ValueError(f"Card {action.card_instance_id} not in hand")
    player.hand.remove(card)
    card.zone = Zone.BENCH
    card.turn_played = state.turn_number
    player.bench.append(card)
    state.emit_event(
        "play_basic",
        player=action.player_id,
        card=card.card_name,
        bench_size=len(player.bench),
    )
    # Risky Ruins (me01-127): non-Darkness Pokémon placed on bench take 20 damage
    if state.active_stadium and state.active_stadium.card_def_id == "me01-127":
        cdef_rr = card_registry.get(card.card_def_id)
        if cdef_rr and "Darkness" not in (cdef_rr.types or []):
            card.current_hp = max(0, card.current_hp - 20)
            card.damage_counters += 2
    # On-bench trigger abilities (fire automatically when the Pokémon is played to bench)
    cdef_card = card_registry.get(card.card_def_id)
    if cdef_card and cdef_card.abilities:
        from app.engine.effects.abilities import BENCH_TRIGGER_ABILITIES
        for ability in cdef_card.abilities:
            if ability.name in BENCH_TRIGGER_ABILITIES:
                bench_action = Action(action.action_type, action.player_id,
                                      card_instance_id=card.instance_id)
                await EffectRegistry.instance().resolve_ability(
                    card.card_def_id, ability.name, state, bench_action, get_player
                )
    return state


async def _play_supporter(state: GameState, action: Action, get_player=None) -> GameState:
    player = state.get_player(action.player_id)
    card = _find_in_hand(player, action.card_instance_id)
    if card is None:
        raise ValueError(f"Supporter {action.card_instance_id} not in hand")
    player.hand.remove(card)
    card.zone = Zone.DISCARD
    player.discard.append(card)
    player.supporter_played_this_turn = True
    # Track Future Supporter for Iron Valiant Majestic Sword
    cdef_sup = card_registry.get(card.card_def_id)
    if cdef_sup and "Future" in (getattr(cdef_sup, "subtypes", None) or []):
        player.future_supporter_played_this_turn = True
    if cdef_sup and "Ancient" in (getattr(cdef_sup, "subtypes", None) or []):
        player.ancient_supporter_played_this_turn = True

    state.emit_event(
        "play_supporter",
        player=action.player_id,
        card=card.card_name,
    )

    # Wide Wall (sv07-076 Rhyperior): prevent all effects of Supporter cards done to opponent's Pokémon
    opp = state.get_opponent(action.player_id)
    wide_wall_active = (opp.active is not None and opp.active.card_def_id == "sv07-076")
    if wide_wall_active:
        opp.wide_wall_protected = True
        state.emit_event("wide_wall_active", player=state.opponent_id(action.player_id),
                         card=card.card_name)

    try:
        result = await EffectRegistry.instance().resolve_trainer(card.card_def_id, state, action, get_player)
    finally:
        if wide_wall_active:
            opp.wide_wall_protected = False

    return result


async def _play_item(state: GameState, action: Action, get_player=None) -> GameState:
    player = state.get_player(action.player_id)
    card = _find_in_hand(player, action.card_instance_id)
    if card is None:
        raise ValueError(f"Item {action.card_instance_id} not in hand")
    player.hand.remove(card)
    card.zone = Zone.DISCARD
    player.discard.append(card)

    state.emit_event(
        "play_item",
        player=action.player_id,
        card=card.card_name,
    )
    return await EffectRegistry.instance().resolve_trainer(card.card_def_id, state, action, get_player)


async def _play_stadium(state: GameState, action: Action, get_player=None) -> GameState:
    player = state.get_player(action.player_id)
    card = _find_in_hand(player, action.card_instance_id)
    if card is None:
        raise ValueError(f"Stadium {action.card_instance_id} not in hand")
    player.hand.remove(card)

    # Discard old stadium if present
    if state.active_stadium:
        state.active_stadium.zone = Zone.DISCARD
        # Return to whoever played it (we don't track that; put in active player's discard)
        state.get_player(action.player_id).discard.append(state.active_stadium)

    card.zone = Zone.STADIUM
    state.active_stadium = card

    state.emit_event(
        "play_stadium",
        player=action.player_id,
        card=card.card_name,
    )
    return await EffectRegistry.instance().resolve_trainer(card.card_def_id, state, action, get_player)


async def _play_tool(state: GameState, action: Action, get_player=None) -> GameState:
    player = state.get_player(action.player_id)
    card = _find_in_hand(player, action.card_instance_id)
    target = _find_in_play(player, action.target_instance_id)
    if card is None or target is None:
        raise ValueError("Tool or target not found")
    player.hand.remove(card)
    card.zone = target.zone  # Tool lives with its host
    card.is_tool_attached = True
    target.tools_attached.append(card.card_def_id)

    state.emit_event(
        "play_tool",
        player=action.player_id,
        card=card.card_name,
        target=target.card_name,
    )
    # Resolve on-attach tool effects (Hero's Cape HP, etc.)
    return await EffectRegistry.instance().resolve_trainer(
        card.card_def_id, state, action, get_player
    )


async def _attach_energy(state: GameState, action: Action, get_player=None) -> GameState:
    player = state.get_player(action.player_id)
    energy_card = _find_in_hand(player, action.card_instance_id)
    target = _find_in_play(player, action.target_instance_id)
    if energy_card is None or target is None:
        raise ValueError("Energy card or target not found")

    player.hand.remove(energy_card)
    energy_card.zone = target.zone

    # Determine what types this energy provides
    if energy_card.energy_provides:
        provides = [EnergyType.from_str(t) for t in energy_card.energy_provides]
    else:
        provides = [EnergyType.COLORLESS]

    primary_type = provides[0] if provides else EnergyType.COLORLESS

    target.energy_attached.append(
        EnergyAttachment(
            energy_type=primary_type,
            source_card_id=energy_card.instance_id,
            card_def_id=energy_card.card_def_id,
            provides=provides,
        )
    )
    player.energy_attached_this_turn = True

    # Inferno Fandango (sv10.5w-013 Emboar): Basic Fire attachments don't count toward 1-per-turn
    from app.engine.effects.abilities import _in_play as _abl_in_play_ae
    is_inferno_fandango = (
        energy_card.card_type.lower() == "energy"
        and energy_card.card_subtype.lower() == "basic"
        and "Fire" in (energy_card.energy_provides or [])
        and any(p.card_def_id == "sv10.5w-013" for p in _abl_in_play_ae(player))
    )
    if is_inferno_fandango:
        player.energy_attached_this_turn = False

    # Daydream (sv06.5-017 Hypno): if daydream_active and attaching to Active Pokémon, end turn
    if player.daydream_active and target is player.active:
        player.daydream_active = False
        state.force_end_turn = True
        state.emit_event("daydream_triggered", player=action.player_id,
                         card=target.card_name)

    state.emit_event(
        "energy_attached",
        player=action.player_id,
        card=energy_card.card_name,
        target=target.card_name,
        energy_type=primary_type.value,
    )

    # Resolve special energy effects (draw on attach, HP boost, etc.)
    await EffectRegistry.instance().resolve_energy(
        energy_card.card_def_id, state, action, get_player
    )

    # Auto Heal (sv09-107 Magearna): while Active, whenever energy is attached to any Pokémon, heal 10 damage from that Pokémon
    from app.engine.effects.abilities import _in_play as _abl_in_play_ae2
    if (player.active and player.active.card_def_id == "sv09-107"
            and target.damage_counters > 0):
        heal = 10
        target.current_hp = min(target.max_hp, target.current_hp + heal)
        target.damage_counters -= 1
        state.emit_event("auto_heal_triggered", player=action.player_id,
                         card=target.card_name, healed=heal)

    # Gnawing Curse (sv05-104 Gengar ex): whenever opp attaches Energy from hand, put 2 counters on that Pokémon
    opp_ge = state.get_opponent(action.player_id)
    opp_ge_id = state.opponent_id(action.player_id)
    if any(p.card_def_id == "sv05-104" for p in (([opp_ge.active] if opp_ge.active else []) + list(opp_ge.bench))):
        target.current_hp -= 20
        target.damage_counters += 2
        state.emit_event("gnawing_curse_triggered", player=opp_ge_id,
                         card=target.card_name)
        from app.engine.effects.base import check_ko
        check_ko(state, target, action.player_id)

    # Electrified Incisors (me01-051 Pachirisu): whenever opponent attaches Energy from hand to their Active, 8 counters
    if target.energy_attach_punish_counters > 0 and target is player.active:
        counters = target.energy_attach_punish_counters
        target.damage_counters += counters
        target.current_hp -= counters * 10
        state.emit_event("electrified_incisors_triggered", player=action.player_id,
                         card=target.card_name, counters=counters)
        from app.engine.effects.base import check_ko as _check_ko_ei
        _check_ko_ei(state, target, action.player_id)

    return state


async def _evolve(state: GameState, action: Action, get_player=None) -> GameState:
    player = state.get_player(action.player_id)
    evo_card = _find_in_hand(player, action.card_instance_id)
    target = _find_in_play(player, action.target_instance_id)
    if evo_card is None or target is None:
        raise ValueError("Evolution card or target not found")

    cdef = card_registry.get(evo_card.card_def_id)
    if cdef is None:
        raise ValueError(f"No card definition for {evo_card.card_def_id}")

    player.hand.remove(evo_card)

    # Copy battle data from pre-evolution to evolution
    evo_card.energy_attached = target.energy_attached
    evo_card.tools_attached = target.tools_attached
    evo_card.status_conditions = set(target.status_conditions)
    evo_card.damage_counters = target.damage_counters  # Carry damage over
    evo_card.evolved_from = target.instance_id
    evo_card.evolved_this_turn = True
    evo_card.turn_played = state.turn_number
    evo_card.zone = target.zone

    # Set HP from card definition (heals damage above new max)
    evo_card.max_hp = cdef.hp or target.max_hp
    evo_card.current_hp = evo_card.max_hp - (evo_card.damage_counters * 10)
    evo_card.current_hp = max(0, evo_card.current_hp)

    stage_map = {"stage1": 1, "stage 1": 1, "stage2": 2, "stage 2": 2, "mega": 2}
    evo_card.evolution_stage = stage_map.get(cdef.stage.lower(), target.evolution_stage + 1)

    # Replace target with evolution
    if player.active and player.active.instance_id == target.instance_id:
        player.active = evo_card
    else:
        for i, b in enumerate(player.bench):
            if b.instance_id == target.instance_id:
                player.bench[i] = evo_card
                break

    # Pre-evolution goes to discard (or lost zone for certain cards — handle in Phase 2)
    target.zone = Zone.DISCARD
    player.discard.append(target)

    state.emit_event(
        "evolve",
        player=action.player_id,
        from_card=target.card_name,
        to_card=evo_card.card_name,
    )
    # On-evolve trigger abilities (fire automatically when Pokémon evolves)
    if cdef and cdef.abilities:
        from app.engine.effects.abilities import EVOLVE_TRIGGER_ABILITIES
        for ability in cdef.abilities:
            if ability.name in EVOLVE_TRIGGER_ABILITIES:
                evo_action = Action(action.action_type, action.player_id,
                                    card_instance_id=evo_card.instance_id)
                await EffectRegistry.instance().resolve_ability(
                    evo_card.card_def_id, ability.name, state, evo_action, get_player
                )

    # Darkest Impulse (sv10-074 TR Ampharos): when opponent evolves, put 4 damage counters
    # on the evolved Pokémon. Doesn't stack — only applied once even if multiple TR Ampharos.
    opp_id_evolve = state.opponent_id(action.player_id)
    opp_evolve = state.get_player(opp_id_evolve)
    from app.engine.effects.abilities import _in_play as _abl_in_play_evolve
    if any(p.card_def_id == "sv10-074" for p in _abl_in_play_evolve(opp_evolve)):
        evo_card.current_hp = max(0, evo_card.current_hp - 40)
        evo_card.damage_counters += 4
        state.emit_event("darkest_impulse_triggered",
                         player=opp_id_evolve, card=evo_card.card_name)
        from app.engine.effects.base import check_ko
        check_ko(state, evo_card, action.player_id)

    return state


async def _retreat(state: GameState, action: Action, get_player=None) -> GameState:
    player = state.get_player(action.player_id)
    if not player.active:
        raise ValueError("No active Pokémon to retreat")
    new_active = _find(player.bench, action.target_instance_id)
    if new_active is None:
        raise ValueError(f"Bench target {action.target_instance_id} not found")

    cdef = card_registry.get(player.active.card_def_id)
    retreat_cost = cdef.retreat_cost if cdef else 0

    # Discard energy equal to retreat cost (discard cheapest type first)
    _discard_retreat_energy(player, player.active, retreat_cost)

    old_active = player.active
    old_active.zone = Zone.BENCH
    old_active.retreated_this_turn = True

    new_active.zone = Zone.ACTIVE
    player.active = new_active
    player.bench.remove(new_active)
    player.bench.append(old_active)
    player.retreat_used_this_turn = True

    state.emit_event(
        "retreat",
        player=action.player_id,
        from_card=old_active.card_name,
        to_card=new_active.card_name,
        energy_discarded=retreat_cost,
    )

    # Holes (me02.5-101 TR Dugtrio): when opp's active moves to bench, place 2 counters
    opp = state.get_opponent(action.player_id)
    opp_id = "p2" if action.player_id == "p1" else "p1"
    from app.engine.effects.attacks import _in_play as _atk_in_play
    if any(p.card_def_id == "me02.5-101" for p in _atk_in_play(opp)):
        old_active.current_hp -= 20
        old_active.damage_counters += 2
        state.emit_event("holes_triggered",
                         player=action.player_id,
                         card=old_active.card_name)
        from app.engine.effects.base import check_ko
        check_ko(state, old_active, action.player_id)

    # Swirling Prose (me02-036 Mismagius ex): when player retreats, confuse their new active
    from app.engine.effects.abilities import _in_play as _abl_in_play
    if any(p.card_def_id == "me02-036" for p in _abl_in_play(opp)):
        if player.active:
            player.active.status_conditions.add(StatusCondition.CONFUSED)
            state.emit_event("swirling_prose_triggered",
                             player=action.player_id,
                             card=player.active.card_name)

    # Lava Zone (sv05-029 Magcargo): when opponent's Active Pokémon retreats, burn their new Active
    from app.engine.effects.abilities import _in_play as _abl_in_play2
    if (player.active
            and any(p.card_def_id == "sv05-029" for p in _abl_in_play2(opp))):
        player.active.status_conditions.add(StatusCondition.BURNED)
        state.emit_event("lava_zone_triggered", player=action.player_id,
                         card=player.active.card_name)

    # Buzzing Boost (sv10-003 Yanmega ex): when promoted from Bench to Active, search deck for up to 3 Basic G Energy
    if player.active and player.active.card_def_id == "sv10-003":
        bb_action = Action(action.action_type, action.player_id,
                           card_instance_id=player.active.instance_id)
        await EffectRegistry.instance().resolve_ability(
            "sv10-003", "Buzzing Boost", state, bb_action, get_player
        )

    return state


def _discard_retreat_energy(
    player: PlayerState, pokemon: CardInstance, count: int
) -> None:
    """Discard `count` energy cards from `pokemon` to pay retreat cost."""
    discarded = 0
    while discarded < count and pokemon.energy_attached:
        att = pokemon.energy_attached.pop(0)
        # Find the physical energy card and move it to discard
        energy_card = _find_card_by_id(player, att.source_card_id)
        if energy_card:
            energy_card.zone = Zone.DISCARD
            if energy_card not in player.discard:
                player.discard.append(energy_card)
        discarded += 1


def _find_card_by_id(player: PlayerState, iid: str) -> Optional[CardInstance]:
    for zone in (player.hand, player.discard, player.bench,
                 ([] if not player.active else [player.active])):
        result = _find(zone if isinstance(zone, list) else [zone], iid)
        if result:
            return result
    return None


async def _use_ability(state: GameState, action: Action, get_player=None) -> GameState:
    player = state.get_player(action.player_id)
    pokemon = _find_in_play(player, action.card_instance_id)
    if pokemon is None:
        raise ValueError(f"Pokémon {action.card_instance_id} not in play")

    cdef = card_registry.get(pokemon.card_def_id)
    ability_name = cdef.abilities[0].name if cdef and cdef.abilities else ""

    pokemon.ability_used_this_turn = True
    state.emit_event(
        "use_ability",
        player=action.player_id,
        card=pokemon.card_name,
        ability=ability_name,
    )
    return await EffectRegistry.instance().resolve_ability(
        pokemon.card_def_id, ability_name, state, action, get_player
    )


# ──────────────────────────────────────────────────────────────────────────────
# Attack phase
# ──────────────────────────────────────────────────────────────────────────────

async def _attack(state: GameState, action: Action, get_player=None) -> GameState:
    player = state.get_player(action.player_id)
    if not player.active:
        raise ValueError("No active Pokémon to attack with")

    cdef = card_registry.get(player.active.card_def_id)

    # Unaware (sv08-031 Skeledirge): snapshot non-damage state to restore after attack
    _unaware_snapshot = None
    _unaware_instance_id = None
    _opp_for_unaware = state.get_player(state.opponent_id(action.player_id))
    if _opp_for_unaware.active:
        _def_cdef_unaware = card_registry.get(_opp_for_unaware.active.card_def_id)
        if _def_cdef_unaware and any(
            ab.name == "Unaware"
            for ab in (_def_cdef_unaware.abilities or [])
        ):
            from copy import deepcopy
            _unaware_instance_id = _opp_for_unaware.active.instance_id
            _unaware_snapshot = {
                "status_conditions": set(_opp_for_unaware.active.status_conditions),
                "energy_attached": list(_opp_for_unaware.active.energy_attached),
            }

    # Memory Dive (sv05-084 Relicanth): index >= 200 = prior-form attack
    _is_md_attack = action.attack_index is not None and action.attack_index >= 200
    # TM attack: index 100–199 means attack comes from an attached Tool card
    _is_tm_attack = action.attack_index is not None and 100 <= action.attack_index < 200
    if _is_md_attack:
        _tm_def_id = None
        _tm_atk_idx = 0
        _md_atk_idx = action.attack_index - 200
        _md_pre_evo_inst = player.active.evolved_from if player.active else None
        _md_pre_evo_card = next(
            (c for c in player.discard if c.instance_id == _md_pre_evo_inst), None
        ) if _md_pre_evo_inst else None
        _md_cdef = card_registry.get(_md_pre_evo_card.card_def_id) if _md_pre_evo_card else None
        attack_name = (
            _md_cdef.attacks[_md_atk_idx].name
            if _md_cdef and _md_cdef.attacks and _md_atk_idx < len(_md_cdef.attacks)
            else "Memory Dive Attack"
        )
    elif _is_tm_attack:
        _tm_tool_slot = (action.attack_index - 100) // 10
        _tm_atk_idx = (action.attack_index - 100) % 10
        _tm_def_id = (player.active.tools_attached[_tm_tool_slot]
                      if player.active and _tm_tool_slot < len(player.active.tools_attached)
                      else None)
        _tm_cdef = card_registry.get(_tm_def_id) if _tm_def_id else None
        attack_name = (
            _tm_cdef.attacks[_tm_atk_idx].name
            if _tm_cdef and _tm_cdef.attacks and _tm_atk_idx < len(_tm_cdef.attacks)
            else "TM Attack"
        )
    else:
        _is_tm_attack = False
        _tm_def_id = None
        _tm_atk_idx = 0
        attack_name = (
            cdef.attacks[action.attack_index].name
            if cdef and action.attack_index is not None
            and action.attack_index < len(cdef.attacks)
            else "Attack"
        )

    state.emit_event(
        "attack_declared",
        player=action.player_id,
        attacker=player.active.card_name,
        attack_name=attack_name,
        attack_index=action.attack_index,
    )

    # Confusion: flip a coin; tails = attack fails + 30 self-damage
    from app.engine.state import StatusCondition as _SC_t
    if player.active and _SC_t.CONFUSED in player.active.status_conditions:
        import random as _rnd_confused
        if not _rnd_confused.choice([True, False]):  # tails
            player.active.current_hp -= 30
            player.active.damage_counters += 3
            state.emit_event("confusion_damage", player=action.player_id,
                             attacker=player.active.card_name)
            from app.engine.effects.base import check_ko
            check_ko(state, player.active, action.player_id)
            return state

    # Sand Attack: defender must flip coin; tails = this attack fails
    if player.active and player.active.attack_requires_flip:
        import random as _rnd_sand
        player.active.attack_requires_flip = False
        if not _rnd_sand.choice([True, False]):  # tails
            state.emit_event("sand_attack_blocked", player=action.player_id,
                             attacker=player.active.card_name,
                             attack_name=attack_name)
            return state

    # Torment: check if this Pokémon is blocked from using this specific attack
    if player.active and player.active.torment_blocked_attack_name:
        if attack_name == player.active.torment_blocked_attack_name:
            player.active.torment_blocked_attack_name = None
            state.emit_event("torment_blocked", player=action.player_id,
                             attacker=player.active.card_name, attack=attack_name)
            return state

    # Boomerang Energy (sv06-166): capture count before attack
    _boomerang_attacker_id = player.active.instance_id if player.active else None
    _boomerang_before = (sum(1 for ea in player.active.energy_attached
                             if ea.card_def_id == "sv06-166")
                         if player.active else 0)

    if _is_md_attack:
        _md_atk_idx2 = action.attack_index - 200
        _md_player = state.get_player(action.player_id)
        _md_pre_evo_inst2 = _md_player.active.evolved_from if _md_player.active else None
        _md_pre_evo_card2 = next(
            (c for c in _md_player.discard if c.instance_id == _md_pre_evo_inst2), None
        ) if _md_pre_evo_inst2 else None
        if _md_pre_evo_card2:
            result = await EffectRegistry.instance().resolve_attack(
                _md_pre_evo_card2.card_def_id,
                _md_atk_idx2,
                state,
                action,
                get_player,
            )
        else:
            result = state
    elif _is_tm_attack and _tm_def_id:
        result = await EffectRegistry.instance().resolve_attack(
            _tm_def_id,
            _tm_atk_idx,
            state,
            action,
            get_player,
        )
    else:
        result = await EffectRegistry.instance().resolve_attack(
            player.active.card_def_id,
            action.attack_index or 0,
            state,
            action,
            get_player,
        )

    # Restore Unaware snapshot
    if _unaware_snapshot is not None:
        _opp_after_unaware = result.get_player(state.opponent_id(action.player_id))
        if (_opp_after_unaware.active
                and _opp_after_unaware.active.instance_id == _unaware_instance_id):
            _opp_after_unaware.active.status_conditions = _unaware_snapshot["status_conditions"]
            _opp_after_unaware.active.energy_attached = _unaware_snapshot["energy_attached"]

    # Boomerang Energy re-attach: if attacker is still active and boomerang energy was discarded by the attack
    _result_player = result.get_player(action.player_id)
    if (_boomerang_before > 0
            and _result_player.active is not None
            and _result_player.active.instance_id == _boomerang_attacker_id):
        _boomerang_after = sum(1 for ea in _result_player.active.energy_attached
                               if ea.card_def_id == "sv06-166")
        _reattach_count = _boomerang_before - _boomerang_after
        if _reattach_count > 0:
            import uuid as _buuid
            for _ in range(_reattach_count):
                _result_player.active.energy_attached.append(EnergyAttachment(
                    energy_type=EnergyType.COLORLESS,
                    source_card_id=str(_buuid.uuid4()),
                    card_def_id="sv06-166",
                    provides=[EnergyType.COLORLESS],
                ))
            result.emit_event("boomerang_energy_reattach", player=action.player_id,
                              count=_reattach_count)
    # Track last attack used (for Spiky Rolling, Mochi Rush, etc.)
    if player.active:
        player.active.last_attack_name = attack_name

    # Festival Lead: enable second attack if Festival Grounds is active
    _FESTIVAL_LEAD_IDS = {"sv08.5-010", "sv08.5-020", "sv08.5-021"}
    fl_player = result.get_player(action.player_id)
    if (fl_player.active is not None
            and fl_player.active.card_def_id in _FESTIVAL_LEAD_IDS
            and fl_player.active.current_hp > 0
            and result.active_stadium is not None
            and result.active_stadium.card_def_id == "sv06-149"
            and not fl_player.festival_lead_pending):
        fl_player.festival_lead_pending = True

    return result


# ──────────────────────────────────────────────────────────────────────────────
# Forced actions
# ──────────────────────────────────────────────────────────────────────────────

async def _switch_active(state: GameState, action: Action, get_player=None) -> GameState:
    """Forced switch — used when the active was KO'd and defender promotes."""
    player = state.get_player(action.player_id)
    new_active = _find(player.bench, action.target_instance_id)
    if new_active is None:
        if player.bench:
            new_active = player.bench[0]
        else:
            return state  # No bench to promote from

    new_active.zone = Zone.ACTIVE
    player.active = new_active
    player.bench.remove(new_active)
    new_active.moved_from_bench_this_turn = True

    state.emit_event(
        "switch_active",
        player=action.player_id,
        card=new_active.card_name,
    )

    # Buzzing Boost (sv10-003 Yanmega ex): when promoted from Bench to Active
    if new_active.card_def_id == "sv10-003":
        bb_action = Action(action.action_type, action.player_id,
                           card_instance_id=new_active.instance_id)
        await EffectRegistry.instance().resolve_ability(
            "sv10-003", "Buzzing Boost", state, bb_action, get_player
        )

    return state


async def _use_stadium(state: GameState, action: Action, get_player=None) -> GameState:
    """Activate an optional once-per-turn stadium effect (e.g. Mystery Garden)."""
    if state.active_stadium is None:
        return state
    state.emit_event("use_stadium", player=action.player_id,
                     stadium=state.active_stadium.card_name)
    return await EffectRegistry.instance().resolve_trainer(
        state.active_stadium.card_def_id, state, action, get_player
    )


def _pass(state: GameState, action: Action, get_player=None) -> GameState:
    state.emit_event("pass", player=action.player_id)
    state.phase = Phase.ATTACK
    return state


def _end_turn(state: GameState, action: Action, get_player=None) -> GameState:
    state.emit_event("end_turn", player=action.player_id)
    return state


# ──────────────────────────────────────────────────────────────────────────────
# Dispatch table
# ──────────────────────────────────────────────────────────────────────────────

TRANSITION_MAP: dict[ActionType, Callable[[GameState, Action], GameState]] = {
    ActionType.PLACE_ACTIVE:    _place_active,
    ActionType.PLACE_BENCH:     _place_bench,
    ActionType.MULLIGAN_REDRAW: _mulligan_redraw,
    ActionType.PLAY_BASIC:      _play_basic,
    ActionType.PLAY_SUPPORTER:  _play_supporter,
    ActionType.PLAY_ITEM:       _play_item,
    ActionType.PLAY_STADIUM:    _play_stadium,
    ActionType.PLAY_TOOL:       _play_tool,
    ActionType.ATTACH_ENERGY:   _attach_energy,
    ActionType.EVOLVE:          _evolve,
    ActionType.RETREAT:         _retreat,
    ActionType.USE_ABILITY:     _use_ability,
    ActionType.USE_STADIUM:     _use_stadium,
    ActionType.ATTACK:          _attack,
    ActionType.SWITCH_ACTIVE:   _switch_active,
    ActionType.PASS:            _pass,
    ActionType.END_TURN:        _end_turn,
}


class StateTransition:
    """Thin wrapper around TRANSITION_MAP. Caller must validate first."""

    @staticmethod
    async def apply(state: GameState, action: Action, get_player=None) -> GameState:
        handler = TRANSITION_MAP.get(action.action_type)
        if not handler:
            raise ValueError(f"No transition handler for {action.action_type}")
        result = handler(state, action, get_player)
        if asyncio.iscoroutine(result):
            return await result
        return result
