"""Effect handlers for Pokémon attacks (Batch 6 — Phase 2).

Each handler is registered as:
    register_attack(card_id, attack_index, handler_func)

Handlers that require player choices are generator functions that yield
ChoiceRequest objects and receive back the chosen Action.

Flat-damage-only attacks with no effects are deliberately NOT registered here;
they fall through to EffectRegistry._default_damage which handles them correctly.
"""

from __future__ import annotations

import logging
import random as _random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.engine.state import GameState
    from app.engine.actions import Action

from app.engine.state import (
    EnergyType,
    Phase,
    StatusCondition,
    Zone,
)
from app.engine.effects.base import (
    ChoiceRequest,
    apply_weakness_resistance,
    check_ko,
    draw_cards,
    get_tool_damage_bonus,
    has_tool,
    parse_damage,
)
from app.engine.effects.abilities import (
    has_adrena_power,
    has_adrena_pheromone,
    has_battle_cage,
    has_cornerstone_stance,
    has_flower_curtain,
    has_mysterious_rock_inn,
    has_spherical_shield,
    has_tundra_wall,
    repelling_veil_protects,
)
from app.cards import registry as card_registry

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Shared damage helpers
# ──────────────────────────────────────────────────────────────────────────────

def _apply_damage(
    state: "GameState",
    action: "Action",
    base_damage: int,
    bypass_wr: bool = False,
    bypass_defender_effects: bool = False,
) -> int:
    """Apply base_damage through the standard pipeline and return final_damage.

    Args:
        bypass_wr: Skip weakness/resistance (for Demolish).
        bypass_defender_effects: Skip ability blocks and Payapa Berry
            (for Shred, Superb Scissors, Demolish).
    """
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)

    if not player.active or not opp.active:
        return 0

    attacker = player.active
    defender = opp.active
    cdef = card_registry.get(attacker.card_def_id)
    attack = (cdef.attacks[action.attack_index]
              if cdef and action.attack_index is not None
              and action.attack_index < len(cdef.attacks) else None)

    if base_damage <= 0:
        state.emit_event(
            "attack_no_damage",
            attacker=attacker.card_name,
            attack_name=attack.name if attack else "",
        )
        return 0

    # prevent_damage_one_turn (Marill Hide / Hop's Phantump Splashing Dodge)
    if defender.prevent_damage_one_turn:
        state.emit_event("damage_prevented", card=defender.card_name,
                         reason="prevent_damage_one_turn")
        return 0

    # Resolute Heart (me02.5-057 Pikachu ex): eligible only if at full HP before this attack
    if defender.card_def_id == "me02.5-057":
        defender.resolute_heart_eligible = (
            defender.damage_counters == 0 and defender.current_hp == defender.max_hp
        )

    total = base_damage + state.active_player_damage_bonus
    if state.active_player_damage_bonus_vs_ex:
        def_cdef = card_registry.get(defender.card_def_id)
        if def_cdef and def_cdef.is_ex:
            total += state.active_player_damage_bonus_vs_ex
    if has_adrena_power(attacker):
        total += 100

    if not bypass_wr:
        total = apply_weakness_resistance(total, attacker, defender, state, opp_id)

    if bypass_defender_effects:
        total += _attacker_tool_bonus(attacker, defender, state)
    else:
        total += get_tool_damage_bonus(
            attacker, defender, action.attack_index or 0, state, action.player_id
        )
    total = max(0, total)

    if not bypass_defender_effects:
        if defender.protected_from_ex and cdef and cdef.is_ex:
            total = 0
        elif has_cornerstone_stance(defender, attacker):
            total = 0
        elif has_mysterious_rock_inn(defender, attacker):
            total = 0
        elif has_adrena_pheromone(defender):
            if _random.choice([True, False]):
                state.emit_event(
                    "adrena_pheromone_blocked",
                    player=opp_id,
                    card=defender.card_name,
                )
                total = 0

    total = max(0, total)
    if not bypass_defender_effects and has_tundra_wall(state, opp_id):
        if any(att.energy_type == EnergyType.WATER for att in defender.energy_attached):
            total = max(0, total - 50)
    if not bypass_defender_effects and defender.incoming_damage_reduction > 0:
        total = max(0, total - defender.incoming_damage_reduction)
    defender.current_hp -= total
    defender.damage_counters += total // 10
    state.emit_event(
        "attack_damage",
        attacker=attacker.card_name,
        defender=defender.card_name,
        attack_name=attack.name if attack else "",
        base_damage=base_damage,
        final_damage=total,
    )

    # Counterattack Quills (me02.5-068 Hop's Pincurchin ex): place 3 counters on attacker
    if (defender.card_def_id == "me02.5-068"
            and total > 0
            and attacker.current_hp > 0):
        attacker.current_hp -= 30
        attacker.damage_counters += 3
        state.emit_event("counterattack_quills_triggered",
                         defender=defender.card_name,
                         attacker=attacker.card_name)
        check_ko(state, attacker, action.player_id)
        if state.phase == Phase.GAME_OVER:
            return total

    check_ko(state, defender, opp_id)
    return total


def _attacker_tool_bonus(attacker, defender, state) -> int:
    """Return only the attacker's tool bonuses (used when bypassing defender effects)."""
    if state.active_stadium and state.active_stadium.card_def_id == "sv06-153":
        return 0  # Jamming Tower disables all tools

    bonus = 0
    defender_cdef = card_registry.get(defender.card_def_id)
    attacker_cdef = card_registry.get(attacker.card_def_id)

    if has_tool(attacker, "sv05-154") and defender_cdef and defender_cdef.is_ex:
        bonus += 50
    if (has_tool(attacker, "sv10.5w-080")
            and attacker_cdef and not attacker_cdef.has_rule_box
            and defender_cdef and defender_cdef.is_ex):
        bonus += 30
    if (has_tool(attacker, "sv08.5-095")
            and StatusCondition.POISONED in attacker.status_conditions):
        bonus += 40
    return bonus


def _do_default_damage(state: "GameState", action: "Action") -> "GameState":
    """Run the standard damage pipeline via the registry (for side-effect attacks)."""
    from app.engine.effects.registry import EffectRegistry
    return EffectRegistry.instance()._default_damage(state, action)


def _apply_bench_damage(
    state: "GameState",
    target_player_id: str,
    target,
    damage: int,
) -> None:
    """Apply flat bench damage (no W/R), respecting Battle Cage, Flower Curtain, Spherical Shield."""
    if damage <= 0:
        return
    if has_battle_cage(state):
        state.emit_event("bench_damage_blocked", reason="battle_cage",
                         card=target.card_name)
        return
    if has_spherical_shield(state, target_player_id):
        state.emit_event("bench_damage_blocked", reason="spherical_shield",
                         card=target.card_name)
        return
    cdef = card_registry.get(target.card_def_id)
    if has_flower_curtain(state, target_player_id):
        if cdef and not cdef.has_rule_box:
            state.emit_event("bench_damage_blocked", reason="flower_curtain",
                             card=target.card_name)
            return
    if has_tundra_wall(state, target_player_id):
        if any(att.energy_type == EnergyType.WATER for att in target.energy_attached):
            damage = max(0, damage - 50)
            if damage <= 0:
                state.emit_event("bench_damage_blocked", reason="tundra_wall",
                                 card=target.card_name)
                return
    target.current_hp -= damage
    target.damage_counters += damage // 10
    state.emit_event(
        "bench_damage",
        player=target_player_id,
        card=target.card_name,
        damage=damage,
    )
    check_ko(state, target, target_player_id)


def _place_bench_counters(
    state: "GameState",
    target_player_id: str,
    target,
    counters: int,
) -> None:
    """Place damage counters on a benched Pokémon (same as bench_damage)."""
    _apply_bench_damage(state, target_player_id, target, counters * 10)


def _is_basic_energy(attachment) -> bool:
    """True if this EnergyAttachment is from a basic energy card."""
    from app.engine.effects.trainers import _is_basic_energy_cdef as _bec
    return _bec(card_registry.get(attachment.card_def_id))


def _in_play(player):
    """All Pokémon in play (active + bench)."""
    pokes = []
    if player.active:
        pokes.append(player.active)
    pokes.extend(player.bench)
    return pokes


def _is_tr_pokemon(pokemon) -> bool:
    """True if this Pokémon's name contains 'Team Rocket's'."""
    return "Team Rocket's" in pokemon.card_name


# ──────────────────────────────────────────────────────────────────────────────
# Category 1: Multi-turn attack locks
# ──────────────────────────────────────────────────────────────────────────────

def _prism_edge(state, action):
    """sv05-025 Iron Leaves ex atk0 — Prism Edge: 180 + can't attack next turn."""
    _do_default_damage(state, action)
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=player.active.card_name,
                         attack="Prism Edge")


def _blood_moon(state, action):
    """sv06-141 Bloodmoon Ursaluna ex atk0 — Blood Moon: 240 + can't attack next turn.

    Seasoned Skill cost reduction is handled in actions.py._get_attack_actions.
    """
    _do_default_damage(state, action)
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=player.active.card_name,
                         attack="Blood Moon")


def _eon_blade(state, action):
    """sv08-076 Latias ex atk0 — Eon Blade: 200 + can't attack next turn."""
    _do_default_damage(state, action)
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=player.active.card_name,
                         attack="Eon Blade")


def _smolder_sault(state, action):
    """sv09-024 Blaziken ex atk0 — Smolder-sault: 200 + can't attack next turn."""
    _do_default_damage(state, action)
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=player.active.card_name,
                         attack="Smolder-sault")


def _rampaging_thunder(state, action):
    """me02.5-155 N's Zekrom atk1 — Rampaging Thunder: 250 + can't attack next turn."""
    _do_default_damage(state, action)
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=player.active.card_name,
                         attack="Rampaging Thunder")


# ──────────────────────────────────────────────────────────────────────────────
# Category 2: Can't-retreat locks
# ──────────────────────────────────────────────────────────────────────────────

def _clutch(state, action):
    """me01-088 Yveltal atk0 — Clutch: 20 + defending can't retreat next turn."""
    _do_default_damage(state, action)
    opp = state.get_opponent(action.player_id)
    if opp.active and state.phase != Phase.GAME_OVER:
        opp.active.cant_retreat_next_turn = True
        state.emit_event("cant_retreat", card=opp.active.card_name)


def _sob(state, action):
    """sv06-064 Wellspring Mask Ogerpon ex atk0 — Sob: 20 + defending can't retreat."""
    _do_default_damage(state, action)
    opp = state.get_opponent(action.player_id)
    if opp.active and state.phase != Phase.GAME_OVER:
        opp.active.cant_retreat_next_turn = True
        state.emit_event("cant_retreat", card=opp.active.card_name)


def _shadow_bind(state, action):
    """sv08.5-037 Dusknoir atk0 — Shadow Bind: 150 + defending can't retreat."""
    _do_default_damage(state, action)
    opp = state.get_opponent(action.player_id)
    if opp.active and state.phase != Phase.GAME_OVER:
        opp.active.cant_retreat_next_turn = True
        state.emit_event("cant_retreat", card=opp.active.card_name)


# ──────────────────────────────────────────────────────────────────────────────
# Category 3: Status conditions
# ──────────────────────────────────────────────────────────────────────────────

def _absolute_snow(state, action):
    """me02.5-047 Mega Froslass ex atk1 — Absolute Snow: 150 + Asleep."""
    _do_default_damage(state, action)
    opp = state.get_opponent(action.player_id)
    if opp.active and state.phase != Phase.GAME_OVER:
        opp.active.status_conditions.add(StatusCondition.ASLEEP)
        state.emit_event("status_applied", status="asleep",
                         card=opp.active.card_name)


def _numbing_water(state, action):
    """sv06-057 Frogadier atk0 — Numbing Water: 20 + flip, heads → Paralyzed."""
    _do_default_damage(state, action)
    opp = state.get_opponent(action.player_id)
    if opp.active and state.phase != Phase.GAME_OVER:
        if _random.choice([True, False]):
            opp.active.status_conditions.add(StatusCondition.PARALYZED)
            state.emit_event("status_applied", status="paralyzed",
                             card=opp.active.card_name)


def _mind_bend(state, action):
    """sv06-095 Munkidori atk0 — Mind Bend: 60 + Confused."""
    _do_default_damage(state, action)
    opp = state.get_opponent(action.player_id)
    if opp.active and state.phase != Phase.GAME_OVER:
        opp.active.status_conditions.add(StatusCondition.CONFUSED)
        state.emit_event("status_applied", status="confused",
                         card=opp.active.card_name)


def _poison_spray(state, action):
    """sv06-118 Brute Bonnet atk0 — Poison Spray: Poison opponent's active.

    Does 0 base damage; the poisoning is the whole effect.
    Repelling Veil (sv10-051 TR Articuno) blocks effect on Basic TR Pokémon.
    """
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_opponent(action.player_id)
    if not opp.active:
        return
    if repelling_veil_protects(opp.active, state, opp_id):
        state.emit_event("effect_blocked", reason="repelling_veil",
                         card=opp.active.card_name)
        return
    opp.active.status_conditions.add(StatusCondition.POISONED)
    state.emit_event("status_applied", status="poisoned", card=opp.active.card_name)


def _poison_chain(state, action):
    """svp-149 Pecharunt atk0 — Poison Chain: 40 damage + TOXIC (3 counters/turn).

    Repelling Veil blocks the status application.
    """
    _do_default_damage(state, action)
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_opponent(action.player_id)
    if opp.active and state.phase != Phase.GAME_OVER:
        if repelling_veil_protects(opp.active, state, opp_id):
            state.emit_event("effect_blocked", reason="repelling_veil",
                             card=opp.active.card_name)
            return
        opp.active.status_conditions.discard(StatusCondition.POISONED)
        opp.active.status_conditions.add(StatusCondition.TOXIC)
        state.emit_event("status_applied", status="toxic",
                         card=opp.active.card_name)


# ──────────────────────────────────────────────────────────────────────────────
# Category 4: Draw and search effects
# ──────────────────────────────────────────────────────────────────────────────

def _double_draw(state, action):
    """me03-042 Binacle atk0 — Double Draw: draw 2 cards."""
    draw_cards(state, action.player_id, 2)


def _allure(state, action):
    """sv06-039 Chi-Yu atk0 — Allure: draw 2 cards."""
    draw_cards(state, action.player_id, 2)


def _collect(state, action):
    """sv10-040 Torchic atk0 — Collect: draw 1 card."""
    draw_cards(state, action.player_id, 1)


def _filch(state, action):
    """sv10-134 Marnie's Impidimp atk0 — Filch: draw 1 card."""
    draw_cards(state, action.player_id, 1)


def _shinobi_blade(state, action):
    """sv06-106 Greninja ex atk0 — Shinobi Blade: 170 + search deck for any card."""
    _do_default_damage(state, action)
    player = state.get_player(action.player_id)
    if not player.deck or state.phase == Phase.GAME_OVER:
        return

    req = ChoiceRequest(
        "choose_cards",
        action.player_id,
        "Shinobi Blade: search your deck for any 1 card to put into your hand",
        cards=list(player.deck),
        min_count=0,
        max_count=1,
    )
    resp = yield req

    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids and player.deck:
        chosen_ids = [player.deck[0].instance_id]

    for cid in chosen_ids:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    _shuffle_deck(player)
    state.emit_event("search_deck", player=action.player_id, count=len(chosen_ids))


def _call_sign(state, action):
    """me01-059 Kirlia atk0 — Call Sign: search deck for up to 3 Pokémon, put into hand."""
    player = state.get_player(action.player_id)
    if not player.deck:
        return

    poke_in_deck = [c for c in player.deck if c.card_type.lower() == "pokemon"]
    if not poke_in_deck:
        _shuffle_deck(player)
        return

    max_count = min(3, len(poke_in_deck))
    req = ChoiceRequest(
        "choose_cards",
        action.player_id,
        "Call Sign: search your deck for up to 3 Pokémon to put into your hand",
        cards=poke_in_deck,
        min_count=0,
        max_count=max_count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in poke_in_deck[:max_count]]

    for cid in chosen_ids:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    _shuffle_deck(player)
    state.emit_event("search_deck", player=action.player_id, count=len(chosen_ids))



def _call_for_family(state, action):
    """me02-067 Toxel atk0 — Call for Family: search deck for up to 2 Basic Pokémon."""
    player = state.get_player(action.player_id)
    available_slots = 5 - len(player.bench)
    if available_slots <= 0 or not player.deck:
        return

    basics = [c for c in player.deck if c.card_type.lower() == "pokemon"
              and c.card_subtype.lower() == "basic"]
    if not basics:
        return

    max_count = min(2, available_slots, len(basics))
    req = ChoiceRequest(
        "choose_cards",
        action.player_id,
        "Call for Family: search your deck for up to 2 Basic Pokémon to put on your Bench",
        cards=basics,
        min_count=0,
        max_count=max_count,
    )
    resp = yield req

    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in basics[:max_count]]

    placed = 0
    for cid in chosen_ids:
        if len(player.bench) >= 5:
            break
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.BENCH
            card.turn_played = state.turn_number
            player.bench.append(card)
            placed += 1
    _shuffle_deck(player)
    state.emit_event("bench_pokemon", player=action.player_id, count=placed)


def _come_and_get_you(state, action):
    """sv08.5-035 Duskull atk0 — Come and Get You: put up to 3 Duskull from discard to bench."""
    player = state.get_player(action.player_id)
    available_slots = 5 - len(player.bench)
    if available_slots <= 0:
        return

    duskulls = [c for c in player.discard if c.card_def_id == "sv08.5-035"]
    if not duskulls:
        return

    max_count = min(3, available_slots, len(duskulls))
    req = ChoiceRequest(
        "choose_cards",
        action.player_id,
        "Come and Get You: choose up to 3 Duskull from your discard to put on Bench",
        cards=duskulls,
        min_count=0,
        max_count=max_count,
    )
    resp = yield req

    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in duskulls[:max_count]]

    placed = 0
    for cid in chosen_ids:
        if len(player.bench) >= 5:
            break
        card = next((c for c in player.discard if c.instance_id == cid), None)
        if card:
            player.discard.remove(card)
            card.zone = Zone.BENCH
            card.turn_played = state.turn_number
            player.bench.append(card)
            placed += 1
    state.emit_event("discard_to_bench", player=action.player_id, count=placed)


# ──────────────────────────────────────────────────────────────────────────────
# Category 5: Variable damage
# ──────────────────────────────────────────────────────────────────────────────

def _powerful_hand(state, action):
    """me01-056 Alakazam atk0 — Powerful Hand: place 2 damage counters per card in hand.

    Damage counters placed directly — no W/R, no ability blocks.
    """
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.active:
        return

    counters = 2 * len(player.hand)
    if counters <= 0:
        state.emit_event("attack_no_damage", attacker="Alakazam", attack_name="Powerful Hand")
        return

    damage = counters * 10
    opp.active.current_hp -= damage
    opp.active.damage_counters += counters
    state.emit_event("attack_damage", attacker="Alakazam", defender=opp.active.card_name,
                     attack_name="Powerful Hand", base_damage=damage, final_damage=damage)
    check_ko(state, opp.active, opp_id)


def _terminal_period(state, action):
    """me01-086 Mega Absol ex atk0 — Terminal Period: KO if exactly 6 damage counters."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.active:
        return

    if opp.active.damage_counters == 6:
        opp.active.current_hp = 0
        state.emit_event("instant_ko", card=opp.active.card_name, reason="Terminal Period")
        check_ko(state, opp.active, opp_id)
    else:
        state.emit_event("attack_no_damage", attacker="Mega Absol ex",
                         attack_name="Terminal Period")


def _claw_of_darkness(state, action):
    """me01-086 Mega Absol ex atk1 — Claw of Darkness: 200 + discard from opp hand."""
    _do_default_damage(state, action)
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.hand or state.phase == Phase.GAME_OVER:
        return

    req = ChoiceRequest(
        "choose_cards",
        action.player_id,
        "Claw of Darkness: choose 1 card from your opponent's hand to discard",
        cards=list(opp.hand),
        min_count=1,
        max_count=1,
    )
    resp = yield req

    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [opp.hand[0].instance_id] if opp.hand else []

    for cid in chosen_ids:
        card = next((c for c in opp.hand if c.instance_id == cid), None)
        if card:
            opp.hand.remove(card)
            card.zone = Zone.DISCARD
            opp.discard.append(card)
            state.emit_event("discard_from_hand", player=opp_id, card=card.card_name,
                             reason="Claw of Darkness")


def _rapid_fire_combo(state, action):
    """me01-104 Mega Kangaskhan ex atk0 — Rapid-Fire Combo: flip until tails, +50/heads."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not player.active or not opp.active:
        return

    heads_count = 0
    while _random.choice([True, False]):
        heads_count += 1

    base_damage = 200 + 50 * heads_count
    state.emit_event("coin_flip_result", attack="Rapid-Fire Combo", heads=heads_count)
    _apply_damage(state, action, base_damage)


def _fighting_wings(state, action):
    """me02-014 Moltres atk0 — Fighting Wings: 20 + 90 if opponent's active is EX."""
    opp = state.get_opponent(action.player_id)
    base_damage = 20
    if opp.active:
        opp_cdef = card_registry.get(opp.active.card_def_id)
        if opp_cdef and opp_cdef.is_ex:
            base_damage += 90
    _apply_damage(state, action, base_damage)


def _growl(state, action):
    """me02.5-008 Chikorita atk0 — Growl: opponent's attacks do 20 less damage next turn."""
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.attack_damage_reduction += 20
        state.emit_event("attack_reduction", card=opp.active.card_name, reduction=20)


def _resentful_refrain(state, action):
    """me02.5-047 Mega Froslass ex atk0 — Resentful Refrain: 50 damage × opponent's hand size."""
    opp = state.get_opponent(action.player_id)
    if not opp.active:
        return
    base_damage = 50 * len(opp.hand)
    _apply_damage(state, action, base_damage)


def _cosmic_beam(state, action):
    """me01-075 Solrock atk0 — Cosmic Beam: 70 if Lunatone on bench; no W/R."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)

    has_lunatone = any(p.card_def_id == "me01-074" for p in player.bench)
    if not has_lunatone:
        state.emit_event("attack_no_damage", attacker="Solrock", attack_name="Cosmic Beam",
                         reason="no Lunatone on bench")
        return

    if not opp.active:
        return

    damage = 70
    opp.active.current_hp -= damage
    opp.active.damage_counters += damage // 10
    state.emit_event("attack_damage", attacker="Solrock", defender=opp.active.card_name,
                     attack_name="Cosmic Beam", base_damage=damage, final_damage=damage)
    check_ko(state, opp.active, opp_id)


def _shred(state, action):
    """me02.5-155 N's Zekrom atk0 — Shred: 70, not affected by effects on opponent's active."""
    _apply_damage(state, action, 70, bypass_wr=False, bypass_defender_effects=True)


def _ground_melter(state, action):
    """sv06-039 Chi-Yu atk1 — Ground Melter: 60 + 60 if stadium; discard the stadium."""
    base_damage = 60
    if state.active_stadium:
        base_damage += 60
        discarded_stadium = state.active_stadium
        state.active_stadium = None
        state.emit_event("stadium_discarded", card=discarded_stadium.card_name,
                         reason="Ground Melter")
    _apply_damage(state, action, base_damage)


def _love_resonance(state, action):
    """sv06-093 Enamorus atk1 — Love Resonance: 80 + 120 if shared type in play."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)

    player_types: set[str] = set()
    for p in _in_play(player):
        cdef = card_registry.get(p.card_def_id)
        if cdef:
            player_types.update(t.lower() for t in (cdef.types or []))

    opp_types: set[str] = set()
    for p in _in_play(opp):
        cdef = card_registry.get(p.card_def_id)
        if cdef:
            opp_types.update(t.lower() for t in (cdef.types or []))

    base_damage = 80
    if player_types & opp_types:
        base_damage += 120
    _apply_damage(state, action, base_damage)


def _energy_feather(state, action):
    """sv06-096 Fezandipiti atk0 — Energy Feather: 30 × energy attached to self."""
    player = state.get_player(action.player_id)
    if not player.active:
        return
    base_damage = 30 * len(player.active.energy_attached)
    _apply_damage(state, action, base_damage)


def _demolish(state, action):
    """sv06-112 Cornerstone Mask Ogerpon ex atk0 — Demolish: 140, not affected by W/R or effects."""
    _apply_damage(state, action, 140, bypass_wr=True, bypass_defender_effects=True)


def _relentless_punches(state, action):
    """sv06-118 Brute Bonnet atk1 — Relentless Punches: 50 + 50 × opp damage counters."""
    opp = state.get_opponent(action.player_id)
    if not opp.active:
        return
    base_damage = 50 + 50 * opp.active.damage_counters
    _apply_damage(state, action, base_damage)


def _irritated_outburst(state, action):
    """sv06.5-039 Pecharunt ex atk0 — Irritated Outburst: 60 × prizes opponent has taken."""
    opp = state.get_opponent(action.player_id)
    prizes_taken = 6 - opp.prizes_remaining
    base_damage = 60 * prizes_taken
    _apply_damage(state, action, base_damage)


def _coordinated_throwing(state, action):
    """sv08-111 Passimian atk0 — Coordinated Throwing: 20 × basic Pokémon in player's play."""
    player = state.get_player(action.player_id)
    basic_count = 0
    for p in _in_play(player):
        cdef = card_registry.get(p.card_def_id)
        if cdef and cdef.stage.lower() == "basic":
            basic_count += 1
    base_damage = 20 * basic_count
    _apply_damage(state, action, base_damage)


def _mad_bite(state, action):
    """sv08.5-054 Bloodmoon Ursaluna atk0 — Mad Bite: 100 + 30 × opp damage counters."""
    opp = state.get_opponent(action.player_id)
    if not opp.active:
        return
    base_damage = 100 + 30 * opp.active.damage_counters
    _apply_damage(state, action, base_damage)


def _back_draft(state, action):
    """sv09-027 N's Darmanitan atk0 — Back Draft: 30 × basic energy in opp's discard."""
    opp = state.get_opponent(action.player_id)
    basic_energy_count = sum(
        1 for c in opp.discard
        if c.card_type.lower() == "energy" and c.card_subtype.lower() == "basic"
    )
    base_damage = 30 * basic_energy_count
    _apply_damage(state, action, base_damage)


def _full_moon_rondo(state, action):
    """sv09-056 Lillie's Clefairy ex atk0 — Full Moon Rondo: 20 + 20 × benched (both sides)."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    total_benched = len(player.bench) + len(opp.bench)
    base_damage = 20 + 20 * total_benched
    _apply_damage(state, action, base_damage)


def _powerful_rage(state, action):
    """sv09-116 N's Reshiram atk0 — Powerful Rage: 20 × damage counters on self."""
    player = state.get_player(action.player_id)
    if not player.active:
        return
    base_damage = 20 * player.active.damage_counters
    _apply_damage(state, action, base_damage)


def _superb_scissors(state, action):
    """sv10-012 Crustle atk0 — Superb Scissors: 120, not affected by effects on opp's active."""
    _apply_damage(state, action, 120, bypass_wr=False, bypass_defender_effects=True)


def _rocket_rush(state, action):
    """sv10-020 TR Spidops atk0 — Rocket Rush: 30 × Team Rocket's Pokémon in player's play."""
    player = state.get_player(action.player_id)
    tr_count = sum(1 for p in _in_play(player) if _is_tr_pokemon(p))
    base_damage = 30 * tr_count
    _apply_damage(state, action, base_damage)


def _double_kick(state, action):
    """sv10-041 Combusken atk1 — Double Kick: flip 2 coins, 40 per heads."""
    heads = sum(1 for _ in range(2) if _random.choice([True, False]))
    state.emit_event("coin_flip_result", attack="Double Kick", heads=heads, flips=2)
    if heads == 0:
        state.emit_event("attack_no_damage", attacker="Combusken", attack_name="Double Kick")
        return
    _apply_damage(state, action, 40 * heads)


def _dark_frost(state, action):
    """sv10-051 TR Articuno atk0 — Dark Frost: 60 + 60 if TR Energy attached."""
    player = state.get_player(action.player_id)
    base_damage = 60
    _TR_ENERGY_ID = "sv10-182"  # Team Rocket's Energy
    if player.active and any(att.card_def_id == _TR_ENERGY_ID
                             for att in player.active.energy_attached):
        base_damage += 60
    _apply_damage(state, action, base_damage)


# ──────────────────────────────────────────────────────────────────────────────
# Category 6: Bench damage
# ──────────────────────────────────────────────────────────────────────────────

def _torrential_pump(state, action):
    """sv06-064 Wellspring Mask Ogerpon ex atk1 — Torrential Pump.

    100 damage. Optionally shuffle 3 Energy into deck; if so,
    +120 damage to 1 of opponent's Benched Pokémon (no W/R).
    """
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return

    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not player.active or not opp.bench:
        return

    energy_on_self = list(player.active.energy_attached)
    if len(energy_on_self) < 3:
        return  # Not enough energy to trigger bonus

    req_opt = ChoiceRequest(
        "choose_option",
        action.player_id,
        "Torrential Pump: shuffle 3 Energy to your deck for +120 bench damage?",
        options=["Shuffle 3 Energy (take bonus)", "Skip"],
    )
    resp_opt = yield req_opt
    option_index = 0  # Default: take the bonus
    if resp_opt and hasattr(resp_opt, "option_index") and resp_opt.option_index is not None:
        option_index = resp_opt.option_index

    if option_index == 1:
        return  # Player chose to skip

    req_energy = ChoiceRequest(
        "choose_cards",
        action.player_id,
        "Torrential Pump: choose 3 Energy from this Pokémon to shuffle into your deck",
        cards=energy_on_self,
        min_count=3,
        max_count=3,
    )
    resp_energy = yield req_energy
    chosen_ids = (resp_energy.chosen_card_ids
                  if resp_energy and hasattr(resp_energy, "chosen_card_ids")
                  and resp_energy.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [a.source_card_id for a in energy_on_self[:3]]

    shuffled = 0
    for cid in chosen_ids[:3]:
        att = next((a for a in player.active.energy_attached
                    if a.source_card_id == cid), None)
        if att:
            player.active.energy_attached.remove(att)
            shuffled += 1
    if shuffled < 3:
        return  # Failed to discard 3; abort bonus

    state.emit_event("energy_shuffled_to_deck", player=action.player_id, count=shuffled)

    req_target = ChoiceRequest(
        "choose_target",
        action.player_id,
        "Torrential Pump: choose 1 of opponent's Benched Pokémon for +120 damage",
        targets=list(opp.bench),
    )
    resp_target = yield req_target
    target = None
    if resp_target and hasattr(resp_target, "target_instance_id") and resp_target.target_instance_id:
        target = next((p for p in opp.bench
                       if p.instance_id == resp_target.target_instance_id), None)
    if target is None and opp.bench:
        target = opp.bench[0]
    if target:
        _apply_bench_damage(state, opp_id, target, 120)


def _mirage_barrage(state, action):
    """sv06-106 Greninja ex atk1 — Mirage Barrage: discard 2 energy, 120 to 2 opp Pokémon.

    No W/R for bench targets.
    """
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)

    if not player.active:
        return

    energy_on_self = list(player.active.energy_attached)
    if len(energy_on_self) < 2:
        state.emit_event("attack_failed", attack="Mirage Barrage", reason="insufficient energy")
        return

    req_energy = ChoiceRequest(
        "choose_cards",
        action.player_id,
        "Mirage Barrage: choose 2 Energy to discard from Greninja ex",
        cards=energy_on_self,
        min_count=2,
        max_count=2,
    )
    resp_energy = yield req_energy
    chosen_ids = (resp_energy.chosen_card_ids
                  if resp_energy and hasattr(resp_energy, "chosen_card_ids")
                  and resp_energy.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [a.source_card_id for a in energy_on_self[:2]]

    for cid in chosen_ids[:2]:
        att = next((a for a in player.active.energy_attached
                    if a.source_card_id == cid), None)
        if att:
            player.active.energy_attached.remove(att)

    all_opp_pokemon = (([opp.active] if opp.active else []) + list(opp.bench))
    if not all_opp_pokemon:
        return

    for hit_num in range(2):
        req_target = ChoiceRequest(
            "choose_target",
            action.player_id,
            f"Mirage Barrage: choose target {hit_num + 1}/2 (120 damage, no W/R for bench)",
            targets=all_opp_pokemon,
        )
        resp_target = yield req_target
        target = None
        if resp_target and hasattr(resp_target, "target_instance_id") and resp_target.target_instance_id:
            target = next((p for p in all_opp_pokemon
                           if p.instance_id == resp_target.target_instance_id), None)
        if target is None:
            target = all_opp_pokemon[0]

        if target is opp.active:
            target.current_hp -= 120
            target.damage_counters += 12
            state.emit_event("attack_damage", attacker="Greninja ex",
                             defender=target.card_name, attack_name="Mirage Barrage",
                             base_damage=120, final_damage=120)
            check_ko(state, target, opp_id)
        else:
            _apply_bench_damage(state, opp_id, target, 120)

        if state.phase == Phase.GAME_OVER:
            return


def _phantom_dive(state, action):
    """sv06-130 Dragapult ex atk1 — Phantom Dive: 200 to active + 6 counters on bench."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return

    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)

    for counter_num in range(6):
        if not opp.bench:
            break
        req = ChoiceRequest(
            "choose_target",
            action.player_id,
            f"Phantom Dive: place damage counter {counter_num + 1}/6 on a Benched Pokémon",
            targets=list(opp.bench),
        )
        resp = yield req
        target = None
        if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
            target = next((p for p in opp.bench
                           if p.instance_id == resp.target_instance_id), None)
        if target is None and opp.bench:
            target = opp.bench[0]
        if target:
            _place_bench_counters(state, opp_id, target, 1)
        if state.phase == Phase.GAME_OVER:
            return


def _flamebody_cannon(state, action):
    """sv09-027 N's Darmanitan atk1 — Flamebody Cannon: 90 + discard all energy + 90 bench."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return

    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)

    if player.active:
        count = len(player.active.energy_attached)
        player.active.energy_attached.clear()
        if count > 0:
            state.emit_event("energy_discarded", player=action.player_id,
                             count=count, reason="Flamebody Cannon")

    if not opp.bench:
        return

    req = ChoiceRequest(
        "choose_target",
        action.player_id,
        "Flamebody Cannon: choose 1 of opponent's Benched Pokémon for 90 damage",
        targets=list(opp.bench),
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in opp.bench
                       if p.instance_id == resp.target_instance_id), None)
    if target is None and opp.bench:
        target = opp.bench[0]
    if target:
        _apply_bench_damage(state, opp_id, target, 90)


def _oil_salvo(state, action):
    """sv10-023 Arboliva ex atk0 — Oil Salvo: choose 1 of opp's Pokémon 6 times, 30 counters each."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)

    all_opp = (([opp.active] if opp.active else []) + list(opp.bench))
    if not all_opp:
        return

    for pick_num in range(6):
        all_opp = (([opp.active] if opp.active else []) + list(opp.bench))
        if not all_opp:
            break
        req = ChoiceRequest(
            "choose_target",
            action.player_id,
            f"Oil Salvo: pick {pick_num + 1}/6 — place 3 damage counters on target",
            targets=all_opp,
        )
        resp = yield req
        target = None
        if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
            target = next((p for p in all_opp
                           if p.instance_id == resp.target_instance_id), None)
        if target is None:
            target = all_opp[0]

        if target is opp.active:
            target.current_hp -= 30
            target.damage_counters += 3
            state.emit_event("damage_counters_placed", player=opp_id,
                             card=target.card_name, counters=3)
            check_ko(state, target, opp_id)
        else:
            _place_bench_counters(state, opp_id, target, 3)

        if state.phase == Phase.GAME_OVER:
            return


def _erasure_ball(state, action):
    """sv10-081 TR Mewtwo ex atk0 — Erasure Ball: 160 + discard up to 2 bench energy + 60/each."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)

    all_bench_energy: list = []
    for bench_poke in opp.bench:
        for att in bench_poke.energy_attached:
            all_bench_energy.append((bench_poke, att))

    if not all_bench_energy:
        _apply_damage(state, action, 160)
        return

    energy_structs = [att for (_, att) in all_bench_energy]
    req = ChoiceRequest(
        "choose_cards",
        action.player_id,
        "Erasure Ball: discard up to 2 Energy from opponent's Benched Pokémon (+60 each)",
        cards=energy_structs,
        min_count=0,
        max_count=2,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [att.source_card_id for (_, att) in all_bench_energy[:2]]

    discarded = 0
    for src_id in chosen_ids:
        for bench_poke, att in list(all_bench_energy):
            if att.source_card_id == src_id and att in bench_poke.energy_attached:
                bench_poke.energy_attached.remove(att)
                discarded += 1
                state.emit_event("energy_discarded", player=opp_id,
                                 card=bench_poke.card_name, reason="Erasure Ball")
                break

    base_damage = 160 + 60 * discarded
    _apply_damage(state, action, base_damage)


def _strike_the_sleeper(state, action):
    """sv10-128 TR Sneasel atk1 — Strike the Sleeper: 20 × bench damage counters on target."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)

    if not opp.bench:
        state.emit_event("attack_no_damage", attacker="TR Sneasel",
                         attack_name="Strike the Sleeper", reason="no benched Pokémon")
        return

    req = ChoiceRequest(
        "choose_target",
        action.player_id,
        "Strike the Sleeper: choose 1 of opponent's Benched Pokémon",
        targets=list(opp.bench),
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in opp.bench
                       if p.instance_id == resp.target_instance_id), None)
    if target is None and opp.bench:
        target = max(opp.bench, key=lambda p: p.damage_counters)

    if target:
        if repelling_veil_protects(target, state, opp_id):
            state.emit_event("effect_blocked", reason="repelling_veil",
                             card=target.card_name)
            return
        damage = 20 * target.damage_counters
        _apply_bench_damage(state, opp_id, target, damage)


def _shadow_bullet(state, action):
    """sv10-136 Marnie's Grimmsnarl ex atk0 — Shadow Bullet: 180 + 30 to 1 benched."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return

    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.bench:
        return

    req = ChoiceRequest(
        "choose_target",
        action.player_id,
        "Shadow Bullet: choose 1 of opponent's Benched Pokémon for 30 damage",
        targets=list(opp.bench),
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in opp.bench
                       if p.instance_id == resp.target_instance_id), None)
    if target is None and opp.bench:
        target = opp.bench[0]
    if target:
        _apply_bench_damage(state, opp_id, target, 30)


def _myriad_leaf_shower(state, action):
    """sv06-025 Teal Mask Ogerpon ex atk0 — Myriad Leaf Shower: 30 + 30 × energy on both actives."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    total_energy = 0
    if player.active:
        total_energy += len(player.active.energy_attached)
    if opp.active:
        total_energy += len(opp.active.energy_attached)
    base_damage = 30 + 30 * total_energy
    _apply_damage(state, action, base_damage)


# ──────────────────────────────────────────────────────────────────────────────
# Category 7: Self-manipulation
# ──────────────────────────────────────────────────────────────────────────────

def _teleportation_attack(state, action):
    """me01-054 Abra atk0 — Teleportation Attack: 10 damage + switch self with bench."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return

    player = state.get_player(action.player_id)
    if not player.bench:
        return

    req = ChoiceRequest(
        "choose_target",
        action.player_id,
        "Teleportation Attack: choose a Benched Pokémon to switch with Abra",
        targets=list(player.bench),
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in player.bench
                       if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = player.bench[0]
    _switch_active_with_bench(player, target)
    state.emit_event("self_switch", player=action.player_id,
                     new_active=player.active.card_name)


def _push_down(state, action):
    """me01-009 Bayleef atk0 — Push Down: 50 + switch opp active to bench; opp picks new active."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return

    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.bench:
        return

    old_active = opp.active
    opp.active = None
    if old_active:
        old_active.zone = Zone.BENCH
        opp.bench.append(old_active)

    req = ChoiceRequest(
        "choose_target",
        opp_id,
        "Push Down: choose your new Active Pokémon from the Bench",
        targets=list(opp.bench),
    )
    resp = yield req
    new_active = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        new_active = next((p for p in opp.bench
                           if p.instance_id == resp.target_instance_id), None)
    if new_active is None and opp.bench:
        new_active = opp.bench[0]
    if new_active:
        opp.bench.remove(new_active)
        new_active.zone = Zone.ACTIVE
        opp.active = new_active
        state.emit_event("forced_switch", player=opp_id,
                         new_active=opp.active.card_name)


def _tuck_tail(state, action):
    """me03-062 Meowth ex atk0 — Tuck Tail: 60 damage + put self and attached cards into hand."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return

    player = state.get_player(action.player_id)
    if not player.active:
        return

    meowth = player.active
    meowth.energy_attached.clear()
    meowth.tools_attached.clear()

    player.active = None
    meowth.zone = Zone.HAND
    player.hand.append(meowth)
    state.emit_event("self_bounce", player=action.player_id, card=meowth.card_name)


def _burst_roar(state, action):
    """sv05-123 Raging Bolt ex atk0 — Burst Roar: discard hand, draw 6."""
    player = state.get_player(action.player_id)
    for card in list(player.hand):
        player.hand.remove(card)
        card.zone = Zone.DISCARD
        player.discard.append(card)
    state.emit_event("hand_discarded", player=action.player_id, reason="Burst Roar")
    draw_cards(state, action.player_id, 6)


def _bellowing_thunder(state, action):
    """sv05-123 Raging Bolt ex atk1 — Bellowing Thunder: 70 × basic energy discarded from Pokémon."""
    player = state.get_player(action.player_id)

    all_basic_energy: list = []
    for poke in _in_play(player):
        for att in poke.energy_attached:
            if _is_basic_energy(att):
                all_basic_energy.append((poke, att))

    if not all_basic_energy:
        state.emit_event("attack_no_damage", attacker="Raging Bolt ex",
                         attack_name="Bellowing Thunder")
        return

    energy_structs = [att for (_, att) in all_basic_energy]
    req = ChoiceRequest(
        "choose_cards",
        action.player_id,
        "Bellowing Thunder: choose any amount of Basic Energy from your Pokémon to discard (+70 each)",
        cards=energy_structs,
        min_count=0,
        max_count=len(energy_structs),
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        # Greedy: discard all for max damage
        chosen_ids = [att.source_card_id for (_, att) in all_basic_energy]

    discarded = 0
    for src_id in chosen_ids:
        for poke, att in list(all_basic_energy):
            if att.source_card_id == src_id and att in poke.energy_attached:
                poke.energy_attached.remove(att)
                discarded += 1
                break

    base_damage = 70 * discarded
    if base_damage <= 0:
        state.emit_event("attack_no_damage", attacker="Raging Bolt ex",
                         attack_name="Bellowing Thunder")
        return
    _apply_damage(state, action, base_damage)


def _icicle_loop(state, action):
    """sv08-056 Chien-Pao atk0 — Icicle Loop: 120 + put 1 energy from self into hand."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return

    player = state.get_player(action.player_id)
    if not player.active or not player.active.energy_attached:
        return

    energy_on_self = list(player.active.energy_attached)
    req = ChoiceRequest(
        "choose_cards",
        action.player_id,
        "Icicle Loop: choose 1 Energy from Chien-Pao to put into your hand",
        cards=energy_on_self,
        min_count=1,
        max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [energy_on_self[0].source_card_id]

    for src_id in chosen_ids[:1]:
        att = next((a for a in player.active.energy_attached
                    if a.source_card_id == src_id), None)
        if att:
            player.active.energy_attached.remove(att)
            state.emit_event("energy_to_hand", player=action.player_id,
                             card_def_id=att.card_def_id)


def _trading_places(state, action):
    """sv09-120 Dunsparce atk0 — Trading Places: switch self with bench."""
    player = state.get_player(action.player_id)
    if not player.bench:
        state.emit_event("attack_no_damage", attacker="Dunsparce",
                         attack_name="Trading Places", reason="no bench")
        return

    req = ChoiceRequest(
        "choose_target",
        action.player_id,
        "Trading Places: choose a Benched Pokémon to switch with Dunsparce",
        targets=list(player.bench),
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in player.bench
                       if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = player.bench[0]
    _switch_active_with_bench(player, target)
    state.emit_event("self_switch", player=action.player_id,
                     new_active=player.active.card_name)


def _ascension(state, action):
    """sv10-011 Dwebble atk0 — Ascension: search deck for evolution, evolve immediately."""
    player = state.get_player(action.player_id)
    if not player.active:
        return

    # Look for cards that evolve from Dwebble (Crustle = sv10-012)
    evo_cards = [c for c in player.deck if c.card_def_id == "sv10-012"]
    if not evo_cards:
        state.emit_event("attack_failed", attack="Ascension", reason="no evolution in deck")
        return

    req = ChoiceRequest(
        "choose_cards",
        action.player_id,
        "Ascension: search your deck for Crustle to evolve Dwebble",
        cards=evo_cards,
        min_count=0,
        max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [evo_cards[0].instance_id]

    for cid in chosen_ids[:1]:
        evo_card = next((c for c in player.deck if c.instance_id == cid), None)
        if evo_card and player.active:
            old_active = player.active
            player.deck.remove(evo_card)

            evo_cdef = card_registry.get(evo_card.card_def_id)
            evo_card.zone = Zone.ACTIVE
            evo_card.max_hp = evo_cdef.hp if evo_cdef else evo_card.max_hp
            evo_card.current_hp = evo_card.max_hp - old_active.damage_counters * 10
            evo_card.damage_counters = old_active.damage_counters
            evo_card.energy_attached = list(old_active.energy_attached)
            evo_card.tools_attached = list(old_active.tools_attached)
            evo_card.status_conditions = set(old_active.status_conditions)
            evo_card.evolved_from = old_active.instance_id
            evo_card.evolution_stage = 1
            evo_card.turn_played = state.turn_number

            player.active = evo_card
            old_active.zone = Zone.DISCARD
            player.discard.append(old_active)

            _shuffle_deck(player)
            state.emit_event("evolved", player=action.player_id,
                             from_card=old_active.card_name, to_card=evo_card.card_name,
                             via="Ascension")


def _take_down(state, action):
    """sv10-019 TR Tarountula atk0 — Take Down: 30 damage + 10 recoil to self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return

    player = state.get_player(action.player_id)
    if player.active:
        player.active.current_hp -= 10
        player.active.damage_counters += 1
        state.emit_event("recoil_damage", player=action.player_id,
                         card=player.active.card_name, damage=10)
        check_ko(state, player.active, action.player_id)


def _nutrients(state, action):
    """sv10-022 Dolliv atk0 — Nutrients: heal 40 damage from 1 of your Pokémon."""
    player = state.get_player(action.player_id)
    healable = [p for p in _in_play(player) if p.damage_counters > 0]
    if not healable:
        state.emit_event("attack_no_damage", attacker="Dolliv", attack_name="Nutrients",
                         reason="no damaged Pokémon")
        return

    req = ChoiceRequest(
        "choose_target",
        action.player_id,
        "Nutrients: choose 1 of your Pokémon to heal 40 damage",
        targets=healable,
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in healable
                       if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = max(healable, key=lambda p: p.damage_counters)

    heal_damage = min(40, target.damage_counters * 10)
    counters_healed = min(4, target.damage_counters)
    target.current_hp = min(target.current_hp + heal_damage, target.max_hp)
    target.damage_counters -= counters_healed
    state.emit_event("healed", player=action.player_id, card=target.card_name, amount=heal_damage)


def _aroma_shot(state, action):
    """sv10-023 Arboliva ex atk1 — Aroma Shot: 160 + cure all Special Conditions from self."""
    _do_default_damage(state, action)
    player = state.get_player(action.player_id)
    if player.active:
        player.active.status_conditions.clear()
        state.emit_event("status_cured", player=action.player_id,
                         card=player.active.card_name, reason="Aroma Shot")


# ──────────────────────────────────────────────────────────────────────────────
# Category 8b: Item-lock attacks
# ──────────────────────────────────────────────────────────────────────────────

def _slight_intrusion(state, action):
    """sv05-023 Rellor atk0 — Slight Intrusion: 30 + 10 recoil to self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.current_hp -= 10
        player.active.damage_counters += 1
        state.emit_event("recoil_damage", player=action.player_id,
                         card=player.active.card_name, damage=10)
        check_ko(state, player.active, action.player_id)


def _rabsca_psychic(state, action):
    """sv05-024 Rabsca atk0 — Psychic: 10 + 30 × Energy on opponent's Active."""
    opp = state.get_opponent(action.player_id)
    if not opp.active:
        return
    base_damage = 10 + 30 * len(opp.active.energy_attached)
    _apply_damage(state, action, base_damage)


def _cruel_arrow(state, action):
    """me02.5-142 Fezandipiti ex atk0 — Cruel Arrow: 100 to 1 of opponent's Pokémon.

    No Weakness/Resistance when targeting Bench.
    """
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)

    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    if not all_opp:
        return

    if not opp.bench:
        _apply_damage(state, action, 100)
        return

    req = ChoiceRequest(
        "choose_target",
        action.player_id,
        "Cruel Arrow: choose 1 of your opponent's Pokémon for 100 damage",
        targets=all_opp,
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in all_opp
                       if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = opp.active or opp.bench[0]

    if target is opp.active:
        _apply_damage(state, action, 100)
    else:
        _apply_bench_damage(state, opp_id, target, 100)


def _overflowing_wishes(state, action):
    """me02.5-089 Mega Gardevoir ex atk0 — Overflowing Wishes.

    Attach 1 Basic {P} Energy from deck to each of your Benched Pokémon.
    """
    from app.engine.state import EnergyAttachment
    player = state.get_player(action.player_id)
    if not player.bench or not player.deck:
        _shuffle_deck(player)
        return

    psychic_energy = [
        c for c in player.deck
        if c.card_type.lower() == "energy"
        and c.card_subtype.lower() == "basic"
        and "Psychic" in (c.energy_provides or [])
    ]
    if not psychic_energy:
        _shuffle_deck(player)
        return

    attached = 0
    for bench_poke in player.bench:
        if not psychic_energy:
            break
        energy_card = psychic_energy.pop(0)
        player.deck.remove(energy_card)
        energy_card.zone = Zone.ATTACHED
        att = EnergyAttachment(
            energy_type=EnergyType.PSYCHIC,
            source_card_id=energy_card.instance_id,
            card_def_id=energy_card.card_def_id,
            provides=[EnergyType.PSYCHIC],
        )
        bench_poke.energy_attached.append(att)
        attached += 1

    _shuffle_deck(player)
    state.emit_event("energy_attached_from_deck", player=action.player_id,
                     count=attached, reason="overflowing_wishes")


def _mega_symphonia(state, action):
    """me02.5-089 Mega Gardevoir ex atk1 — Mega Symphonia: 50 × {P} Energy on all your Pokémon."""
    player = state.get_player(action.player_id)
    psychic_count = 0
    for poke in ([player.active] if player.active else []) + list(player.bench):
        for att in poke.energy_attached:
            if EnergyType.PSYCHIC in att.provides:
                psychic_count += 1
    base_damage = 50 * psychic_count
    if base_damage <= 0:
        state.emit_event("attack_no_damage", attacker="Mega Gardevoir ex",
                         attack_name="Mega Symphonia")
        return
    _apply_damage(state, action, base_damage)


def _shooting_moons(state, action):
    """me03-031 Mega Clefable ex atk0 — Shooting Moons: 120 + discard up to 4 Energy from hand, +40 each."""
    player = state.get_player(action.player_id)
    energy_in_hand = [c for c in player.hand
                      if c.card_type.lower() == "energy"]
    if not energy_in_hand:
        _apply_damage(state, action, 120)
        return

    max_count = min(4, len(energy_in_hand))
    req = ChoiceRequest(
        "choose_cards",
        action.player_id,
        "Shooting Moons: discard up to 4 Energy from your hand (+40 damage each)",
        cards=energy_in_hand,
        min_count=0,
        max_count=max_count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in energy_in_hand[:max_count]]

    discarded = 0
    for cid in chosen_ids:
        card = next((c for c in player.hand if c.instance_id == cid), None)
        if card:
            player.hand.remove(card)
            card.zone = Zone.DISCARD
            player.discard.append(card)
            discarded += 1

    base_damage = 120 + 40 * discarded
    _apply_damage(state, action, base_damage)

def _itchy_pollen(state, action):
    """me02.5-016 Budew atk0 — Itchy Pollen: 10 + opponent can't play Items next turn."""
    _do_default_damage(state, action)
    opp = state.get_opponent(action.player_id)
    if state.phase != Phase.GAME_OVER:
        opp.items_locked_this_turn = True
        state.emit_event("items_locked", player=state.opponent_id(action.player_id),
                         reason="itchy_pollen")


def _poison_chain(state, action):
    """svp-149 Pecharunt atk0 — Poison Chain: 10 + Poison + opponent can't retreat next turn."""
    _do_default_damage(state, action)
    opp = state.get_opponent(action.player_id)
    if opp.active and state.phase != Phase.GAME_OVER:
        opp.active.status_conditions.add(StatusCondition.POISONED)
        opp.active.cant_retreat_next_turn = True
        state.emit_event("status_applied", status="poisoned", card=opp.active.card_name)
        state.emit_event("cant_retreat", card=opp.active.card_name, reason="poison_chain")


# ──────────────────────────────────────────────────────────────────────────────
# Category 9: Copy-attack handlers
# ──────────────────────────────────────────────────────────────────────────────

# Card IDs for copy-attack handlers — excluded from copy candidates to prevent chains.
_COPY_ATTACK_KEYS = {"sv09-098:0", "sv10-087:0"}


async def _night_joker(state, action):
    """sv09-098 N's Zoroark ex atk0 — Night Joker.

    Choose one of your benched N's Pokémon and use one of its attacks.
    Energy cost is paid by N's Zoroark ex. Depth limit: 1 (no chain copying).
    """
    from app.cards import registry as card_registry
    from app.engine.effects.registry import EffectRegistry

    player = state.get_player(action.player_id)

    # Find bench N's Pokémon candidates with at least one non-copy attack.
    best_poke = None
    best_atk_idx = 0
    best_damage = -1

    for poke in player.bench:
        if not poke.card_name.startswith("N's"):
            continue
        cdef = card_registry.get(poke.card_def_id)
        if not cdef:
            continue
        for atk_idx, atk in enumerate(cdef.attacks):
            key = f"{cdef.tcgdex_id}:{atk_idx}"
            if key in _COPY_ATTACK_KEYS:
                continue
            dmg = parse_damage(atk.damage)
            if dmg > best_damage:
                best_damage = dmg
                best_poke = poke
                best_atk_idx = atk_idx

    if best_poke is None:
        state.emit_event(
            "copy_attack_no_target",
            card="N's Zoroark ex",
            attack="Night Joker",
            reason="No benched N's Pokémon with a valid attack",
        )
        return

    best_cdef = card_registry.get(best_poke.card_def_id)
    atk_name = best_cdef.attacks[best_atk_idx].name if best_cdef else "unknown"
    state.emit_event(
        "copy_attack",
        card="N's Zoroark ex",
        attack="Night Joker",
        source_card=best_poke.card_name,
        copied_attack=atk_name,
    )
    await EffectRegistry.instance().resolve_attack(
        best_poke.card_def_id, best_atk_idx, state, action
    )


async def _gemstone_mimicry(state, action):
    """sv10-087 TR Mimikyu atk0 — Gemstone Mimicry.

    Choose 1 of your opponent's Active Tera Pokémon's attacks and use it.
    If the opponent's Active is not Tera, deal 0 damage instead.
    Depth limit: 1 (no chain copying).
    """
    from app.cards import registry as card_registry
    from app.engine.effects.registry import EffectRegistry

    opp = state.get_opponent(action.player_id)
    if opp.active is None:
        state.emit_event(
            "copy_attack_no_target",
            card="TR Mimikyu",
            attack="Gemstone Mimicry",
            reason="Opponent has no Active Pokémon",
        )
        return

    opp_cdef = card_registry.get(opp.active.card_def_id)
    if opp_cdef is None or not opp_cdef.is_tera:
        state.emit_event(
            "copy_attack_no_target",
            card="TR Mimikyu",
            attack="Gemstone Mimicry",
            reason=f"Opponent's Active ({opp.active.card_name}) is not a Tera Pokémon",
        )
        return

    # Pick the highest-damage non-copy attack from the Tera Pokémon.
    best_atk_idx = None
    best_damage = -1
    for atk_idx, atk in enumerate(opp_cdef.attacks):
        key = f"{opp_cdef.tcgdex_id}:{atk_idx}"
        if key in _COPY_ATTACK_KEYS:
            continue
        dmg = parse_damage(atk.damage)
        if dmg > best_damage:
            best_damage = dmg
            best_atk_idx = atk_idx

    if best_atk_idx is None:
        state.emit_event(
            "copy_attack_no_target",
            card="TR Mimikyu",
            attack="Gemstone Mimicry",
            reason=f"{opp.active.card_name} has no copyable attacks",
        )
        return

    atk_name = opp_cdef.attacks[best_atk_idx].name
    state.emit_event(
        "copy_attack",
        card="TR Mimikyu",
        attack="Gemstone Mimicry",
        source_card=opp.active.card_name,
        copied_attack=atk_name,
    )
    await EffectRegistry.instance().resolve_attack(
        opp.active.card_def_id, best_atk_idx, state, action
    )


# ──────────────────────────────────────────────────────────────────────────────
# Batch 1 handlers (me03 / me02.5 sets)
# ──────────────────────────────────────────────────────────────────────────────

def _gooey_thread(state, action):
    """me03-001 Spinarak atk0 — Gooey Thread: 10 + can't retreat next turn."""
    _do_default_damage(state, action)
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.cant_retreat_next_turn = True
        state.emit_event("cant_retreat", card=opp.active.card_name, attack="Gooey Thread")


def _poison_ring(state, action):
    """me03-002 Ariados atk0 — Poison Ring: 50 + poisoned + can't retreat."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.POISONED)
        opp.active.cant_retreat_next_turn = True
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="poisoned+cant_retreat", attack="Poison Ring")


def _icy_wind(state, action):
    """me03-023 Amaura atk0 — Icy Wind: 50 + Asleep."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.ASLEEP)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="asleep", attack="Icy Wind")


def _thunder_shock_dedenne(state, action):
    """me03-029 Dedenne atk1 — Thunder Shock: 30 + flip, heads=Paralyzed."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):
        opp = state.get_opponent(action.player_id)
        if opp.active:
            opp.active.status_conditions.add(StatusCondition.PARALYZED)
            state.emit_event("status_applied", card=opp.active.card_name,
                             status="paralyzed", attack="Thunder Shock")


def _perplex(state, action):
    """me03-034 Meowstic atk0 — Perplex: 0 damage + Confused."""
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.CONFUSED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="confused", attack="Perplex")


def _poison_jab(state, action):
    """me03-051 Skorupi atk0 — Poison Jab: 20 + Poisoned."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.POISONED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="poisoned", attack="Poison Jab")


def _hazardous_tail(state, action):
    """me03-052 Drapion atk1 — Hazardous Tail: 100 + 70 recoil to self + Paralyzed."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    if player.active:
        player.active.current_hp -= 70
        player.active.damage_counters += 7
        state.emit_event("recoil_damage", player=action.player_id,
                         card=player.active.card_name, damage=70)
        check_ko(state, player.active, action.player_id)
        if state.phase == Phase.GAME_OVER:
            return
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.PARALYZED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="paralyzed", attack="Hazardous Tail")


def _ericas_gloom_poison_spray(state, action):
    """me02.5-002 Erika's Gloom atk0 — Poison Spray: 50 + Poisoned."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.POISONED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="poisoned", attack="Poison Spray")


def _bind(state, action):
    """me02.5-007 Erika's Tangela atk0 — Bind: 50 + flip, heads=Paralyzed."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):
        opp = state.get_opponent(action.player_id)
        if opp.active:
            opp.active.status_conditions.add(StatusCondition.PARALYZED)
            state.emit_event("status_applied", card=opp.active.card_name,
                             status="paralyzed", attack="Bind")


def _stun_spore(state, action):
    """me02.5-013 Beautifly atk0 — Stun Spore: 40 + flip, heads=Paralyzed."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):
        opp = state.get_opponent(action.player_id)
        if opp.active:
            opp.active.status_conditions.add(StatusCondition.PARALYZED)
            state.emit_event("status_applied", card=opp.active.card_name,
                             status="paralyzed", attack="Stun Spore")


def _super_singe(state, action):
    """me02.5-030 Pignite atk0 — Super Singe: 70 + Burned."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.BURNED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="burned", attack="Super Singe")


def _collapse(state, action):
    """me03-063 Snorlax atk1 — Collapse: 160 + this Pokémon is now Asleep."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.status_conditions.add(StatusCondition.ASLEEP)
        state.emit_event("status_applied", card=player.active.card_name,
                         status="asleep (self)", attack="Collapse")


def _twilight_poison(state, action):
    """me02.5-015 Dustox atk0 — Twilight Poison: 100 + Asleep + Poisoned."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.ASLEEP)
        opp.active.status_conditions.add(StatusCondition.POISONED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="asleep+poisoned", attack="Twilight Poison")


def _bloom_powder(state, action):
    """me02.5-003 Erika's Vileplume ex atk0 — Bloom Powder: 160 + Asleep + Poisoned."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.ASLEEP)
        opp.active.status_conditions.add(StatusCondition.POISONED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="asleep+poisoned", attack="Bloom Powder")


def _dire_nails(state, action):
    """me03-016 Salazzle ex atk1 — Dire Nails: 100 + Burned + Poisoned + self switch."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.BURNED)
        opp.active.status_conditions.add(StatusCondition.POISONED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="burned+poisoned", attack="Dire Nails")
    if player.bench:
        req = ChoiceRequest(
            "choose_target", action.player_id,
            "Dire Nails: choose a Benched Pokémon to switch with Salazzle ex",
            targets=list(player.bench),
        )
        resp = yield req
        target = None
        if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
            target = next((p for p in player.bench
                           if p.instance_id == resp.target_instance_id), None)
        if target is None:
            target = player.bench[0]
        _switch_active_with_bench(player, target)
        state.emit_event("self_switch", player=action.player_id,
                         new_active=player.active.card_name)


def _heat_breath(state, action):
    """me03-017 Turtonator atk0 — Heat Breath: 80 + flip, heads=+80."""
    base_damage = 80
    if _random.choice([True, False]):
        base_damage += 80
        state.emit_event("coin_flip_result", attack="Heat Breath", heads=1)
    _apply_damage(state, action, base_damage)


# Multi-turn attack locks ────────────────────────────────────────────────────

def _leafy_cyclone(state, action):
    """me02.5-005 Erika's Weepinbell atk1 — Leafy Cyclone: 70 + can't attack next turn."""
    _do_default_damage(state, action)
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=player.active.card_name,
                         attack="Leafy Cyclone")


def _metal_slash(state, action):
    """me03-058 Aegislash atk1 — Metal Slash: 230 + can't use attacks next turn."""
    _do_default_damage(state, action)
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=player.active.card_name,
                         attack="Metal Slash")


def _dark_strike(state, action):
    """me03-053 Yveltal ex atk1 — Dark Strike: 210 + can't use Dark Strike next turn."""
    _do_default_damage(state, action)
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=player.active.card_name,
                         attack="Dark Strike")


def _freezing_chill(state, action):
    """me03-024 Aurorus atk0 — Freezing Chill: 150 + opponent can't use attacks next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.cant_attack_next_turn = True
        state.emit_event("cant_attack", card=opp.active.card_name, attack="Freezing Chill")


# Heals ──────────────────────────────────────────────────────────────────────

def _nap(state, action):
    """me03-033 Espurr atk0 — Nap: heal 20 damage from this Pokémon."""
    player = state.get_player(action.player_id)
    if player.active and player.active.damage_counters > 0:
        heal = min(20, player.active.damage_counters * 10)
        counters = min(2, player.active.damage_counters)
        player.active.current_hp = min(player.active.current_hp + heal, player.active.max_hp)
        player.active.damage_counters -= counters
        state.emit_event("healed", player=action.player_id,
                         card=player.active.card_name, amount=heal)


def _sweet_scent(state, action):
    """me03-035 Spritzee atk0 — Sweet Scent: heal 30 damage from 1 of your Pokémon."""
    player = state.get_player(action.player_id)
    healable = [p for p in _in_play(player) if p.damage_counters > 0]
    if not healable:
        state.emit_event("attack_no_damage", attacker="Spritzee", attack_name="Sweet Scent",
                         reason="no damaged Pokémon")
        return
    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Sweet Scent: choose 1 of your Pokémon to heal 30 damage",
        targets=healable,
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in healable
                       if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = max(healable, key=lambda p: p.damage_counters)
    heal = min(30, target.damage_counters * 10)
    counters = min(3, target.damage_counters)
    target.current_hp = min(target.current_hp + heal, target.max_hp)
    target.damage_counters -= counters
    state.emit_event("healed", player=action.player_id, card=target.card_name, amount=heal)


def _draining_kiss(state, action):
    """me03-036 Aromatisse atk0 — Draining Kiss: 50 + heal 30 from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active and player.active.damage_counters > 0:
        heal = min(30, player.active.damage_counters * 10)
        counters = min(3, player.active.damage_counters)
        player.active.current_hp = min(player.active.current_hp + heal, player.active.max_hp)
        player.active.damage_counters -= counters
        state.emit_event("healed", player=action.player_id,
                         card=player.active.card_name, amount=heal)


def _shining_feathers(state, action):
    """me02.5-026 Ethan's Ho-Oh ex atk0 — Shining Feathers: 160 + heal 50 from each Pokémon."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    for poke in _in_play(player):
        if poke.damage_counters > 0:
            heal = min(50, poke.damage_counters * 10)
            counters = min(5, poke.damage_counters)
            poke.current_hp = min(poke.current_hp + heal, poke.max_hp)
            poke.damage_counters -= counters
            state.emit_event("healed", player=action.player_id,
                             card=poke.card_name, amount=heal)


# Variable damage ────────────────────────────────────────────────────────────

def _regal_command(state, action):
    """me03-006 Serperior atk0 — Regal Command: 20 × your Pokémon in play."""
    player = state.get_player(action.player_id)
    base_damage = 20 * len(_in_play(player))
    _apply_damage(state, action, base_damage)


def _solar_coiling(state, action):
    """me03-006 Serperior atk1 — Solar Coiling: 100 + 150 if Rosa's Encouragement in discard."""
    player = state.get_player(action.player_id)
    # Rosa's Encouragement card ID: me03-084
    has_rosa = any(c.card_def_id == "me03-084" for c in player.discard)
    base_damage = 100 + (150 if has_rosa else 0)
    _apply_damage(state, action, base_damage)


def _hydro_turn(state, action):
    """me03-022 Lapras ex atk0 — Hydro Turn: 30 × {W} energy attached + switch self."""
    player = state.get_player(action.player_id)
    if not player.active:
        return
    water_count = sum(1 for att in player.active.energy_attached
                      if att.energy_type == EnergyType.WATER)
    base_damage = 30 * water_count
    _apply_damage(state, action, base_damage)
    if state.phase == Phase.GAME_OVER or not player.bench:
        return
    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Hydro Turn: choose a Benched Pokémon to switch with Lapras ex",
        targets=list(player.bench),
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in player.bench
                       if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = player.bench[0]
    _switch_active_with_bench(player, target)
    state.emit_event("self_switch", player=action.player_id,
                     new_active=player.active.card_name)


def _incessant_onslaught(state, action):
    """me03-028 Luxray atk0 — Incessant Onslaught: 70 × prize cards taken."""
    player = state.get_player(action.player_id)
    prizes_taken = 6 - player.prizes_remaining
    base_damage = 70 * prizes_taken
    if base_damage <= 0:
        state.emit_event("attack_no_damage", attacker="Luxray",
                         attack_name="Incessant Onslaught")
        return
    _apply_damage(state, action, base_damage)


def _strong_volt(state, action):
    """me03-028 Luxray atk1 — Strong Volt: 200 + discard 2 Energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if not player.active or not player.active.energy_attached:
        return
    energy_on_self = list(player.active.energy_attached)
    if len(energy_on_self) < 2:
        player.active.energy_attached.clear()
        state.emit_event("energy_discarded", player=action.player_id,
                         count=len(energy_on_self), reason="Strong Volt")
        return
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Strong Volt: discard 2 Energy from Luxray",
        cards=energy_on_self, min_count=2, max_count=2,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [a.source_card_id for a in energy_on_self[:2]]
    discarded = 0
    for src_id in chosen_ids[:2]:
        att = next((a for a in player.active.energy_attached
                    if a.source_card_id == src_id), None)
        if att:
            player.active.energy_attached.remove(att)
            discarded += 1
    state.emit_event("energy_discarded", player=action.player_id,
                     count=discarded, reason="Strong Volt")


def _double_eater(state, action):
    """me03-032 Mawile atk0 — Double Eater: discard up to 2 Energy from hand, 60 per discarded."""
    player = state.get_player(action.player_id)
    energy_in_hand = [c for c in player.hand if c.card_type.lower() == "energy"]
    if not energy_in_hand:
        state.emit_event("attack_no_damage", attacker="Mawile", attack_name="Double Eater",
                         reason="no energy in hand")
        return
    max_count = min(2, len(energy_in_hand))
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Double Eater: discard up to 2 Energy from hand (+60 damage each)",
        cards=energy_in_hand, min_count=0, max_count=max_count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in energy_in_hand[:max_count]]
    discarded = 0
    for cid in chosen_ids:
        card = next((c for c in player.hand if c.instance_id == cid), None)
        if card:
            player.hand.remove(card)
            card.zone = Zone.DISCARD
            player.discard.append(card)
            discarded += 1
    base_damage = 60 * discarded
    if base_damage <= 0:
        state.emit_event("attack_no_damage", attacker="Mawile", attack_name="Double Eater")
        return
    _apply_damage(state, action, base_damage)


def _meowstic_psychic(state, action):
    """me03-034 Meowstic atk1 — Psychic: 30 + 30 × Energy on opponent's Active."""
    opp = state.get_opponent(action.player_id)
    if not opp.active:
        return
    base_damage = 30 + 30 * len(opp.active.energy_attached)
    _apply_damage(state, action, base_damage)


def _get_angry(state, action):
    """me03-044 Tyrunt atk0 — Get Angry: 20 × damage counters on this Pokémon."""
    player = state.get_player(action.player_id)
    if not player.active:
        return
    base_damage = 20 * player.active.damage_counters
    if base_damage <= 0:
        state.emit_event("attack_no_damage", attacker="Tyrunt", attack_name="Get Angry")
        return
    _apply_damage(state, action, base_damage)


def _vengeful_kick(state, action):
    """me03-046 Hawlucha atk0 — Vengeful Kick: 30 + 60 if any benched Pokémon have damage counters."""
    player = state.get_player(action.player_id)
    has_damaged_bench = any(p.damage_counters > 0 for p in player.bench)
    base_damage = 30 + (60 if has_damaged_bench else 0)
    _apply_damage(state, action, base_damage)


def _mind_jack(state, action):
    """me03-050 Gengar atk0 — Mind Jack: 10 + 30 × opponent's Benched Pokémon."""
    opp = state.get_opponent(action.player_id)
    base_damage = 10 + 30 * len(opp.bench)
    _apply_damage(state, action, base_damage)


def _retaliatory_incisors(state, action):
    """me03-061 Raticate atk1 — Retaliatory Incisors: 40 × total damage counters on own benched Rattata."""
    player = state.get_player(action.player_id)
    # Rattata card ID: me03-060
    rattata_counters = sum(p.damage_counters for p in player.bench
                           if p.card_def_id == "me03-060")
    base_damage = 40 * rattata_counters
    if base_damage <= 0:
        state.emit_event("attack_no_damage", attacker="Raticate",
                         attack_name="Retaliatory Incisors")
        return
    _apply_damage(state, action, base_damage)


def _flower_garden_rondo(state, action):
    """me02.5-006 Erika's Victreebel atk0 — Flower Garden Rondo: 40 × Erika's Pokémon in play."""
    player = state.get_player(action.player_id)
    erikas_count = sum(1 for p in _in_play(player) if "Erika's" in p.card_name)
    base_damage = 40 * erikas_count
    if base_damage <= 0:
        state.emit_event("attack_no_damage", attacker="Erika's Victreebel",
                         attack_name="Flower Garden Rondo")
        return
    _apply_damage(state, action, base_damage)


def _energy_straw(state, action):
    """me02.5-013 Beautifly atk1 — Energy Straw: reveal opponent's hand, 80 × energy cards found."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    energy_count = sum(1 for c in opp.hand if c.card_type.lower() == "energy")
    state.emit_event("hand_revealed", player=opp_id,
                     reason="Energy Straw", energy_count=energy_count)
    if energy_count == 0:
        state.emit_event("attack_no_damage", attacker="Beautifly",
                         attack_name="Energy Straw")
        return
    base_damage = 80 * energy_count
    _apply_damage(state, action, base_damage)


def _flare_fall(state, action):
    """me02.5-025 Entei atk0 — Flare Fall: 30 + 90 if 4+ {R} energy in play on your side."""
    player = state.get_player(action.player_id)
    fire_count = sum(
        1 for poke in _in_play(player)
        for att in poke.energy_attached
        if att.energy_type == EnergyType.FIRE
    )
    base_damage = 30 + (90 if fire_count >= 4 else 0)
    _apply_damage(state, action, base_damage)


def _giant_bouquet(state, action):
    """me02.5-010 Mega Meganium ex atk0 — Giant Bouquet: 70 + 50 × {G} Energy attached to self."""
    player = state.get_player(action.player_id)
    if not player.active:
        return
    grass_count = sum(1 for att in player.active.energy_attached
                      if att.energy_type == EnergyType.GRASS)
    base_damage = 70 + 50 * grass_count
    _apply_damage(state, action, base_damage)


def _roasting_burn(state, action):
    """me02.5-028 Camerupt atk0 — Roasting Burn: 110 if opponent's Active is Burned, else 0."""
    opp = state.get_opponent(action.player_id)
    if not opp.active:
        return
    if StatusCondition.BURNED in opp.active.status_conditions:
        _apply_damage(state, action, 110)
    else:
        state.emit_event("attack_no_damage", attacker="Camerupt",
                         attack_name="Roasting Burn", reason="target not burned")


def _crimson_blast(state, action):
    """me02.5-031 Mega Emboar ex atk0 — Crimson Blast: 320 + 60 recoil to self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.current_hp -= 60
        player.active.damage_counters += 6
        state.emit_event("recoil_damage", player=action.player_id,
                         card=player.active.card_name, damage=60)
        check_ko(state, player.active, action.player_id)


# Coin flips ─────────────────────────────────────────────────────────────────

def _powerful_steam(state, action):
    """me03-025 Volcanion atk1 — Powerful Steam: 90 × heads (flip per {W} Energy)."""
    player = state.get_player(action.player_id)
    if not player.active:
        return
    water_count = sum(1 for att in player.active.energy_attached
                      if att.energy_type == EnergyType.WATER)
    if water_count == 0:
        state.emit_event("attack_no_damage", attacker="Volcanion",
                         attack_name="Powerful Steam", reason="no W energy")
        return
    heads_count = sum(1 for _ in range(water_count) if _random.choice([True, False]))
    state.emit_event("coin_flip_result", attack="Powerful Steam",
                     flips=water_count, heads=heads_count)
    if heads_count == 0:
        state.emit_event("attack_no_damage", attacker="Volcanion",
                         attack_name="Powerful Steam", reason="all tails")
        return
    base_damage = 90 * heads_count
    _apply_damage(state, action, base_damage)


def _double_scratch(state, action):
    """me03-026 Shinx atk0 — Double Scratch: flip 2 coins, 10 × heads."""
    heads_count = sum(1 for _ in range(2) if _random.choice([True, False]))
    state.emit_event("coin_flip_result", attack="Double Scratch", flips=2, heads=heads_count)
    if heads_count == 0:
        state.emit_event("attack_no_damage", attacker="Shinx", attack_name="Double Scratch")
        return
    base_damage = 10 * heads_count
    _apply_damage(state, action, base_damage)


def _wreak_havoc(state, action):
    """me03-045 Tyrantrum atk0 — Wreak Havoc: 160 + flip until tails, discard top card per heads."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    heads_count = 0
    while _random.choice([True, False]):
        heads_count += 1
    state.emit_event("coin_flip_result", attack="Wreak Havoc", heads=heads_count)
    for _ in range(heads_count):
        if opp.deck:
            top_card = opp.deck.pop(0)
            top_card.zone = Zone.DISCARD
            opp.discard.append(top_card)
            state.emit_event("deck_discarded", player=opp_id, card=top_card.card_name,
                             reason="Wreak Havoc")


def _surprise_attack(state, action):
    """me03-048 Gastly atk0 — Surprise Attack: flip coin, tails = no damage, heads = 30."""
    if _random.choice([True, False]):
        state.emit_event("coin_flip_result", attack="Surprise Attack", result="heads")
        _apply_damage(state, action, 30)
    else:
        state.emit_event("coin_flip_result", attack="Surprise Attack", result="tails")
        state.emit_event("attack_no_damage", attacker="Gastly", attack_name="Surprise Attack")


# Search/draw ────────────────────────────────────────────────────────────────

def _send_flowers(state, action):
    """me03-003 Shaymin atk0 — Send Flowers: search deck for Energy, attach to 1 benched {G} Pokémon."""
    from app.engine.state import EnergyAttachment
    player = state.get_player(action.player_id)
    # Find benched Grass-type pokemon
    grass_bench = [p for p in player.bench
                   if any("Grass" in (card_registry.get(p.card_def_id).types or [])
                          if card_registry.get(p.card_def_id) else False)]
    if not grass_bench or not player.deck:
        _shuffle_deck(player)
        state.emit_event("send_flowers", player=action.player_id, reason="no target or empty deck")
        return

    energy_in_deck = [c for c in player.deck if c.card_type.lower() == "energy"]
    if not energy_in_deck:
        _shuffle_deck(player)
        state.emit_event("send_flowers", player=action.player_id, reason="no energy in deck")
        return

    # Choose target bench pokemon
    req_target = ChoiceRequest(
        "choose_target", action.player_id,
        "Send Flowers: choose a Benched {G} Pokémon to attach Energy to",
        targets=grass_bench,
    )
    resp_target = yield req_target
    target = None
    if resp_target and hasattr(resp_target, "target_instance_id") and resp_target.target_instance_id:
        target = next((p for p in grass_bench
                       if p.instance_id == resp_target.target_instance_id), None)
    if target is None:
        target = grass_bench[0]

    # Choose energy from deck
    req_energy = ChoiceRequest(
        "choose_cards", action.player_id,
        "Send Flowers: choose an Energy card from deck to attach",
        cards=energy_in_deck, min_count=0, max_count=1,
    )
    resp_energy = yield req_energy
    chosen_ids = (resp_energy.chosen_card_ids if resp_energy and hasattr(resp_energy, "chosen_card_ids")
                  and resp_energy.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [energy_in_deck[0].instance_id]

    for cid in chosen_ids[:1]:
        energy_card = next((c for c in player.deck if c.instance_id == cid), None)
        if energy_card:
            player.deck.remove(energy_card)
            cdef = card_registry.get(energy_card.card_def_id)
            provides_strs = cdef.energy_provides if cdef and cdef.energy_provides else ["Colorless"]
            provides = [EnergyType.from_str(t) for t in provides_strs]
            primary = provides[0] if provides else EnergyType.COLORLESS
            target.energy_attached.append(EnergyAttachment(
                energy_type=primary,
                source_card_id=energy_card.instance_id,
                card_def_id=energy_card.card_def_id,
                provides=provides,
            ))
            state.emit_event("send_flowers", player=action.player_id,
                             target=target.card_name, energy=energy_card.card_name)

    _shuffle_deck(player)


def _find_a_friend(state, action):
    """me03-010 Rowlet atk0 — Find a Friend: search deck for any Pokémon, reveal and put in hand."""
    player = state.get_player(action.player_id)
    pokemon_in_deck = [c for c in player.deck if c.card_type.lower() == "pokemon"]
    if not pokemon_in_deck:
        _shuffle_deck(player)
        state.emit_event("find_a_friend", player=action.player_id, found=0)
        return
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Find a Friend: choose a Pokémon from deck to put in hand",
        cards=pokemon_in_deck, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [pokemon_in_deck[0].instance_id]
    found = 0
    for cid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
            found += 1
    _shuffle_deck(player)
    state.emit_event("find_a_friend", player=action.player_id, found=found)


def _feather_shot(state, action):
    """me03-011 Dartrix atk1 — Feather Shot: discard ALL energy from self + 90 to 1 opp Pokémon."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)

    if player.active:
        count = len(player.active.energy_attached)
        player.active.energy_attached.clear()
        if count > 0:
            state.emit_event("energy_discarded", player=action.player_id,
                             count=count, reason="Feather Shot")

    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    if not all_opp:
        return

    if not opp.bench:
        _apply_damage(state, action, 90)
        return

    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Feather Shot: choose 1 of opponent's Pokémon for 90 damage (no W/R for bench)",
        targets=all_opp,
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in all_opp
                       if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = opp.active or opp.bench[0]

    if target is opp.active:
        _apply_damage(state, action, 90)
    else:
        _apply_bench_damage(state, opp_id, target, 90)


def _tail_generator(state, action):
    """me03-029 Dedenne atk0 — Tail Generator: choose Basic {L} from discard (up to energy count), attach 1, rest to hand."""
    from app.engine.state import EnergyAttachment
    player = state.get_player(action.player_id)
    if not player.active:
        return

    energy_count = len(player.active.energy_attached)
    if energy_count == 0:
        state.emit_event("attack_no_damage", attacker="Dedenne", attack_name="Tail Generator",
                         reason="no energy attached")
        return

    lightning_in_discard = [c for c in player.discard
                             if c.card_type.lower() == "energy"
                             and c.card_subtype.lower() == "basic"
                             and "Lightning" in (c.energy_provides or [])]
    if not lightning_in_discard:
        state.emit_event("tail_generator", player=action.player_id, found=0)
        return

    max_count = min(energy_count, len(lightning_in_discard))
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        f"Tail Generator: choose up to {max_count} Basic {{L}} Energy from discard",
        cards=lightning_in_discard, min_count=0, max_count=max_count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in lightning_in_discard[:max_count]]

    chosen_cards = [c for c in lightning_in_discard if c.instance_id in chosen_ids]
    if not chosen_cards:
        return

    # Attach 1 to self, rest to hand
    first = chosen_cards[0]
    player.discard.remove(first)
    cdef = card_registry.get(first.card_def_id)
    provides_strs = cdef.energy_provides if cdef and cdef.energy_provides else ["Lightning"]
    provides = [EnergyType.from_str(t) for t in provides_strs]
    primary = provides[0] if provides else EnergyType.LIGHTNING
    player.active.energy_attached.append(EnergyAttachment(
        energy_type=primary,
        source_card_id=first.instance_id,
        card_def_id=first.card_def_id,
        provides=provides,
    ))
    state.emit_event("tail_generator", player=action.player_id, attached=first.card_name)

    for extra in chosen_cards[1:]:
        player.discard.remove(extra)
        extra.zone = Zone.HAND
        player.hand.append(extra)

    state.emit_event("tail_generator_hand", player=action.player_id,
                     to_hand=len(chosen_cards) - 1)


def _chirp(state, action):
    """me03-066 Fletchling atk0 — Chirp: search deck for up to 2 Pokémon with {F} Resistance."""
    player = state.get_player(action.player_id)
    fighting_resistant = []
    for c in player.deck:
        if c.card_type.lower() != "pokemon":
            continue
        cdef = card_registry.get(c.card_def_id)
        if not cdef:
            continue
        resistances = cdef.resistances or []
        for r in resistances:
            if isinstance(r, dict) and r.get("type") == "Fighting":
                fighting_resistant.append(c)
                break
            elif hasattr(r, "type") and r.type == "Fighting":
                fighting_resistant.append(c)
                break
    if not fighting_resistant:
        _shuffle_deck(player)
        state.emit_event("chirp", player=action.player_id, found=0)
        return
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Chirp: choose up to 2 Pokémon with {F} Resistance from deck to put in hand",
        cards=fighting_resistant, min_count=0, max_count=2,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in fighting_resistant[:2]]
    found = 0
    for cid in chosen_ids:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
            found += 1
    _shuffle_deck(player)
    state.emit_event("chirp", player=action.player_id, found=found)


def _hand_trim(state, action):
    """me03-067 Furfrou atk0 — Hand Trim: discard random cards from opponent's hand until 5 remain."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    discarded = 0
    while len(opp.hand) > 5:
        card = _random.choice(opp.hand)
        opp.hand.remove(card)
        card.zone = Zone.DISCARD
        opp.discard.append(card)
        discarded += 1
    if discarded > 0:
        state.emit_event("hand_trim", player=action.player_id, discarded=discarded)


def _gormandizer(state, action):
    """me03-063 Snorlax atk0 — Gormandizer: flip until tails, search+attach up to heads Basic Energy."""
    from app.engine.state import EnergyAttachment
    player = state.get_player(action.player_id)

    heads_count = 0
    while _random.choice([True, False]):
        heads_count += 1
    state.emit_event("coin_flip_result", attack="Gormandizer", heads=heads_count)

    if heads_count == 0 or not player.deck:
        return

    basic_energy_in_deck = [c for c in player.deck
                             if c.card_type.lower() == "energy"
                             and c.card_subtype.lower() == "basic"]
    if not basic_energy_in_deck:
        _shuffle_deck(player)
        return

    all_targets = _in_play(player)
    max_count = min(heads_count, len(basic_energy_in_deck))

    req = ChoiceRequest(
        "choose_cards", action.player_id,
        f"Gormandizer: choose up to {max_count} Basic Energy from deck to attach",
        cards=basic_energy_in_deck, min_count=0, max_count=max_count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in basic_energy_in_deck[:max_count]]

    attached = 0
    for cid in chosen_ids[:max_count]:
        energy_card = next((c for c in player.deck if c.instance_id == cid), None)
        if energy_card and all_targets:
            player.deck.remove(energy_card)
            # Choose target for this energy
            req_t = ChoiceRequest(
                "choose_target", action.player_id,
                f"Gormandizer: choose a Pokémon to attach {energy_card.card_name} to",
                targets=all_targets,
            )
            resp_t = yield req_t
            target = None
            if resp_t and hasattr(resp_t, "target_instance_id") and resp_t.target_instance_id:
                target = next((p for p in all_targets
                               if p.instance_id == resp_t.target_instance_id), None)
            if target is None:
                target = player.active or all_targets[0]
            cdef = card_registry.get(energy_card.card_def_id)
            provides_strs = cdef.energy_provides if cdef and cdef.energy_provides else ["Colorless"]
            provides = [EnergyType.from_str(t) for t in provides_strs]
            primary = provides[0] if provides else EnergyType.COLORLESS
            target.energy_attached.append(EnergyAttachment(
                energy_type=primary,
                source_card_id=energy_card.instance_id,
                card_def_id=energy_card.card_def_id,
                provides=provides,
            ))
            attached += 1

    _shuffle_deck(player)
    state.emit_event("gormandizer", player=action.player_id, attached=attached)


def _explosion_y(state, action):
    """me02.5-022 Mega Charizard Y ex atk0 — Explosion Y: discard 3 energy + 280 to 1 opp Pokémon."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)

    if player.active and player.active.energy_attached:
        energy_on_self = list(player.active.energy_attached)
        to_discard = min(3, len(energy_on_self))
        req = ChoiceRequest(
            "choose_cards", action.player_id,
            f"Explosion Y: discard {to_discard} Energy from this Pokémon",
            cards=energy_on_self, min_count=to_discard, max_count=to_discard,
        )
        resp = yield req
        chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                      and resp.chosen_card_ids else [])
        if not chosen_ids:
            chosen_ids = [a.source_card_id for a in energy_on_self[:to_discard]]
        for src_id in chosen_ids[:to_discard]:
            att = next((a for a in player.active.energy_attached
                        if a.source_card_id == src_id), None)
            if att:
                player.active.energy_attached.remove(att)
        state.emit_event("energy_discarded", player=action.player_id,
                         count=to_discard, reason="Explosion Y")

    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    if not all_opp:
        return

    if not opp.bench:
        _apply_damage(state, action, 280)
        return

    req_target = ChoiceRequest(
        "choose_target", action.player_id,
        "Explosion Y: choose 1 of opponent's Pokémon for 280 damage (no W/R for bench)",
        targets=all_opp,
    )
    resp_target = yield req_target
    target = None
    if resp_target and hasattr(resp_target, "target_instance_id") and resp_target.target_instance_id:
        target = next((p for p in all_opp
                       if p.instance_id == resp_target.target_instance_id), None)
    if target is None:
        target = opp.active or opp.bench[0]

    if target is opp.active:
        _apply_damage(state, action, 280)
    else:
        _apply_bench_damage(state, opp_id, target, 280)


def _lava_burst(state, action):
    """me02.5-024 Ethan's Magcargo atk0 — Lava Burst: discard up to 5 {R} energy, 70 per discarded."""
    player = state.get_player(action.player_id)
    if not player.active:
        return
    fire_energy = [att for att in player.active.energy_attached
                   if att.energy_type == EnergyType.FIRE]
    if not fire_energy:
        state.emit_event("attack_no_damage", attacker="Ethan's Magcargo",
                         attack_name="Lava Burst", reason="no Fire energy")
        return
    max_count = min(5, len(fire_energy))
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Lava Burst: discard up to 5 {R} Energy (+70 damage each)",
        cards=fire_energy, min_count=0, max_count=max_count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [a.source_card_id for a in fire_energy[:max_count]]
    discarded = 0
    for src_id in chosen_ids:
        att = next((a for a in player.active.energy_attached
                    if a.source_card_id == src_id), None)
        if att:
            player.active.energy_attached.remove(att)
            discarded += 1
    base_damage = 70 * discarded
    if base_damage <= 0:
        state.emit_event("attack_no_damage", attacker="Ethan's Magcargo",
                         attack_name="Lava Burst")
        return
    _apply_damage(state, action, base_damage)


def _power_stomp(state, action):
    """me02.5-028 Camerupt atk1 — Power Stomp: 170 + discard 2 Energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if not player.active or not player.active.energy_attached:
        return
    energy_on_self = list(player.active.energy_attached)
    to_discard = min(2, len(energy_on_self))
    if to_discard < 2:
        player.active.energy_attached.clear()
        state.emit_event("energy_discarded", player=action.player_id,
                         count=to_discard, reason="Power Stomp")
        return
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Power Stomp: discard 2 Energy from Camerupt",
        cards=energy_on_self, min_count=2, max_count=2,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [a.source_card_id for a in energy_on_self[:2]]
    discarded = 0
    for src_id in chosen_ids[:2]:
        att = next((a for a in player.active.energy_attached
                    if a.source_card_id == src_id), None)
        if att:
            player.active.energy_attached.remove(att)
            discarded += 1
    state.emit_event("energy_discarded", player=action.player_id,
                     count=discarded, reason="Power Stomp")


def _nasty_plot(state, action):
    """me03-016 Salazzle ex atk0 — Nasty Plot: search deck for up to 2 cards, put in hand."""
    player = state.get_player(action.player_id)
    if not player.deck:
        state.emit_event("nasty_plot", player=action.player_id, found=0)
        return
    max_count = min(2, len(player.deck))
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Nasty Plot: choose up to 2 cards from deck to put in hand",
        cards=list(player.deck), min_count=0, max_count=max_count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in player.deck[:max_count]]
    found = 0
    for cid in chosen_ids[:max_count]:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
            found += 1
    _shuffle_deck(player)
    state.emit_event("nasty_plot", player=action.player_id, found=found)


# Bench damage ───────────────────────────────────────────────────────────────

def _jetting_blow(state, action):
    """me03-021 Mega Starmie ex atk0 — Jetting Blow: 120 + 50 to 1 opponent's bench."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.bench:
        return
    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Jetting Blow: choose 1 of opponent's Benched Pokémon for 50 damage",
        targets=list(opp.bench),
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in opp.bench
                       if p.instance_id == resp.target_instance_id), None)
    if target is None and opp.bench:
        target = opp.bench[0]
    if target:
        _apply_bench_damage(state, opp_id, target, 50)


def _nebula_beam(state, action):
    """me03-021 Mega Starmie ex atk1 — Nebula Beam: 210, not affected by W/R or effects."""
    _apply_damage(state, action, 210, bypass_wr=True, bypass_defender_effects=True)


def _earthquake(state, action):
    """me03-065 Diggersby atk0 — Earthquake: 140 + 30 to each of your own Benched Pokémon."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    for bench_poke in list(player.bench):
        if bench_poke.current_hp <= 0:
            continue
        bench_poke.current_hp -= 30
        bench_poke.damage_counters += 3
        state.emit_event("recoil_damage", player=action.player_id,
                         card=bench_poke.card_name, damage=30)
        check_ko(state, bench_poke, action.player_id)
        if state.phase == Phase.GAME_OVER:
            return


# Energy manipulation ─────────────────────────────────────────────────────────

def _obliterating_nose(state, action):
    """me03-038 Probopass atk1 — Obliterating Nose: 260 + discard 3 Energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if not player.active or not player.active.energy_attached:
        return
    energy_on_self = list(player.active.energy_attached)
    to_discard = min(3, len(energy_on_self))
    if to_discard < 3:
        player.active.energy_attached.clear()
        state.emit_event("energy_discarded", player=action.player_id,
                         count=to_discard, reason="Obliterating Nose")
        return
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Obliterating Nose: discard 3 Energy from Probopass",
        cards=energy_on_self, min_count=3, max_count=3,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [a.source_card_id for a in energy_on_self[:3]]
    discarded = 0
    for src_id in chosen_ids[:3]:
        att = next((a for a in player.active.energy_attached
                    if a.source_card_id == src_id), None)
        if att:
            player.active.energy_attached.remove(att)
            discarded += 1
    state.emit_event("energy_discarded", player=action.player_id,
                     count=discarded, reason="Obliterating Nose")


def _sonic_ripper(state, action):
    """me03-055 Mega Skarmory ex atk0 — Sonic Ripper: shuffle all energy attached into deck + 220."""
    player = state.get_player(action.player_id)
    if player.active:
        count = len(player.active.energy_attached)
        player.active.energy_attached.clear()
        if count > 0:
            state.emit_event("energy_shuffled_to_deck", player=action.player_id,
                             count=count, reason="Sonic Ripper")
    _apply_damage(state, action, 220)


def _rock_tumble(state, action):
    """me03-041 Landorus atk0 — Rock Tumble: 50, not affected by Resistance."""
    _apply_damage(state, action, 50)


def _screw_knuckle(state, action):
    """me03-041 Landorus atk1 — Screw Knuckle: 120 + put 1 Energy from self into hand."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if not player.active or not player.active.energy_attached:
        return
    energy_on_self = list(player.active.energy_attached)
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Screw Knuckle: choose 1 Energy from Landorus to put into your hand",
        cards=energy_on_self, min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [energy_on_self[0].source_card_id]
    for src_id in chosen_ids[:1]:
        att = next((a for a in player.active.energy_attached
                    if a.source_card_id == src_id), None)
        if att:
            player.active.energy_attached.remove(att)
            state.emit_event("energy_to_hand", player=action.player_id,
                             card_def_id=att.card_def_id)


# Complex attacks ─────────────────────────────────────────────────────────────

def _blow_through(state, action):
    """me03-009 Vivillon atk0 — Blow Through: 60 + 60 if a Stadium is in play."""
    base_damage = 60 + (60 if state.active_stadium else 0)
    _apply_damage(state, action, base_damage)


def _crushing_arrow(state, action):
    """me03-012 Decidueye ex atk0 — Crushing Arrow: 240 + discard an Energy from opp's Active."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.active or not opp.active.energy_attached:
        return
    energy_on_opp = list(opp.active.energy_attached)
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Crushing Arrow: choose 1 Energy to discard from opponent's Active Pokémon",
        cards=energy_on_opp, min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [energy_on_opp[0].source_card_id]
    for src_id in chosen_ids[:1]:
        att = next((a for a in opp.active.energy_attached
                    if a.source_card_id == src_id), None)
        if att:
            opp.active.energy_attached.remove(att)
            state.emit_event("energy_discarded", player=opp_id,
                             card=opp.active.card_name, reason="Crushing Arrow")


def _follow_me(state, action):
    """me03-030 Clefairy atk0 — Follow Me: switch 1 of opponent's Bench Pokémon to Active."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.bench:
        state.emit_event("attack_no_damage", attacker="Clefairy",
                         attack_name="Follow Me", reason="no bench")
        return
    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Follow Me: choose 1 of opponent's Benched Pokémon to switch to Active",
        targets=list(opp.bench),
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in opp.bench
                       if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = opp.bench[0]
    _switch_active_with_bench(opp, target)
    state.emit_event("forced_switch", player=opp_id,
                     new_active=opp.active.card_name)


def _gaia_wave(state, action):
    """me03-047 Mega Zygarde ex atk0 — Gaia Wave: 200 + 30 less damage from attacks next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.incoming_damage_reduction += 30
        state.emit_event("damage_reduction", card=player.active.card_name, reduction=30)


def _nullifying_zero(state, action):
    """me03-047 Mega Zygarde ex atk1 — Nullifying Zero: flip for each opp Pokémon, 150 per heads."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    if not all_opp:
        return
    for poke in list(all_opp):
        if _random.choice([True, False]):
            state.emit_event("coin_flip_result", attack="Nullifying Zero",
                             target=poke.card_name, result="heads")
            if poke is opp.active:
                _apply_damage(state, action, 150)
            else:
                _apply_bench_damage(state, opp_id, poke, 150)
            if state.phase == Phase.GAME_OVER:
                return
        else:
            state.emit_event("coin_flip_result", attack="Nullifying Zero",
                             target=poke.card_name, result="tails")


def _soul_destroyer(state, action):
    """me03-053 Yveltal ex atk0 — Soul Destroyer: KO each opp Pokémon with ≤50 HP remaining."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    for poke in list(all_opp):
        if poke.current_hp <= 50:
            poke.current_hp = 0
            check_ko(state, poke, opp_id)
            if state.phase == Phase.GAME_OVER:
                return


def _strafe(state, action):
    """me03-054 Chien-Pao atk0 — Strafe: 20 + may switch self with bench."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if not player.bench:
        return
    req = ChoiceRequest(
        "choose_option", action.player_id,
        "Strafe: switch Chien-Pao with a Benched Pokémon?",
        options=["Switch", "Keep Active"],
    )
    resp = yield req
    option_index = 0
    if resp and hasattr(resp, "option_index") and resp.option_index is not None:
        option_index = resp.option_index
    if option_index == 1:
        return
    req_target = ChoiceRequest(
        "choose_target", action.player_id,
        "Strafe: choose a Benched Pokémon to switch with",
        targets=list(player.bench),
    )
    resp_target = yield req_target
    target = None
    if resp_target and hasattr(resp_target, "target_instance_id") and resp_target.target_instance_id:
        target = next((p for p in player.bench
                       if p.instance_id == resp_target.target_instance_id), None)
    if target is None:
        target = player.bench[0]
    _switch_active_with_bench(player, target)
    state.emit_event("self_switch", player=action.player_id,
                     new_active=player.active.card_name)


def _rising_blade(state, action):
    """me03-054 Chien-Pao atk1 — Rising Blade: 80 + 80 if opponent's Active is Pokémon ex."""
    opp = state.get_opponent(action.player_id)
    base_damage = 80
    if opp.active:
        opp_cdef = card_registry.get(opp.active.card_def_id)
        if opp_cdef and opp_cdef.is_ex:
            base_damage += 80
    _apply_damage(state, action, base_damage)


def _weaponized_swords(state, action):
    """me03-057 Doublade atk0 — Weaponized Swords: 60 × Honedge/Doublade/Aegislash in hand."""
    player = state.get_player(action.player_id)
    blade_ids = {"me03-056", "me03-057", "me03-058"}
    blade_count = sum(1 for c in player.hand if c.card_def_id in blade_ids)
    base_damage = 60 * blade_count
    if base_damage <= 0:
        state.emit_event("attack_no_damage", attacker="Doublade",
                         attack_name="Weaponized Swords",
                         reason="no Honedge/Doublade/Aegislash in hand")
        return
    state.emit_event("weaponized_swords", player=action.player_id, blade_count=blade_count)
    _apply_damage(state, action, base_damage)


def _scrape_off(state, action):
    """me03-061 Raticate atk0 — Scrape Off: 20 + discard ALL Pokémon Tools from opp's Active."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if opp.active and opp.active.tools_attached:
        count = len(opp.active.tools_attached)
        opp.active.tools_attached.clear()
        state.emit_event("tools_discarded", player=opp_id,
                         card=opp.active.card_name, count=count, reason="Scrape Off")
    _do_default_damage(state, action)


def _haunt(state, action):
    """me03-049 Haunter atk0 — Haunt: place 3 damage counters on opponent's Active (no W/R)."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.active:
        return
    opp.active.current_hp -= 30
    opp.active.damage_counters += 3
    state.emit_event("damage_counters_placed", player=opp_id,
                     card=opp.active.card_name, counters=3, reason="Haunt")
    check_ko(state, opp.active, opp_id)


def _geobuster(state, action):
    """me03-070 Core Memory atk0 — Geobuster: 350 + discard ALL energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active and player.active.energy_attached:
        count = len(player.active.energy_attached)
        player.active.energy_attached.clear()
        state.emit_event("energy_discarded", player=action.player_id,
                         count=count, reason="Geobuster")


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _switch_active_with_bench(player, bench_poke) -> None:
    """Swap bench_poke into the active slot."""
    old_active = player.active
    if old_active is None:
        bench_poke.zone = Zone.ACTIVE
        player.active = bench_poke
        player.bench.remove(bench_poke)
        return
    old_active.zone = Zone.BENCH
    bench_poke.zone = Zone.ACTIVE
    player.active = bench_poke
    player.bench.remove(bench_poke)
    player.bench.append(old_active)


def _shuffle_deck(player) -> None:
    """Shuffle player's deck in place."""
    _random.shuffle(player.deck)


def _ambush(state, action):
    """me02.5-017 Grubbin — Ambush: 10+ / flip coin, heads = 30 more."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):
        _apply_damage(state, action, 30)


# ──────────────────────────────────────────────────────────────────────────────
# Batch 2: ASC (Ascended Heroes) me02.5-034 through me02.5-133
# ──────────────────────────────────────────────────────────────────────────────

def _ember(state, action):
    """me02.5-034 Salandit atk0 — Ember: 30 + discard 1 Energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active and player.active.energy_attached:
        player.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="ember", count=1)


def _sudden_scorching(state, action):
    """me02.5-035 Salazzle atk0 — Sudden Scorching: opponent discards 1, +2 if evolved this turn."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)

    discard_count = 1
    if (player.active and player.active.evolved_from is not None
            and player.active.turn_played == state.turn_number):
        discard_count += 2

    if not opp.hand:
        state.emit_event("sudden_scorching", player=action.player_id, discarded=0)
        return

    req = ChoiceRequest(
        "choose_cards", action.player_id,
        f"Sudden Scorching: opponent discards {discard_count} card(s) from hand",
        cards=opp.hand, min_count=min(discard_count, len(opp.hand)),
        max_count=min(discard_count, len(opp.hand)),
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in opp.hand[:discard_count]]

    discarded = 0
    for cid in chosen_ids[:discard_count]:
        card = next((c for c in opp.hand if c.instance_id == cid), None)
        if card:
            opp.hand.remove(card)
            card.zone = Zone.DISCARD
            opp.discard.append(card)
            discarded += 1
    state.emit_event("sudden_scorching", player=action.player_id, discarded=discarded)


def _flamethrower(state, action):
    """me02.5-035 Salazzle atk1 — Flamethrower: 130 + discard 1 Energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active and player.active.energy_attached:
        player.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="flamethrower", count=1)


def _flare_strike_asc(state, action):
    """me02.5-038 Cinderace ex atk0 — Flare Strike: 280 + can't use this attack next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=player.active.card_name,
                         attack="Flare Strike")


def _garnet_volley(state, action):
    """me02.5-038 Cinderace ex atk1 — Garnet Volley: 180 to 1 of opponent's Pokémon, no W/R for bench."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    if not all_opp:
        return

    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Garnet Volley: choose 1 of opponent's Pokémon",
        targets=all_opp,
    )
    resp = yield req
    target = None
    if resp and resp.target_instance_id:
        target = next((p for p in all_opp if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = opp.active or opp.bench[0]

    if target is opp.active:
        _apply_damage(state, action, 180)
    else:
        _apply_bench_damage(state, opp_id, target, 180)


def _hydro_pump_asc(state, action):
    """me02.5-040 Golduck atk0 — Hydro Pump: 60 + 20 per {W} Energy attached to self."""
    player = state.get_player(action.player_id)
    water_count = sum(1 for att in player.active.energy_attached
                      if att.energy_type == EnergyType.WATER) if player.active else 0
    _apply_damage(state, action, 60 + 20 * water_count)


def _crunch(state, action):
    """me02.5-042 Croconaw atk0 — Crunch: 50 + flip coin, heads: discard 1 Energy from opp's active."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):  # heads
        opp = state.get_opponent(action.player_id)
        state.emit_event("coin_flip_result", attack="Crunch", result="heads")
        if opp.active and opp.active.energy_attached:
            opp.active.energy_attached.pop(0)
            state.emit_event("energy_discarded", card=opp.active.card_name,
                             reason="crunch", count=1)
    else:
        state.emit_event("coin_flip_result", attack="Crunch", result="tails")


def _mortal_crunch(state, action):
    """me02.5-043 Mega Feraligatr ex atk0 — Mortal Crunch: 200 + 200 if opp active has damage counters."""
    opp = state.get_opponent(action.player_id)
    bonus = 200 if opp.active and opp.active.damage_counters > 0 else 0
    _apply_damage(state, action, 200 + bonus)


def _hail_claw(state, action):
    """me02.5-045 Weavile atk1 — Hail Claw: 70 + discard all Energy from self + Paralyze defender."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.energy_attached.clear()
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="hail_claw", count="all")
    opp = state.get_opponent(action.player_id)
    if opp.active and state.phase != Phase.GAME_OVER:
        opp.active.status_conditions.add(StatusCondition.PARALYZED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="PARALYZED", attack="Hail Claw")


def _regi_charge_w(state, action):
    """me02.5-048 Regice ex atk0 — Regi Charge: attach up to 2 Basic {W} from discard to self."""
    from app.engine.state import EnergyAttachment
    player = state.get_player(action.player_id)
    w_energy = [c for c in player.discard
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Water" in (c.energy_provides or [])]
    if not w_energy or not player.active:
        state.emit_event("regi_charge", player=action.player_id, attached=0, type="W")
        return

    max_count = min(2, len(w_energy))
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Regi Charge: attach up to 2 Basic {W} Energy from discard to Regice ex",
        cards=w_energy, min_count=0, max_count=max_count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in w_energy[:max_count]]

    attached = 0
    for cid in chosen_ids[:max_count]:
        ec = next((c for c in player.discard if c.instance_id == cid), None)
        if ec and player.active:
            player.discard.remove(ec)
            ec.zone = player.active.zone
            player.active.energy_attached.append(EnergyAttachment(
                energy_type=EnergyType.WATER,
                source_card_id=ec.instance_id,
                card_def_id=ec.card_def_id,
                provides=[EnergyType.WATER],
            ))
            attached += 1
    state.emit_event("regi_charge", player=action.player_id, attached=attached, type="W")


def _ice_prison(state, action):
    """me02.5-048 Regice ex atk1 — Ice Prison: 140 + discard 2 Energy from self + Paralyze."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        for _ in range(2):
            if player.active.energy_attached:
                player.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="ice_prison", count=2)
    opp = state.get_opponent(action.player_id)
    if opp.active and state.phase != Phase.GAME_OVER:
        opp.active.status_conditions.add(StatusCondition.PARALYZED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="PARALYZED", attack="Ice Prison")


def _sheer_cold(state, action):
    """me02.5-050 N's Vanillish atk1 — Sheer Cold: 60 + opp can't attack next turn."""
    _do_default_damage(state, action)
    opp = state.get_opponent(action.player_id)
    if opp.active and state.phase != Phase.GAME_OVER:
        opp.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=opp.active.card_name,
                         attack="Sheer Cold")


def _snow_coating(state, action):
    """me02.5-051 N's Vanilluxe atk0 — Snow Coating: double damage counters on each opp Pokémon."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    for poke in list(all_opp):
        if poke.damage_counters > 0:
            extra = poke.damage_counters * 10
            poke.damage_counters *= 2
            poke.current_hp -= extra
            state.emit_event("snow_coating", player=opp_id,
                             card=poke.card_name, counters_added=poke.damage_counters // 2)
            check_ko(state, poke, opp_id)
            if state.phase == Phase.GAME_OVER:
                return
    state.emit_event("attack_no_damage", attacker="N's Vanilluxe",
                     attack_name="Snow Coating")


def _blizzard(state, action):
    """me02.5-051 N's Vanilluxe atk1 — Blizzard: 120 + 10 to each benched opponent."""
    _apply_damage(state, action, 120)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    for bench_poke in list(opp.bench):
        _apply_bench_damage(state, opp_id, bench_poke, 10)
        if state.phase == Phase.GAME_OVER:
            return


def _cold_cyclone(state, action):
    """me02.5-053 Frosmoth atk0 — Cold Cyclone: 90 + move 1 {W} Energy from self to benched."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if not player.bench or not player.active:
        return

    w_energies = [att for att in player.active.energy_attached
                  if att.energy_type == EnergyType.WATER]
    if not w_energies:
        return

    req_target = ChoiceRequest(
        "choose_target", action.player_id,
        "Cold Cyclone: move 1 {W} Energy to a benched Pokémon",
        targets=player.bench,
    )
    resp_target = yield req_target
    target = None
    if resp_target and resp_target.target_instance_id:
        target = next((p for p in player.bench
                       if p.instance_id == resp_target.target_instance_id), None)
    if target is None:
        target = player.bench[0]

    att = w_energies[0]
    player.active.energy_attached.remove(att)
    target.energy_attached.append(att)
    state.emit_event("energy_moved", player=action.player_id,
                     from_card=player.active.card_name, to_card=target.card_name)


def _ice_shot(state, action):
    """me02.5-054 Glastrier atk0 — Ice Shot: 20 + 20 to 1 benched opponent (no W/R)."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.bench:
        return

    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Ice Shot: choose 1 of opponent's Benched Pokémon (20 damage)",
        targets=opp.bench,
    )
    resp = yield req
    target = None
    if resp and resp.target_instance_id:
        target = next((p for p in opp.bench if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = opp.bench[0]
    _apply_bench_damage(state, opp_id, target, 20)


def _frosty_typhoon(state, action):
    """me02.5-054 Glastrier atk1 — Frosty Typhoon: 130 + can't attack next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=player.active.card_name,
                         attack="Frosty Typhoon")


def _quick_blow(state, action):
    """me02.5-056 Raichu atk0 — Quick Blow: 20 + flip coin, heads = +50."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):  # heads
        state.emit_event("coin_flip_result", attack="Quick Blow", result="heads")
        _apply_damage(state, action, 50)
    else:
        state.emit_event("coin_flip_result", attack="Quick Blow", result="tails")


def _discard_one_l_energy(state, action):
    """me02.5-056 Raichu atk1 — Strong Volt: 150 + discard 1 {L} Energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        l_energy = next((att for att in player.active.energy_attached
                         if att.energy_type == EnergyType.LIGHTNING), None)
        if l_energy:
            player.active.energy_attached.remove(l_energy)
            state.emit_event("energy_discarded", card=player.active.card_name,
                             reason="strong_volt_raichu", count=1)


def _topaz_bolt(state, action):
    """me02.5-057 Pikachu ex atk0 — Topaz Bolt: 300 + discard 3 Energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        for _ in range(3):
            if player.active.energy_attached:
                player.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="topaz_bolt", count=3)


def _hundred_hitting_ball(state, action):
    """me02.5-058 Voltorb ex atk0 — Hundred-Hitting Ball: 100 + flip until tails, +100/heads."""
    heads = 0
    while _random.choice([True, False]):
        heads += 1
    state.emit_event("coin_flip_result", attack="Hundred-Hitting Ball",
                     heads=heads)
    _apply_damage(state, action, 100 + 100 * heads)


def _hold_still(state, action):
    """me02.5-059 Tynamo atk0 — Hold Still: heal 10 HP from self, no damage."""
    player = state.get_player(action.player_id)
    if player.active:
        heal = min(10, player.active.damage_counters * 10)
        if heal > 0:
            player.active.current_hp = min(player.active.max_hp,
                                           player.active.current_hp + heal)
            player.active.damage_counters = max(0,
                                                player.active.damage_counters - heal // 10)
            state.emit_event("healed", player=action.player_id,
                             card=player.active.card_name, amount=heal)
    state.emit_event("attack_no_damage", attacker="Tynamo", attack_name="Hold Still")


def _split_bomb(state, action):
    """me02.5-061 Mega Eelektross ex atk0 — Split Bomb: 60 to each of 2 opp Pokémon."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    if not all_opp:
        return

    if len(all_opp) == 1:
        if all_opp[0] is opp.active:
            _apply_damage(state, action, 60)
        else:
            _apply_bench_damage(state, opp_id, all_opp[0], 60)
        return

    req = ChoiceRequest(
        "choose_targets", action.player_id,
        "Split Bomb: choose 2 of opponent's Pokémon (60 each)",
        targets=all_opp, min_count=2, max_count=2,
    )
    resp = yield req
    chosen_ids = set()
    if resp and hasattr(resp, "target_instance_ids") and resp.target_instance_ids:
        chosen_ids = set(resp.target_instance_ids[:2])
    if len(chosen_ids) < 2:
        chosen_ids = {p.instance_id for p in all_opp[:2]}

    for poke in list(all_opp):
        if poke.instance_id not in chosen_ids:
            continue
        if poke is opp.active:
            _apply_damage(state, action, 60)
        else:
            _apply_bench_damage(state, opp_id, poke, 60)
        if state.phase == Phase.GAME_OVER:
            return


def _disaster_shock(state, action):
    """me02.5-061 Mega Eelektross ex atk1 — Disaster Shock: 190, may discard 2 L → Paralyze."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if not player.active:
        return

    l_energies = [att for att in player.active.energy_attached
                  if att.energy_type == EnergyType.LIGHTNING]
    if len(l_energies) < 2:
        return

    req = ChoiceRequest(
        "choose_option", action.player_id,
        "Disaster Shock: discard 2 {L} Energy to Paralyze the opponent?",
        options=["Yes, discard 2 {L}", "No"],
    )
    resp = yield req
    if resp is None or (resp.selected_option or 0) != 0:
        return

    for att in l_energies[:2]:
        player.active.energy_attached.remove(att)
    state.emit_event("energy_discarded", card=player.active.card_name,
                     reason="disaster_shock", count=2)
    opp = state.get_opponent(action.player_id)
    if opp.active and state.phase != Phase.GAME_OVER:
        opp.active.status_conditions.add(StatusCondition.PARALYZED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="PARALYZED", attack="Disaster Shock")


def _pouncing_trap(state, action):
    """me02.5-062 Stunfisk atk0 — Pouncing Trap: 30 + can't retreat, +100 incoming next attack."""
    _do_default_damage(state, action)
    opp = state.get_opponent(action.player_id)
    if opp.active and state.phase != Phase.GAME_OVER:
        opp.active.cant_retreat_next_turn = True
        # incoming_damage_reduction = -100 means +100 damage on next attack
        opp.active.incoming_damage_reduction = -100
        state.emit_event("pouncing_trap", card=opp.active.card_name)


def _powerful_bolt(state, action):
    """me02.5-064 Heliolisk atk0 — Powerful Bolt: 70 per energy, flip coin per energy."""
    player = state.get_player(action.player_id)
    energy_count = len(player.active.energy_attached) if player.active else 0
    if energy_count == 0:
        state.emit_event("attack_no_damage", attacker="Heliolisk",
                         attack_name="Powerful Bolt")
        return
    heads = sum(1 for _ in range(energy_count) if _random.choice([True, False]))
    state.emit_event("coin_flip_result", attack="Powerful Bolt",
                     heads=heads, flips=energy_count)
    if heads == 0:
        state.emit_event("attack_no_damage", attacker="Heliolisk",
                         attack_name="Powerful Bolt")
        return
    _apply_damage(state, action, 70 * heads)


def _volt_switch_l(state, action):
    """me02.5-066 Vikavolt atk0 — Volt Switch: 90 + switch self with benched {L} Pokémon."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    l_bench = [p for p in player.bench
               if any(att.energy_type == EnergyType.LIGHTNING
                      for att in p.energy_attached)
               or _pokemon_has_type_by_card(p, "Lightning")]
    if not l_bench:
        return

    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Volt Switch: switch Vikavolt with a benched {L} Pokémon",
        targets=l_bench,
    )
    resp = yield req
    bench_poke = None
    if resp and resp.target_instance_id:
        bench_poke = next((p for p in l_bench if p.instance_id == resp.target_instance_id), None)
    if bench_poke is None:
        bench_poke = l_bench[0]
    _switch_active_with_bench(player, bench_poke)
    state.emit_event("volt_switch", player=action.player_id,
                     new_active=bench_poke.card_name)


def _pokemon_has_type_by_card(pokemon, type_str: str) -> bool:
    """Check Pokémon type from card definition (attacks.py local helper)."""
    cdef = card_registry.get(pokemon.card_def_id)
    return bool(cdef and type_str in (cdef.types or []))


def _fast_flight(state, action):
    """me02.5-067 Tapu Koko atk0 — Fast Flight: discard hand, draw 5 (no damage)."""
    player = state.get_player(action.player_id)
    for c in list(player.hand):
        player.hand.remove(c)
        c.zone = Zone.DISCARD
        player.discard.append(c)
    from app.engine.effects.base import draw_cards
    drawn = draw_cards(state, action.player_id, 5)
    state.emit_event("fast_flight", player=action.player_id, drawn=drawn)
    state.emit_event("attack_no_damage", attacker="Tapu Koko", attack_name="Fast Flight")


def _thunder_blast(state, action):
    """me02.5-067 Tapu Koko atk1 — Thunder Blast: 130 + discard 2 Energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        for _ in range(2):
            if player.active.energy_attached:
                player.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="thunder_blast", count=2)


def _spiky_thunder(state, action):
    """me02.5-068 Hop's Pincurchin ex atk0 — Spiky Thunder: 120 + draw 2 cards."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    from app.engine.effects.base import draw_cards
    drawn = draw_cards(state, action.player_id, 2)
    state.emit_event("spiky_thunder_draw", player=action.player_id, drawn=drawn)


def _thunderous_bolt(state, action):
    """me02.5-070 Iono's Bellibolt ex atk0 — Thunderous Bolt: 230 + can't attack next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=player.active.card_name,
                         attack="Thunderous Bolt")


def _quick_attack_asc(state, action):
    """me02.5-071 Iono's Wattrel atk0 — Quick Attack: 10 + flip coin, heads = +20."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):  # heads
        state.emit_event("coin_flip_result", attack="Quick Attack", result="heads")
        _apply_damage(state, action, 20)
    else:
        state.emit_event("coin_flip_result", attack="Quick Attack", result="tails")


def _hadron_spark(state, action):
    """me02.5-073 Miraidon ex atk1 — Hadron Spark: 120 + 120 if opp active is Pokémon ex."""
    opp = state.get_opponent(action.player_id)
    bonus = 0
    if opp.active:
        opp_cdef = card_registry.get(opp.active.card_def_id)
        if opp_cdef and opp_cdef.is_ex:
            bonus = 120
    _apply_damage(state, action, 120 + bonus)


def _metronome(state, action):
    """me02.5-075 Clefable atk0 — Metronome: copy one of opp's active's attacks."""
    opp = state.get_opponent(action.player_id)
    if not opp.active:
        state.emit_event("attack_no_damage", attacker="Clefable",
                         attack_name="Metronome")
        return
    opp_cdef = card_registry.get(opp.active.card_def_id)
    if not opp_cdef or not opp_cdef.attacks:
        state.emit_event("attack_no_damage", attacker="Clefable",
                         attack_name="Metronome")
        return

    if len(opp_cdef.attacks) > 1:
        req = ChoiceRequest(
            "choose_option", action.player_id,
            "Metronome: choose which of opponent's attacks to copy",
            options=[f"{i}: {a.name}" for i, a in enumerate(opp_cdef.attacks)],
        )
        resp = yield req
        attack_idx = (resp.selected_option or 0) if resp else 0
    else:
        attack_idx = 0

    attack_idx = max(0, min(attack_idx, len(opp_cdef.attacks) - 1))
    copied_attack = opp_cdef.attacks[attack_idx]
    base_dmg = _parse_damage(copied_attack.damage) if copied_attack.damage else 0
    if base_dmg > 0:
        _apply_damage(state, action, base_dmg)
    state.emit_event("metronome", player=action.player_id,
                     copied_from=opp.active.card_name,
                     attack_name=copied_attack.name)


def _parse_damage(damage_str) -> int:
    """Parse a damage string like '100+' or '120' to an int."""
    if damage_str is None:
        return 0
    s = str(damage_str).strip().rstrip("+×x").strip()
    try:
        return int(s)
    except ValueError:
        return 0


def _focused_wish(state, action):
    """me02.5-077 TR Exeggcute atk0 — Focused Wish: 10 + flip coin, heads = +20."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):  # heads
        state.emit_event("coin_flip_result", attack="Focused Wish", result="heads")
        _apply_damage(state, action, 20)
    else:
        state.emit_event("coin_flip_result", attack="Focused Wish", result="tails")


def _tri_kinesis(state, action):
    """me02.5-078 TR Exeggutor atk0 — Tri Kinesis: flip 3 coins, all heads → KO 1 opp Pokémon."""
    flips = [_random.choice([True, False]) for _ in range(3)]
    heads = sum(flips)
    state.emit_event("coin_flip_result", attack="Tri Kinesis",
                     heads=heads, flips=3, results=flips)
    if heads < 3:
        state.emit_event("attack_no_damage", attacker="Team Rocket's Exeggutor",
                         attack_name="Tri Kinesis")
        return

    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    if not all_opp:
        return

    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Tri Kinesis (all heads!): choose 1 of opponent's Pokémon to KO",
        targets=all_opp,
    )
    resp = yield req
    target = None
    if resp and resp.target_instance_id:
        target = next((p for p in all_opp if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = opp.active or opp.bench[0]

    target.current_hp = 0
    target_pid = opp_id
    state.emit_event("tri_kinesis_ko", player=action.player_id,
                     target=target.card_name)
    check_ko(state, target, target_pid)


def _double_edge(state, action):
    """me02.5-078 TR Exeggutor atk1 — Double-Edge: 150 + 30 recoil to self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.current_hp -= 30
        player.active.damage_counters += 3
        state.emit_event("recoil_damage", player=action.player_id,
                         card=player.active.card_name, damage=30)
        check_ko(state, player.active, action.player_id)


def _erasure_ball_asc(state, action):
    """me02.5-079 TR Mewtwo ex atk0 — Erasure Ball: 160 + discard up to 2 Energy from YOUR bench, +60 each."""
    player = state.get_player(action.player_id)
    bench_with_energy = [p for p in player.bench if p.energy_attached]
    if not bench_with_energy:
        _apply_damage(state, action, 160)
        return

    req = ChoiceRequest(
        "choose_targets", action.player_id,
        "Erasure Ball: choose up to 2 of your Benched Pokémon to discard 1 Energy from (+60 each)",
        targets=bench_with_energy, min_count=0, max_count=2,
    )
    resp = yield req
    chosen_ids = set()
    if resp and hasattr(resp, "target_instance_ids") and resp.target_instance_ids:
        chosen_ids = set(resp.target_instance_ids[:2])

    discarded = 0
    for poke in bench_with_energy:
        if poke.instance_id not in chosen_ids:
            continue
        if poke.energy_attached:
            poke.energy_attached.pop(0)
            discarded += 1

    state.emit_event("erasure_ball_asc", player=action.player_id, discarded=discarded)
    _apply_damage(state, action, 160 + 60 * discarded)


def _hide(state, action):
    """me02.5-083 Marill atk0 — Hide: flip coin, heads = prevent all damage next turn."""
    player = state.get_player(action.player_id)
    if _random.choice([True, False]):  # heads
        state.emit_event("coin_flip_result", attack="Hide", result="heads")
        if player.active:
            player.active.prevent_damage_one_turn = True
            state.emit_event("damage_prevention_set", card=player.active.card_name,
                             attack="Hide")
    else:
        state.emit_event("coin_flip_result", attack="Hide", result="tails")
    state.emit_event("attack_no_damage", attacker="Marill", attack_name="Hide")


def _energized_balloon(state, action):
    """me02.5-084 Azumarill ex atk0 — Energized Balloon: 60 + 40 per {P} Energy attached to self."""
    player = state.get_player(action.player_id)
    p_count = sum(1 for att in player.active.energy_attached
                  if EnergyType.PSYCHIC in att.provides) if player.active else 0
    _apply_damage(state, action, 60 + 40 * p_count)


def _ascension_misdreavus(state, action):
    """me02.5-085 Misdreavus atk0 — Ascension: search deck for Mismagius to evolve into."""
    player = state.get_player(action.player_id)
    if not player.active:
        return

    evo_cards = [c for c in player.deck if c.card_def_id == "me02.5-086"]
    if not evo_cards:
        state.emit_event("attack_failed", attack="Ascension",
                         reason="no Mismagius in deck")
        return

    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Ascension: search your deck for Mismagius",
        cards=evo_cards, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [evo_cards[0].instance_id]

    for cid in chosen_ids[:1]:
        evo_card = next((c for c in player.deck if c.instance_id == cid), None)
        if evo_card and player.active:
            old_active = player.active
            player.deck.remove(evo_card)
            evo_cdef = card_registry.get(evo_card.card_def_id)
            evo_card.zone = Zone.ACTIVE
            evo_card.max_hp = evo_cdef.hp if evo_cdef else evo_card.max_hp
            evo_card.current_hp = evo_card.max_hp - old_active.damage_counters * 10
            evo_card.damage_counters = old_active.damage_counters
            evo_card.energy_attached = list(old_active.energy_attached)
            evo_card.tools_attached = list(old_active.tools_attached)
            evo_card.status_conditions = set(old_active.status_conditions)
            evo_card.evolved_from = old_active.instance_id
            evo_card.evolution_stage = 1
            evo_card.turn_played = state.turn_number
            player.active = evo_card
            old_active.zone = Zone.DISCARD
            player.discard.append(old_active)
            _shuffle_deck(player)
            state.emit_event("evolved", player=action.player_id,
                             from_card=old_active.card_name,
                             to_card=evo_card.card_name,
                             via="Ascension")


def _assassins_magic(state, action):
    """me02.5-086 Mismagius atk0 — Assassin's Magic: 60 + 60 more if opp active has Special Condition."""
    opp = state.get_opponent(action.player_id)
    bonus = 0
    if opp.active and opp.active.status_conditions:
        bonus = 60
    _apply_damage(state, action, 60 + bonus)


def _cursed_words(state, action):
    """me02.5-091 Banette atk0 — Cursed Words: opponent reveals hand, shuffles 3 cards back."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if len(opp.hand) <= 3:
        for c in list(opp.hand):
            opp.hand.remove(c)
            opp.deck.append(c)
        _shuffle_deck(opp)
        state.emit_event("cursed_words", player=action.player_id,
                         shuffled=len(opp.deck))
        return

    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Cursed Words: choose 3 cards from opponent's hand to shuffle into deck",
        cards=opp.hand, min_count=3, max_count=3,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids or len(chosen_ids) < 3:
        chosen_ids = [c.instance_id for c in opp.hand[:3]]

    shuffled = 0
    for cid in chosen_ids[:3]:
        card = next((c for c in opp.hand if c.instance_id == cid), None)
        if card:
            opp.hand.remove(card)
            opp.deck.append(card)
            shuffled += 1
    _shuffle_deck(opp)
    state.emit_event("cursed_words", player=action.player_id, shuffled=shuffled)


def _roto_call(state, action):
    """me02.5-092 Rotom atk0 — Roto Call: search deck for any Rotom Pokémon, put in hand."""
    player = state.get_player(action.player_id)
    rotom_cards = [c for c in player.deck
                   if c.card_type.lower() == "pokemon"
                   and "Rotom" in c.card_name]
    if not rotom_cards:
        _shuffle_deck(player)
        state.emit_event("roto_call", player=action.player_id, found=0)
        return

    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Roto Call: choose any number of Rotom Pokémon from deck to put in hand",
        cards=rotom_cards, min_count=0, max_count=len(rotom_cards),
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [c.instance_id for c in rotom_cards])

    found = 0
    for cid in chosen_ids:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
            found += 1
    _shuffle_deck(player)
    state.emit_event("roto_call", player=action.player_id, found=found)


def _gadget_show(state, action):
    """me02.5-092 Rotom atk1 — Gadget Show: 30 × tools on all your Pokémon."""
    player = state.get_player(action.player_id)
    tool_count = sum(len(p.tools_attached) for p in _in_play(player))
    if tool_count == 0:
        state.emit_event("attack_no_damage", attacker="Rotom",
                         attack_name="Gadget Show")
        return
    _apply_damage(state, action, 30 * tool_count)


def _splashing_dodge(state, action):
    """me02.5-095 Hop's Phantump atk0 — Splashing Dodge: 10 + flip coin, heads = prevent all damage."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if _random.choice([True, False]):  # heads
        state.emit_event("coin_flip_result", attack="Splashing Dodge", result="heads")
        if player.active:
            player.active.prevent_damage_one_turn = True
            state.emit_event("damage_prevention_set", card=player.active.card_name,
                             attack="Splashing Dodge")
    else:
        state.emit_event("coin_flip_result", attack="Splashing Dodge", result="tails")


def _horrifying_revenge(state, action):
    """me02.5-096 Hop's Trevenant atk0 — Horrifying Revenge: 30 + 100 if Hop's Pokémon KO'd last turn."""
    prev_turn = state.turn_number - 1
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    ko_happened = any(
        e.get("event_type") == "ko"
        and e.get("ko_player") == player_id
        and "Hop's" in (e.get("card_name") or "")
        and e.get("turn", -1) == prev_turn
        for e in state.events
    )
    bonus = 100 if ko_happened else 0
    _apply_damage(state, action, 30 + bonus)


def _phantasmal_barrage(state, action):
    """me02.5-098 Spectrier atk1 — Phantasmal Barrage: discard all energy, 12 counters on 1 opp Pokémon."""
    player = state.get_player(action.player_id)
    if player.active:
        player.active.energy_attached.clear()
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="phantasmal_barrage", count="all")

    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    if not all_opp:
        state.emit_event("attack_no_damage", attacker="Spectrier",
                         attack_name="Phantasmal Barrage")
        return

    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Phantasmal Barrage: place 12 damage counters on 1 of opponent's Pokémon",
        targets=all_opp,
    )
    resp = yield req
    target = None
    if resp and resp.target_instance_id:
        target = next((p for p in all_opp if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = opp.active or opp.bench[0]

    _place_bench_counters(state, opp_id, target, 12)


def _relentless_burrowing(state, action):
    """me02.5-100 TR Diglett atk0 — Relentless Burrowing: flip until tails, discard top opp deck card each heads."""
    opp = state.get_opponent(action.player_id)
    heads = 0
    while _random.choice([True, False]):
        if opp.deck:
            top_card = opp.deck.pop(0)
            top_card.zone = Zone.DISCARD
            opp.discard.append(top_card)
            heads += 1
        else:
            break
    state.emit_event("relentless_burrowing", player=action.player_id, discarded=heads)
    state.emit_event("attack_no_damage", attacker="Team Rocket's Diglett",
                     attack_name="Relentless Burrowing")


def _spin_and_draw(state, action):
    """me02.5-102 Hitmontop atk0 — Spin and Draw: shuffle hand into deck, draw 6."""
    player = state.get_player(action.player_id)
    for c in list(player.hand):
        player.hand.remove(c)
        player.deck.append(c)
    _shuffle_deck(player)
    from app.engine.effects.base import draw_cards
    drawn = draw_cards(state, action.player_id, 6)
    state.emit_event("spin_and_draw", player=action.player_id, drawn=drawn)
    state.emit_event("attack_no_damage", attacker="Hitmontop",
                     attack_name="Spin and Draw")


def _seventh_kick(state, action):
    """me02.5-104 Medicham atk0 — Seventh Kick: 150, does nothing if hand ≠ 7 cards."""
    player = state.get_player(action.player_id)
    if len(player.hand) != 7:
        state.emit_event("attack_no_damage", attacker="Medicham",
                         attack_name="Seventh Kick",
                         reason=f"hand has {len(player.hand)} cards, not 7")
        return
    _apply_damage(state, action, 150)


def _cosmic_beam_asc(state, action):
    """me02.5-106 Solrock atk0 — Cosmic Beam: 70 if Lunatone on bench, bypass W/R."""
    player = state.get_player(action.player_id)
    has_lunatone = any("Lunatone" in p.card_name for p in player.bench)
    if not has_lunatone:
        state.emit_event("attack_no_damage", attacker="Solrock",
                         attack_name="Cosmic Beam", reason="no Lunatone on bench")
        return
    _apply_damage(state, action, 70, bypass_wr=True)


def _regi_charge_f(state, action):
    """me02.5-107 Regirock ex atk0 — Regi Charge: attach up to 2 Basic {F} from discard to self."""
    from app.engine.state import EnergyAttachment
    player = state.get_player(action.player_id)
    f_energy = [c for c in player.discard
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Fighting" in (c.energy_provides or [])]
    if not f_energy or not player.active:
        state.emit_event("regi_charge", player=action.player_id, attached=0, type="F")
        return

    max_count = min(2, len(f_energy))
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Regi Charge: attach up to 2 Basic {F} Energy from discard to Regirock ex",
        cards=f_energy, min_count=0, max_count=max_count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in f_energy[:max_count]]

    attached = 0
    for cid in chosen_ids[:max_count]:
        ec = next((c for c in player.discard if c.instance_id == cid), None)
        if ec and player.active:
            player.discard.remove(ec)
            ec.zone = player.active.zone
            player.active.energy_attached.append(EnergyAttachment(
                energy_type=EnergyType.FIGHTING,
                source_card_id=ec.instance_id,
                card_def_id=ec.card_def_id,
                provides=[EnergyType.FIGHTING],
            ))
            attached += 1
    state.emit_event("regi_charge", player=action.player_id, attached=attached, type="F")


def _giant_rock(state, action):
    """me02.5-107 Regirock ex atk1 — Giant Rock: 140 + 140 if opp active is Stage 2."""
    opp = state.get_opponent(action.player_id)
    bonus = 0
    if opp.active:
        opp_cdef = card_registry.get(opp.active.card_def_id)
        if opp_cdef and opp_cdef.stage.lower() in ("stage 2", "stage2", "mega"):
            bonus = 140
    _apply_damage(state, action, 140 + bonus)


def _megaton_fall(state, action):
    """me02.5-108 Groudon atk1 — Megaton Fall: 150 + 30 recoil to self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.current_hp -= 30
        player.active.damage_counters += 3
        state.emit_event("recoil_damage", player=action.player_id,
                         card=player.active.card_name, damage=30)
        check_ko(state, player.active, action.player_id)


def _rock_hurl(state, action):
    """me02.5-109 Cynthia's Gible atk0 — Rock Hurl: 20, ignore Resistance."""
    _apply_damage(state, action, 20, bypass_wr=True)


def _corkscrew_dive(state, action):
    """me02.5-111 Cynthia's Garchomp ex atk0 — Corkscrew Dive: 100 + draw until 6 in hand."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    from app.engine.effects.base import draw_cards
    to_draw = max(0, 6 - len(player.hand))
    if to_draw > 0:
        drawn = draw_cards(state, action.player_id, to_draw)
        state.emit_event("corkscrew_dive_draw", player=action.player_id, drawn=drawn)


def _draconic_buster(state, action):
    """me02.5-111 Cynthia's Garchomp ex atk1 — Draconic Buster: 260 + discard all energy."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.energy_attached.clear()
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="draconic_buster", count="all")


def _accelerating_stab(state, action):
    """me02.5-112 Riolu atk0 — Accelerating Stab: 30 + can't attack next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=player.active.card_name,
                         attack="Accelerating Stab")


def _aura_jab(state, action):
    """me02.5-113 Mega Lucario ex atk0 — Aura Jab: 130 + attach up to 3 Basic {F} from discard to benched."""
    from app.engine.state import EnergyAttachment
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if not player.bench:
        return

    f_energy = [c for c in player.discard
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Fighting" in (c.energy_provides or [])]
    if not f_energy:
        return

    max_count = min(3, len(f_energy))
    req_cards = ChoiceRequest(
        "choose_cards", action.player_id,
        "Aura Jab: attach up to 3 Basic {F} Energy from discard to benched Pokémon",
        cards=f_energy, min_count=0, max_count=max_count,
    )
    resp_cards = yield req_cards
    chosen_ids = (resp_cards.chosen_card_ids if resp_cards and hasattr(resp_cards, "chosen_card_ids")
                  and resp_cards.chosen_card_ids else [])
    if not chosen_ids:
        return

    for cid in chosen_ids[:max_count]:
        ec = next((c for c in player.discard if c.instance_id == cid), None)
        if not ec or not player.bench:
            continue
        req_target = ChoiceRequest(
            "choose_target", action.player_id,
            f"Aura Jab: attach {ec.card_name} to which benched Pokémon?",
            targets=player.bench,
        )
        resp_target = yield req_target
        target = None
        if resp_target and resp_target.target_instance_id:
            target = next((p for p in player.bench
                           if p.instance_id == resp_target.target_instance_id), None)
        if target is None:
            target = player.bench[0]
        player.discard.remove(ec)
        ec.zone = target.zone
        target.energy_attached.append(EnergyAttachment(
            energy_type=EnergyType.FIGHTING,
            source_card_id=ec.instance_id,
            card_def_id=ec.card_def_id,
            provides=[EnergyType.FIGHTING],
        ))
        state.emit_event("aura_jab_attach", player=action.player_id,
                         target=target.card_name, energy=ec.card_name)


def _mega_brave(state, action):
    """me02.5-113 Mega Lucario ex atk1 — Mega Brave: 270 + can't attack next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=player.active.card_name,
                         attack="Mega Brave")


def _flopping_trap(state, action):
    """me02.5-114 Stunfisk ex atk1 — Flopping Trap: 100 + 100 if self has damage counters."""
    player = state.get_player(action.player_id)
    bonus = 100 if player.active and player.active.damage_counters > 0 else 0
    _apply_damage(state, action, 100 + bonus)


def _guard_press(state, action):
    """me02.5-119 Carkol atk0 — Guard Press: 20 + reduce 20 incoming damage next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.incoming_damage_reduction += 20
        state.emit_event("damage_reduction", card=player.active.card_name, reduction=20)


def _somersault_dive(state, action):
    """me02.5-116 Mega Hawlucha ex atk0 — Somersault Dive: 120 + 140 if stadium in play, discard it."""
    bonus = 0
    if state.active_stadium:
        bonus = 140
        stadium = state.active_stadium
        state.active_stadium = None
        state.emit_event("stadium_discarded", stadium=stadium.card_name,
                         reason="somersault_dive")
    _apply_damage(state, action, 120 + bonus)


def _counter_jewel(state, action):
    """me02.5-117 Carbink atk0 — Counter Jewel: 70 + 100 if opp has 2 or fewer prizes."""
    opp = state.get_opponent(action.player_id)
    bonus = 100 if opp.prizes_remaining <= 2 else 0
    _apply_damage(state, action, 70 + bonus)


def _tar_cannon(state, action):
    """me02.5-120 Coalossal atk0 — Tar Cannon: 140 to 1 opp Pokémon, need 10+ Basic F in discard."""
    player = state.get_player(action.player_id)
    f_in_discard = sum(1 for c in player.discard
                       if c.card_type.lower() == "energy"
                       and c.card_subtype.lower() == "basic"
                       and "Fighting" in (c.energy_provides or []))
    if f_in_discard < 10:
        state.emit_event("attack_no_damage", attacker="Coalossal",
                         attack_name="Tar Cannon",
                         reason=f"only {f_in_discard} Basic F in discard (need 10)")
        return

    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    if not all_opp:
        return

    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Tar Cannon: choose 1 of opponent's Pokémon (140 damage, no W/R for bench)",
        targets=all_opp,
    )
    resp = yield req
    target = None
    if resp and resp.target_instance_id:
        target = next((p for p in all_opp if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = opp.active or opp.bench[0]

    if target is opp.active:
        _apply_damage(state, action, 140)
    else:
        _apply_bench_damage(state, opp_id, target, 140)


def _bulky_bump(state, action):
    """me02.5-120 Coalossal atk1 — Bulky Bump: 220 + discard 3 Energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        for _ in range(3):
            if player.active.energy_attached:
                player.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="bulky_bump", count=3)


def _orichalcum_fang(state, action):
    """me02.5-121 Koraidon ex atk0 — Orichalcum Fang: 50 + 120 if your Pokémon KO'd last turn."""
    prev_turn = state.turn_number - 1
    player_id = action.player_id
    ko_happened = any(
        e.get("event_type") == "ko"
        and e.get("ko_player") == player_id
        and e.get("turn", -1) == prev_turn
        for e in state.events
    )
    bonus = 120 if ko_happened else 0
    _apply_damage(state, action, 50 + bonus)


def _impact_blow(state, action):
    """me02.5-121 Koraidon ex atk1 — Impact Blow: 200 + can't attack next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=player.active.card_name,
                         attack="Impact Blow")


def _settle_the_score(state, action):
    """me02.5-122 Okidogi atk1 — Settle the Score: 80 + 60 per prize opp took last turn."""
    prev_turn = state.turn_number - 1
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    prizes_last_turn = sum(
        e.get("count", 0)
        for e in state.events
        if e.get("event_type") == "prizes_taken"
        and e.get("taking_player") == opp_id
        and e.get("turn", -1) == prev_turn
    )
    _apply_damage(state, action, 80 + 60 * prizes_last_turn)


def _void_gale(state, action):
    """me02.5-125 Mega Gengar ex atk0 — Void Gale: 230 + move 1 Energy from self to benched."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if not player.active or not player.active.energy_attached or not player.bench:
        return

    req_target = ChoiceRequest(
        "choose_target", action.player_id,
        "Void Gale: move 1 Energy from Mega Gengar ex to a benched Pokémon",
        targets=player.bench,
    )
    resp_target = yield req_target
    target = None
    if resp_target and resp_target.target_instance_id:
        target = next((p for p in player.bench
                       if p.instance_id == resp_target.target_instance_id), None)
    if target is None:
        target = player.bench[0]

    att = player.active.energy_attached[0]
    player.active.energy_attached.remove(att)
    target.energy_attached.append(att)
    state.emit_event("energy_moved", player=action.player_id,
                     from_card=player.active.card_name, to_card=target.card_name)


def _deceit(state, action):
    """me02.5-126 TR Murkrow atk0 — Deceit: search deck for Supporter, put in hand."""
    player = state.get_player(action.player_id)
    supporters = [c for c in player.deck
                  if c.card_type.lower() == "trainer"
                  and c.card_subtype.lower() == "supporter"]
    if not supporters:
        _shuffle_deck(player)
        state.emit_event("deceit", player=action.player_id, found=0)
        return

    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Deceit: choose a Supporter from deck to put in hand",
        cards=supporters, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [supporters[0].instance_id]

    for cid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    _shuffle_deck(player)
    state.emit_event("deceit", player=action.player_id, found=len(chosen_ids))
    state.emit_event("attack_no_damage", attacker="Team Rocket's Murkrow",
                     attack_name="Deceit")


def _torment(state, action):
    """me02.5-126 TR Murkrow atk1 — Torment: 30 + choose 1 opp attack, opp can't use it next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if not opp.active:
        return
    opp_cdef = card_registry.get(opp.active.card_def_id)
    if not opp_cdef or not opp_cdef.attacks:
        return

    if len(opp_cdef.attacks) > 1:
        req = ChoiceRequest(
            "choose_option", action.player_id,
            "Torment: choose one of opponent's attacks to lock",
            options=[a.name for a in opp_cdef.attacks],
        )
        resp = yield req
        locked_idx = (resp.selected_option or 0) if resp else 0
    else:
        locked_idx = 0

    locked_idx = max(0, min(locked_idx, len(opp_cdef.attacks) - 1))
    opp.active.cant_attack_next_turn = True
    state.emit_event("torment", player=action.player_id,
                     locked_attack=opp_cdef.attacks[locked_idx].name,
                     target=opp.active.card_name)


def _rocket_feathers(state, action):
    """me02.5-127 TR Honchkrow atk0 — Rocket Feathers: 60× per TR Supporter discarded from hand."""
    player = state.get_player(action.player_id)
    tr_supporters = [c for c in player.hand
                     if c.card_type.lower() == "trainer"
                     and c.card_subtype.lower() == "supporter"
                     and "Team Rocket's" in c.card_name]
    if not tr_supporters:
        state.emit_event("attack_no_damage", attacker="Team Rocket's Honchkrow",
                         attack_name="Rocket Feathers")
        return

    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Rocket Feathers: discard any number of Team Rocket's Supporter cards for +60 each",
        cards=tr_supporters, min_count=0, max_count=len(tr_supporters),
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])

    discarded = 0
    for cid in chosen_ids:
        card = next((c for c in player.hand if c.instance_id == cid), None)
        if card:
            player.hand.remove(card)
            card.zone = Zone.DISCARD
            player.discard.append(card)
            discarded += 1

    if discarded == 0:
        state.emit_event("attack_no_damage", attacker="Team Rocket's Honchkrow",
                         attack_name="Rocket Feathers")
        return
    _apply_damage(state, action, 60 * discarded)


def _gnaw_off(state, action):
    """me02.5-128 Poochyena atk0 — Gnaw Off: 30 + flip coin, heads = +20."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):  # heads
        state.emit_event("coin_flip_result", attack="Gnaw Off", result="heads")
        _apply_damage(state, action, 20)
    else:
        state.emit_event("coin_flip_result", attack="Gnaw Off", result="tails")


def _scarring_shout(state, action):
    """me02.5-132 Galarian Obstagoon atk0 — Scarring Shout: 70 × damage counters on opp's active."""
    opp = state.get_opponent(action.player_id)
    if not opp.active or opp.active.damage_counters == 0:
        state.emit_event("attack_no_damage", attacker="Galarian Obstagoon",
                         attack_name="Scarring Shout")
        return
    _apply_damage(state, action, 70 * opp.active.damage_counters)


def _punk_smash(state, action):
    """me02.5-132 Galarian Obstagoon atk1 — Punk Smash: 160 + discard 1 Energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active and player.active.energy_attached:
        player.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="punk_smash", count=1)


def _raging_curse(state, action):
    """me02.5-133 Cynthia's Spiritomb atk0 — Raging Curse: 10 × damage counters on all Cynthia's benched."""
    player = state.get_player(action.player_id)
    cynthia_bench = [p for p in player.bench if "Cynthia's" in p.card_name]
    total_counters = sum(p.damage_counters for p in cynthia_bench)
    if total_counters == 0:
        state.emit_event("attack_no_damage", attacker="Cynthia's Spiritomb",
                         attack_name="Raging Curse")
        return
    _apply_damage(state, action, 10 * total_counters)

def register_all(registry) -> None:
    """Register all Pokémon attack handlers."""

    # Category 1: Multi-turn attack locks
    registry.register_attack("sv05-025", 0, _prism_edge)
    registry.register_attack("sv06-141", 0, _blood_moon)
    registry.register_attack("sv08-076", 0, _eon_blade)
    registry.register_attack("sv09-024", 0, _smolder_sault)
    registry.register_attack("me02.5-155", 1, _rampaging_thunder)

    # Category 2: Can't-retreat locks
    registry.register_attack("me01-088", 0, _clutch)
    registry.register_attack("sv06-064", 0, _sob)
    registry.register_attack("sv08.5-037", 0, _shadow_bind)

    # Category 3: Status conditions
    registry.register_attack("me02.5-047", 1, _absolute_snow)
    registry.register_attack("sv06-057", 0, _numbing_water)
    registry.register_attack("sv06-095", 0, _mind_bend)
    registry.register_attack("me02.5-099", 0, _mind_bend)     # Munkidori alt print
    registry.register_attack("sv06-118", 0, _poison_spray)
    registry.register_attack("svp-149", 0, _poison_chain)

    # Category 4: Draw and search effects
    registry.register_attack("me03-042", 0, _double_draw)
    registry.register_attack("sv06-039", 0, _allure)
    registry.register_attack("sv10-040", 0, _collect)
    registry.register_attack("me01-058", 0, _collect)         # Ralts — Collect (alt print)
    registry.register_attack("sv10-134", 0, _filch)
    registry.register_attack("sv06-106", 0, _shinobi_blade)
    registry.register_attack("me02-067", 0, _call_for_family)
    registry.register_attack("me01-059", 0, _call_sign)       # Kirlia — Call Sign
    registry.register_attack("sv08.5-035", 0, _come_and_get_you)

    # Category 5: Variable damage
    registry.register_attack("me01-056", 0, _powerful_hand)
    registry.register_attack("me01-086", 0, _terminal_period)
    registry.register_attack("me01-086", 1, _claw_of_darkness)
    registry.register_attack("me01-104", 0, _rapid_fire_combo)
    registry.register_attack("me02-014", 0, _fighting_wings)
    registry.register_attack("me02.5-008", 0, _growl)
    registry.register_attack("me02.5-047", 0, _resentful_refrain)
    registry.register_attack("me01-075", 0, _cosmic_beam)
    registry.register_attack("me02.5-155", 0, _shred)
    registry.register_attack("sv06-039", 1, _ground_melter)
    registry.register_attack("sv06-093", 1, _love_resonance)
    registry.register_attack("sv06-096", 0, _energy_feather)
    registry.register_attack("sv06-112", 0, _demolish)
    registry.register_attack("sv06-118", 1, _relentless_punches)
    registry.register_attack("sv06.5-039", 0, _irritated_outburst)
    registry.register_attack("sv08-111", 0, _coordinated_throwing)
    registry.register_attack("sv08.5-054", 0, _mad_bite)
    registry.register_attack("sv09-027", 0, _back_draft)
    registry.register_attack("sv09-056", 0, _full_moon_rondo)
    registry.register_attack("me02.5-076", 0, _full_moon_rondo)   # Lillie's Clefairy ex alt print
    registry.register_attack("sv09-116", 0, _powerful_rage)
    registry.register_attack("sv10-012", 0, _superb_scissors)
    registry.register_attack("sv10-020", 0, _rocket_rush)
    registry.register_attack("sv10-041", 1, _double_kick)
    registry.register_attack("sv10-051", 0, _dark_frost)
    registry.register_attack("sv05-024", 0, _rabsca_psychic)      # Rabsca — Psychic
    registry.register_attack("me02.5-142", 0, _cruel_arrow)       # Fezandipiti ex — Cruel Arrow
    registry.register_attack("me02.5-089", 0, _overflowing_wishes) # Mega Gardevoir ex — Overflowing Wishes
    registry.register_attack("me02.5-089", 1, _mega_symphonia)    # Mega Gardevoir ex — Mega Symphonia
    registry.register_attack("me03-031", 0, _shooting_moons)      # Mega Clefable ex — Shooting Moons

    # Category 6: Bench damage
    registry.register_attack("sv06-064", 1, _torrential_pump)
    registry.register_attack("sv06-106", 1, _mirage_barrage)
    registry.register_attack("sv06-130", 1, _phantom_dive)
    registry.register_attack("me02.5-160", 1, _phantom_dive)      # Dragapult ex alt print
    registry.register_attack("sv09-027", 1, _flamebody_cannon)
    registry.register_attack("sv10-023", 0, _oil_salvo)
    registry.register_attack("sv10-081", 0, _erasure_ball)
    registry.register_attack("sv10-128", 1, _strike_the_sleeper)
    registry.register_attack("sv10-136", 0, _shadow_bullet)
    registry.register_attack("sv06-025", 0, _myriad_leaf_shower)

    # Category 7: Self-manipulation
    registry.register_attack("me01-054", 0, _teleportation_attack)
    registry.register_attack("me01-009", 0, _push_down)
    registry.register_attack("me03-062", 0, _tuck_tail)
    registry.register_attack("sv05-123", 0, _burst_roar)
    registry.register_attack("sv05-123", 1, _bellowing_thunder)
    registry.register_attack("sv08-056", 0, _icicle_loop)
    registry.register_attack("sv09-120", 0, _trading_places)
    registry.register_attack("sv10-011", 0, _ascension)
    registry.register_attack("sv10-019", 0, _take_down)
    registry.register_attack("sv10-022", 0, _nutrients)
    registry.register_attack("sv10-023", 1, _aroma_shot)

    # Category 8b: Item-lock attacks
    registry.register_attack("me02.5-016", 0, _itchy_pollen)
    registry.register_attack("svp-149",    0, _poison_chain)
    registry.register_attack("sv05-023",   0, _slight_intrusion)  # Rellor — Slight Intrusion

    # Category 9: Copy-attack stubs
    registry.register_attack("sv09-098", 0, _night_joker)
    registry.register_attack("sv10-087", 0, _gemstone_mimicry)

    # ── Batch 1: me03 / me02.5 new handlers ─────────────────────────────────
    # Status conditions
    registry.register_attack("me03-001", 0, _gooey_thread)
    registry.register_attack("me03-002", 0, _poison_ring)
    registry.register_attack("me03-023", 0, _icy_wind)
    registry.register_attack("me03-029", 1, _thunder_shock_dedenne)
    registry.register_attack("me03-034", 0, _perplex)
    registry.register_attack("me03-051", 0, _poison_jab)
    registry.register_attack("me03-052", 1, _hazardous_tail)
    registry.register_attack("me02.5-002", 0, _ericas_gloom_poison_spray)
    registry.register_attack("me02.5-007", 0, _bind)
    registry.register_attack("me02.5-013", 0, _stun_spore)
    registry.register_attack("me02.5-030", 0, _super_singe)
    registry.register_attack("me03-063", 1, _collapse)
    registry.register_attack("me02.5-015", 0, _twilight_poison)
    registry.register_attack("me02.5-003", 0, _bloom_powder)
    registry.register_attack("me03-016", 1, _dire_nails)
    registry.register_attack("me03-017", 0, _heat_breath)

    # Multi-turn attack locks
    registry.register_attack("me02.5-005", 1, _leafy_cyclone)
    registry.register_attack("me03-058", 1, _metal_slash)
    registry.register_attack("me03-053", 1, _dark_strike)
    registry.register_attack("me03-024", 0, _freezing_chill)

    # Heals
    registry.register_attack("me03-033", 0, _nap)
    registry.register_attack("me03-035", 0, _sweet_scent)
    registry.register_attack("me03-036", 0, _draining_kiss)
    registry.register_attack("me02.5-026", 0, _shining_feathers)

    # Variable damage
    registry.register_attack("me03-006", 0, _regal_command)
    registry.register_attack("me03-006", 1, _solar_coiling)
    registry.register_attack("me03-022", 0, _hydro_turn)
    registry.register_attack("me03-028", 0, _incessant_onslaught)
    registry.register_attack("me03-028", 1, _strong_volt)
    registry.register_attack("me03-032", 0, _double_eater)
    registry.register_attack("me03-034", 1, _meowstic_psychic)
    registry.register_attack("me03-044", 0, _get_angry)
    registry.register_attack("me03-046", 0, _vengeful_kick)
    registry.register_attack("me03-050", 0, _mind_jack)
    registry.register_attack("me03-061", 1, _retaliatory_incisors)
    registry.register_attack("me02.5-006", 0, _flower_garden_rondo)
    registry.register_attack("me02.5-013", 1, _energy_straw)
    registry.register_attack("me02.5-025", 0, _flare_fall)
    registry.register_attack("me02.5-010", 0, _giant_bouquet)
    registry.register_attack("me02.5-028", 0, _roasting_burn)
    registry.register_attack("me02.5-031", 0, _crimson_blast)

    # Coin flips
    registry.register_attack("me03-025", 1, _powerful_steam)
    registry.register_attack("me03-026", 0, _double_scratch)
    registry.register_attack("me03-045", 0, _wreak_havoc)
    registry.register_attack("me03-048", 0, _surprise_attack)

    # Search/draw
    registry.register_attack("me03-003", 0, _send_flowers)
    registry.register_attack("me03-010", 0, _find_a_friend)
    registry.register_attack("me03-011", 1, _feather_shot)
    registry.register_attack("me03-029", 0, _tail_generator)
    registry.register_attack("me03-066", 0, _chirp)
    registry.register_attack("me03-067", 0, _hand_trim)
    registry.register_attack("me03-063", 0, _gormandizer)
    registry.register_attack("me02.5-022", 0, _explosion_y)
    registry.register_attack("me02.5-024", 0, _lava_burst)
    registry.register_attack("me02.5-028", 1, _power_stomp)
    registry.register_attack("me03-016", 0, _nasty_plot)

    # Bench damage
    registry.register_attack("me03-021", 0, _jetting_blow)
    registry.register_attack("me03-021", 1, _nebula_beam)
    registry.register_attack("me03-065", 0, _earthquake)

    # Energy manipulation
    registry.register_attack("me03-038", 1, _obliterating_nose)
    registry.register_attack("me03-055", 0, _sonic_ripper)
    registry.register_attack("me03-041", 0, _rock_tumble)
    registry.register_attack("me03-041", 1, _screw_knuckle)

    # Complex
    registry.register_attack("me03-009", 0, _blow_through)
    registry.register_attack("me03-012", 0, _crushing_arrow)
    registry.register_attack("me03-030", 0, _follow_me)
    registry.register_attack("me03-047", 0, _gaia_wave)
    registry.register_attack("me03-047", 1, _nullifying_zero)
    registry.register_attack("me03-053", 0, _soul_destroyer)
    registry.register_attack("me03-054", 0, _strafe)
    registry.register_attack("me03-054", 1, _rising_blade)
    registry.register_attack("me03-057", 0, _weaponized_swords)
    registry.register_attack("me03-061", 0, _scrape_off)
    registry.register_attack("me03-049", 0, _haunt)
    registry.register_attack("me03-070", 0, _geobuster)

    # Reuse existing handlers for new card IDs
    registry.register_attack("me02.5-019", 0, _rocket_rush)
    registry.register_attack("me02.5-033", 0, _back_draft)
    registry.register_attack("me02.5-033", 1, _flamebody_cannon)
    registry.register_attack("me03-004", 0, _slight_intrusion)
    registry.register_attack("me02.5-001", 0, _slight_intrusion)
    registry.register_attack("me02.5-018", 0, _take_down)
    registry.register_attack("me03-060", 0, _take_down)
    registry.register_attack("me02.5-014", 0, _trading_places)

    # ── Alternate-print registrations (same handler, different TCGDex IDs) ────
    registry.register_attack("sv08.5-004", 0, _itchy_pollen)        # Budew (PE alt)
    registry.register_attack("sv06.5-038", 0, _cruel_arrow)         # Fezandipiti ex (alt)
    registry.register_attack("svp-166",    0, _myriad_leaf_shower)  # Teal Mask Ogerpon ex (promo)
    registry.register_attack("sv10-024",   0, _collect)             # Rellor (SV7)
    registry.register_attack("me02.5-017", 0, _ambush)              # Grubbin

    # ── Batch 2: ASC (Ascended Heroes) me02.5-034 through me02.5-133 ────────

    # me02.5-034 Salandit
    registry.register_attack("me02.5-034", 0, _ember)

    # me02.5-035 Salazzle
    registry.register_attack("me02.5-035", 0, _sudden_scorching)
    registry.register_attack("me02.5-035", 1, _flamethrower)

    # me02.5-036 Pachirisu — Quick Attack: 10 + flip for +10 (reuse _ambush logic)
    registry.register_attack("me02.5-036", 0, _ambush)

    # me02.5-037 Litleo — default damage only (no handler needed)

    # me02.5-038 Cinderace ex
    registry.register_attack("me02.5-038", 0, _flare_strike_asc)
    registry.register_attack("me02.5-038", 1, _garnet_volley)

    # me02.5-039 Psyduck — handled by ability; no attack handler override
    # me02.5-039 atk0: default

    # me02.5-040 Golduck
    registry.register_attack("me02.5-040", 0, _hydro_pump_asc)

    # me02.5-041 Seel — Slight Intrusion
    registry.register_attack("me02.5-041", 0, _slight_intrusion)

    # me02.5-042 Croconaw
    registry.register_attack("me02.5-042", 0, _crunch)

    # me02.5-043 Mega Feraligatr ex
    registry.register_attack("me02.5-043", 0, _mortal_crunch)
    # atk1 is default damage

    # me02.5-044 Swinub — Beset = _clutch (cant retreat + damage)
    registry.register_attack("me02.5-044", 1, _clutch)

    # me02.5-045 Weavile
    registry.register_attack("me02.5-045", 1, _hail_claw)

    # me02.5-046 Crabominable — default damage only

    # me02.5-047 N's Vanillish — handled in Batch 1 (absolute_snow / resentful_refrain)

    # me02.5-048 Regice ex
    registry.register_attack("me02.5-048", 0, _regi_charge_w)
    registry.register_attack("me02.5-048", 1, _ice_prison)

    # me02.5-049 Spheal — Call for Family
    registry.register_attack("me02.5-049", 0, _call_for_family)

    # me02.5-050 N's Vanillish
    registry.register_attack("me02.5-050", 1, _sheer_cold)

    # me02.5-051 N's Vanilluxe
    registry.register_attack("me02.5-051", 0, _snow_coating)
    registry.register_attack("me02.5-051", 1, _blizzard)

    # me02.5-052 Snom — default damage only

    # me02.5-053 Frosmoth (ability: Alluring Wings; atk: Cold Cyclone)
    registry.register_attack("me02.5-053", 0, _cold_cyclone)

    # me02.5-054 Glastrier
    registry.register_attack("me02.5-054", 0, _ice_shot)
    registry.register_attack("me02.5-054", 1, _frosty_typhoon)

    # me02.5-055 Joltik — default damage only

    # me02.5-056 Raichu
    registry.register_attack("me02.5-056", 0, _quick_blow)
    registry.register_attack("me02.5-056", 1, _discard_one_l_energy)

    # me02.5-057 Pikachu ex (ability: Resolute Heart; atk: Topaz Bolt)
    registry.register_attack("me02.5-057", 0, _topaz_bolt)

    # me02.5-058 Voltorb ex
    registry.register_attack("me02.5-058", 0, _hundred_hitting_ball)

    # me02.5-059 Tynamo
    registry.register_attack("me02.5-059", 0, _hold_still)

    # me02.5-060 Eelektrik — handled by ability (Dynamotor); no atk override

    # me02.5-061 Mega Eelektross ex
    registry.register_attack("me02.5-061", 0, _split_bomb)
    registry.register_attack("me02.5-061", 1, _disaster_shock)

    # me02.5-062 Stunfisk
    registry.register_attack("me02.5-062", 0, _pouncing_trap)

    # me02.5-063 Helioptile — default damage only

    # me02.5-064 Heliolisk
    registry.register_attack("me02.5-064", 0, _powerful_bolt)

    # me02.5-065 Charjabug — default damage only

    # me02.5-066 Vikavolt
    registry.register_attack("me02.5-066", 0, _volt_switch_l)

    # me02.5-067 Tapu Koko
    registry.register_attack("me02.5-067", 0, _fast_flight)
    registry.register_attack("me02.5-067", 1, _thunder_blast)

    # me02.5-068 Hop's Pincurchin ex (ability: Counterattack Quills; atk: Spiky Thunder)
    registry.register_attack("me02.5-068", 0, _spiky_thunder)

    # me02.5-069 Clefairy — default damage only

    # me02.5-070 Iono's Bellibolt ex (ability: Electric Streamer; atk: Thunderous Bolt)
    registry.register_attack("me02.5-070", 0, _thunderous_bolt)

    # me02.5-071 Iono's Wattrel
    registry.register_attack("me02.5-071", 0, _quick_attack_asc)

    # me02.5-072 Iono's Kilowattrel — ability: Flashing Draw; no atk override

    # me02.5-073 Miraidon ex
    registry.register_attack("me02.5-073", 1, _hadron_spark)

    # me02.5-074 Mime Jr. — default damage only

    # me02.5-075 Clefable
    registry.register_attack("me02.5-075", 0, _metronome)

    # me02.5-076 Lillie's Clefairy ex — Full Moon Rondo (registered above)

    # me02.5-077 TR Exeggcute
    registry.register_attack("me02.5-077", 0, _focused_wish)

    # me02.5-078 TR Exeggutor
    registry.register_attack("me02.5-078", 0, _tri_kinesis)
    registry.register_attack("me02.5-078", 1, _double_edge)

    # me02.5-079 TR Mewtwo ex (ability: Power Saver; atk: Erasure Ball)
    registry.register_attack("me02.5-079", 0, _erasure_ball_asc)

    # me02.5-080 Meditite — default damage only

    # me02.5-081 Medicham — Draining Kiss (atk0)
    registry.register_attack("me02.5-081", 0, _draining_kiss)

    # me02.5-082 Togekiss — Wonder Kiss (ability; passive); no atk override

    # me02.5-083 Marill
    registry.register_attack("me02.5-083", 0, _hide)

    # me02.5-084 Azumarill ex (ability: Bubble Gathering; atk: Energized Balloon)
    registry.register_attack("me02.5-084", 0, _energized_balloon)

    # me02.5-085 Misdreavus
    registry.register_attack("me02.5-085", 0, _ascension_misdreavus)

    # me02.5-086 Mismagius
    registry.register_attack("me02.5-086", 0, _assassins_magic)

    # me02.5-087 Shuppet — Collect
    registry.register_attack("me02.5-087", 0, _collect)

    # me02.5-088 Banette — Call Sign
    registry.register_attack("me02.5-088", 0, _call_sign)

    # me02.5-089 Mega Gardevoir ex — registered in Batch 1

    # me02.5-090 Gastly — default damage only

    # me02.5-091 Banette (Cursed Words)
    registry.register_attack("me02.5-091", 0, _cursed_words)

    # me02.5-092 Rotom
    registry.register_attack("me02.5-092", 0, _roto_call)
    registry.register_attack("me02.5-092", 1, _gadget_show)

    # me02.5-093 Mime Jr. (alt) — default damage only

    # me02.5-094 Misdreavus (alt) — default damage only

    # me02.5-095 Hop's Phantump
    registry.register_attack("me02.5-095", 0, _splashing_dodge)

    # me02.5-096 Hop's Trevenant
    registry.register_attack("me02.5-096", 0, _horrifying_revenge)
    registry.register_attack("me02.5-096", 1, _clutch)

    # me02.5-097 Diancie — Gemstone Mimicry
    registry.register_attack("me02.5-097", 0, _gemstone_mimicry)

    # me02.5-098 Spectrier
    registry.register_attack("me02.5-098", 1, _phantasmal_barrage)

    # me02.5-099 Munkidori — Mind Bend (registered in Batch 1)

    # me02.5-100 TR Diglett
    registry.register_attack("me02.5-100", 0, _relentless_burrowing)

    # me02.5-101 TR Dugtrio — Holes (passive); no atk override

    # me02.5-102 Hitmontop
    registry.register_attack("me02.5-102", 0, _spin_and_draw)

    # me02.5-103 Hitmonlee — Collect
    registry.register_attack("me02.5-103", 0, _collect)

    # me02.5-104 Medicham
    registry.register_attack("me02.5-104", 0, _seventh_kick)

    # me02.5-105 Lunatone — ability: Lunar Cycle; no special atk

    # me02.5-106 Solrock
    registry.register_attack("me02.5-106", 0, _cosmic_beam_asc)

    # me02.5-107 Regirock ex
    registry.register_attack("me02.5-107", 0, _regi_charge_f)
    registry.register_attack("me02.5-107", 1, _giant_rock)

    # me02.5-108 Groudon
    registry.register_attack("me02.5-108", 1, _megaton_fall)

    # me02.5-109 Cynthia's Gible
    registry.register_attack("me02.5-109", 0, _rock_hurl)

    # me02.5-110 Cynthia's Gabite — ability: Champion's Call; no atk override

    # me02.5-111 Cynthia's Garchomp ex
    registry.register_attack("me02.5-111", 0, _corkscrew_dive)
    registry.register_attack("me02.5-111", 1, _draconic_buster)

    # me02.5-112 Riolu
    registry.register_attack("me02.5-112", 0, _accelerating_stab)

    # me02.5-113 Mega Lucario ex
    registry.register_attack("me02.5-113", 0, _aura_jab)
    registry.register_attack("me02.5-113", 1, _mega_brave)

    # me02.5-114 Stunfisk ex
    registry.register_attack("me02.5-114", 1, _flopping_trap)

    # me02.5-115 Geodude — Slight Intrusion (Reckless Charge)
    registry.register_attack("me02.5-115", 0, _slight_intrusion)

    # me02.5-116 Mega Hawlucha ex (ability: Tenacious Body; atk: Somersault Dive)
    registry.register_attack("me02.5-116", 0, _somersault_dive)

    # me02.5-117 Carbink (ability: Double Type; atk: Counter Jewel)
    registry.register_attack("me02.5-117", 0, _counter_jewel)

    # me02.5-118 Rolycoly — default damage only

    # me02.5-119 Carkol
    registry.register_attack("me02.5-119", 0, _guard_press)

    # me02.5-120 Coalossal
    registry.register_attack("me02.5-120", 0, _tar_cannon)
    registry.register_attack("me02.5-120", 1, _bulky_bump)

    # me02.5-121 Koraidon ex
    registry.register_attack("me02.5-121", 0, _orichalcum_fang)
    registry.register_attack("me02.5-121", 1, _impact_blow)

    # me02.5-122 Okidogi (Settle the Score)
    registry.register_attack("me02.5-122", 1, _settle_the_score)

    # me02.5-123 Morpeko — default damage only

    # me02.5-124 Munchlax — default damage only

    # me02.5-125 Mega Gengar ex (ability: Shadowy Concealment; atk: Void Gale)
    registry.register_attack("me02.5-125", 0, _void_gale)

    # me02.5-126 TR Murkrow
    registry.register_attack("me02.5-126", 0, _deceit)
    registry.register_attack("me02.5-126", 1, _torment)

    # me02.5-127 TR Honchkrow
    registry.register_attack("me02.5-127", 0, _rocket_feathers)

    # me02.5-128 Poochyena
    registry.register_attack("me02.5-128", 0, _gnaw_off)

    # me02.5-129 Mightyena — Kick Away = Push Down
    registry.register_attack("me02.5-129", 0, _push_down)

    # me02.5-130 Nuzleaf — default damage only

    # me02.5-131 Galarian Zigzagoon — default damage only

    # me02.5-132 Galarian Obstagoon
    registry.register_attack("me02.5-132", 0, _scarring_shout)
    registry.register_attack("me02.5-132", 1, _punk_smash)

    # me02.5-133 Cynthia's Spiritomb
    registry.register_attack("me02.5-133", 0, _raging_curse)
