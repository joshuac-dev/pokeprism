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
    bypass_resistance_only: bool = False,
) -> int:
    """Apply base_damage through the standard pipeline and return final_damage.

    Args:
        bypass_wr: Skip weakness/resistance (for Demolish).
        bypass_defender_effects: Skip ability blocks and Payapa Berry
            (for Shred, Superb Scissors, Demolish).
        bypass_resistance_only: Skip only resistance, not weakness (for Rock Tumble etc.).
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
    # Sturdy (sv10.5b-052 Crustle): same Resolute Heart mechanic
    if defender.card_def_id == "sv10.5b-052":
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
        total = apply_weakness_resistance(total, attacker, defender, state, opp_id,
                                          skip_resistance=bypass_resistance_only)

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

    if not bypass_defender_effects:
        # Thick Fat (me02-022 Dewgong): reduce damage by 30 from Fire/Water attackers
        if defender.card_def_id == "me02-022":
            attacker_def = card_registry.get(attacker.card_def_id)
            if attacker_def and any(t in (attacker_def.types or []) for t in ("Fire", "Water")):
                total = max(0, total - 30)

        # Diamond Coat (me02-041 Mega Diancie ex): reduce damage by 30
        if defender.card_def_id == "me02-041":
            total = max(0, total - 30)

        # Crown Opal: prevent all damage from Basic non-Colorless attackers
        if defender.prevent_damage_from_basic_noncolorless:
            attacker_def = card_registry.get(attacker.card_def_id)
            if attacker_def:
                is_basic = attacker_def.stage.lower() == "basic"
                is_only_colorless = (attacker_def.types or []) == ["Colorless"]
                if is_basic and not is_only_colorless:
                    state.emit_event("damage_prevented", card=defender.card_name,
                                     reason="crown_opal")
                    return 0

        # prevent_damage_from_basic (Archaludon Coated Attack, Mega Manectric ex Flash Ray)
        if defender.prevent_damage_from_basic:
            attacker_def = card_registry.get(attacker.card_def_id)
            if attacker_def and (attacker_def.stage or "").lower() == "basic":
                state.emit_event("damage_prevented", card=defender.card_name,
                                 reason="prevent_damage_from_basic")
                return 0

        # Intimidating Fang (me01-024 Pyroar): opp attacks do 30 less
        if defender.card_def_id == "me01-024":
            total = max(0, total - 30)

        # Gear Coating (sv10.5b-063 Klinklang): Metal Pokémon with Metal energy take 20 less damage
        _opp_in_play_gc = ([opp.active] if opp.active else []) + list(opp.bench)
        if any(p.card_def_id == "sv10.5b-063" for p in _opp_in_play_gc):
            _def_cdef_gc = card_registry.get(defender.card_def_id)
            if (_def_cdef_gc and "Metal" in (_def_cdef_gc.types or [])
                    and any(att.energy_type == EnergyType.METAL
                            for att in defender.energy_attached)):
                total = max(0, total - 20)

        # Bouffer (sv10.5w-077 Bouffalant ex): takes 30 less damage from attacks
        if defender.card_def_id == "sv10.5w-077":
            total = max(0, total - 30)

    # Supreme Overlord (me02.5-148 Kingambit): +30 per prize opponent has taken
    if attacker.card_def_id == "me02.5-148":
        prizes_taken = 6 - state.get_player(action.player_id).prizes_remaining
        total += prizes_taken * 30

    # Excited Power (me02-062 Seviper): +120 for Darkness Pokémon if Seviper in play
    _attacker_cdef2 = card_registry.get(attacker.card_def_id)
    if _attacker_cdef2 and "Darkness" in (_attacker_cdef2.types or []):
        _atk_player = state.get_player(action.player_id)
        _sev_in_play = ([_atk_player.active] if _atk_player.active else []) + list(_atk_player.bench)
        if any(p.card_def_id == "me02-062" for p in _sev_in_play):
            total += 120
            state.emit_event("excited_power_bonus", player=action.player_id,
                             attacker=attacker.card_name)

    # Powerful a-Salt (me01-084 Garganacl): +30 for all Fighting attackers on attacker's side
    _atk_player2 = state.get_player(action.player_id)
    _atk_in_play2 = ([_atk_player2.active] if _atk_player2.active else []) + list(_atk_player2.bench)
    if any(p.card_def_id == "me01-084" for p in _atk_in_play2):
        _atk_cdef3 = card_registry.get(attacker.card_def_id)
        if _atk_cdef3 and "Fighting" in (_atk_cdef3.types or []):
            total += 30
            state.emit_event("powerful_a_salt_bonus", player=action.player_id,
                             attacker=attacker.card_name)

    # Regal Cheer (sv10.5b-003 Serperior ex): +20 for all attackers on attacker's side
    _atk_player3 = state.get_player(action.player_id)
    _atk_in_play3 = ([_atk_player3.active] if _atk_player3.active else []) + list(_atk_player3.bench)
    if any(p.card_def_id == "sv10.5b-003" for p in _atk_in_play3):
        total += 20
        state.emit_event("regal_cheer_bonus", player=action.player_id,
                         attacker=attacker.card_name)

    # Mighty Shell (sv10.5b-023 Carracosta): if defender is Carracosta AND attacker has Special Energy → 0 damage
    _SPECIAL_ENERGY_IDS = {"me02.5-216", "me03-086", "me03-088", "sv05-161",
                            "sv06-167", "sv08-191", "sv10-182", "sv10.5w-086"}
    if defender.card_def_id == "sv10.5b-023":
        if any(ea.card_def_id in _SPECIAL_ENERGY_IDS for ea in attacker.energy_attached):
            state.emit_event("mighty_shell_blocked", defender=defender.card_name,
                             attacker=attacker.card_name)
            return 0

    total = max(0, total)
    if not bypass_defender_effects and has_tundra_wall(state, opp_id):
        if any(att.energy_type == EnergyType.WATER for att in defender.energy_attached):
            total = max(0, total - 50)
    if not bypass_defender_effects and defender.incoming_damage_reduction > 0:
        total = max(0, total - defender.incoming_damage_reduction)
    if attacker.attack_damage_reduction > 0:
        total = max(0, total - attacker.attack_damage_reduction)
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

    # Spiteful Swirl (me01-087 Spiritomb): when Spiritomb on defender's side AND defender is Dark type, place 10 HP on attacker
    if total > 0 and attacker.current_hp > 0:
        _def_player = state.get_player(opp_id)
        _def_in_play = ([_def_player.active] if _def_player.active else []) + list(_def_player.bench)
        if any(p.card_def_id == "me01-087" for p in _def_in_play):
            _def_cdef = card_registry.get(defender.card_def_id)
            if _def_cdef and "Darkness" in (_def_cdef.types or []):
                attacker.current_hp -= 10
                attacker.damage_counters += 1
                state.emit_event("spiteful_swirl_triggered", player=opp_id,
                                 attacker=attacker.card_name)
                check_ko(state, attacker, action.player_id)
                if state.phase == Phase.GAME_OVER:
                    return total

    # Poison Point (sv10.5b-056 Scolipede): when Scolipede takes damage, poison the attacker
    if total > 0 and defender.card_def_id == "sv10.5b-056" and attacker.current_hp > 0:
        attacker.status_conditions.add(StatusCondition.POISONED)
        state.emit_event("poison_point_triggered", player=opp_id,
                         attacker=attacker.card_name)

    # Counterattacking Crest (me02.5-135 Mega Scrafty ex): place 5 counters on attacker
    if (defender.card_def_id == "me02.5-135"
            and total > 0
            and attacker.current_hp > 0):
        attacker.current_hp -= 50
        attacker.damage_counters += 5
        state.emit_event("counterattacking_crest_triggered",
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
_COPY_ATTACK_KEYS = {"sv09-098:0", "sv10-087:0", "sv10.5w-062:1"}


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


def _big_bite(state, action):
    """me02.5-114 Stunfisk ex atk0 — Big Bite: 30 + defending Pokémon can't retreat next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.cant_retreat_next_turn = True


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


# ── Batch 3 attack handlers ──────────────────────────────────────────────────

def _knock_off(state, action):
    """me02.5-134 Scraggy atk0 — Knock Off: 20 + discard random card from opp hand."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.hand:
        discarded = _random.choice(opp.hand)
        opp.hand.remove(discarded)
        discarded.zone = Zone.DISCARD
        opp.discard.append(discarded)
        state.emit_event("knock_off", player=action.player_id, discarded=discarded.card_name)


def _outlaw_leg(state, action):
    """me02.5-135 Mega Scrafty ex atk0 — Outlaw Leg: 160 + discard hand + top deck from opp."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.hand:
        discarded = _random.choice(opp.hand)
        opp.hand.remove(discarded)
        discarded.zone = Zone.DISCARD
        opp.discard.append(discarded)
        state.emit_event("knock_off", player=action.player_id, discarded=discarded.card_name)
    if opp.deck:
        top = opp.deck.pop()
        top.zone = Zone.DISCARD
        opp.discard.append(top)
        state.emit_event("deck_discard", player=action.player_id, card=top.card_name)


def _thunderbolt_rotom(state, action):
    """me02-029 Rotom ex atk0 — Thunderbolt: 130 + discard all energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.energy_attached.clear()
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="thunderbolt_rotom", count="all")


# me02.5-137 N's Zoroark ex atk0 uses the existing async _night_joker (defined earlier)


def _bone_shot(state, action):
    """me02.5-139 Mandibuzz ex atk0 — Bone Shot: 50 to 1 of opp's Pokémon (no W/R)."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    all_opp = ([opp.active] if opp.active else []) + opp.bench
    if not all_opp:
        return
    target = min(all_opp, key=lambda p: p.current_hp)
    if target is opp.active:
        _apply_damage(state, action, 50)
    else:
        _apply_bench_damage(state, opp_id, target, 50)
    state.emit_event("bone_shot", player=action.player_id, target=target.card_name)


def _vulture_claw(state, action):
    """me02.5-139 Mandibuzz ex atk1 — Vulture Claw: 160 + discard random card from opp hand."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.hand:
        c = _random.choice(opp.hand)
        opp.hand.remove(c)
        c.zone = Zone.DISCARD
        opp.discard.append(c)
        state.emit_event("knock_off", player=action.player_id, discarded=c.card_name)


def _masters_punch(state, action):
    """me02.5-140 Pangoro atk1 — Master's Punch: 80 + 120 if Benched Pancham has damage."""
    player = state.get_player(action.player_id)
    bonus = 120 if any(
        "Pancham" in p.card_name and p.damage_counters > 0
        for p in player.bench
    ) else 0
    _apply_damage(state, action, 80 + bonus)


def _filch(state, action):
    """me02.5-141 Hoopa atk0 — Filch: Draw 2 cards."""
    from app.engine.effects.abilities import draw_cards as _draw_cards
    _draw_cards(state, action.player_id, 2)
    state.emit_event("filch", player=action.player_id)


def _knuckle_impact(state, action):
    """me02.5-141 Hoopa atk1 — Knuckle Impact: 130 + can't attack next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("cant_attack_next_turn", card=player.active.card_name)


def _mochi_rush(state, action):
    """me02.5-143 Pecharunt atk0 — Mochi Rush: 20 + 50 if used last turn."""
    player = state.get_player(action.player_id)
    bonus = 50 if (player.active and player.active.last_attack_name == "Mochi Rush") else 0
    _apply_damage(state, action, 20 + bonus)


def _regi_charge_m(state, action):
    """me02.5-145 Registeel ex atk0 — Regi Charge: attach up to 2 Basic Metal Energy from discard."""
    from app.engine.state import EnergyAttachment, EnergyType as _ET
    player = state.get_player(action.player_id)
    metal_energy = [c for c in player.discard
                    if c.card_type.lower() == "energy"
                    and any(t in (c.energy_provides or []) for t in ["Metal", "M"])]
    if not metal_energy or not player.active:
        state.emit_event("attack_no_damage", attacker="Registeel ex", attack_name="Regi Charge")
        return
    count = min(2, len(metal_energy))
    for i in range(count):
        e = metal_energy[i]
        player.discard.remove(e)
        e.zone = player.active.zone
        player.active.energy_attached.append(EnergyAttachment(
            energy_type=_ET.METAL,
            source_card_id=e.instance_id,
            card_def_id=e.card_def_id,
        ))
    state.emit_event("regi_charge", player=action.player_id, count=count)


def _protecting_steel(state, action):
    """me02.5-145 Registeel ex atk1 — Protecting Steel: 140 + take 50 less damage next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.incoming_damage_reduction += 50


def _rapid_draw(state, action):
    """me02.5-147 Bisharp atk0 — Rapid Draw: 50 + draw 2 cards."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    from app.engine.effects.abilities import draw_cards as _draw_cards
    _draw_cards(state, action.player_id, 2)
    state.emit_event("rapid_draw", player=action.player_id)


def _double_edged_slash(state, action):
    """me02.5-148 Kingambit atk0 — Double-Edged Slash: 180 + 50 to self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.damage_counters += 5
        player.active.current_hp -= 50
        state.emit_event("self_damage", player=action.player_id,
                         card=player.active.card_name, amount=50)
        check_ko(state, player.active, action.player_id)


def _stun_needle(state, action):
    """me02.5-149 Togedemaru ex atk0 — Stun Needle: 20 + flip coin, heads = Paralyzed."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):
        opp = state.get_opponent(action.player_id)
        if opp.active:
            opp.active.status_conditions.add(StatusCondition.PARALYZED)
            state.emit_event("status_applied", card=opp.active.card_name, status="paralyzed")


def _spiky_rolling(state, action):
    """me02.5-149 Togedemaru ex atk1 — Spiky Rolling: 80 + 80 if Spiky Rolling used last turn."""
    player = state.get_player(action.player_id)
    bonus = 80 if (player.active and player.active.last_attack_name == "Spiky Rolling") else 0
    _apply_damage(state, action, 80 + bonus)


def _powerful_rage_reshiram(state, action):
    """me02.5-154 N's Reshiram atk0 — Powerful Rage: 20× damage counters on self."""
    player = state.get_player(action.player_id)
    counters = player.active.damage_counters if player.active else 0
    _apply_damage(state, action, 20 * counters)


def _knickknack_carrying(state, action):
    """me02.5-156 Noibat atk0 — Knickknack Carrying: search deck for a Pokémon Tool."""
    player = state.get_player(action.player_id)
    tools = [c for c in player.deck if c.card_subtype.lower() == "tool"]
    if not tools:
        state.emit_event("knickknack_carrying", player=action.player_id, found=0)
        return
    req = ChoiceRequest("choose_cards", action.player_id,
                        "Knickknack Carrying: search for a Pokémon Tool.",
                        cards=tools, min_count=0, max_count=1)
    resp = yield req
    chosen = (resp.selected_cards if resp else []) or [tools[0].instance_id]
    for iid in chosen[:1]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    state.emit_event("knickknack_carrying", player=action.player_id)


def _agility_noivern(state, action):
    """me02.5-157 Noivern atk0 — Agility: 40 + heads = prevent damage next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):
        player = state.get_player(action.player_id)
        if player.active:
            player.active.prevent_damage_one_turn = True
            state.emit_event("agility_heads", card=player.active.card_name)


def _enhanced_blade(state, action):
    """me02.5-157 Noivern atk1 — Enhanced Blade: 70 + 70 if Tool attached."""
    player = state.get_player(action.player_id)
    bonus = 70 if (player.active and player.active.tools_attached) else 0
    _apply_damage(state, action, 70 + bonus)


def _pawcket_pilfer(state, action):
    """me02.5-161 Team Rocket's Meowth atk0 — Paw-cket Pilfer: reveal random opp hand card."""
    opp = state.get_opponent(action.player_id)
    if opp.hand:
        card = _random.choice(opp.hand)
        state.emit_event("pawcket_pilfer", player=action.player_id, revealed=card.card_name)


def _fury_swipes(state, action):
    """me02.5-161 Team Rocket's Meowth atk1 — Fury Swipes: flip 3 coins, 20 per heads."""
    heads = sum(1 for _ in range(3) if _random.choice([True, False]))
    _apply_damage(state, action, 20 * heads)


def _comet_punch(state, action):
    """me02.5-162 Team Rocket's Kangaskhan ex atk0 — Comet Punch: flip 4 coins, 30 per heads."""
    heads = sum(1 for _ in range(4) if _random.choice([True, False]))
    _apply_damage(state, action, 30 * heads)


def _wicked_impact(state, action):
    """me02.5-162 TR Kangaskhan ex atk1 — Wicked Impact: 120 + 100 if TR supporter played."""
    player = state.get_player(action.player_id)
    bonus = 100 if player.tr_supporter_played_this_turn else 0
    _apply_damage(state, action, 120 + bonus)


def _rising_lunge(state, action):
    """me02.5-163 Larry's Dunsparce atk0 — Rising Lunge: 10 + 20 on heads."""
    bonus = 20 if _random.choice([True, False]) else 0
    _apply_damage(state, action, 10 + bonus)


def _work_rush(state, action):
    """me02.5-164 Larry's Dudunsparce ex atk0 — Work Rush: 80 per heads, 1 flip per Energy."""
    player = state.get_player(action.player_id)
    energy_count = len(player.active.energy_attached) if player.active else 0
    heads = sum(1 for _ in range(energy_count) if _random.choice([True, False]))
    _apply_damage(state, action, 80 * heads)


def _energy_crush(state, action):
    """me02.5-166 Delcatty atk1 — Energy Crush: 40× per Energy on all opp Pokémon."""
    opp = state.get_opponent(action.player_id)
    total_energy = sum(
        len(p.energy_attached)
        for p in ([opp.active] if opp.active else []) + opp.bench
    )
    _apply_damage(state, action, 40 * total_energy)


def _spike_draw(state, action):
    """me02.5-167 Zangoose ex atk0 — Spike Draw: 20 + draw 2 cards."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    from app.engine.effects.abilities import draw_cards as _draw_cards
    _draw_cards(state, action.player_id, 2)


def _wild_scissors(state, action):
    """me02.5-167 Zangoose ex atk1 — Wild Scissors: 180 + 30 to self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.damage_counters += 3
        player.active.current_hp -= 30
        check_ko(state, player.active, action.player_id)


def _minor_errand_running(state, action):
    """me02.5-168 Larry's Starly atk0 — Minor Errand-Running: search for up to 2 Basic Energy."""
    player = state.get_player(action.player_id)
    energies = [c for c in player.deck if c.card_type.lower() == "energy"]
    if not energies:
        state.emit_event("minor_errand_running", player=action.player_id, count=0)
        return
    req = ChoiceRequest("choose_cards", action.player_id,
                        "Minor Errand-Running: search for up to 2 Basic Energy.",
                        cards=energies, min_count=0, max_count=2)
    resp = yield req
    chosen = (resp.selected_cards if resp else []) or [e.instance_id for e in energies[:2]]
    for iid in chosen[:2]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    state.emit_event("minor_errand_running", player=action.player_id)


def _facade(state, action):
    """me02.5-170 Larry's Staraptor atk0 — Facade: 60 + 100 if Burned or Poisoned."""
    player = state.get_player(action.player_id)
    bonus = 100 if (player.active and (
        StatusCondition.BURNED in player.active.status_conditions or
        StatusCondition.POISONED in player.active.status_conditions
    )) else 0
    _apply_damage(state, action, 60 + bonus)


def _feathery_strike(state, action):
    """me02.5-170 Larry's Staraptor atk1 — Feathery Strike: 150 + discard 2 Energy + 50 to bench."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        for _ in range(2):
            if player.active.energy_attached:
                player.active.energy_attached.pop(0)
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if opp.bench:
        target = _random.choice(opp.bench)
        _apply_bench_damage(state, opp_id, target, 50)


def _assault_landing(state, action):
    """me02.5-171 Fan Rotom atk0 — Assault Landing: 70, but nothing if no Stadium in play."""
    if state.active_stadium:
        _do_default_damage(state, action)
    else:
        state.emit_event("attack_no_damage", attacker="Fan Rotom",
                         attack_name="Assault Landing", reason="no_stadium")


def _kaleidowaltz(state, action):
    """me02.5-172 Mega Audino ex atk0 — Kaleidowaltz: flip 3 coins, attach 2 Energy per heads."""
    from app.engine.state import EnergyAttachment, EnergyType as _ET
    heads = sum(1 for _ in range(3) if _random.choice([True, False]))
    if heads == 0:
        state.emit_event("kaleidowaltz", player=action.player_id, heads=0)
        return
    player = state.get_player(action.player_id)
    energies = [c for c in player.deck if c.card_type.lower() == "energy"]
    if not energies:
        state.emit_event("kaleidowaltz", player=action.player_id, heads=heads)
        return
    max_count = min(heads * 2, len(energies))
    req = ChoiceRequest("choose_cards", action.player_id,
                        f"Kaleidowaltz: search for up to {max_count} Basic Energy to attach.",
                        cards=energies, min_count=0, max_count=max_count)
    resp = yield req
    chosen_ids = (resp.selected_cards if resp else []) or [e.instance_id for e in energies[:max_count]]
    all_poke = ([player.active] if player.active else []) + player.bench
    for iid in chosen_ids[:max_count]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card and all_poke:
            player.deck.remove(card)
            target = all_poke[0]
            card.zone = target.zone
            target.energy_attached.append(EnergyAttachment(
                energy_type=_ET.COLORLESS,
                source_card_id=card.instance_id,
                card_def_id=card.card_def_id,
            ))
    state.emit_event("kaleidowaltz", player=action.player_id, heads=heads)


def _ear_force(state, action):
    """me02.5-172 Mega Audino ex atk1 — Ear Force: 20 + 80 per Energy on opp's Active."""
    opp = state.get_opponent(action.player_id)
    energy_count = len(opp.active.energy_attached) if opp.active else 0
    _apply_damage(state, action, 20 + 80 * energy_count)


def _peck_the_wound(state, action):
    """me02.5-173 Larry's Rufflet atk0 — Peck the Wound: 20 + 80 if opp Active has damage."""
    opp = state.get_opponent(action.player_id)
    bonus = 80 if (opp.active and opp.active.damage_counters > 0) else 0
    _apply_damage(state, action, 20 + bonus)


def _dozing_draw(state, action):
    """me02.5-175 Larry's Komala atk0 — Dozing Draw: self Asleep + draw 2 cards."""
    player = state.get_player(action.player_id)
    if player.active:
        player.active.status_conditions.add(StatusCondition.ASLEEP)
        state.emit_event("status_applied", card=player.active.card_name, status="asleep")
    from app.engine.effects.abilities import draw_cards as _draw_cards
    _draw_cards(state, action.player_id, 2)


def _dragon_strike(state, action):
    """me02.5-176 Drampa atk1 — Dragon Strike: 120 + can't use next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("cant_attack_next_turn", card=player.active.card_name)


def _fickle_spitting(state, action):
    """me02.5-177 Hop's Cramorant atk0 — Fickle Spitting: 120 only if opp has 3 or 4 prizes."""
    opp = state.get_opponent(action.player_id)
    if opp.prizes_remaining in (3, 4):
        state.emit_event("attack_no_damage", attacker="Hop's Cramorant",
                         attack_name="Fickle Spitting", reason="prize_condition_not_met")
        return
    _do_default_damage(state, action)


def _prism_charge(state, action):
    """me02.5-178 Terapagos atk0 — Prism Charge: search for up to 3 Basic Energy, attach."""
    from app.engine.state import EnergyAttachment, EnergyType as _ET
    player = state.get_player(action.player_id)
    energies = [c for c in player.deck if c.card_type.lower() == "energy"]
    if not energies:
        state.emit_event("prism_charge", player=action.player_id, count=0)
        return
    req = ChoiceRequest("choose_cards", action.player_id,
                        "Prism Charge: search for up to 3 Basic Energy.",
                        cards=energies, min_count=0, max_count=3)
    resp = yield req
    chosen_ids = (resp.selected_cards if resp else []) or [e.instance_id for e in energies[:3]]
    all_poke = ([player.active] if player.active else []) + player.bench
    if not all_poke:
        return
    for iid in chosen_ids[:3]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            target = all_poke[0]
            card.zone = target.zone
            target.energy_attached.append(EnergyAttachment(
                energy_type=_ET.COLORLESS,
                source_card_id=card.instance_id,
                card_def_id=card.card_def_id,
            ))
    state.emit_event("prism_charge", player=action.player_id)


def _unified_beatdown(state, action):
    """me02.5-179 Terapagos ex atk0 — Unified Beatdown: 30× benched Pokémon."""
    player = state.get_player(action.player_id)
    bench_count = len(player.bench)
    _apply_damage(state, action, 30 * bench_count)


def _crown_opal(state, action):
    """me02.5-179 Terapagos ex atk1 — Crown Opal: 180 + prevent basic non-C damage next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.prevent_damage_from_basic_noncolorless = True
        state.emit_event("crown_opal", card=player.active.card_name)


def _breakthrough_assault(state, action):
    """me02.5-153 Rayquaza atk0 — Breakthrough Assault: 20 + 90 if moved from bench this turn."""
    player = state.get_player(action.player_id)
    bonus = 90 if (player.active and player.active.moved_from_bench_this_turn) else 0
    _apply_damage(state, action, 20 + bonus)


def _ryuno_glide(state, action):
    """me02.5-152 Mega Dragonite ex atk0 — Ryuno Glide: 330 + discard 2 Energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        for _ in range(2):
            if player.active.energy_attached:
                player.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="ryuno_glide", count=2)


# ── me02 (PFL) attack handlers ──────────────────────────────────────────────

def _disperse_drool(state, action):
    """me02-2 Gloom atk0 — Disperse Drool: 20 + 20 to each Benched Pokémon (both sides)."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    player = state.get_player(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    for poke in list(opp.bench):
        _apply_bench_damage(state, opp_id, poke, 20)
        if state.phase == Phase.GAME_OVER:
            return
    for poke in list(player.bench):
        _apply_bench_damage(state, action.player_id, poke, 20)
        if state.phase == Phase.GAME_OVER:
            return


def _pollen_bomb(state, action):
    """me02-3 Vileplume atk0 — Pollen Bomb: 30 + Asleep + Poisoned."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.update({StatusCondition.ASLEEP, StatusCondition.POISONED})
        state.emit_event("status_applied", card=opp.active.card_name, status="asleep+poisoned")


def _lively_flower(state, action):
    """me02-3 Vileplume atk1 — Lively Flower: 60 base (simplified, skip heal check)."""
    _do_default_damage(state, action)


def _juggernaut_horn(state, action):
    """me02-4 Mega Heracross ex atk0 — Juggernaut Horn: 100 + approx bonus from damage."""
    player = state.get_player(action.player_id)
    bonus = min(player.active.damage_counters * 10, 300) if player.active else 0
    _apply_damage(state, action, 100 + bonus)


def _mountain_ramming(state, action):
    """me02-4 Mega Heracross ex atk1 — Mountain Ramming: 170 + mill 2 from opp's deck."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    for _ in range(2):
        if opp.deck:
            c = opp.deck.pop()
            c.zone = Zone.DISCARD
            opp.discard.append(c)
    state.emit_event("deck_mill", player=action.player_id, count=2)


def _bugs_cannon(state, action):
    """me02-8 Genesect atk0 — Bug's Cannon: 20 per G Energy to lowest-HP opp Pokémon."""
    player = state.get_player(action.player_id)
    g_energy = sum(1 for att in (player.active.energy_attached if player.active else [])
                   if att.energy_type == EnergyType.GRASS)
    if g_energy == 0:
        state.emit_event("attack_no_damage", attacker="Genesect", attack_name="Bug's Cannon")
        return
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    all_opp = ([opp.active] if opp.active else []) + opp.bench
    if not all_opp:
        return
    target = min(all_opp, key=lambda p: p.current_hp)
    if target is opp.active:
        _apply_damage(state, action, g_energy * 20)
    else:
        _apply_bench_damage(state, opp_id, target, g_energy * 20)
    state.emit_event("bugs_cannon", player=action.player_id, damage=g_energy * 20)


def _flail_around(state, action):
    """me02-9 Nymble atk0 — Flail Around: flip 3 coins, 10 per heads."""
    heads = sum(1 for _ in range(3) if _random.choice([True, False]))
    _apply_damage(state, action, 10 * heads)


def _jumping_shot(state, action):
    """me02-10 Lokix atk1 — Jumping Shot: 150 + shuffle self into deck."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        poke = player.active
        poke.energy_attached.clear()
        poke.tools_attached.clear()
        poke.zone = Zone.DECK
        player.active = None
        player.deck.insert(0, poke)
        _random.shuffle(player.deck)
        state.emit_event("jumping_shot", player=action.player_id, card=poke.card_name)


# ── Batch 3 additional PFL/ASC handlers ──────────────────────────────────────

def _sweet_circle(state, action):
    """me02-044 Alcremie atk0 — Sweet Circle: 20× per own Pokémon in play."""
    player = state.get_player(action.player_id)
    count = len([player.active] if player.active else []) + len(player.bench)
    _apply_damage(state, action, 20 * count)


def _electric_run(state, action):
    """me02-031 Boltund atk0 — Electric Run: 70 + 70 on heads."""
    bonus = 70 if _random.choice([True, False]) else 0
    _apply_damage(state, action, 70 + bonus)


def _sneaky_placement(state, action):
    """me02-046 Bramblin atk0 — Sneaky Placement: 1 damage counter on 1 opp Pokémon."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    all_opp = ([opp.active] if opp.active else []) + opp.bench
    if not all_opp:
        return
    target = min(all_opp, key=lambda p: p.current_hp)
    if target is opp.active:
        _apply_damage(state, action, 10)
    else:
        _apply_bench_damage(state, opp_id, target, 10)


def _infernal_slash(state, action):
    """me02-020 Ceruledge atk0 — Infernal Slash: 220, discard 4 Fire Energy from hand first."""
    player = state.get_player(action.player_id)
    fire_in_hand = [c for c in player.hand
                    if c.card_type.lower() == "energy"
                    and any(x in (c.energy_provides or []) for x in ["R", "Fire", "fire"])]
    if len(fire_in_hand) < 4:
        state.emit_event("attack_no_damage", attacker="Ceruledge", attack_name="Infernal Slash",
                         reason="not_enough_fire_energy")
        return
    for c in fire_in_hand[:4]:
        player.hand.remove(c)
        c.zone = Zone.DISCARD
        player.discard.append(c)
    _do_default_damage(state, action)


def _gather_strength(state, action):
    """me02-019 Charcadet atk0 — Gather Strength: search deck for up to 2 Basic Energy → hand."""
    player = state.get_player(action.player_id)
    energies = [c for c in player.deck if c.card_type.lower() == "energy"]
    if not energies:
        return
    req = ChoiceRequest("choose_cards", action.player_id,
                        "Gather Strength: search for up to 2 Basic Energy.",
                        cards=energies, min_count=0, max_count=2)
    resp = yield req
    chosen = (resp.selected_cards if resp else []) or [e.instance_id for e in energies[:2]]
    for iid in chosen[:2]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    _shuffle_deck(player)
    state.emit_event("gather_strength", player=action.player_id)


def _swelling_light(state, action):
    """me02-039 Cresselia atk0 — Swelling Light: search for up to 2 P Energy, attach to self."""
    from app.engine.state import EnergyAttachment, EnergyType as _ET
    player = state.get_player(action.player_id)
    p_energy = [c for c in player.deck if c.card_type.lower() == "energy"]
    if not p_energy or not player.active:
        return
    req = ChoiceRequest("choose_cards", action.player_id,
                        "Swelling Light: search for up to 2 P Energy to attach.",
                        cards=p_energy, min_count=0, max_count=2)
    resp = yield req
    chosen = (resp.selected_cards if resp else []) or [e.instance_id for e in p_energy[:2]]
    for iid in chosen[:2]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card and player.active:
            player.deck.remove(card)
            card.zone = Zone.ACTIVE
            player.active.energy_attached.append(_ET_ATTACH(card))
    _shuffle_deck(player)
    state.emit_event("swelling_light", player=action.player_id)


def _blaze_ball_darumaka(state, action):
    """me02-015 Darumaka — Blaze Ball: 10 + 20 per R Energy."""
    player = state.get_player(action.player_id)
    r_count = sum(1 for att in (player.active.energy_attached if player.active else [])
                  if att.energy_type == EnergyType.FIRE)
    _apply_damage(state, action, 10 + 20 * r_count)


def _blaze_ball_darmanitan(state, action):
    """me02-016 Darmanitan — Blaze Ball: 40 + 40 per R Energy."""
    player = state.get_player(action.player_id)
    r_count = sum(1 for att in (player.active.energy_attached if player.active else [])
                  if att.energy_type == EnergyType.FIRE)
    _apply_damage(state, action, 40 + 40 * r_count)


def _finishing_blow(state, action):
    """me02-038 Granbull atk1 — Finishing Blow: 90 + 90 if opp's Active has damage counters."""
    opp = state.get_opponent(action.player_id)
    bonus = 90 if (opp.active and opp.active.damage_counters > 0) else 0
    _apply_damage(state, action, 90 + bonus)


def _wreck(state, action):
    """me02-025 Mamoswine atk0 — Wreck: 120 + 120 if Stadium in play, then discard it."""
    bonus = 0
    if state.active_stadium is not None:
        bonus = 120
        state.active_stadium = None
        state.emit_event("stadium_discarded", reason="wreck")
    _apply_damage(state, action, 120 + bonus)


def _blizzard_edge(state, action):
    """me02-025 Mamoswine atk1 — Blizzard Edge: 200 — discard 2 Energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        for _ in range(2):
            if player.active.energy_attached:
                player.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="blizzard_edge", count=2)


def _garland_ray(state, action):
    """me02-041 Mega Diancie ex atk0 — Garland Ray: discard up to 2 Energy, 120× per discarded."""
    player = state.get_player(action.player_id)
    if not player.active:
        return
    available = len(player.active.energy_attached)
    discard_count = min(2, available)
    for _ in range(discard_count):
        if player.active.energy_attached:
            player.active.energy_attached.pop(0)
    _apply_damage(state, action, 120 * discard_count)
    if discard_count:
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="garland_ray", count=discard_count)


def _soothing_melody(state, action):
    """me02-040 Meloetta atk0 — Soothing Melody: heal 120 from 1 benched P Pokémon."""
    player = state.get_player(action.player_id)
    p_bench = [p for p in player.bench if p.damage_counters > 0]
    if not p_bench:
        return
    target = max(p_bench, key=lambda p: p.damage_counters)
    heal = min(120, target.damage_counters * 10)
    counters = min(12, target.damage_counters)
    target.current_hp = min(target.current_hp + heal, target.max_hp)
    target.damage_counters -= counters
    state.emit_event("heal", player=action.player_id, card=target.card_name, amount=heal)


def _hexa_magic(state, action):
    """me02-036 Mismagius ex atk0 — Hexa-Magic: 150 + draw up to 6 cards."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    needed = max(0, 6 - len(player.hand))
    if needed > 0:
        from app.engine.effects.abilities import draw_cards
        draw_cards(state, action.player_id, needed)
    state.emit_event("hexa_magic", player=action.player_id)


def _raging_charge(state, action):
    """me02-048 Paldean Tauros atk0 — Raging Charge: 40× per Tauros with damage."""
    player = state.get_player(action.player_id)
    tauros_count = sum(
        1 for p in _in_play(player)
        if "Tauros" in p.card_name and p.damage_counters > 0
    )
    _apply_damage(state, action, 40 * tauros_count)


def _double_edge_tauros(state, action):
    """me02-048 Paldean Tauros atk1 — Double-Edge: 70 + 20 to self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.damage_counters += 2
        player.active.current_hp -= 20
        from app.engine.effects.base import check_ko
        check_ko(state, player.active, action.player_id)


def _growl_attack(state, action):
    """me02-032 Pawmi atk0 — Growl: opponent's Active does 30 less damage next turn."""
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.incoming_damage_reduction = getattr(opp.active, 'incoming_damage_reduction', 0)
        # Apply as outgoing damage reduction on opp's active
        # Use a workaround: add to a temporary field
        opp.active.outgoing_damage_reduction = getattr(opp.active, 'outgoing_damage_reduction', 0) + 30
    state.emit_event("growl_attack", player=action.player_id)


def _voltaic_fist(state, action):
    """me02-034 Pawmot atk0 — Voltaic Fist: 130 + optional 60 self + paralyze opp."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    # AI applies self-damage + paralyze if it won't self-KO
    player = state.get_player(action.player_id)
    if player.active and player.active.current_hp > 60:
        player.active.damage_counters += 6
        player.active.current_hp -= 60
        from app.engine.effects.base import check_ko
        check_ko(state, player.active, action.player_id)
        if state.phase == Phase.GAME_OVER:
            return
        opp = state.get_opponent(action.player_id)
        if opp.active:
            opp.active.status_conditions.add(StatusCondition.PARALYZED)
            state.emit_event("status_applied", card=opp.active.card_name, status="paralyzed")


def _rising_lunge_piloswine(state, action):
    """me02-024 Piloswine atk0 — Rising Lunge: 30 + 30 on heads."""
    bonus = 30 if _random.choice([True, False]) else 0
    _apply_damage(state, action, 30 + bonus)


def _call_for_support(state, action):
    """me02-027 Piplup atk0 — Call for Support: search deck for a Supporter, put in hand."""
    player = state.get_player(action.player_id)
    supporters = [c for c in player.deck if c.card_subtype.lower() == "supporter"]
    if not supporters:
        return
    req = ChoiceRequest("choose_cards", action.player_id,
                        "Call for Support: search for a Supporter card.",
                        cards=supporters, min_count=0, max_count=1)
    resp = yield req
    chosen = (resp.selected_cards if resp else []) or [supporters[0].instance_id]
    for iid in chosen[:1]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    _shuffle_deck(player)
    state.emit_event("call_for_support", player=action.player_id)


def _targeted_dive(state, action):
    """me02-028 Prinplup atk1 — Targeted Dive: 70 to 1 bench Pokémon (no W/R)."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.bench:
        return
    target = min(opp.bench, key=lambda p: p.current_hp)
    _apply_bench_damage(state, opp_id, target, 70)
    state.emit_event("bench_damage", attacker="Prinplup", target=target.card_name, damage=70)


def _burning_flare(state, action):
    """me02-017 Reshiram atk1 — Burning Flare: 240 + 60 to self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.damage_counters += 6
        player.active.current_hp -= 60
        from app.engine.effects.base import check_ko
        check_ko(state, player.active, action.player_id)


def _bubble_drain(state, action):
    """me02-021 Seel atk0 — Bubble Drain: 20 + heal 20 from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active and player.active.damage_counters > 0:
        heal = min(20, player.active.damage_counters * 10)
        player.active.current_hp = min(player.active.current_hp + heal, player.active.max_hp)
        player.active.damage_counters -= min(2, player.active.damage_counters)
        state.emit_event("heal", player=action.player_id, card=player.active.card_name, amount=heal)


def _crystal_fall(state, action):
    """me02-026 Suicune atk0 — Crystal Fall: 30 + 90 if 4+ W Energy in play."""
    player = state.get_player(action.player_id)
    total_w = sum(
        1 for p in _in_play(player)
        for att in p.energy_attached
        if att.energy_type == EnergyType.WATER
    )
    bonus = 90 if total_w >= 4 else 0
    _apply_damage(state, action, 30 + bonus)


def _double_headbutt(state, action):
    """me02-051 Trapinch atk0 — Double Headbutt: flip 2 coins, 10× per heads."""
    heads = sum(1 for _ in range(2) if _random.choice([True, False]))
    _apply_damage(state, action, 10 * heads)


def _play_rough(state, action):
    """me02-030 Yamper atk0 — Play Rough: 20 + 20 on heads."""
    bonus = 20 if _random.choice([True, False]) else 0
    _apply_damage(state, action, 20 + bonus)


def _limit_break(state, action):
    """me02-045 Zacian atk0 — Limit Break: 50 + 90 if opp has 3 or fewer prizes."""
    opp = state.get_opponent(action.player_id)
    bonus = 90 if opp.prizes_remaining <= 3 else 0
    _apply_damage(state, action, 50 + bonus)


def _brave_bird(state, action):
    """me02.5-174 Larry's Braviary atk1 — Brave Bird: 120 + 30 to self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.damage_counters += 3
        player.active.current_hp -= 30
        from app.engine.effects.base import check_ko
        check_ko(state, player.active, action.player_id)


def _inferno_x_charizard(state, action):
    """me02-013 Mega Charizard X ex atk0 — Inferno X: discard any R Energy, 90× per discarded."""
    player = state.get_player(action.player_id)
    if not player.active:
        return
    r_energy = [att for att in player.active.energy_attached
                if att.energy_type == EnergyType.FIRE]
    count = len(r_energy)  # AI discards all Fire Energy
    for att in r_energy:
        player.active.energy_attached.remove(att)
    if count == 0:
        state.emit_event("attack_no_damage", attacker="Mega Charizard X ex",
                         attack_name="Inferno X", reason="no_fire_energy")
        return
    _apply_damage(state, action, 90 * count)
    state.emit_event("energy_discarded", card=player.active.card_name,
                     reason="inferno_x", count=count)


def _slam_dewgong(state, action):
    """me02-022 Dewgong atk0 — Slam: flip 2 coins, 70 per heads."""
    heads = sum(1 for _ in range(2) if _random.choice([True, False]))
    _apply_damage(state, action, 70 * heads)


def _ET_ATTACH(card):
    """Helper to create an EnergyAttachment from an energy card."""
    from app.engine.state import EnergyAttachment, EnergyType as _ET
    return _ET(energy_type=_ET.COLORLESS, source_card_id=card.instance_id,
               card_def_id=card.card_def_id)


# ── Batch 4 Attack Handlers ───────────────────────────────────────────────────

def _guard_press_exeggutor(state, action):
    """me01-005 Exeggutor atk0 — Guard Press: 30 + reduce incoming by 30 next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.incoming_damage_reduction = 30
        state.emit_event("guard_press", player=action.player_id)


def _iron_feathers(state, action):
    """me02-070 Empoleon ex atk0 — Iron Feathers: 210 + prevent all damage next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.prevent_damage_one_turn = True
        state.emit_event("iron_feathers", player=action.player_id)


def _frost_barrier(state, action):
    """me01-036 Mega Abomasnow ex atk1 — Frost Barrier: 200 + reduce incoming by 30."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.incoming_damage_reduction = 30
        state.emit_event("frost_barrier", player=action.player_id)


def _flashing_bolt(state, action):
    """me01-047 Magnezone atk1 — Flashing Bolt: 160 + can't use this attack next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.locked_attack_index = 1
        state.emit_event("flashing_bolt_locked", player=action.player_id)


def _bright_horns(state, action):
    """me01-064 Xerneas atk1 — Bright Horns: 120 + can't use this attack next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.locked_attack_index = 1
        state.emit_event("bright_horns_locked", player=action.player_id)


def _coated_attack(state, action):
    """me02-075 Archaludon atk0 — Coated Attack: 120 + prevent damage from Basic next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.prevent_damage_from_basic = True
        state.emit_event("coated_attack", player=action.player_id)


def _flash_ray(state, action):
    """me01-050 Mega Manectric ex atk0 — Flash Ray: 120 + prevent damage from Basic next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.prevent_damage_from_basic = True
        state.emit_event("flash_ray", player=action.player_id)


def _power_rush(state, action):
    """me02-069 Eternatus atk1 — Power Rush: 130 + flip, tails = can't attack next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):
        state.emit_event("power_rush_flip", player=action.player_id, result="heads")
    else:
        player = state.get_player(action.player_id)
        if player.active:
            player.active.cant_attack_next_turn = True
        state.emit_event("power_rush_flip", player=action.player_id, result="tails")


def _shatter_stadium(state, action):
    """me02-069 Eternatus atk0 — Shatter: 50 + discard Stadium."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if state.active_stadium is not None:
        discarded = state.active_stadium.card_name
        state.active_stadium = None
        state.emit_event("stadium_discarded", card=discarded, reason="shatter")


def _dazzle_blast(state, action):
    """me01-053 Heliolisk atk0 — Dazzle Blast: 20 + Confuse opponent's Active."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.CONFUSED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="confused", attack="Dazzle Blast")


def _greedy_fang(state, action):
    """me02-061 Mega Sharpedo ex atk0 — Greedy Fang: 70 + draw 2 cards."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    drawn = draw_cards(state, action.player_id, 2)
    state.emit_event("greedy_fang_draw", player=action.player_id, drawn=drawn)


def _hungry_jaws(state, action):
    """me02-061 Mega Sharpedo ex atk1 — Hungry Jaws: 120 + 150 more if self has damage counters."""
    player = state.get_player(action.player_id)
    bonus = 150 if (player.active and player.active.damage_counters > 0) else 0
    _apply_damage(state, action, 120 + bonus)


def _ambush_murkrow(state, action):
    """me02-057 Murkrow atk0 — Ambush: 10 + 20 more if heads."""
    bonus = 20 if _random.choice([True, False]) else 0
    _apply_damage(state, action, 10 + bonus)
    state.emit_event("ambush_flip", player=action.player_id,
                     result="heads" if bonus else "tails")


def _sniping_feathers(state, action):
    """me02-058 Honchkrow atk1 — Sniping Feathers: discard 2 Energy from self, 120 to any opp."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)

    if player.active:
        discarded = 0
        while discarded < 2 and player.active.energy_attached:
            player.active.energy_attached.pop(0)
            discarded += 1
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="sniping_feathers", count=discarded)

    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    if not all_opp:
        return
    if not opp.bench:
        _apply_damage(state, action, 120)
        return

    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Sniping Feathers: choose 1 of your opponent's Pokémon for 120 damage",
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
        _apply_damage(state, action, 120)
    else:
        _apply_bench_damage(state, opp_id, target, 120)


def _cocky_claw(state, action):
    """me02-059 Sableye atk0 — Cocky Claw: 20 + 70 if Stage 2 Darkness Pokémon on bench."""
    player = state.get_player(action.player_id)
    bonus = 0
    for bench_poke in player.bench:
        bdef = card_registry.get(bench_poke.card_def_id)
        if bdef and (bdef.stage or "").lower() in ("stage2", "stage 2") and "Darkness" in (bdef.types or []):
            bonus = 70
            break
    _apply_damage(state, action, 20 + bonus)


def _vengeful_fang(state, action):
    """me02-066 Krookodile atk0 — Vengeful Fang: 60 + 160 if any of your Pokémon KO'd last turn."""
    player_id = action.player_id
    prev_turn = state.turn_number - 1
    was_ko = any(
        e.get("event_type") == "ko"
        and e.get("ko_player") == player_id
        and e.get("turn", -1) == prev_turn
        for e in state.events
    )
    bonus = 160 if was_ko else 0
    _apply_damage(state, action, 60 + bonus)


def _triple_draw(state, action):
    """me02-072 Bronzong atk0 — Triple Draw: draw 3 cards."""
    drawn = draw_cards(state, action.player_id, 3)
    state.emit_event("triple_draw", player=action.player_id, drawn=drawn)


def _tool_drop(state, action):
    """me02-072 Bronzong atk1 — Tool Drop: 40 × number of Pokémon Tools in play."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)

    total_tools = 0
    all_pokes = (
        ([player.active] if player.active else []) + list(player.bench) +
        ([opp.active] if opp.active else []) + list(opp.bench)
    )
    for poke in all_pokes:
        total_tools += len(poke.tools_attached)
    _apply_damage(state, action, 40 * total_tools)


def _find_a_friend_togedemaru(state, action):
    """me02-073 Togedemaru atk0 — Find a Friend: search deck for 1 Pokémon, put on Bench."""
    player = state.get_player(action.player_id)
    if len(player.bench) >= 5 or not player.deck:
        return
    pokemon_in_deck = [c for c in player.deck if c.card_type.lower() == "pokemon"]
    if not pokemon_in_deck:
        _shuffle_deck(player)
        return
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Find a Friend: choose 1 Pokémon from deck to put on Bench",
        cards=pokemon_in_deck, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [pokemon_in_deck[0].instance_id]
    for cid in chosen_ids[:1]:
        if len(player.bench) >= 5:
            break
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.BENCH
            card.turn_played = state.turn_number
            player.bench.append(card)
    _shuffle_deck(player)
    state.emit_event("find_a_friend", player=action.player_id)


def _hyper_beam_duraludon(state, action):
    """me02-074 Duraludon atk0 — Hyper Beam: 70 + discard 1 Energy from opp Active."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active and opp.active.energy_attached:
        opp.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", card=opp.active.card_name,
                         reason="hyper_beam", count=1)


def _ball_roll(state, action):
    """me02-076 Jigglypuff atk0 — Ball Roll: flip until tails, 20 per heads."""
    heads = 0
    while _random.choice([True, False]):
        heads += 1
    damage = 20 * heads
    if damage > 0:
        _apply_damage(state, action, damage)
    else:
        state.emit_event("attack_no_damage", attacker="Jigglypuff", attack_name="Ball Roll")
    state.emit_event("ball_roll_flip", player=action.player_id, heads=heads)


def _round_wigglytuff(state, action):
    """me02-077 Wigglytuff atk0 — Round: 40 × Pokémon with Round attack in play."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    count = 0
    all_pokes = (
        ([player.active] if player.active else []) + list(player.bench) +
        ([opp.active] if opp.active else []) + list(opp.bench)
    )
    for poke in all_pokes:
        pdef = card_registry.get(poke.card_def_id)
        if pdef and any((a.name or "").lower() == "round" for a in (pdef.attacks or [])):
            count += 1
    _apply_damage(state, action, 40 * count)


def _astonish(state, action):
    """me02-078 Aipom atk0 — Astonish: 20 + opp reveals and shuffles a random hand card."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_player(opp_id)
    if opp.hand:
        card = _random.choice(opp.hand)
        opp.hand.remove(card)
        card.zone = Zone.DECK
        opp.deck.append(card)
        _shuffle_deck(opp)
        state.emit_event("astonish", player=action.player_id,
                         discarded_card=card.card_name)


def _dual_tail(state, action):
    """me02-079 Ambipom atk1 — Dual Tail: discard 2 Energy from self, 60 to each of 2 opp Pokémon."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)

    if player.active:
        discarded = 0
        while discarded < 2 and player.active.energy_attached:
            player.active.energy_attached.pop(0)
            discarded += 1
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="dual_tail", count=discarded)

    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    if len(all_opp) == 0:
        return
    if len(all_opp) == 1:
        if all_opp[0] is opp.active:
            _apply_damage(state, action, 60)
        else:
            _apply_bench_damage(state, opp_id, all_opp[0], 60)
        return

    req = ChoiceRequest(
        "choose_targets", action.player_id,
        "Dual Tail: choose 2 of your opponent's Pokémon for 60 damage each",
        targets=all_opp,
    )
    resp = yield req
    chosen_ids = []
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        chosen_ids = [resp.target_instance_id]
    if not chosen_ids:
        chosen_ids = [p.instance_id for p in all_opp[:2]]

    targets_chosen = [p for p in all_opp if p.instance_id in chosen_ids][:2]
    if not targets_chosen:
        targets_chosen = all_opp[:2]

    for t in targets_chosen:
        if t is opp.active:
            _apply_damage(state, action, 60)
        else:
            _apply_bench_damage(state, opp_id, t, 60)
        if state.phase == Phase.GAME_OVER:
            return


def _energizing_sketch(state, action):
    """me02-080 Smeargle atk0 — Energizing Sketch: flip 3 coins, attach Basic Energy from discard per heads."""
    player = state.get_player(action.player_id)
    heads = sum(1 for _ in range(3) if _random.choice([True, False]))
    state.emit_event("energizing_sketch_flip", player=action.player_id, heads=heads)
    if heads == 0:
        return

    from app.engine.state import EnergyAttachment, EnergyType as _ET
    energy_types = {
        "grass": _ET.GRASS, "fire": _ET.FIRE, "water": _ET.WATER,
        "lightning": _ET.LIGHTNING, "psychic": _ET.PSYCHIC, "fighting": _ET.FIGHTING,
        "darkness": _ET.DARKNESS, "metal": _ET.METAL,
    }
    basic_discard = [c for c in player.discard
                     if c.card_type.lower() == "energy"]
    bench_targets = list(player.bench)
    if not basic_discard or not bench_targets:
        return

    attached = 0
    for _ in range(heads):
        if attached >= len(bench_targets):
            break
        if not basic_discard:
            break
        energy_card = _random.choice(basic_discard)
        basic_discard.remove(energy_card)
        player.discard.remove(energy_card)
        target = bench_targets[attached]
        etype = energy_types.get(energy_card.card_name.lower().replace(" energy", ""), _ET.COLORLESS)
        target.energy_attached.append(EnergyAttachment(
            energy_type=etype,
            source_card_id=energy_card.instance_id,
            card_def_id=energy_card.card_def_id,
        ))
        attached += 1
    state.emit_event("energizing_sketch_attach", player=action.player_id, count=attached)


def _bind_down(state, action):
    """me01-001 Bulbasaur atk0 — Bind Down: 10 + opp can't retreat next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.cant_retreat_next_turn = True
        state.emit_event("bind_down", player=action.player_id,
                         card=opp.active.card_name)


def _jam_packed(state, action):
    """me01-004 Exeggcute atk0 — Jam-Packed: search deck for Basic {G} Energy, attach to self."""
    player = state.get_player(action.player_id)
    if not player.active or not player.deck:
        return
    from app.engine.state import EnergyAttachment, EnergyType as _ET
    grass_energy = [c for c in player.deck
                    if c.card_type.lower() == "energy" and
                    "grass" in c.card_name.lower()]
    if not grass_energy:
        _shuffle_deck(player)
        return
    energy_card = grass_energy[0]
    player.deck.remove(energy_card)
    player.active.energy_attached.append(EnergyAttachment(
        energy_type=_ET.GRASS,
        source_card_id=energy_card.instance_id,
        card_def_id=energy_card.card_def_id,
    ))
    _shuffle_deck(player)
    state.emit_event("jam_packed", player=action.player_id,
                     card=player.active.card_name)


def _stomping_wood(state, action):
    """me01-005 Exeggutor atk1 — Stomping Wood: 60 + 30 per {G} Energy attached to self."""
    player = state.get_player(action.player_id)
    g_count = sum(1 for att in (player.active.energy_attached if player.active else [])
                  if att.energy_type == EnergyType.GRASS)
    _apply_damage(state, action, 60 + 30 * g_count)


def _poison_powder_tangela(state, action):
    """me01-006 Tangela atk0 — Poison Powder: Poison opponent's Active (no damage)."""
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_player(opp_id)
    if opp.active and StatusCondition.POISONED not in opp.active.status_conditions:
        opp.active.status_conditions.add(StatusCondition.POISONED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="poisoned", attack="Poison Powder")


def _pumped_up_whip(state, action):
    """me01-007 Tangrowth atk1 — Pumped-Up Whip: 120 + 140 if 2+ extra Energy attached."""
    player = state.get_player(action.player_id)
    if not player.active:
        _apply_damage(state, action, 120)
        return
    cdef = card_registry.get(player.active.card_def_id)
    attack = (cdef.attacks[action.attack_index] if cdef and action.attack_index is not None
              and action.attack_index < len(cdef.attacks) else None)
    attack_cost = len(attack.cost) if attack and attack.cost else 0
    extra = len(player.active.energy_attached) - attack_cost
    bonus = 140 if extra >= 2 else 0
    _apply_damage(state, action, 120 + bonus)


def _reversing_gust(state, action):
    """me01-015 Shiftry atk0 — Reversing Gust: flip, heads = shuffle opp's Active into deck."""
    if not _random.choice([True, False]):
        state.emit_event("reversing_gust_flip", player=action.player_id, result="tails")
        return
    state.emit_event("reversing_gust_flip", player=action.player_id, result="heads")
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_player(opp_id)
    if not opp.active:
        return
    active_poke = opp.active
    active_poke.zone = Zone.DECK
    opp.deck.append(active_poke)
    opp.active = None
    if opp.bench:
        new_active = opp.bench.pop(0)
        new_active.zone = Zone.ACTIVE
        opp.active = new_active
    _shuffle_deck(opp)
    state.emit_event("reversing_gust_ko", player=action.player_id,
                     shuffled_card=active_poke.card_name)


def _perplex_shiftry(state, action):
    """me01-015 Shiftry atk1 — Perplex: 100 + Confused."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.CONFUSED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="confused", attack="Perplex")


def _traverse_time(state, action):
    """me01-012 Celebi atk0 — Traverse Time: search deck for up to 3 Grass Pokémon or Stadiums."""
    player = state.get_player(action.player_id)
    if not player.deck:
        return
    eligible = []
    for c in player.deck:
        cdef = card_registry.get(c.card_def_id)
        if cdef and c.card_type.lower() == "pokemon" and "Grass" in (cdef.types or []):
            eligible.append(c)
        elif c.card_type.lower() == "trainer" and (c.card_subtype or "").lower() == "stadium":
            if c not in eligible:
                eligible.append(c)
    if not eligible:
        _shuffle_deck(player)
        return
    max_count = min(3, len(eligible))
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Traverse Time: search for up to 3 Grass Pokémon or Stadium cards",
        cards=eligible, min_count=0, max_count=max_count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in eligible[:max_count]]
    for cid in chosen_ids[:3]:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    _shuffle_deck(player)
    state.emit_event("traverse_time", player=action.player_id, count=len(chosen_ids[:3]))


def _earthen_power(state, action):
    """me01-018 Dhelmise atk0 — Earthen Power: 30 + 50 if a Stadium is in play."""
    bonus = 50 if state.active_stadium is not None else 0
    _apply_damage(state, action, 30 + bonus)


def _roasting_heat(state, action):
    """me01-022 Mega Camerupt ex atk0 — Roasting Heat: 80 + 160 if opp Active is Burned."""
    opp = state.get_opponent(action.player_id)
    bonus = 160 if (opp.active and StatusCondition.BURNED in opp.active.status_conditions) else 0
    _apply_damage(state, action, 80 + bonus)


def _volcanic_meteor(state, action):
    """me01-022 Mega Camerupt ex atk1 — Volcanic Meteor: 280 + discard 2 Energy."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        discarded = 0
        while discarded < 2 and player.active.energy_attached:
            player.active.energy_attached.pop(0)
            discarded += 1
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="volcanic_meteor", count=discarded)


def _singe_only(state, action):
    """me01-025 Volcanion atk0 — Singe: Burn opponent's Active (no damage)."""
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_player(opp_id)
    if opp.active and StatusCondition.BURNED not in opp.active.status_conditions:
        opp.active.status_conditions.add(StatusCondition.BURNED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="burned", attack="Singe")


def _backfire(state, action):
    """me01-025 Volcanion atk1 — Backfire: 130 + put 2 Fire Energy from discard into hand."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    fire_in_discard = [c for c in player.discard if c.card_type.lower() == "energy"
                       and "fire" in c.card_name.lower()]
    count = 0
    for card in fire_in_discard[:2]:
        player.discard.remove(card)
        card.zone = Zone.HAND
        player.hand.append(card)
        count += 1
    state.emit_event("backfire_retrieve", player=action.player_id, count=count)


def _jumping_kick_raboot(state, action):
    """me01-027 Raboot atk0 — Jumping Kick: 40 to any 1 of opponent's Pokémon."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    if not all_opp:
        return
    if not opp.bench:
        _apply_damage(state, action, 40)
        return
    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Jumping Kick: choose 1 of your opponent's Pokémon for 40 damage",
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
        _apply_damage(state, action, 40)
    else:
        _apply_bench_damage(state, opp_id, target, 40)


def _turbo_flare(state, action):
    """me01-028 Cinderace atk0 — Turbo Flare: 50 + search up to 3 Basic Energy, attach to Bench."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if not player.deck or not player.bench:
        return
    from app.engine.state import EnergyAttachment, EnergyType as _ET
    basic_energy = [c for c in player.deck if c.card_type.lower() == "energy"]
    if not basic_energy:
        _shuffle_deck(player)
        return
    max_count = min(3, len(basic_energy), len(player.bench))
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Turbo Flare: choose up to 3 Basic Energy from deck to attach to Bench",
        cards=basic_energy, min_count=0, max_count=max_count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in basic_energy[:max_count]]
    energy_types = {
        "grass": _ET.GRASS, "fire": _ET.FIRE, "water": _ET.WATER,
        "lightning": _ET.LIGHTNING, "psychic": _ET.PSYCHIC, "fighting": _ET.FIGHTING,
        "darkness": _ET.DARKNESS, "metal": _ET.METAL,
    }
    attached = 0
    for cid in chosen_ids[:3]:
        if attached >= len(player.bench):
            break
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            etype = energy_types.get(card.card_name.lower().replace(" energy", ""), _ET.COLORLESS)
            target = player.bench[attached]
            target.energy_attached.append(EnergyAttachment(
                energy_type=etype,
                source_card_id=card.instance_id,
                card_def_id=card.card_def_id,
            ))
            attached += 1
    _shuffle_deck(player)
    state.emit_event("turbo_flare_attach", player=action.player_id, count=attached)


def _coiling_crush(state, action):
    """me01-030 Centiskorch atk0 — Coiling Crush: 50 + flip 2 coins, discard 1 Energy per heads."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    for _ in range(2):
        if _random.choice([True, False]):
            if opp.active and opp.active.energy_attached:
                opp.active.energy_attached.pop(0)
                state.emit_event("energy_discarded", card=opp.active.card_name,
                                 reason="coiling_crush", count=1)


def _scorching_earth(state, action):
    """me01-031 Chi-Yu atk0 — Scorching Earth: 40 + if Stadium in play, discard it."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if state.active_stadium is not None:
        opp_id = state.opponent_id(action.player_id)
        discarded = state.active_stadium.card_name
        state.active_stadium = None
        state.emit_event("stadium_discarded", card=discarded, reason="scorching_earth",
                         player=opp_id)


def _riptide(state, action):
    """me01-034 Kyogre atk0 — Riptide: 20 × Basic W Energy in discard, then shuffle them back."""
    player = state.get_player(action.player_id)
    water_energy = [c for c in player.discard
                    if c.card_type.lower() == "energy" and "water" in c.card_name.lower()]
    count = len(water_energy)
    damage = 20 * count
    if damage > 0:
        _apply_damage(state, action, damage)
    else:
        state.emit_event("attack_no_damage", attacker="Kyogre", attack_name="Riptide")
    for card in water_energy:
        player.discard.remove(card)
        card.zone = Zone.DECK
        player.deck.append(card)
    _shuffle_deck(player)
    state.emit_event("riptide", player=action.player_id, count=count)


def _swirling_waves(state, action):
    """me01-034 Kyogre atk1 — Swirling Waves: 130 + discard 2 Energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        discarded = 0
        while discarded < 2 and player.active.energy_attached:
            player.active.energy_attached.pop(0)
            discarded += 1
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="swirling_waves", count=discarded)


def _hammer_lanche(state, action):
    """me01-036 Mega Abomasnow ex atk0 — Hammer-lanche: discard top 6, 100 per W Energy discarded."""
    player = state.get_player(action.player_id)
    discarded_water = 0
    for _ in range(6):
        if not player.deck:
            break
        card = player.deck.pop()
        card.zone = Zone.DISCARD
        player.discard.append(card)
        if card.card_type.lower() == "energy" and "water" in card.card_name.lower():
            discarded_water += 1
    damage = 100 * discarded_water
    if damage > 0:
        _apply_damage(state, action, damage)
    else:
        state.emit_event("attack_no_damage", attacker="Mega Abomasnow ex",
                         attack_name="Hammer-lanche")
    state.emit_event("hammer_lanche", player=action.player_id,
                     water_discarded=discarded_water)


def _aqua_launcher(state, action):
    """me01-038 Clawitzer atk0 — Aqua Launcher: 210 + discard ALL Energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        count = len(player.active.energy_attached)
        player.active.energy_attached.clear()
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="aqua_launcher", count=count)


def _double_stab(state, action):
    """me01-040 Drizzile atk0 — Double Stab: 30 per heads (2 flips)."""
    heads = sum(1 for _ in range(2) if _random.choice([True, False]))
    damage = 30 * heads
    if damage > 0:
        _apply_damage(state, action, damage)
    else:
        state.emit_event("attack_no_damage", attacker="Drizzile", attack_name="Double Stab")
    state.emit_event("double_stab_flip", player=action.player_id, heads=heads)


def _bring_down(state, action):
    """me01-041 Inteleon atk0 — Bring Down: KO the Pokémon with fewest remaining HP."""
    player_id = action.player_id
    player = state.get_player(player_id)
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)

    all_pokes = []
    for p in player.bench:
        all_pokes.append((p, player_id))
    if opp.active:
        all_pokes.append((opp.active, opp_id))
    for p in opp.bench:
        all_pokes.append((p, opp_id))

    if not all_pokes:
        state.emit_event("bring_down_no_target", player=player_id)
        return

    min_hp = min(p.current_hp for p, _ in all_pokes)
    candidates = [(p, pid) for p, pid in all_pokes if p.current_hp == min_hp]

    if len(candidates) == 1:
        target, target_player_id = candidates[0]
    else:
        opp_candidates = [(p, pid) for p, pid in candidates if pid == opp_id]
        target, target_player_id = opp_candidates[0] if opp_candidates else candidates[0]

    target.current_hp = 0
    check_ko(state, target, target_player_id)
    state.emit_event("bring_down", player=player_id, target=target.card_name)


def _water_shot(state, action):
    """me01-041 Inteleon atk1 — Water Shot: 110 + discard 1 Energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active and player.active.energy_attached:
        player.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="water_shot", count=1)


def _chilling_wings(state, action):
    """me01-043 Frosmoth atk0 — Chilling Wings: 20 to each of opponent's Pokémon."""
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_player(opp_id)
    if opp.active:
        _apply_damage(state, action, 20)
        if state.phase == Phase.GAME_OVER:
            return
    for bench_poke in list(opp.bench):
        _apply_bench_damage(state, opp_id, bench_poke, 20)
        if state.phase == Phase.GAME_OVER:
            return


def _upper_spark(state, action):
    """me01-047 Magnezone atk0 — Upper Spark: 50 + 120 if evolved from Magneton this turn."""
    bonus = 0
    player_id = action.player_id
    for e in state.events:
        if (e.get("event_type") == "evolved"
                and e.get("player") == player_id
                and e.get("turn") == state.turn_number
                and "magneton" in str(e.get("from_card", "")).lower()
                and "magnezone" in str(e.get("to_card", "")).lower()):
            bonus = 120
            break
    _apply_damage(state, action, 50 + bonus)


def _electro_fall(state, action):
    """me01-048 Raikou atk0 — Electro Fall: 30 + 90 if 4 or more L Energy in play."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    all_pokes = (
        ([player.active] if player.active else []) + list(player.bench) +
        ([opp.active] if opp.active else []) + list(opp.bench)
    )
    l_count = sum(
        sum(1 for att in poke.energy_attached if att.energy_type == EnergyType.LIGHTNING)
        for poke in all_pokes
    )
    bonus = 90 if l_count >= 4 else 0
    _apply_damage(state, action, 30 + bonus)


def _riotous_blasting(state, action):
    """me01-050 Mega Manectric ex atk1 — Riotous Blasting: 200 + 130 if you discard all Energy."""
    player = state.get_player(action.player_id)
    has_energy = player.active and bool(player.active.energy_attached)
    bonus = 0
    if has_energy:
        count = len(player.active.energy_attached)
        player.active.energy_attached.clear()
        state.emit_event("energy_discarded", card=player.active.card_name,
                         reason="riotous_blasting", count=count)
        bonus = 130
    _apply_damage(state, action, 200 + bonus)


def _damage_beat(state, action):
    """me01-061 Shedinja atk0 — Damage Beat: 20 × damage counters on opp Active."""
    opp = state.get_opponent(action.player_id)
    counters = opp.active.damage_counters if opp.active else 0
    damage = 20 * counters
    if damage > 0:
        _apply_damage(state, action, damage)
    else:
        state.emit_event("attack_no_damage", attacker="Shedinja", attack_name="Damage Beat")


def _triple_spin(state, action):
    """me01-062 Spoink atk0 — Triple Spin: flip 3 coins, 10 per heads."""
    heads = sum(1 for _ in range(3) if _random.choice([True, False]))
    damage = 10 * heads
    if damage > 0:
        _apply_damage(state, action, damage)
    else:
        state.emit_event("attack_no_damage", attacker="Spoink", attack_name="Triple Spin")
    state.emit_event("triple_spin_flip", player=action.player_id, heads=heads)


def _geo_gate(state, action):
    """me01-064 Xerneas atk0 — Geo Gate: search deck for up to 3 Basic Psychic Pokémon, bench them."""
    player = state.get_player(action.player_id)
    if not player.deck:
        return
    available_slots = 5 - len(player.bench)
    if available_slots <= 0:
        return
    psychic_basics = []
    for c in player.deck:
        if c.card_type.lower() != "pokemon":
            continue
        cdef = card_registry.get(c.card_def_id)
        if cdef and (cdef.stage or "").lower() == "basic" and "Psychic" in (cdef.types or []):
            psychic_basics.append(c)
    if not psychic_basics:
        _shuffle_deck(player)
        return
    max_count = min(3, available_slots, len(psychic_basics))
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Geo Gate: search for up to 3 Basic Psychic Pokémon to bench",
        cards=psychic_basics, min_count=0, max_count=max_count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in psychic_basics[:max_count]]
    placed = 0
    for cid in chosen_ids[:3]:
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
    state.emit_event("geo_gate", player=action.player_id, count=placed)


def _horrifying_bite(state, action):
    """me01-066 Houndstone atk0 — Horrifying Bite: flip until tails, heads=shuffle opp hand card."""
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_player(opp_id)
    heads = 0
    while _random.choice([True, False]):
        heads += 1
        if opp.hand:
            card = _random.choice(opp.hand)
            opp.hand.remove(card)
            card.zone = Zone.DECK
            opp.deck.append(card)
            state.emit_event("horrifying_bite_discard", player=action.player_id,
                             discarded=card.card_name)
    _shuffle_deck(opp)
    state.emit_event("horrifying_bite_flip", player=action.player_id, heads=heads)


def _jynx_psychic(state, action):
    """me01-057 Jynx atk0 — Psychic: 30 + 30 per Energy on opponent's Active."""
    opp = state.get_opponent(action.player_id)
    energy_count = len(opp.active.energy_attached) if opp.active else 0
    _apply_damage(state, action, 30 + 30 * energy_count)


def _gale_thrust(state, action):
    """me02-084 Mega Lopunny ex atk0 — Gale Thrust: 60 + 170 if moved from bench this turn."""
    player = state.get_player(action.player_id)
    bonus = 0
    if player.active and player.active.moved_from_bench_this_turn:
        bonus = 170
    _apply_damage(state, action, 60 + bonus)


def _spiky_hopper(state, action):
    """me02-084 Mega Lopunny ex atk1 — Spiky Hopper: 160, bypass defender effects."""
    _apply_damage(state, action, 160, bypass_defender_effects=True)


# ── Batch 5: MEG attack handlers ─────────────────────────────────────────────

def _pow_pow_punching(state, action):
    """me01-071 Tyrogue atk0 — Pow-Pow Punching: flip until tails, 30 per heads."""
    heads = 0
    while _random.choice([True, False]):
        heads += 1
    state.emit_event("coin_flip_result", attack="Pow-Pow Punching", heads=heads)
    if heads > 0:
        _apply_damage(state, action, heads * 30)
    else:
        state.emit_event("attack_no_damage", attacker="Tyrogue",
                         attack_name="Pow-Pow Punching")


def _wild_press(state, action):
    """me01-073 Hariyama atk0 — Wild Press: 210 damage + 70 recoil to self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.current_hp -= 70
        player.active.damage_counters += 7
        state.emit_event("recoil_damage", player=action.player_id,
                         card=player.active.card_name, damage=70)
        check_ko(state, player.active, action.player_id)


def _reckless_charge_toxicroak(state, action):
    """me01-079 Toxicroak atk0 — Reckless Charge: 70 damage + 20 recoil to self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.current_hp -= 20
        player.active.damage_counters += 2
        state.emit_event("recoil_damage", player=action.player_id,
                         card=player.active.card_name, damage=20)
        check_ko(state, player.active, action.player_id)


def _shadowy_side_kick(state, action):
    """me01-080 Marshadow atk0 — Shadowy Side Kick: 60. If this KOs opp, prevent all damage next turn."""
    opp = state.get_opponent(action.player_id)
    opp_active_before = opp.active
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if opp_active_before and (opp.active is None or opp.active.instance_id != opp_active_before.instance_id):
        if player.active:
            player.active.prevent_damage_one_turn = True
            state.emit_event("shadowy_side_kick_shield", player=action.player_id,
                             card=player.active.card_name)


def _stony_kick(state, action):
    """me01-081 Stonjourner atk0 — Stony Kick: 20 to active + 20 to 1 opp bench (no W/R for bench)."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if opp.bench:
        target = opp.bench[0]
        _apply_bench_damage(state, opp_id, target, 20)


def _boundless_power(state, action):
    """me01-081 Stonjourner atk1 — Boundless Power: 140 + can't attack next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=player.active.card_name,
                         attack="Boundless Power")


def _naclstack_rock_hurl(state, action):
    """me01-083 Naclstack atk0 — Rock Hurl: 50, not affected by Resistance."""
    _apply_damage(state, action, 50, bypass_resistance_only=True)


def _gobble_down(state, action):
    """me01-094 Mega Mawile ex atk0 — Gobble Down: 80 × prizes player has taken."""
    player = state.get_player(action.player_id)
    prizes_taken = 6 - player.prizes_remaining
    total = 80 * prizes_taken
    if total <= 0:
        state.emit_event("attack_no_damage", attacker="Mega Mawile ex",
                         attack_name="Gobble Down", reason="no prizes taken")
        return
    _apply_damage(state, action, total)


def _huge_bite(state, action):
    """me01-094 Mega Mawile ex atk1 — Huge Bite: 260 normally, 30 if opp active already damaged."""
    opp = state.get_opponent(action.player_id)
    if opp.active and opp.active.damage_counters > 0:
        _apply_damage(state, action, 30)
    else:
        _apply_damage(state, action, 260)


def _greedy_hunt(state, action):
    """me01-090 Thievul atk0 — Greedy Hunt: 20 + draw until 6 in hand."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    to_draw = max(0, 6 - len(player.hand))
    if to_draw > 0:
        drawn = draw_cards(state, action.player_id, to_draw)
        state.emit_event("greedy_hunt_draw", player=action.player_id, drawn=drawn)


def _miraculous_paint(state, action):
    """me01-092 Grafaiai atk0 — Miraculous Paint: 90 + flip, heads = paralyzed."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):  # heads
        opp = state.get_opponent(action.player_id)
        if opp.active:
            opp.active.status_conditions.add(StatusCondition.PARALYZED)
            state.emit_event("miraculous_paint_status", player=action.player_id,
                             target=opp.active.card_name, status="Paralyzed")
    else:
        state.emit_event("coin_flip_result", attack="Miraculous Paint", result="tails")


def _welcoming_tail(state, action):
    """me01-093 Steelix atk0 — Welcoming Tail: 40 + 200 bonus if attacker has exactly 6 prizes left."""
    player = state.get_player(action.player_id)
    if player.prizes_remaining == 6:
        _apply_damage(state, action, 240)
    else:
        _apply_damage(state, action, 40)


def _mountain_breaker(state, action):
    """me01-087 Spiritomb atk0 — Mountain Breaker: 10 + discard top card of opp's deck."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if opp.deck:
        top = opp.deck.pop(0)
        top.zone = Zone.DISCARD
        opp.discard.append(top)
        state.emit_event("deck_discarded", player=opp_id, card=top.card_name,
                         reason="Mountain Breaker")


def _windup_swing(state, action):
    """me01-098 Tinkaton atk0 — Windup Swing: 240 − 60 per energy on opp's active (min 0)."""
    opp = state.get_opponent(action.player_id)
    energy_count = len(opp.active.energy_attached) if opp.active else 0
    damage = max(0, 240 - energy_count * 60)
    if damage <= 0:
        state.emit_event("attack_no_damage", attacker="Tinkaton",
                         attack_name="Windup Swing")
        return
    _apply_damage(state, action, damage)


def _all_you_can_grab(state, action):
    """me01-099 Gholdengo atk0 — All-You-Can-Grab: flip until tails, search N cards from deck."""
    player = state.get_player(action.player_id)
    heads = 0
    while _random.choice([True, False]):
        heads += 1
    state.emit_event("coin_flip_result", attack="All-You-Can-Grab", heads=heads)
    if heads == 0:
        state.emit_event("attack_no_damage", attacker="Gholdengo",
                         attack_name="All-You-Can-Grab")
        return
    grabbed = 0
    for _ in range(min(heads, len(player.deck))):
        if not player.deck:
            break
        card = player.deck.pop(0)
        card.zone = Zone.HAND
        player.hand.append(card)
        grabbed += 1
    _shuffle_deck(player)
    state.emit_event("all_you_can_grab", player=action.player_id, grabbed=grabbed)


def _illusory_impulse(state, action):
    """me01-100 Mega Latias ex atk1 — Illusory Impulse: 300 + discard all energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        count = len(player.active.energy_attached)
        player.active.energy_attached.clear()
        if count > 0:
            state.emit_event("energy_discarded", player=action.player_id,
                             card=player.active.card_name, count=count,
                             reason="Illusory Impulse")


def _pluck(state, action):
    """me01-102 Spearow atk0 — Pluck: discard all Pokémon Tools from opp's active, then 10 damage."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if opp.active and opp.active.tools_attached:
        removed = list(opp.active.tools_attached)
        opp.active.tools_attached.clear()
        for tool_id in removed:
            state.emit_event("tool_discarded", player=opp_id,
                             card=opp.active.card_name, tool=tool_id)
    _apply_damage(state, action, 10)


def _repeating_drill(state, action):
    """me01-103 Fearow atk0 — Repeating Drill: 5 flips, 30 per heads."""
    damage = 0
    heads = 0
    for _ in range(5):
        if _random.choice([True, False]):
            heads += 1
            damage += 30
    state.emit_event("coin_flip_result", attack="Repeating Drill", heads=heads, flips=5)
    if damage > 0:
        _apply_damage(state, action, damage)
    else:
        state.emit_event("attack_no_damage", attacker="Fearow",
                         attack_name="Repeating Drill")


def _quick_gift(state, action):
    """me01-105 Delibird atk0 — Quick Gift: search 1 any card from deck, put in hand."""
    player = state.get_player(action.player_id)
    if not player.deck:
        state.emit_event("attack_no_damage", attacker="Delibird",
                         attack_name="Quick Gift", reason="empty deck")
        return
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Quick Gift: choose 1 card from deck to put in hand",
        cards=player.deck, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [player.deck[0].instance_id]
    card = next((c for c in player.deck if c.instance_id in chosen_ids), None)
    if card:
        player.deck.remove(card)
        card.zone = Zone.HAND
        player.hand.append(card)
    _shuffle_deck(player)
    state.emit_event("quick_gift", player=action.player_id,
                     card=card.card_name if card else "unknown")
    state.emit_event("attack_no_damage", attacker="Delibird", attack_name="Quick Gift")


def _charm(state, action):
    """me01-107 Buneary atk0 — Charm: opp's active deals 20 less damage next turn."""
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.attack_damage_reduction += 20
        state.emit_event("charm_applied", player=action.player_id,
                         target=opp.active.card_name, reduction=20)
    state.emit_event("attack_no_damage", attacker="Buneary", attack_name="Charm")


def _dashing_kick(state, action):
    """me01-108 Lopunny atk0 — Dashing Kick: 50 to 1 opp bench only (no W/R)."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.bench:
        state.emit_event("attack_no_damage", attacker="Lopunny",
                         attack_name="Dashing Kick", reason="no bench targets")
        return
    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Dashing Kick: choose 1 of opponent's Benched Pokémon for 50 damage",
        targets=list(opp.bench),
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in opp.bench
                       if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = opp.bench[0]
    _apply_bench_damage(state, opp_id, target, 50)


def _bellyful_of_milk(state, action):
    """me01-106 Miltank atk0 — Bellyful of Milk: flip 2, both heads = heal all from 1 friendly."""
    flip1 = _random.choice([True, False])
    flip2 = _random.choice([True, False])
    state.emit_event("coin_flip_result", attack="Bellyful of Milk",
                     flip1="heads" if flip1 else "tails",
                     flip2="heads" if flip2 else "tails")
    if flip1 and flip2:
        player = state.get_player(action.player_id)
        healable = [p for p in _in_play(player) if p.damage_counters > 0]
        if healable:
            target = max(healable, key=lambda p: p.damage_counters)
            req = ChoiceRequest(
                "choose_target", action.player_id,
                "Bellyful of Milk: choose 1 of your Pokémon to heal all damage",
                targets=list(_in_play(player)),
            )
            resp = yield req
            chosen = None
            if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
                chosen = next((p for p in _in_play(player)
                               if p.instance_id == resp.target_instance_id), None)
            if chosen is None:
                chosen = target
            healed = chosen.damage_counters * 10
            chosen.current_hp = chosen.max_hp
            chosen.damage_counters = 0
            state.emit_event("healed", player=action.player_id,
                             card=chosen.card_name, amount=healed)
    state.emit_event("attack_no_damage", attacker="Miltank", attack_name="Bellyful of Milk")


def _hyper_lariat(state, action):
    """me01-112 Bewear atk1 — Hyper Lariat: 100 + 100 if 2 flips both heads."""
    flip1 = _random.choice([True, False])
    flip2 = _random.choice([True, False])
    state.emit_event("coin_flip_result", attack="Hyper Lariat",
                     flip1="heads" if flip1 else "tails",
                     flip2="heads" if flip2 else "tails")
    bonus = 100 if (flip1 and flip2) else 0
    _apply_damage(state, action, 100 + bonus)


def _chrono_burst(state, action):
    """me01-095 Dialga atk1 — Chrono Burst: 80 (or 160 if attacker shuffles all energy to deck)."""
    player = state.get_player(action.player_id)
    if player.active and player.active.energy_attached:
        energy_cards_snapshot = list(player.active.energy_attached)
        player.active.energy_attached.clear()
        for ec in energy_cards_snapshot:
            source_card = next((c for c in player.discard
                                if c.instance_id == ec.source_card_id), None)
            if source_card:
                player.discard.remove(source_card)
                source_card.zone = Zone.DECK
                player.deck.append(source_card)
        _shuffle_deck(player)
        state.emit_event("chrono_burst_shuffle", player=action.player_id,
                         count=len(energy_cards_snapshot))
        _apply_damage(state, action, 160)
    else:
        _apply_damage(state, action, 80)


def _cutting_riposte(state, action):
    """me01-085 Crawdaunt atk1 — Cutting Riposte: 130 (conditional cost reduction FLAGGED)."""
    _apply_damage(state, action, 130)


# ── Batch 5: BLK attack handlers ─────────────────────────────────────────────

def _venoshock_30(state, action):
    """sv10.5b-055 Whirlipede atk0 — Venoshock: 30 + 60 if opp's active is Poisoned."""
    opp = state.get_opponent(action.player_id)
    bonus = 60 if (opp.active and StatusCondition.POISONED in opp.active.status_conditions) else 0
    _apply_damage(state, action, 30 + bonus)


def _venoshock_90(state, action):
    """sv10.5b-056 Scolipede atk0 — Venoshock: 90 + 90 if opp's active is Poisoned."""
    opp = state.get_opponent(action.player_id)
    bonus = 90 if (opp.active and StatusCondition.POISONED in opp.active.status_conditions) else 0
    _apply_damage(state, action, 90 + bonus)


def _command_the_grass(state, action):
    """sv10.5b-003 Serperior ex atk0 — Command the Grass: 150 + search up to 3 any cards from deck."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if not player.deck:
        return
    search_count = min(3, len(player.deck))
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Command the Grass: choose up to 3 cards from deck to put in hand",
        cards=player.deck, min_count=0, max_count=search_count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in player.deck[:search_count]]
    grabbed = 0
    for cid in chosen_ids[:search_count]:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
            grabbed += 1
    _shuffle_deck(player)
    state.emit_event("command_the_grass", player=action.player_id, grabbed=grabbed)


def _lively_needles(state, action):
    """sv10.5b-008 Maractus atk0 — Lively Needles: 20 + 100 if Maractus was healed this turn."""
    bonus = 0
    for ev in state.events:
        if (ev.get("type") in ("healed", "heal")
                and ev.get("player") == action.player_id
                and ev.get("turn") == state.turn_number):
            player = state.get_player(action.player_id)
            if player.active and ev.get("card") == player.active.card_name:
                bonus = 100
                break
    _apply_damage(state, action, 20 + bonus)


def _bemusing_aroma(state, action):
    """sv10.5b-007 Lilligant atk0 — Bemusing Aroma: 30 + flip: heads=Paralyzed+Poisoned, tails=self Confused."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    player = state.get_player(action.player_id)
    if _random.choice([True, False]):  # heads
        state.emit_event("coin_flip_result", attack="Bemusing Aroma", result="heads")
        if opp.active:
            opp.active.status_conditions.add(StatusCondition.PARALYZED)
            opp.active.status_conditions.add(StatusCondition.POISONED)
            state.emit_event("bemusing_aroma_hit", player=action.player_id,
                             target=opp.active.card_name)
    else:
        state.emit_event("coin_flip_result", attack="Bemusing Aroma", result="tails")
        if player.active:
            player.active.status_conditions.add(StatusCondition.CONFUSED)
            state.emit_event("bemusing_aroma_self_confused", player=action.player_id,
                             card=player.active.card_name)


def _dangerous_reaction(state, action):
    """sv10.5b-011 Amoonguss atk0 — Dangerous Reaction: 30 + 120 if opp has any Special Condition."""
    opp = state.get_opponent(action.player_id)
    bonus = 0
    if opp.active and opp.active.status_conditions:
        bonus = 120
    _apply_damage(state, action, 30 + bonus)


def _v_force(state, action):
    """sv10.5b-012 Victini atk0 — V-Force: 120, but 0 if player has fewer than 5 Benched Pokémon."""
    player = state.get_player(action.player_id)
    if len(player.bench) < 5:
        state.emit_event("attack_no_damage", attacker="Victini",
                         attack_name="V-Force", reason="bench not full")
        return
    _apply_damage(state, action, 120)


def _smashing_headbutt(state, action):
    """sv10.5b-014 Darmanitan atk1 — Smashing Headbutt: 180 + discard 2 energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        for _ in range(min(2, len(player.active.energy_attached))):
            if player.active.energy_attached:
                player.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", player=action.player_id,
                         card=player.active.card_name, count=2,
                         reason="Smashing Headbutt")


def _round_player_20(state, action):
    """sv10.5b-019 Tympole atk0 — Round: 20 × count of player's own Pokémon with 'Round' attack."""
    player = state.get_player(action.player_id)
    count = sum(1 for p in _in_play(player)
                if card_registry.get(p.card_def_id)
                and any((a.name or "").lower() == "round"
                        for a in (card_registry.get(p.card_def_id).attacks or [])))
    total = 20 * count
    if total <= 0:
        state.emit_event("attack_no_damage", attacker="Tympole", attack_name="Round")
        return
    _apply_damage(state, action, total)


def _round_player_40(state, action):
    """sv10.5b-020 Palpitoad atk0 — Round: 40 × count of player's own Pokémon with 'Round' attack."""
    player = state.get_player(action.player_id)
    count = sum(1 for p in _in_play(player)
                if card_registry.get(p.card_def_id)
                and any((a.name or "").lower() == "round"
                        for a in (card_registry.get(p.card_def_id).attacks or [])))
    total = 40 * count
    if total <= 0:
        state.emit_event("attack_no_damage", attacker="Palpitoad", attack_name="Round")
        return
    _apply_damage(state, action, total)


def _round_player_70(state, action):
    """sv10.5b-021 Seismitoad atk0 — Round: 70 × count of player's own Pokémon with 'Round' attack."""
    player = state.get_player(action.player_id)
    count = sum(1 for p in _in_play(player)
                if card_registry.get(p.card_def_id)
                and any((a.name or "").lower() == "round"
                        for a in (card_registry.get(p.card_def_id).attacks or [])))
    total = 70 * count
    if total <= 0:
        state.emit_event("attack_no_damage", attacker="Seismitoad", attack_name="Round")
        return
    _apply_damage(state, action, total)


def _ancient_seaweed(state, action):
    """sv10.5b-022 Tirtouga atk0 — Ancient Seaweed: 30 × Item cards in opp's discard."""
    opp = state.get_opponent(action.player_id)
    item_count = sum(1 for c in opp.discard
                     if getattr(c, "card_type", "").lower() in ("item", "trainer")
                     and getattr(c, "card_subtype", "").lower() == "item")
    total = 30 * item_count
    if total <= 0:
        state.emit_event("attack_no_damage", attacker="Tirtouga",
                         attack_name="Ancient Seaweed")
        return
    _apply_damage(state, action, total)


def _snotted_up(state, action):
    """sv10.5b-025 Cubchoo atk0 — Snotted Up: 10 + opp's active can't attack next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=opp.active.card_name,
                         attack="Snotted Up")


def _carracosta_big_bite(state, action):
    """sv10.5b-023 Carracosta atk0 — Big Bite: 150 + opp's active can't retreat next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.cant_retreat_next_turn = True
        state.emit_event("multi_turn_lock", card=opp.active.card_name,
                         attack="Big Bite")


def _continuous_headbutt(state, action):
    """sv10.5b-026 Beartic atk0 — Continuous Headbutt: flip until tails, 50 per heads."""
    heads = 0
    while _random.choice([True, False]):
        heads += 1
    state.emit_event("coin_flip_result", attack="Continuous Headbutt", heads=heads)
    if heads > 0:
        _apply_damage(state, action, heads * 50)
    else:
        state.emit_event("attack_no_damage", attacker="Beartic",
                         attack_name="Continuous Headbutt")


def _beartic_sheer_cold(state, action):
    """sv10.5b-026 Beartic atk1 — Sheer Cold: 150 + opp's active can't attack next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.cant_attack_next_turn = True
        state.emit_event("multi_turn_lock", card=opp.active.card_name,
                         attack="Sheer Cold")


def _drag_off(state, action):
    """sv10.5b-027 Cryogonal atk0 — Drag Off: switch 1 opp bench to Active, then 20 damage."""
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_player(opp_id)
    if not opp.bench:
        _apply_damage(state, action, 20)
        return
    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Drag Off: choose 1 of opponent's Benched Pokémon to switch to Active Spot",
        targets=list(opp.bench),
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in opp.bench
                       if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = opp.bench[0]
    from app.engine.effects.abilities import _switch_active_with_bench as _sab
    _sab(opp, target)
    state.emit_event("forced_switch", player=opp_id, new_active=opp.active.card_name)
    _apply_damage(state, action, 20)


def _blizzard_burst(state, action):
    """sv10.5b-028 Kyurem ex atk1 — Blizzard Burst: 130 + 10×opp_prizes_taken to each opp bench."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    prizes_taken = 6 - opp.prizes_remaining
    bench_damage = 10 * prizes_taken
    if bench_damage > 0:
        for target in list(opp.bench):
            _apply_bench_damage(state, opp_id, target, bench_damage)
            if state.phase == Phase.GAME_OVER:
                return


def _charge_thundurus(state, action):
    """sv10.5b-033 Thundurus atk0 — Charge: search deck for 1 Basic {L} Energy, attach to self."""
    from app.engine.effects.abilities import _attach_from_hand_or_discard
    player = state.get_player(action.player_id)
    if not player.active:
        state.emit_event("attack_no_damage", attacker="Thundurus", attack_name="Charge")
        return
    l_energy = [c for c in player.deck
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Lightning" in (c.energy_provides or [])]
    if not l_energy:
        _shuffle_deck(player)
        state.emit_event("attack_no_damage", attacker="Thundurus",
                         attack_name="Charge", reason="no L energy in deck")
        return
    ec = l_energy[0]
    player.deck.remove(ec)
    _attach_from_hand_or_discard(player, player.active, ec)
    _shuffle_deck(player)
    state.emit_event("charge_attach", player=action.player_id,
                     card=player.active.card_name, energy=ec.card_name)
    state.emit_event("attack_no_damage", attacker="Thundurus", attack_name="Charge")


def _disaster_volt(state, action):
    """sv10.5b-033 Thundurus atk1 — Disaster Volt: 110 + discard 1 energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active and player.active.energy_attached:
        player.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", player=action.player_id,
                         card=player.active.card_name, count=1,
                         reason="Disaster Volt")


def _buzz_flip(state, action):
    """sv10.5b-032 Eelektross atk1 — Buzz Flip: 4 flips, 100 per heads."""
    heads = sum(1 for _ in range(4) if _random.choice([True, False]))
    state.emit_event("coin_flip_result", attack="Buzz Flip", heads=heads, flips=4)
    total = heads * 100
    if total > 0:
        _apply_damage(state, action, total)
    else:
        state.emit_event("attack_no_damage", attacker="Eelektross", attack_name="Buzz Flip")


def _rest_munna(state, action):
    """sv10.5b-035 Munna atk0 — Rest: self becomes Asleep + heal 30."""
    player = state.get_player(action.player_id)
    if player.active:
        player.active.status_conditions.add(StatusCondition.ASLEEP)
        heal = min(30, player.active.damage_counters * 10)
        if heal > 0:
            player.active.current_hp = min(player.active.max_hp,
                                           player.active.current_hp + heal)
            player.active.damage_counters = max(0,
                                                player.active.damage_counters - heal // 10)
            state.emit_event("healed", player=action.player_id,
                             card=player.active.card_name, amount=heal)
        state.emit_event("status_applied", player=action.player_id,
                         card=player.active.card_name, status="Asleep",
                         attack="Rest")
    state.emit_event("attack_no_damage", attacker="Munna", attack_name="Rest")


def _dream_calling(state, action):
    """sv10.5b-036 Musharna atk0 — Dream Calling: search deck for any number of Fennel cards, put in hand."""
    player = state.get_player(action.player_id)
    fennel_cards = [c for c in player.deck
                    if "fennel" in c.card_name.lower()]
    for card in fennel_cards:
        player.deck.remove(card)
        card.zone = Zone.HAND
        player.hand.append(card)
    _shuffle_deck(player)
    state.emit_event("dream_calling", player=action.player_id,
                     found=len(fennel_cards))
    state.emit_event("attack_no_damage", attacker="Musharna", attack_name="Dream Calling")


def _sleep_pulse(state, action):
    """sv10.5b-036 Musharna atk1 — Sleep Pulse: 50 + opp's active becomes Asleep."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.ASLEEP)
        state.emit_event("status_applied", player=action.player_id,
                         card=opp.active.card_name, status="Asleep",
                         attack="Sleep Pulse")


def _calm_mind(state, action):
    """sv10.5b-041 Beheeyem atk0 — Calm Mind: heal 40 from self."""
    player = state.get_player(action.player_id)
    if player.active:
        heal = min(40, player.active.damage_counters * 10)
        if heal > 0:
            player.active.current_hp = min(player.active.max_hp,
                                           player.active.current_hp + heal)
            player.active.damage_counters = max(0,
                                                player.active.damage_counters - heal // 10)
            state.emit_event("healed", player=action.player_id,
                             card=player.active.card_name, amount=heal)
    state.emit_event("attack_no_damage", attacker="Beheeyem", attack_name="Calm Mind")


def _beheeyem_psychic(state, action):
    """sv10.5b-041 Beheeyem atk1 — Psychic: 80 + 30 per energy on opp's active."""
    opp = state.get_opponent(action.player_id)
    energy_count = len(opp.active.energy_attached) if opp.active else 0
    _apply_damage(state, action, 80 + energy_count * 30)


def _slight_shift(state, action):
    """sv10.5b-040 Elgyem atk0 — Slight Shift: move 1 energy from opp Pokémon to another opp Pokémon."""
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_player(opp_id)
    all_opp_pokes = ([opp.active] if opp.active else []) + list(opp.bench)
    pokes_with_energy = [p for p in all_opp_pokes if p.energy_attached]
    if not pokes_with_energy or len(all_opp_pokes) < 2:
        state.emit_event("attack_no_damage", attacker="Elgyem",
                         attack_name="Slight Shift", reason="no energy to move")
        return
    source = pokes_with_energy[0]
    energy = source.energy_attached.pop(0)
    targets = [p for p in all_opp_pokes if p.instance_id != source.instance_id]
    dest = targets[0]
    dest.energy_attached.append(energy)
    state.emit_event("energy_moved", player=opp_id,
                     from_card=source.card_name, to_card=dest.card_name)
    state.emit_event("attack_no_damage", attacker="Elgyem", attack_name="Slight Shift")


def _evo_lariat(state, action):
    """sv10.5b-039 Reuniclus atk1 — Evo-Lariat: 40 + 40 per Evolution Pokémon on attacker's side."""
    player = state.get_player(action.player_id)
    evo_count = sum(1 for p in _in_play(player)
                    if card_registry.get(p.card_def_id)
                    and (card_registry.get(p.card_def_id).stage or "").lower()
                    in ("stage 1", "stage 2", "mega", "vmax", "ex evolution"))
    _apply_damage(state, action, 40 + evo_count * 40)


def _golett_best_punch(state, action):
    """sv10.5b-042 Golett atk0 — Best Punch: 60 if heads, 0 if tails."""
    if _random.choice([True, False]):
        state.emit_event("coin_flip_result", attack="Best Punch", result="heads")
        _apply_damage(state, action, 60)
    else:
        state.emit_event("coin_flip_result", attack="Best Punch", result="tails")
        state.emit_event("attack_no_damage", attacker="Golett", attack_name="Best Punch")


def _double_smash(state, action):
    """sv10.5b-043 Golurk atk0 — Double Smash: 2 flips, 80 per heads."""
    heads = sum(1 for _ in range(2) if _random.choice([True, False]))
    state.emit_event("coin_flip_result", attack="Double Smash", heads=heads, flips=2)
    total = heads * 80
    if total > 0:
        _apply_damage(state, action, total)
    else:
        state.emit_event("attack_no_damage", attacker="Golurk", attack_name="Double Smash")


def _echoed_voice(state, action):
    """sv10.5b-044 Meloetta ex atk0 — Echoed Voice: 30 + 80 if used 2 turns ago."""
    bonus = 0
    current_turn = state.turn_number
    for ev in state.events:
        if (ev.get("type") == "attack_start"
                and ev.get("attack_name") == "Echoed Voice"
                and ev.get("player") == action.player_id
                and abs(current_turn - ev.get("turn", 0)) == 2):
            bonus = 80
            break
    _apply_damage(state, action, 30 + bonus)


def _swing_around(state, action):
    """sv10.5b-049 Conkeldurr atk0 — Swing Around: 100 + 2 flips, 50 per heads."""
    flip1 = _random.choice([True, False])
    flip2 = _random.choice([True, False])
    state.emit_event("coin_flip_result", attack="Swing Around",
                     flip1="heads" if flip1 else "tails",
                     flip2="heads" if flip2 else "tails")
    bonus = (50 if flip1 else 0) + (50 if flip2 else 0)
    _apply_damage(state, action, 100 + bonus)


def _hammer_arm(state, action):
    """sv10.5b-048 Gurdurr atk1 — Hammer Arm: 60 + discard top card of opp's deck."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if opp.deck:
        top = opp.deck.pop(0)
        top.zone = Zone.DISCARD
        opp.discard.append(top)
        state.emit_event("deck_discarded", player=opp_id, card=top.card_name,
                         reason="Hammer Arm")


def _piercing_drill(state, action):
    """sv10.5b-046 Excadrill ex atk0 — Piercing Drill: 60 + 60 to 1 opp bench Pokémon with damage."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    damaged_bench = [p for p in opp.bench if p.damage_counters > 0]
    if damaged_bench:
        target = damaged_bench[0]
        _apply_bench_damage(state, opp_id, target, 60)


def _excadrill_rock_tumble(state, action):
    """sv10.5b-046 Excadrill ex atk1 — Rock Tumble: 200, not affected by Resistance."""
    _apply_damage(state, action, 200, bypass_resistance_only=True)


def _shoulder_throw(state, action):
    """sv10.5b-050 Throh atk0 — Shoulder Throw: 120 − 30 per Colorless in opp's active retreat cost."""
    opp = state.get_opponent(action.player_id)
    cdef = card_registry.get(opp.active.card_def_id) if opp.active else None
    retreat_cost = getattr(cdef, "retreat_cost", 0) if cdef else 0
    damage = max(0, 120 - retreat_cost * 30)
    if damage <= 0:
        state.emit_event("attack_no_damage", attacker="Throh",
                         attack_name="Shoulder Throw")
        return
    _apply_damage(state, action, damage)


def _flail_dwebble(state, action):
    """sv10.5b-051 Dwebble atk0 — Flail: 10 × self damage counters."""
    player = state.get_player(action.player_id)
    counters = player.active.damage_counters if player.active else 0
    total = counters * 10
    if total <= 0:
        state.emit_event("attack_no_damage", attacker="Dwebble", attack_name="Flail")
        return
    _apply_damage(state, action, total)


def _stone_edge(state, action):
    """sv10.5b-052 Crustle atk0 — Stone Edge: 80 + 60 if coin heads."""
    bonus = 60 if _random.choice([True, False]) else 0
    state.emit_event("coin_flip_result", attack="Stone Edge",
                     result="heads" if bonus else "tails")
    _apply_damage(state, action, 80 + bonus)


def _abundant_harvest(state, action):
    """sv10.5b-053 Landorus atk0 — Abundant Harvest: attach 1 Basic {F} Energy from discard to self."""
    from app.engine.effects.abilities import _attach_from_hand_or_discard
    player = state.get_player(action.player_id)
    if not player.active:
        state.emit_event("attack_no_damage", attacker="Landorus",
                         attack_name="Abundant Harvest")
        return
    f_energy = [c for c in player.discard
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Fighting" in (c.energy_provides or [])]
    if not f_energy:
        state.emit_event("attack_no_damage", attacker="Landorus",
                         attack_name="Abundant Harvest", reason="no F energy in discard")
        return
    _attach_from_hand_or_discard(player, player.active, f_energy[0])
    state.emit_event("abundant_harvest", player=action.player_id,
                     card=player.active.card_name)
    state.emit_event("attack_no_damage", attacker="Landorus", attack_name="Abundant Harvest")


def _earthquake_landorus(state, action):
    """sv10.5b-053 Landorus atk1 — Earthquake: 110 + 10 to each of attacker's own bench."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    for target in list(player.bench):
        target.current_hp -= 10
        target.damage_counters += 1
        state.emit_event("self_bench_damage", player=action.player_id,
                         card=target.card_name, damage=10)
        check_ko(state, target, action.player_id)
        if state.phase == Phase.GAME_OVER:
            return


def _sandile_tighten_up(state, action):
    """sv10.5b-057 Sandile atk0 — Tighten Up: 10 + opp discards 1 random card from hand."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_player(opp_id)
    if opp.hand:
        card = _random.choice(opp.hand)
        opp.hand.remove(card)
        card.zone = Zone.DISCARD
        opp.discard.append(card)
        state.emit_event("hand_discarded", player=opp_id, card=card.card_name,
                         reason="Tighten Up")


def _krokorok_tighten_up(state, action):
    """sv10.5b-058 Krokorok atk0 — Tighten Up: 40 + opp discards 2 random cards from hand."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_player(opp_id)
    for _ in range(min(2, len(opp.hand))):
        if opp.hand:
            card = _random.choice(opp.hand)
            opp.hand.remove(card)
            card.zone = Zone.DISCARD
            opp.discard.append(card)
            state.emit_event("hand_discarded", player=opp_id, card=card.card_name,
                             reason="Tighten Up")


def _voltage_burst(state, action):
    """sv10.5b-034 Zekrom ex atk1 — Voltage Burst: 130 + 50×opp_prizes_taken + 30 recoil."""
    opp = state.get_opponent(action.player_id)
    prizes_taken = 6 - opp.prizes_remaining
    _apply_damage(state, action, 130 + prizes_taken * 50)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.current_hp -= 30
        player.active.damage_counters += 3
        state.emit_event("recoil_damage", player=action.player_id,
                         card=player.active.card_name, damage=30)
        check_ko(state, player.active, action.player_id)


def _cellular_evolution_noop(state, action):
    """sv10.5b-038 Duosion atk0 — Cellular Evolution: FLAGGED, in-battle evolution from deck."""
    state.emit_event("attack_no_damage", attacker="Duosion",
                     attack_name="Cellular Evolution",
                     reason="complex_flagged")


def _cellular_ascension_noop(state, action):
    """sv10.5b-039 Reuniclus atk0 — Cellular Ascension: FLAGGED, mass in-battle evolution."""
    state.emit_event("attack_no_damage", attacker="Reuniclus",
                     attack_name="Cellular Ascension",
                     reason="complex_flagged")


# ── Batch 6: BLK/WHT/DRI attack handlers ─────────────────────────────────────

def _cursed_slug(state, action):
    """sv10.5b-059 Krookodile atk1 — Cursed Slug: 120+ / +120 if opp has ≤3 cards in hand."""
    opp = state.get_opponent(action.player_id)
    base = 120
    bonus = 120 if len(opp.hand) <= 3 else 0
    _apply_damage(state, action, base + bonus)


def _wild_lances(state, action):
    """sv10.5b-060 Escavalier atk0 — Wild Lances: 90 + 30 recoil."""
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


def _klink_hard_gears(state, action):
    """sv10.5b-061 Klink atk0 — Hard Gears: 10 + take 10 less damage next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.incoming_damage_reduction += 10
        state.emit_event("damage_reduction_set", player=action.player_id,
                         card=player.active.card_name, amount=10)


def _klang_hard_gears(state, action):
    """sv10.5b-062 Klang atk0 — Hard Gears: 50 + take 20 less damage next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.incoming_damage_reduction += 20
        state.emit_event("damage_reduction_set", player=action.player_id,
                         card=player.active.card_name, amount=20)


def _finishing_blow(state, action):
    """sv10.5b-065 Bisharp atk1 — Finishing Blow: 60+ / +60 if opp already has damage counters."""
    opp = state.get_opponent(action.player_id)
    if opp.active and opp.active.damage_counters > 0:
        _apply_damage(state, action, 120)
    else:
        _apply_damage(state, action, 60)


def _righteous_edge(state, action):
    """sv10.5b-066 Cobalion atk0 — Righteous Edge: 20 + discard Special Energy from opp active."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.active:
        return
    _SPECIAL_ENERGY_IDS_RE = {"me02.5-216", "me03-086", "me03-088", "sv05-161",
                               "sv06-167", "sv08-191", "sv10-182", "sv10.5w-086"}
    specials = [a for a in opp.active.energy_attached
                if a.card_def_id in _SPECIAL_ENERGY_IDS_RE]
    if specials:
        opp.active.energy_attached.remove(specials[0])
        state.emit_event("energy_discarded", player=opp_id,
                         card=opp.active.card_name, count=1, reason="Righteous Edge")


def _metal_arms(state, action):
    """sv10.5b-066 Cobalion atk1 — Metal Arms: 80 + 40 more if Pokémon Tool attached."""
    player = state.get_player(action.player_id)
    has_tool_attached = bool(player.active and player.active.tools_attached)
    _apply_damage(state, action, 80 + (40 if has_tool_attached else 0))


def _protect_charge(state, action):
    """sv10.5b-067 Genesect ex atk0 — Protect Charge: 150 + take 30 less damage next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active:
        player.active.incoming_damage_reduction += 30
        state.emit_event("damage_reduction_set", player=action.player_id,
                         card=player.active.card_name, amount=30)


def _gather_strength(state, action):
    """sv10.5b-068 Axew atk0 — Gather Strength: search deck for up to 2 Basic Energy."""
    player = state.get_player(action.player_id)
    basics = [c for c in player.deck
              if c.card_type.lower() == "energy" and c.card_subtype.lower() == "basic"]
    if not basics:
        state.emit_event("gather_strength", player=action.player_id, found=0)
        return
    count = min(2, len(basics))
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Gather Strength: choose up to 2 Basic Energy cards from your deck",
        cards=basics, min_count=0, max_count=count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [c.instance_id for c in basics[:count]])
    added = 0
    for cid in chosen_ids[:count]:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
            added += 1
    _random.shuffle(player.deck)
    state.emit_event("gather_strength", player=action.player_id, found=added)


def _cross_cut(state, action):
    """sv10.5b-070 Haxorus atk0 — Cross-Cut: 80 + 80 more if opp's active is an Evolution."""
    opp = state.get_opponent(action.player_id)
    opp_cdef = card_registry.get(opp.active.card_def_id) if opp.active else None
    is_evolution = opp_cdef and opp_cdef.stage.lower() not in ("basic", "")
    _apply_damage(state, action, 80 + (80 if is_evolution else 0))


def _axe_blast(state, action):
    """sv10.5b-070 Haxorus atk1 — Axe Blast: if opp's Active is Basic, it is Knocked Out."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.active:
        return
    opp_cdef = card_registry.get(opp.active.card_def_id)
    if opp_cdef and opp_cdef.stage.lower() == "basic":
        opp.active.current_hp = 0
        opp.active.damage_counters = opp.active.max_hp // 10
        state.emit_event("instant_ko", card=opp.active.card_name, reason="Axe Blast")
        check_ko(state, opp.active, opp_id)
    else:
        state.emit_event("attack_no_damage", attacker="Haxorus",
                         attack_name="Axe Blast", reason="Opponent's Active is not Basic")


def _scout(state, action):
    """sv10.5b-071 Pidove atk0 — Scout: reveal opponent's hand (no damage)."""
    opp = state.get_opponent(action.player_id)
    state.emit_event("hand_revealed", player=state.opponent_id(action.player_id),
                     cards=[c.card_name for c in opp.hand], attack="Scout")


def _fly_tranquill(state, action):
    """sv10.5b-072 Tranquill atk0 — Fly: flip coin; tails=nothing, heads=40 + prevent damage."""
    if _random.choice([True, False]):  # heads
        _apply_damage(state, action, 40)
        if state.phase == Phase.GAME_OVER:
            return
        player = state.get_player(action.player_id)
        if player.active:
            player.active.prevent_damage_one_turn = True
            state.emit_event("prevent_damage_set", player=action.player_id,
                             card=player.active.card_name)
    else:
        state.emit_event("attack_no_damage", attacker="Tranquill",
                         attack_name="Fly", reason="tails")


def _add_on(state, action):
    """sv10.5b-073 Unfezant atk0 — Add On: draw 4 cards (no damage)."""
    draw_cards(state, action.player_id, 4)
    state.emit_event("draw", player=action.player_id, count=4, reason="Add On")


def _swift_flight(state, action):
    """sv10.5b-073 Unfezant atk1 — Swift Flight: 120 + flip; heads=prevent damage next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):  # heads
        player = state.get_player(action.player_id)
        if player.active:
            player.active.prevent_damage_one_turn = True
            state.emit_event("prevent_damage_set", player=action.player_id,
                             card=player.active.card_name)


def _return_audino(state, action):
    """sv10.5b-074 Audino atk0 — Return: 30 + draw cards until hand has 6."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    needed = max(0, 6 - len(player.hand))
    if needed > 0:
        draw_cards(state, action.player_id, needed)
        state.emit_event("draw", player=action.player_id, count=needed, reason="Return")


def _tail_slap(state, action):
    """sv10.5b-075 Minccino atk0 — Tail Slap: flip 2 coins, 20 damage per heads."""
    heads = sum(1 for _ in range(2) if _random.choice([True, False]))
    total = 20 * heads
    if total > 0:
        _apply_damage(state, action, total)
    else:
        state.emit_event("attack_no_damage", attacker="Minccino",
                         attack_name="Tail Slap", reason="all tails")


def _do_the_wave(state, action):
    """sv10.5b-076 Cinccino atk0 — Do the Wave: 20 + 20 per benched Pokémon."""
    player = state.get_player(action.player_id)
    bench_count = len(player.bench)
    _apply_damage(state, action, 20 + 20 * bench_count)


def _aerial_ace(state, action):
    """sv10.5b-078 Braviary atk0 — Aerial Ace: 40 + flip; heads=+40."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):  # heads
        _apply_damage(state, action, 40)


def _healing_wrapping(state, action):
    """sv10.5w-003 Leavanny atk0 — Healing Wrapping: heal 100 from each of your Basic Pokémon (no damage)."""
    player = state.get_player(action.player_id)
    all_poke = ([player.active] if player.active else []) + list(player.bench)
    healed_any = False
    for poke in all_poke:
        cdef = card_registry.get(poke.card_def_id)
        if cdef and cdef.stage.lower() == "basic" and poke.damage_counters > 0:
            heal = min(100, poke.damage_counters * 10)
            heal_counters = heal // 10
            poke.current_hp = min(poke.max_hp, poke.current_hp + heal)
            poke.damage_counters -= heal_counters
            state.emit_event("heal", player=action.player_id,
                             card=poke.card_name, amount=heal)
            healed_any = True
    if not healed_any:
        state.emit_event("attack_no_damage", attacker="Leavanny",
                         attack_name="Healing Wrapping", reason="no damaged Basic Pokémon")


def _x_scissor(state, action):
    """sv10.5w-003 Leavanny atk1 — X-Scissor: 90 + flip; heads=+40."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):  # heads
        _apply_damage(state, action, 40)


def _absorb(state, action):
    """sv10.5w-004 Cottonee atk0 — Absorb: 10 + heal 10 from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active and player.active.damage_counters > 0:
        heal = min(10, player.active.damage_counters * 10)
        heal_counters = heal // 10
        player.active.current_hp = min(player.active.max_hp, player.active.current_hp + heal)
        player.active.damage_counters -= heal_counters
        state.emit_event("heal", player=action.player_id,
                         card=player.active.card_name, amount=heal)


def _energy_gift_whimsicott(state, action):
    """sv10.5w-005 Whimsicott ex atk0 — Energy Gift: search deck for up to 3 Basic Energy, attach to any Pokémon."""
    from app.engine.state import EnergyAttachment
    player = state.get_player(action.player_id)
    basics = [c for c in player.deck
              if c.card_type.lower() == "energy" and c.card_subtype.lower() == "basic"]
    if not basics:
        state.emit_event("energy_gift", player=action.player_id, found=0)
        return
    count = min(3, len(basics))
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Energy Gift: choose up to 3 Basic Energy cards from your deck",
        cards=basics, min_count=0, max_count=count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [c.instance_id for c in basics[:count]])
    all_poke = ([player.active] if player.active else []) + list(player.bench)
    for cid in chosen_ids[:count]:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if not card or not all_poke:
            continue
        player.deck.remove(card)
        target = all_poke[0]
        provides = [EnergyType.from_str(t) for t in card.energy_provides] if card.energy_provides else [EnergyType.COLORLESS]
        primary = provides[0]
        target.energy_attached.append(
            EnergyAttachment(energy_type=primary, source_card_id=card.instance_id,
                             card_def_id=card.card_def_id, provides=provides)
        )
        state.emit_event("energy_attached", player=action.player_id,
                         card=card.card_name, target=target.card_name,
                         energy_type=primary.value)
    _random.shuffle(player.deck)


def _wondrous_cotton(state, action):
    """sv10.5w-005 Whimsicott ex atk1 — Wondrous Cotton: 50 per Trainer in opp's hand."""
    opp = state.get_opponent(action.player_id)
    trainer_count = sum(1 for c in opp.hand
                        if c.card_type.lower() in ("trainer", "item", "supporter", "stadium", "tool"))
    state.emit_event("hand_revealed", player=state.opponent_id(action.player_id),
                     cards=[c.card_name for c in opp.hand], attack="Wondrous Cotton")
    total = 50 * trainer_count
    if total > 0:
        _apply_damage(state, action, total)
    else:
        state.emit_event("attack_no_damage", attacker="Whimsicott ex",
                         attack_name="Wondrous Cotton", reason="no Trainer cards in opp hand")


def _acid_spray(state, action):
    """sv10.5w-009 Accelgor atk0 — Acid Spray: 50 + flip; heads=discard 1 energy from opp."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):  # heads
        opp = state.get_opponent(action.player_id)
        opp_id = state.opponent_id(action.player_id)
        if opp.active and opp.active.energy_attached:
            opp.active.energy_attached.pop(0)
            state.emit_event("energy_discarded", player=opp_id,
                             card=opp.active.card_name, count=1, reason="Acid Spray")


def _giga_drain(state, action):
    """sv10.5w-010 Virizion atk0 — Giga Drain: 30 + heal same amount dealt from self."""
    dmg_dealt = _apply_damage(state, action, 30)
    if state.phase == Phase.GAME_OVER or dmg_dealt <= 0:
        return
    player = state.get_player(action.player_id)
    if player.active and player.active.damage_counters > 0:
        heal = min(dmg_dealt, player.active.damage_counters * 10)
        heal_counters = heal // 10
        player.active.current_hp = min(player.active.max_hp, player.active.current_hp + heal)
        player.active.damage_counters -= heal_counters
        state.emit_event("heal", player=action.player_id,
                         card=player.active.card_name, amount=heal)


def _brighten_and_burn(state, action):
    """sv10.5w-016 Litwick atk0 — Brighten and Burn: look at top deck card, may discard (no damage)."""
    player = state.get_player(action.player_id)
    if not player.deck:
        state.emit_event("attack_no_damage", attacker="Litwick",
                         attack_name="Brighten and Burn", reason="empty deck")
        return
    top_card = player.deck[-1]
    state.emit_event("top_card_revealed", player=action.player_id,
                     card=top_card.card_name, attack="Brighten and Burn")
    req = ChoiceRequest(
        "choose_options", action.player_id,
        f"Brighten and Burn: Discard {top_card.card_name}?",
        options=["Yes, discard it", "No, leave it"],
    )
    resp = yield req
    choice = (resp.selected_option if resp and hasattr(resp, "selected_option")
               and resp.selected_option else "No, leave it")
    if "yes" in choice.lower() or "discard" in choice.lower():
        player.deck.pop()
        top_card.zone = Zone.DISCARD
        player.discard.append(top_card)
        state.emit_event("card_discarded", player=action.player_id, card=top_card.card_name,
                         reason="Brighten and Burn")


def _lampent_fire_blast(state, action):
    """sv10.5w-017 Lampent atk0 — Fire Blast: 50 + discard 1 energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active and player.active.energy_attached:
        player.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", player=action.player_id,
                         card=player.active.card_name, count=1, reason="Fire Blast")


def _incendiary_pillar(state, action):
    """sv10.5w-018 Chandelure atk0 — Incendiary Pillar: 50 + 100 more if ≥10 Basic Fire in discard."""
    player = state.get_player(action.player_id)
    fire_in_discard = sum(1 for c in player.discard
                          if c.card_type.lower() == "energy"
                          and c.card_subtype.lower() == "basic"
                          and "Fire" in (c.energy_provides or []))
    bonus = 100 if fire_in_discard >= 10 else 0
    _apply_damage(state, action, 50 + bonus)


def _burn_it_all_up(state, action):
    """sv10.5w-018 Chandelure atk1 — Burn It All Up: 180 + discard all energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active and player.active.energy_attached:
        count = len(player.active.energy_attached)
        player.active.energy_attached.clear()
        state.emit_event("energy_discarded", player=action.player_id,
                         card=player.active.card_name, count=count, reason="Burn It All Up")


def _licking_catch(state, action):
    """sv10.5w-019 Heatmor atk0 — Licking Catch: search deck for up to 3 Fire Pokémon or Basic Fire Energy (no damage)."""
    player = state.get_player(action.player_id)
    candidates = [c for c in player.deck
                  if (c.card_type.lower() in ("pokémon", "pokemon")
                      and "Fire" in (card_registry.get(c.card_def_id).types or [] if card_registry.get(c.card_def_id) else []))
                  or (c.card_type.lower() == "energy"
                      and c.card_subtype.lower() == "basic"
                      and "Fire" in (c.energy_provides or []))]
    if not candidates:
        state.emit_event("licking_catch", player=action.player_id, found=0)
        return
    count = min(3, len(candidates))
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Licking Catch: choose up to 3 Fire Pokémon or Basic Fire Energy from your deck",
        cards=candidates, min_count=0, max_count=count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [c.instance_id for c in candidates[:count]])
    added = 0
    for cid in chosen_ids[:count]:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
            added += 1
    _random.shuffle(player.deck)
    state.emit_event("licking_catch", player=action.player_id, found=added)


def _blazing_burst(state, action):
    """sv10.5w-020 Reshiram ex atk1 — Blazing Burst: 130 + 50 per opp prize taken + discard 1 energy."""
    opp = state.get_opponent(action.player_id)
    prizes_taken = 6 - opp.prizes_remaining
    _apply_damage(state, action, 130 + 50 * prizes_taken)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active and player.active.energy_attached:
        player.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", player=action.player_id,
                         card=player.active.card_name, count=1, reason="Blazing Burst")


def _energized_shell(state, action):
    """sv10.5w-022 Dewott atk0 — Energized Shell: 30 per energy attached to self."""
    player = state.get_player(action.player_id)
    energy_count = len(player.active.energy_attached) if player.active else 0
    total = 30 * energy_count
    if total > 0:
        _apply_damage(state, action, total)
    else:
        state.emit_event("attack_no_damage", attacker="Dewott",
                         attack_name="Energized Shell", reason="no energy attached")


def _energized_slash(state, action):
    """sv10.5w-023 Samurott atk0 — Energized Slash: 30 + 50 per energy attached to self."""
    player = state.get_player(action.player_id)
    energy_count = len(player.active.energy_attached) if player.active else 0
    _apply_damage(state, action, 30 + 50 * energy_count)


def _bared_fangs(state, action):
    """sv10.5w-024 Basculin atk1 — Bared Fangs: 50, but does nothing if opp has no damage counters."""
    opp = state.get_opponent(action.player_id)
    if not opp.active or opp.active.damage_counters == 0:
        state.emit_event("attack_no_damage", attacker="Basculin",
                         attack_name="Bared Fangs", reason="opp has no damage counters")
        return
    _do_default_damage(state, action)


def _ducklett_firefighting(state, action):
    """sv10.5w-025 Ducklett atk0 — Firefighting: discard a Fire Energy from opp's Active (no damage)."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.active:
        return
    fire_att = next((a for a in opp.active.energy_attached
                     if a.energy_type == EnergyType.FIRE), None)
    if fire_att:
        opp.active.energy_attached.remove(fire_att)
        state.emit_event("energy_discarded", player=opp_id,
                         card=opp.active.card_name, count=1, reason="Firefighting")
    else:
        state.emit_event("attack_no_damage", attacker="Ducklett",
                         attack_name="Firefighting", reason="no Fire Energy on opp active")


def _swanna_air_slash(state, action):
    """sv10.5w-026 Swanna atk1 — Air Slash: 120 + discard 1 energy from self."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if player.active and player.active.energy_attached:
        player.active.energy_attached.pop(0)
        state.emit_event("energy_discarded", player=action.player_id,
                         card=player.active.card_name, count=1, reason="Air Slash")


def _ice_edge(state, action):
    """sv10.5w-027 Vanillite / sv10.5w-039 Yamask — Ice Edge / Focused Wish: base + flip heads +20."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):  # heads
        _apply_damage(state, action, 20)


def _ice_beam_vanillish(state, action):
    """sv10.5w-028 Vanillish atk1 — Ice Beam: base + flip; heads=Paralyzed."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):  # heads
        opp = state.get_opponent(action.player_id)
        if opp.active:
            opp.active.status_conditions.add(StatusCondition.PARALYZED)
            state.emit_event("status_applied", card=opp.active.card_name,
                             status="paralyzed", attack="Ice Beam")


def _double_freeze(state, action):
    """sv10.5w-029 Vanilluxe atk1 — Double Freeze: flip 2 coins; 90 per heads; any heads=Paralyzed."""
    heads = sum(1 for _ in range(2) if _random.choice([True, False]))
    total = 90 * heads
    if total > 0:
        _apply_damage(state, action, total)
        opp = state.get_opponent(action.player_id)
        if opp.active:
            opp.active.status_conditions.add(StatusCondition.PARALYZED)
            state.emit_event("status_applied", card=opp.active.card_name,
                             status="paralyzed", attack="Double Freeze")
    else:
        state.emit_event("attack_no_damage", attacker="Vanilluxe",
                         attack_name="Double Freeze", reason="all tails")


def _keldeo_gale_thrust(state, action):
    """sv10.5w-030 Keldeo ex atk0 — Gale Thrust: 30 + 90 if moved from bench this turn."""
    player = state.get_player(action.player_id)
    bonus = 90 if (player.active and player.active.moved_from_bench_this_turn) else 0
    _apply_damage(state, action, 30 + bonus)


def _sonic_edge(state, action):
    """sv10.5w-030 Keldeo ex atk1 — Sonic Edge: 120, not affected by opp's effects."""
    _apply_damage(state, action, 120, bypass_defender_effects=True)


def _zebstrika_electrobullet(state, action):
    """sv10.5w-032 Zebstrika atk1 — Electrobullet: 100 + 30 to random benched opp Pokémon."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if opp.bench:
        target = _random.choice(opp.bench)
        _apply_bench_damage(state, opp_id, target, 30)


def _joltik_surprise(state, action):
    """sv10.5w-033 Joltik atk0 — Surprise Attack: flip coin; tails=nothing, heads=30."""
    if _random.choice([True, False]):  # heads
        _do_default_damage(state, action)
    else:
        state.emit_event("attack_no_damage", attacker="Joltik",
                         attack_name="Surprise Attack", reason="tails")


def _galvantula_discharge(state, action):
    """sv10.5w-034 Galvantula atk0 — Discharge: discard all Lightning energy; 50 per discarded."""
    player = state.get_player(action.player_id)
    if not player.active:
        return
    lightning = [a for a in player.active.energy_attached
                 if a.energy_type == EnergyType.LIGHTNING]
    count = len(lightning)
    for att in lightning:
        player.active.energy_attached.remove(att)
    if count > 0:
        state.emit_event("energy_discarded", player=action.player_id,
                         card=player.active.card_name, count=count, reason="Discharge")
        _apply_damage(state, action, 50 * count)
    else:
        state.emit_event("attack_no_damage", attacker="Galvantula",
                         attack_name="Discharge", reason="no Lightning energy")


def _stunfisk_muddy_bolt(state, action):
    """sv10.5w-035 Stunfisk atk0 — Muddy Bolt: 20 + 20 more if has Fighting energy."""
    player = state.get_player(action.player_id)
    has_fighting = (player.active and any(a.energy_type == EnergyType.FIGHTING
                                          for a in player.active.energy_attached))
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if has_fighting:
        _apply_damage(state, action, 20)


def _swoobat_happy_return(state, action):
    """sv10.5w-037 Swoobat atk0 — Happy Return: put 1 Benched Pokémon + attached into hand (no damage)."""
    player = state.get_player(action.player_id)
    if not player.bench:
        state.emit_event("attack_no_damage", attacker="Swoobat",
                         attack_name="Happy Return", reason="no benched Pokémon")
        return
    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Happy Return: choose a Benched Pokémon to put into your hand",
        targets=list(player.bench),
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in player.bench
                       if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = player.bench[0]
    player.bench.remove(target)
    target.energy_attached.clear()
    target.tools_attached.clear()
    target.zone = Zone.HAND
    player.hand.append(target)
    state.emit_event("pokemon_bounced", player=action.player_id, card=target.card_name,
                     reason="Happy Return")


def _sigilyph_reflect(state, action):
    """sv10.5w-038 Sigilyph atk0 — Reflect: take 40 less damage next turn (no attack damage)."""
    player = state.get_player(action.player_id)
    if player.active:
        player.active.incoming_damage_reduction += 40
        state.emit_event("damage_reduction_set", player=action.player_id,
                         card=player.active.card_name, amount=40)
    state.emit_event("attack_no_damage", attacker="Sigilyph",
                     attack_name="Reflect", reason="defensive setup")


def _sigilyph_telekinesis(state, action):
    """sv10.5w-038 Sigilyph atk1 — Telekinesis: 70 to 1 opp Pokémon, not affected by W/R (no damage)."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.active:
        return
    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Telekinesis: choose 1 of your opponent's Pokémon to deal 70 damage to",
        targets=all_opp,
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in all_opp
                       if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = opp.active
    if target == opp.active:
        _apply_damage(state, action, 70, bypass_wr=True)
    else:
        _apply_bench_damage(state, opp_id, target, 70)


def _cofagrigus_extended_damagriiigus(state, action):
    """sv10.5w-040 Cofagrigus atk0 — Extended Damagriiigus: move all damage counters from 1 benched to 1 opp Pokémon."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    damaged_bench = [p for p in player.bench if p.damage_counters > 0]
    if not damaged_bench or not opp.active:
        state.emit_event("attack_no_damage", attacker="Cofagrigus",
                         attack_name="Extended Damagriiigus",
                         reason="no damaged bench or no opp active")
        return
    req = ChoiceRequest(
        "choose_target", action.player_id,
        "Extended Damagriiigus: choose 1 of your Benched Pokémon to move damage counters from",
        targets=damaged_bench,
    )
    resp = yield req
    source = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        source = next((p for p in damaged_bench
                       if p.instance_id == resp.target_instance_id), None)
    if source is None:
        source = damaged_bench[0]
    counters = source.damage_counters
    source.damage_counters = 0
    source.current_hp = source.max_hp
    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    req2 = ChoiceRequest(
        "choose_target", action.player_id,
        "Extended Damagriiigus: choose 1 of your opponent's Pokémon to move damage counters to",
        targets=all_opp,
    )
    resp2 = yield req2
    dest = None
    if resp2 and hasattr(resp2, "target_instance_id") and resp2.target_instance_id:
        dest = next((p for p in all_opp
                     if p.instance_id == resp2.target_instance_id), None)
    if dest is None:
        dest = opp.active
    dest.damage_counters += counters
    dest.current_hp -= counters * 10
    state.emit_event("damage_counters_moved", player=action.player_id,
                     source=source.card_name, dest=dest.card_name, counters=counters)
    check_ko(state, dest, opp_id)


def _cofagrigus_perplex(state, action):
    """sv10.5w-040 Cofagrigus atk1 — Perplex: 60 + Confused."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.CONFUSED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="confused", attack="Perplex")


def _gothorita_fortunate_eye(state, action):
    """sv10.5w-042 Gothorita atk0 — Fortunate Eye: look at top 5 of opp's deck (no damage)."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    top5 = opp.deck[-5:] if len(opp.deck) >= 5 else list(opp.deck)
    state.emit_event("deck_peeked", player=opp_id, cards=[c.card_name for c in top5],
                     count=len(top5), attack="Fortunate Eye")


def _synchro_shot(state, action):
    """sv10.5w-043 Gothitelle atk0 — Synchro Shot: 90 + 90 if hand sizes equal."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    bonus = 90 if len(player.hand) == len(opp.hand) else 0
    _apply_damage(state, action, 90 + bonus)


def _oceanic_gloom(state, action):
    """sv10.5w-044 Frillish atk0 — Oceanic Gloom: 20 + opp can't play Items next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp_id = state.opponent_id(action.player_id)
    opp_player = state.get_player(opp_id)
    opp_player.items_locked_this_turn = True
    state.emit_event("items_locked", player=opp_id, reason="Oceanic Gloom")


def _power_press(state, action):
    """sv10.5w-045 Jellicent ex atk0 — Power Press: 80 + 120 more if has ≥2 extra energy (cost 2, so ≥4 total)."""
    player = state.get_player(action.player_id)
    energy_count = len(player.active.energy_attached) if player.active else 0
    bonus = 120 if energy_count >= 4 else 0
    _apply_damage(state, action, 80 + bonus)


def _roggenrola_harden(state, action):
    """sv10.5w-046 Roggenrola atk0 — Harden: prevent all damage ≤30 from attacks next turn (no attack damage)."""
    player = state.get_player(action.player_id)
    if player.active:
        player.active.incoming_damage_reduction += 30
        state.emit_event("damage_reduction_set", player=action.player_id,
                         card=player.active.card_name, amount=30)
    state.emit_event("attack_no_damage", attacker="Roggenrola",
                     attack_name="Harden", reason="defensive setup")


def _boldore_smack_down(state, action):
    """sv10.5w-047 Boldore atk0 — Smack Down: 30 + 50 if opp's active has Fighting Resistance."""
    opp = state.get_opponent(action.player_id)
    opp_cdef = card_registry.get(opp.active.card_def_id) if opp.active else None
    has_f_resist = (opp_cdef and any(r.type.lower() == "fighting"
                                     for r in opp_cdef.resistances))
    _apply_damage(state, action, 30 + (50 if has_f_resist else 0))


def _gigalith_vengeful_cannon(state, action):
    """sv10.5w-048 Gigalith atk0 — Vengeful Cannon: 20 per damage counter on benched Fighting Pokémon."""
    player = state.get_player(action.player_id)
    total_counters = 0
    for poke in player.bench:
        cdef = card_registry.get(poke.card_def_id)
        if cdef and "Fighting" in (cdef.types or []):
            total_counters += poke.damage_counters
    total = 20 * total_counters
    if total > 0:
        _apply_damage(state, action, total)
    else:
        state.emit_event("attack_no_damage", attacker="Gigalith",
                         attack_name="Vengeful Cannon", reason="no damage counters on benched Fighting Pokémon")


def _sawk_rising_chop(state, action):
    """sv10.5w-049 Sawk atk1 — Rising Chop: 90 if opp is ex; bypass W/R. Does nothing if not ex."""
    opp = state.get_opponent(action.player_id)
    opp_cdef = card_registry.get(opp.active.card_def_id) if opp.active else None
    if not opp_cdef or not opp_cdef.is_ex:
        state.emit_event("attack_no_damage", attacker="Sawk",
                         attack_name="Rising Chop", reason="opp active is not a Pokémon ex")
        return
    _apply_damage(state, action, 90, bypass_wr=True)


def _archen_acrobatics(state, action):
    """sv10.5w-050 Archen atk0 — Acrobatics: 30 + flip 2 coins, +30 per heads."""
    heads = sum(1 for _ in range(2) if _random.choice([True, False]))
    _apply_damage(state, action, 30 + 30 * heads)


def _mienshao_smash_uppercut(state, action):
    """sv10.5w-053 Mienshao atk1 — Smash Uppercut: 80, not affected by Resistance."""
    _apply_damage(state, action, 80, bypass_resistance_only=True)


def _purrloin_invite_evil(state, action):
    """sv10.5w-055 Purrloin atk0 — Invite Evil: search deck for up to 3 Dark Pokémon (no damage)."""
    player = state.get_player(action.player_id)
    dark_poke = [c for c in player.deck
                 if c.card_type.lower() in ("pokémon", "pokemon")
                 and card_registry.get(c.card_def_id) is not None
                 and "Darkness" in (card_registry.get(c.card_def_id).types or [])]
    if not dark_poke:
        state.emit_event("invite_evil", player=action.player_id, found=0)
        return
    count = min(3, len(dark_poke))
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Invite Evil: choose up to 3 Darkness Pokémon from your deck",
        cards=dark_poke, min_count=0, max_count=count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [c.instance_id for c in dark_poke[:count]])
    added = 0
    for cid in chosen_ids[:count]:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
            added += 1
    _random.shuffle(player.deck)
    state.emit_event("invite_evil", player=action.player_id, found=added)


def _liepard_knock_off(state, action):
    """sv10.5w-056 Liepard atk0 — Knock Off: 50 + discard random card from opp hand."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if opp.hand:
        card = _random.choice(opp.hand)
        opp.hand.remove(card)
        card.zone = Zone.DISCARD
        opp.discard.append(card)
        state.emit_event("knock_off", player=action.player_id, discarded=card.card_name)


def _scrafty_ruffians(state, action):
    """sv10.5w-058 Scrafty atk0 — Ruffians Attack: flip per Dark Pokémon in play; 60 per heads."""
    player = state.get_player(action.player_id)
    all_poke = ([player.active] if player.active else []) + list(player.bench)
    dark_count = sum(1 for p in all_poke
                     if card_registry.get(p.card_def_id)
                     and "Darkness" in (card_registry.get(p.card_def_id).types or []))
    heads = sum(1 for _ in range(dark_count) if _random.choice([True, False]))
    total = 60 * heads
    if total > 0:
        _apply_damage(state, action, total)
    else:
        state.emit_event("attack_no_damage", attacker="Scrafty",
                         attack_name="Ruffians Attack", reason="all tails")


def _gunk_shot(state, action):
    """sv10.5w-060 Garbodor atk1 — Gunk Shot: 120 + Poisoned."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.POISONED)
        state.emit_event("status_applied", card=opp.active.card_name,
                         status="poisoned", attack="Gunk Shot")


def _zorua_take_down(state, action):
    """sv10.5w-061 Zorua atk0 — Take Down: 30 + 10 recoil."""
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


def _zoroark_mind_jack(state, action):
    """sv10.5w-062 Zoroark atk0 — Mind Jack: 30 per opp benched Pokémon."""
    opp = state.get_opponent(action.player_id)
    bench_count = len(opp.bench)
    total = 30 * bench_count
    if total > 0:
        _apply_damage(state, action, total)
    else:
        state.emit_event("attack_no_damage", attacker="Zoroark",
                         attack_name="Mind Jack", reason="no opp benched Pokémon")


async def _zoroark_foul_play(state, action):
    """sv10.5w-062 Zoroark atk1 — Foul Play: use opp active's highest-damage attack."""
    from app.engine.effects.registry import EffectRegistry

    opp = state.get_opponent(action.player_id)
    if opp.active is None:
        state.emit_event("copy_attack_no_target", card="Zoroark", attack="Foul Play",
                         reason="Opponent has no Active Pokémon")
        return

    opp_cdef = card_registry.get(opp.active.card_def_id)
    if opp_cdef is None:
        state.emit_event("copy_attack_no_target", card="Zoroark", attack="Foul Play",
                         reason="No card definition for opp active")
        return

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
        state.emit_event("copy_attack_no_target", card="Zoroark", attack="Foul Play",
                         reason=f"{opp.active.card_name} has no copyable attacks")
        return

    atk_name = opp_cdef.attacks[best_atk_idx].name
    state.emit_event("copy_attack", card="Zoroark", attack="Foul Play",
                     source_card=opp.active.card_name, copied_attack=atk_name)
    await EffectRegistry.instance().resolve_attack(
        opp.active.card_def_id, best_atk_idx, state, action
    )


def _body_slam_deino(state, action):
    """sv10.5w-065 Deino atk0 — Body Slam: 20 + flip; heads=Paralyzed."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):  # heads
        opp = state.get_opponent(action.player_id)
        if opp.active:
            opp.active.status_conditions.add(StatusCondition.PARALYZED)
            state.emit_event("status_applied", card=opp.active.card_name,
                             status="paralyzed", attack="Body Slam")


def _double_hit_zweilous(state, action):
    """sv10.5w-066 Zweilous atk0 — Double Hit: flip 2 coins; 40 per heads."""
    heads = sum(1 for _ in range(2) if _random.choice([True, False]))
    total = 40 * heads
    if total > 0:
        _apply_damage(state, action, total)
    else:
        state.emit_event("attack_no_damage", attacker="Zweilous",
                         attack_name="Double Hit", reason="all tails")


def _hydreigon_dark_bite(state, action):
    """sv10.5w-067 Hydreigon ex atk0 — Dark Bite: 200 + opp can't retreat next turn."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.cant_retreat_next_turn = True
        state.emit_event("cant_retreat", card=opp.active.card_name, attack="Dark Bite")


def _ferrothorn_power_whip(state, action):
    """sv10.5w-069 Ferrothorn atk0 — Power Whip: choose 1 opp Pokémon; 20 per energy on self."""
    player = state.get_player(action.player_id)
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    energy_count = len(player.active.energy_attached) if player.active else 0
    damage = 20 * energy_count
    if damage <= 0 or not opp.active:
        state.emit_event("attack_no_damage", attacker="Ferrothorn",
                         attack_name="Power Whip", reason="no energy or no opp active")
        return
    all_opp = ([opp.active] if opp.active else []) + list(opp.bench)
    req = ChoiceRequest(
        "choose_target", action.player_id,
        f"Power Whip: choose 1 of your opponent's Pokémon to deal {damage} damage to",
        targets=all_opp,
    )
    resp = yield req
    target = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        target = next((p for p in all_opp
                       if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = opp.active
    if target == opp.active:
        _apply_damage(state, action, damage)
    else:
        _apply_bench_damage(state, opp_id, target, damage)


def _durant_bite_together(state, action):
    """sv10.5w-070 Durant atk0 — Bite Together: 20 + 20 if Durant is on bench."""
    player = state.get_player(action.player_id)
    has_durant_bench = any(card_registry.get(p.card_def_id)
                           and card_registry.get(p.card_def_id).name == "Durant"
                           for p in player.bench)
    _apply_damage(state, action, 20 + (20 if has_durant_bench else 0))


def _druddigon_shred(state, action):
    """sv10.5w-071 Druddigon atk0 — Shred: 40, not affected by opp's effects."""
    _apply_damage(state, action, 40, bypass_defender_effects=True)


def _druddigon_ambush(state, action):
    """sv10.5w-071 Druddigon atk1 — Ambush: 90 + flip; heads=+60."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):  # heads
        _apply_damage(state, action, 60)


def _patrat_procurement(state, action):
    """sv10.5w-072 Patrat atk0 — Procurement: search deck for 1 Item card, put in hand (no damage)."""
    player = state.get_player(action.player_id)
    items = [c for c in player.deck
             if c.card_type.lower() in ("trainer",) and c.card_subtype.lower() == "item"]
    if not items:
        state.emit_event("procurement", player=action.player_id, found=0)
        return
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Procurement: choose 1 Item card from your deck",
        cards=items, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [items[0].instance_id])
    for cid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    _random.shuffle(player.deck)
    state.emit_event("procurement", player=action.player_id, found=len(chosen_ids[:1]))


def _watchog_hyper_fang(state, action):
    """sv10.5w-073 Watchog atk1 — Hyper Fang: flip; tails=nothing, heads=80."""
    if _random.choice([True, False]):  # heads
        _do_default_damage(state, action)
    else:
        state.emit_event("attack_no_damage", attacker="Watchog",
                         attack_name="Hyper Fang", reason="tails")


def _lillipup_play_rough(state, action):
    """sv10.5w-074 Lillipup atk0 — Play Rough: 10 + flip; heads=+20."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    if _random.choice([True, False]):  # heads
        _apply_damage(state, action, 20)


def _force_switch_no_damage(state, action):
    """sv10.5w-075 Herdier / sv10-002 Yanma — Roar/Whirlwind: switch opp active to bench (no damage)."""
    opp = state.get_opponent(action.player_id)
    opp_id = state.opponent_id(action.player_id)
    if not opp.bench:
        state.emit_event("attack_no_damage", attacker=state.get_player(action.player_id).active.card_name
                         if state.get_player(action.player_id).active else "?",
                         attack_name="Roar", reason="no opp bench")
        return
    old_active = opp.active
    opp.active = None
    if old_active:
        old_active.zone = Zone.BENCH
        opp.bench.append(old_active)
    req = ChoiceRequest(
        "choose_target", opp_id,
        "Roar: choose your new Active Pokémon from the Bench",
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
        state.emit_event("forced_switch", player=opp_id, new_active=opp.active.card_name)


def _stoutland_odor_sleuth(state, action):
    """sv10.5w-076 Stoutland atk0 — Odor Sleuth: flip 3 coins; put up to that many cards from discard to hand."""
    player = state.get_player(action.player_id)
    heads = sum(1 for _ in range(3) if _random.choice([True, False]))
    if heads == 0 or not player.discard:
        state.emit_event("odor_sleuth", player=action.player_id, retrieved=0)
        return
    count = min(heads, len(player.discard))
    retrieved = 0
    for _ in range(count):
        if player.discard:
            card = _random.choice(player.discard)
            player.discard.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
            retrieved += 1
    state.emit_event("odor_sleuth", player=action.player_id, retrieved=retrieved)


def _stoutland_special_fang(state, action):
    """sv10.5w-076 Stoutland atk1 — Special Fang: 100 + 100 if has Special Energy."""
    _SPECIAL_ENERGY_IDS_SF = {"me02.5-216", "me03-086", "me03-088", "sv05-161",
                               "sv06-167", "sv08-191", "sv10-182", "sv10.5w-086"}
    player = state.get_player(action.player_id)
    has_special = (player.active and any(a.card_def_id in _SPECIAL_ENERGY_IDS_SF
                                         for a in player.active.energy_attached))
    _apply_damage(state, action, 100 + (100 if has_special else 0))


def _bouffalant_gold_breaker(state, action):
    """sv10.5w-077 Bouffalant ex atk0 — Gold Breaker: 100 + 100 if opp is a Pokémon ex."""
    opp = state.get_opponent(action.player_id)
    opp_cdef = card_registry.get(opp.active.card_def_id) if opp.active else None
    bonus = 100 if (opp_cdef and opp_cdef.is_ex) else 0
    _apply_damage(state, action, 100 + bonus)


def _tornadus_wrapped_in_wind(state, action):
    """sv10.5w-078 Tornadus atk0 — Wrapped in Wind: attach 1 Basic Energy from hand to self (no damage)."""
    from app.engine.state import EnergyAttachment
    player = state.get_player(action.player_id)
    if not player.active:
        return
    basic_energy = [c for c in player.hand
                    if c.card_type.lower() == "energy" and c.card_subtype.lower() == "basic"]
    if not basic_energy:
        state.emit_event("attack_no_damage", attacker="Tornadus",
                         attack_name="Wrapped in Wind", reason="no Basic Energy in hand")
        return
    req = ChoiceRequest(
        "choose_cards", action.player_id,
        "Wrapped in Wind: choose 1 Basic Energy from your hand to attach to Tornadus",
        cards=basic_energy, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [basic_energy[0].instance_id])
    for cid in chosen_ids[:1]:
        card = next((c for c in player.hand if c.instance_id == cid), None)
        if card:
            player.hand.remove(card)
            provides = [EnergyType.from_str(t) for t in card.energy_provides] if card.energy_provides else [EnergyType.COLORLESS]
            primary = provides[0]
            player.active.energy_attached.append(
                EnergyAttachment(energy_type=primary, source_card_id=card.instance_id,
                                 card_def_id=card.card_def_id, provides=provides)
            )
            state.emit_event("energy_attached", player=action.player_id,
                             card=card.card_name, target=player.active.card_name,
                             energy_type=primary.value)


def _tornadus_hurricane(state, action):
    """sv10.5w-078 Tornadus atk1 — Hurricane: 100 + move 1 Basic Energy from self to bench Pokémon."""
    _do_default_damage(state, action)
    if state.phase == Phase.GAME_OVER:
        return
    player = state.get_player(action.player_id)
    if not player.active or not player.bench:
        return
    basic_energy = [a for a in player.active.energy_attached
                    if a.energy_type != EnergyType.COLORLESS]
    if not basic_energy:
        return
    att = basic_energy[0]
    player.active.energy_attached.remove(att)
    target = player.bench[0]
    target.energy_attached.append(att)
    state.emit_event("energy_moved", player=action.player_id,
                     from_card=player.active.card_name, to_card=target.card_name,
                     energy_type=att.energy_type.value)


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
    registry.register_attack("me02.5-114", 0, _big_bite)
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

    # ── Batch 3: me02.5-134+ and me02 (PFL) ──────────────────────────────────

    # me02.5-134 Scraggy
    registry.register_attack("me02.5-134", 0, _knock_off)

    # me02.5-135 Mega Scrafty ex
    registry.register_attack("me02.5-135", 0, _outlaw_leg)

    # me02-029 Rotom ex — Thunderbolt
    registry.register_attack("me02-029", 0, _thunderbolt_rotom)

    # me02.5-137 N's Zoroark ex — Night Joker
    registry.register_attack("me02.5-137", 0, _night_joker)

    # me02.5-139 Mandibuzz ex
    registry.register_attack("me02.5-139", 0, _bone_shot)
    registry.register_attack("me02.5-139", 1, _vulture_claw)

    # me02.5-140 Pangoro
    registry.register_attack("me02.5-140", 1, _masters_punch)

    # me02.5-141 Hoopa
    registry.register_attack("me02.5-141", 0, _filch)
    registry.register_attack("me02.5-141", 1, _knuckle_impact)

    # me02.5-143 Pecharunt
    registry.register_attack("me02.5-143", 0, _mochi_rush)

    # me02.5-144 Mawile — Call for Family
    registry.register_attack("me02.5-144", 0, _call_for_family)

    # me02.5-145 Registeel ex
    registry.register_attack("me02.5-145", 0, _regi_charge_m)
    registry.register_attack("me02.5-145", 1, _protecting_steel)

    # me02.5-146 Pawniard — Push Down
    registry.register_attack("me02.5-146", 0, _push_down)

    # me02.5-147 Bisharp
    registry.register_attack("me02.5-147", 0, _rapid_draw)

    # me02.5-148 Kingambit
    registry.register_attack("me02.5-148", 0, _double_edged_slash)

    # me02.5-149 Togedemaru ex
    registry.register_attack("me02.5-149", 0, _stun_needle)
    registry.register_attack("me02.5-149", 1, _spiky_rolling)

    # me02.5-152 Mega Dragonite ex
    registry.register_attack("me02.5-152", 0, _ryuno_glide)

    # me02.5-153 Rayquaza
    registry.register_attack("me02.5-153", 0, _breakthrough_assault)

    # me02.5-154 N's Reshiram
    registry.register_attack("me02.5-154", 0, _powerful_rage_reshiram)

    # me02.5-156 Noibat
    registry.register_attack("me02.5-156", 0, _knickknack_carrying)

    # me02.5-157 Noivern
    registry.register_attack("me02.5-157", 0, _agility_noivern)
    registry.register_attack("me02.5-157", 1, _enhanced_blade)

    # me02.5-161 Team Rocket's Meowth
    registry.register_attack("me02.5-161", 0, _pawcket_pilfer)
    registry.register_attack("me02.5-161", 1, _fury_swipes)

    # me02.5-162 Team Rocket's Kangaskhan ex
    registry.register_attack("me02.5-162", 0, _comet_punch)
    registry.register_attack("me02.5-162", 1, _wicked_impact)

    # me02.5-163 Larry's Dunsparce
    registry.register_attack("me02.5-163", 0, _rising_lunge)

    # me02.5-164 Larry's Dudunsparce ex
    registry.register_attack("me02.5-164", 0, _work_rush)

    # me02.5-166 Delcatty
    registry.register_attack("me02.5-166", 1, _energy_crush)

    # me02.5-167 Zangoose ex
    registry.register_attack("me02.5-167", 0, _spike_draw)
    registry.register_attack("me02.5-167", 1, _wild_scissors)

    # me02.5-168 Larry's Starly
    registry.register_attack("me02.5-168", 0, _minor_errand_running)

    # me02.5-170 Larry's Staraptor
    registry.register_attack("me02.5-170", 0, _facade)
    registry.register_attack("me02.5-170", 1, _feathery_strike)

    # me02.5-171 Fan Rotom
    registry.register_attack("me02.5-171", 0, _assault_landing)

    # me02.5-172 Mega Audino ex
    registry.register_attack("me02.5-172", 0, _kaleidowaltz)
    registry.register_attack("me02.5-172", 1, _ear_force)

    # me02.5-173 Larry's Rufflet
    registry.register_attack("me02.5-173", 0, _peck_the_wound)

    # me02.5-174 Larry's Braviary — Clutch (retreat lock)
    registry.register_attack("me02.5-174", 0, _clutch)

    # me02.5-175 Larry's Komala
    registry.register_attack("me02.5-175", 0, _dozing_draw)

    # me02.5-176 Drampa
    registry.register_attack("me02.5-176", 1, _dragon_strike)

    # me02.5-177 Hop's Cramorant
    registry.register_attack("me02.5-177", 0, _fickle_spitting)

    # me02.5-178 Terapagos
    registry.register_attack("me02.5-178", 0, _prism_charge)

    # me02.5-179 Terapagos ex
    registry.register_attack("me02.5-179", 0, _unified_beatdown)
    registry.register_attack("me02.5-179", 1, _crown_opal)

    # me02-2 Gloom
    registry.register_attack("me02-002", 0, _disperse_drool)

    # me02-3 Vileplume
    registry.register_attack("me02-003", 0, _pollen_bomb)
    registry.register_attack("me02-003", 1, _lively_flower)

    # me02-4 Mega Heracross ex
    registry.register_attack("me02-004", 0, _juggernaut_horn)
    registry.register_attack("me02-004", 1, _mountain_ramming)

    # me02-6 Lombre — Mega Drain = _draining_kiss
    registry.register_attack("me02-006", 0, _draining_kiss)

    # me02-8 Genesect
    registry.register_attack("me02-008", 0, _bugs_cannon)

    # me02-9 Nymble
    registry.register_attack("me02-009", 0, _flail_around)

    # me02-10 Lokix
    registry.register_attack("me02-010", 1, _jumping_shot)

    # me02-42 Mimikyu — Call for Family
    registry.register_attack("me02-042", 0, _call_for_family)

    # me02-43 Milcery — Draining Kiss
    registry.register_attack("me02-043", 0, _draining_kiss)

    # me02-49 Gligar — Poison Jab
    registry.register_attack("me02-049", 0, _poison_jab)

    # me02-50 Gliscor — Poison Ring
    registry.register_attack("me02-050", 0, _poison_ring)

    # ── Additional Batch 3 handlers (PFL + ASC) ─────────────────────────────
    registry.register_attack("me02-044", 0, _sweet_circle)         # Alcremie
    registry.register_attack("me02-031", 0, _electric_run)         # Boltund
    registry.register_attack("me02-046", 0, _sneaky_placement)     # Bramblin
    registry.register_attack("me02-020", 0, _infernal_slash)       # Ceruledge
    registry.register_attack("me02-019", 0, _gather_strength)      # Charcadet
    registry.register_attack("me02-039", 0, _swelling_light)       # Cresselia atk0
    registry.register_attack("me02-015", 0, _blaze_ball_darumaka)  # Darumaka
    registry.register_attack("me02-016", 0, _blaze_ball_darmanitan) # Darmanitan
    registry.register_attack("me02-022", 0, _slam_dewgong)         # Dewgong atk0
    registry.register_attack("me02-038", 1, _finishing_blow)       # Granbull atk1
    registry.register_attack("me02-025", 0, _wreck)                # Mamoswine atk0
    registry.register_attack("me02-025", 1, _blizzard_edge)        # Mamoswine atk1
    registry.register_attack("me02-041", 0, _garland_ray)          # Mega Diancie ex atk0
    registry.register_attack("me02-040", 0, _soothing_melody)      # Meloetta atk0
    registry.register_attack("me02-036", 0, _hexa_magic)           # Mismagius ex atk0
    registry.register_attack("me02-048", 0, _raging_charge)        # Paldean Tauros atk0
    registry.register_attack("me02-048", 1, _double_edge_tauros)   # Paldean Tauros atk1
    registry.register_attack("me02-032", 0, _growl_attack)         # Pawmi atk0
    registry.register_attack("me02-034", 0, _voltaic_fist)         # Pawmot atk0
    registry.register_attack("me02-024", 0, _rising_lunge_piloswine) # Piloswine atk0
    registry.register_attack("me02-027", 0, _call_for_support)     # Piplup atk0
    registry.register_attack("me02-028", 1, _targeted_dive)        # Prinplup atk1
    registry.register_attack("me02-017", 1, _burning_flare)        # Reshiram atk1
    registry.register_attack("me02-021", 0, _bubble_drain)         # Seel atk0
    registry.register_attack("me02-026", 0, _crystal_fall)         # Suicune atk0
    registry.register_attack("me02-051", 0, _double_headbutt)      # Trapinch atk0
    registry.register_attack("me02-030", 0, _play_rough)           # Yamper atk0
    registry.register_attack("me02-045", 0, _limit_break)          # Zacian atk0
    registry.register_attack("me02.5-174", 1, _brave_bird)         # Larry's Braviary atk1

    # me02-013 Mega Charizard X ex — Inferno X
    registry.register_attack("me02-013", 0, _inferno_x_charizard)

    # ── Batch 4 Registrations ─────────────────────────────────────────────────

    # PFL Cards
    registry.register_attack("me02-056", 0, _void_gale)                    # Mega Gengar ex — Void Gale
    registry.register_attack("me02-057", 0, _ambush_murkrow)               # Murkrow — Ambush
    registry.register_attack("me02-058", 1, _sniping_feathers)             # Honchkrow — Sniping Feathers
    registry.register_attack("me02-059", 0, _cocky_claw)                   # Sableye — Cocky Claw
    registry.register_attack("me02-060", 0, _take_down)                    # Carvanha — Reckless Charge (recoil)
    registry.register_attack("me02-061", 0, _greedy_fang)                  # Mega Sharpedo ex — Greedy Fang
    registry.register_attack("me02-061", 1, _hungry_jaws)                  # Mega Sharpedo ex — Hungry Jaws
    registry.register_attack("me02-063", 0, _allure)                       # Absol — Allure
    registry.register_attack("me02-066", 0, _vengeful_fang)                # Krookodile — Vengeful Fang
    registry.register_attack("me02-069", 0, _shatter_stadium)              # Eternatus — Shatter
    registry.register_attack("me02-069", 1, _power_rush)                   # Eternatus — Power Rush
    registry.register_attack("me02-070", 0, _iron_feathers)                # Empoleon ex — Iron Feathers
    registry.register_attack("me02-071", 0, _hide)                         # Bronzor — Iron Defense
    registry.register_attack("me02-072", 0, _triple_draw)                  # Bronzong — Triple Draw
    registry.register_attack("me02-072", 1, _tool_drop)                    # Bronzong — Tool Drop
    registry.register_attack("me02-073", 0, _find_a_friend_togedemaru)     # Togedemaru — Find a Friend
    registry.register_attack("me02-074", 0, _hyper_beam_duraludon)         # Duraludon — Hyper Beam
    registry.register_attack("me02-075", 0, _coated_attack)                # Archaludon — Coated Attack
    registry.register_attack("me02-076", 0, _ball_roll)                    # Jigglypuff — Ball Roll
    registry.register_attack("me02-077", 0, _round_wigglytuff)             # Wigglytuff — Round
    registry.register_attack("me02-078", 0, _astonish)                     # Aipom — Astonish
    registry.register_attack("me02-079", 1, _dual_tail)                    # Ambipom — Dual Tail
    registry.register_attack("me02-080", 0, _energizing_sketch)            # Smeargle — Energizing Sketch
    registry.register_attack("me02-081", 0, _surprise_attack)              # Zigzagoon — Surprise Attack
    registry.register_attack("me02-083", 0, _teleportation_attack)         # Buneary — Run Around
    registry.register_attack("me02-084", 0, _gale_thrust)                  # Mega Lopunny ex — Gale Thrust
    registry.register_attack("me02-084", 1, _spiky_hopper)                 # Mega Lopunny ex — Spiky Hopper

    # MEG Cards
    registry.register_attack("me01-001", 0, _bind_down)                    # Bulbasaur — Bind Down
    registry.register_attack("me01-003", 0, _draining_kiss)                # Mega Venusaur ex — Jungle Dump (heal)
    registry.register_attack("me01-004", 0, _jam_packed)                   # Exeggcute — Jam-Packed
    registry.register_attack("me01-005", 0, _guard_press_exeggutor)        # Exeggutor — Guard Press
    registry.register_attack("me01-005", 1, _stomping_wood)                # Exeggutor — Stomping Wood
    registry.register_attack("me01-006", 0, _poison_powder_tangela)        # Tangela — Poison Powder
    registry.register_attack("me01-007", 0, _draining_kiss)                # Tangrowth — Absorb (heal)
    registry.register_attack("me01-007", 1, _pumped_up_whip)               # Tangrowth — Pumped-Up Whip
    registry.register_attack("me01-012", 0, _traverse_time)                # Celebi — Traverse Time
    registry.register_attack("me01-013", 0, _bubble_drain)                 # Seedot — Nap (heal 20)
    registry.register_attack("me01-015", 0, _reversing_gust)               # Shiftry — Reversing Gust
    registry.register_attack("me01-015", 1, _perplex_shiftry)              # Shiftry — Perplex (100 + confused)
    registry.register_attack("me01-017", 0, _teleportation_attack)         # Ninjask — U-turn
    registry.register_attack("me01-018", 0, _earthen_power)                # Dhelmise — Earthen Power
    registry.register_attack("me01-021", 0, _call_for_family)              # Numel — Call for Family
    registry.register_attack("me01-022", 0, _roasting_heat)                # Mega Camerupt ex — Roasting Heat
    registry.register_attack("me01-022", 1, _volcanic_meteor)              # Mega Camerupt ex — Volcanic Meteor
    registry.register_attack("me01-024", 0, _super_singe)                  # Pyroar — Searing Flame
    registry.register_attack("me01-025", 0, _singe_only)                   # Volcanion — Singe
    registry.register_attack("me01-025", 1, _backfire)                     # Volcanion — Backfire
    registry.register_attack("me01-026", 0, _surprise_attack)              # Scorbunny — Wild Kick
    registry.register_attack("me01-027", 0, _jumping_kick_raboot)          # Raboot — Jumping Kick
    registry.register_attack("me01-028", 0, _turbo_flare)                  # Cinderace — Turbo Flare
    registry.register_attack("me01-030", 0, _coiling_crush)                # Centiskorch — Coiling Crush
    registry.register_attack("me01-031", 0, _scorching_earth)              # Chi-Yu — Scorching Earth
    registry.register_attack("me01-032", 0, _call_for_family)              # Mantine — Call for Family
    registry.register_attack("me01-033", 1, _take_down)                    # Corphish — Take Down
    registry.register_attack("me01-034", 0, _riptide)                      # Kyogre — Riptide
    registry.register_attack("me01-034", 1, _swirling_waves)               # Kyogre — Swirling Waves
    registry.register_attack("me01-036", 0, _hammer_lanche)                # Mega Abomasnow ex — Hammer-lanche
    registry.register_attack("me01-036", 1, _frost_barrier)                # Mega Abomasnow ex — Frost Barrier
    registry.register_attack("me01-038", 0, _aqua_launcher)                # Clawitzer — Aqua Launcher
    registry.register_attack("me01-039", 0, _surprise_attack)              # Sobble — Surprise Attack
    registry.register_attack("me01-040", 0, _double_stab)                  # Drizzile — Double Stab
    registry.register_attack("me01-041", 0, _bring_down)                   # Inteleon — Bring Down
    registry.register_attack("me01-041", 1, _water_shot)                   # Inteleon — Water Shot
    registry.register_attack("me01-042", 0, _hide)                         # Snom — Hide
    registry.register_attack("me01-043", 0, _chilling_wings)               # Frosmoth — Chilling Wings
    registry.register_attack("me01-044", 0, _stun_spore)                   # Eiscue — Freezing Headbutt (flip paralyzed)
    registry.register_attack("me01-046", 0, _stun_spore)                   # Magneton — Thunder Shock (flip paralyzed)
    registry.register_attack("me01-047", 0, _upper_spark)                  # Magnezone — Upper Spark
    registry.register_attack("me01-047", 1, _flashing_bolt)                # Magnezone — Flashing Bolt
    registry.register_attack("me01-048", 0, _electro_fall)                 # Raikou — Electro Fall
    registry.register_attack("me01-049", 0, _take_down)                    # Electrike — Thunder Jolt (recoil)
    registry.register_attack("me01-050", 0, _flash_ray)                    # Mega Manectric ex — Flash Ray
    registry.register_attack("me01-050", 1, _riotous_blasting)             # Mega Manectric ex — Riotous Blasting
    registry.register_attack("me01-052", 0, _double_headbutt)              # Helioptile — Double Scratch
    registry.register_attack("me01-053", 0, _dazzle_blast)                 # Heliolisk — Dazzle Blast
    registry.register_attack("me01-057", 0, _jynx_psychic)                 # Jynx — Psychic
    registry.register_attack("me01-060", 0, _overflowing_wishes)           # Mega Gardevoir ex — Overflowing Wishes
    registry.register_attack("me01-060", 1, _mega_symphonia)               # Mega Gardevoir ex — Mega Symphonia
    registry.register_attack("me01-061", 0, _damage_beat)                  # Shedinja — Damage Beat
    registry.register_attack("me01-062", 0, _triple_spin)                  # Spoink — Triple Spin
    registry.register_attack("me01-064", 0, _geo_gate)                     # Xerneas — Geo Gate
    registry.register_attack("me01-064", 1, _bright_horns)                 # Xerneas — Bright Horns
    registry.register_attack("me01-065", 1, _take_down)                    # Greavard — Take Down
    registry.register_attack("me01-066", 0, _horrifying_bite)              # Houndstone — Horrifying Bite
    registry.register_attack("me01-070", 0, _bind)                         # Onix — Bind (flip paralyzed)

    # ── Batch 5: MEG attack registrations ─────────────────────────────────────
    registry.register_attack("me01-071", 0, _pow_pow_punching)             # Tyrogue — Pow-Pow Punching
    registry.register_attack("me01-073", 0, _wild_press)                   # Hariyama — Wild Press
    registry.register_attack("me01-076", 0, _accelerating_stab)            # Riolu — Accelerating Stab
    registry.register_attack("me01-077", 0, _aura_jab)                     # Mega Lucario ex — Aura Jab
    registry.register_attack("me01-077", 1, _mega_brave)                   # Mega Lucario ex — Mega Brave
    registry.register_attack("me01-079", 0, _reckless_charge_toxicroak)    # Toxicroak — Reckless Charge
    registry.register_attack("me01-080", 0, _shadowy_side_kick)            # Marshadow — Shadowy Side Kick
    registry.register_attack("me01-081", 0, _stony_kick)                   # Stonjourner — Stony Kick
    registry.register_attack("me01-081", 1, _boundless_power)              # Stonjourner — Boundless Power
    registry.register_attack("me01-083", 0, _naclstack_rock_hurl)          # Naclstack — Rock Hurl
    registry.register_attack("me01-085", 1, _cutting_riposte)              # Crawdaunt — Cutting Riposte
    registry.register_attack("me01-087", 0, _mountain_breaker)             # Spiritomb — Mountain Breaker
    registry.register_attack("me01-090", 0, _greedy_hunt)                  # Thievul — Greedy Hunt
    registry.register_attack("me01-091", 0, _poison_jab)                   # Shroodle — Poison Jab
    registry.register_attack("me01-092", 0, _miraculous_paint)             # Grafaiai — Miraculous Paint
    registry.register_attack("me01-093", 0, _welcoming_tail)               # Steelix — Welcoming Tail
    registry.register_attack("me01-094", 0, _gobble_down)                  # Mega Mawile ex — Gobble Down
    registry.register_attack("me01-094", 1, _huge_bite)                    # Mega Mawile ex — Huge Bite
    registry.register_attack("me01-095", 1, _chrono_burst)                 # Dialga — Chrono Burst
    registry.register_attack("me01-098", 0, _windup_swing)                 # Tinkaton — Windup Swing
    registry.register_attack("me01-099", 0, _all_you_can_grab)             # Gholdengo — All-You-Can-Grab
    registry.register_attack("me01-100", 0, _teleportation_attack)         # Mega Latias ex — Strafe
    registry.register_attack("me01-100", 1, _illusory_impulse)             # Mega Latias ex — Illusory Impulse
    registry.register_attack("me01-102", 0, _pluck)                        # Spearow — Pluck
    registry.register_attack("me01-103", 0, _repeating_drill)              # Fearow — Repeating Drill
    registry.register_attack("me01-105", 0, _quick_gift)                   # Delibird — Quick Gift
    registry.register_attack("me01-106", 0, _bellyful_of_milk)             # Miltank — Bellyful of Milk
    registry.register_attack("me01-107", 0, _charm)                        # Buneary — Charm
    registry.register_attack("me01-108", 0, _dashing_kick)                 # Lopunny — Dashing Kick
    registry.register_attack("me01-109", 0, _collect)                      # Yungoos — Collect
    registry.register_attack("me01-112", 1, _hyper_lariat)                 # Bewear — Hyper Lariat

    # ── Batch 5: BLK attack registrations ─────────────────────────────────────
    registry.register_attack("sv10.5b-002", 0, _stun_spore)                # Servine — Wrap (flip paralyzed)
    registry.register_attack("sv10.5b-003", 0, _command_the_grass)         # Serperior ex — Command the Grass
    registry.register_attack("sv10.5b-004", 0, _collect)                   # Pansage — Collect
    registry.register_attack("sv10.5b-006", 0, _hide)                      # Petilil — Hide
    registry.register_attack("sv10.5b-007", 0, _bemusing_aroma)            # Lilligant — Bemusing Aroma
    registry.register_attack("sv10.5b-008", 0, _lively_needles)            # Maractus — Lively Needles
    registry.register_attack("sv10.5b-010", 0, _poison_powder_tangela)     # Foongus — Toxic Spore
    registry.register_attack("sv10.5b-011", 0, _dangerous_reaction)        # Amoonguss — Dangerous Reaction
    registry.register_attack("sv10.5b-012", 0, _v_force)                   # Victini — V-Force
    registry.register_attack("sv10.5b-014", 0, _super_singe)               # Darmanitan — Searing Flame
    registry.register_attack("sv10.5b-014", 1, _smashing_headbutt)         # Darmanitan — Smashing Headbutt
    registry.register_attack("sv10.5b-017", 0, _collect)                   # Panpour — Collect
    registry.register_attack("sv10.5b-019", 0, _round_player_20)           # Tympole — Round
    registry.register_attack("sv10.5b-020", 0, _round_player_40)           # Palpitoad — Round
    registry.register_attack("sv10.5b-021", 0, _round_player_70)           # Seismitoad — Round
    registry.register_attack("sv10.5b-022", 0, _ancient_seaweed)           # Tirtouga — Ancient Seaweed
    registry.register_attack("sv10.5b-023", 0, _carracosta_big_bite)       # Carracosta — Big Bite
    registry.register_attack("sv10.5b-025", 0, _snotted_up)                # Cubchoo — Snotted Up
    registry.register_attack("sv10.5b-026", 0, _continuous_headbutt)       # Beartic — Continuous Headbutt
    registry.register_attack("sv10.5b-026", 1, _beartic_sheer_cold)        # Beartic — Sheer Cold
    registry.register_attack("sv10.5b-027", 0, _drag_off)                  # Cryogonal — Drag Off
    registry.register_attack("sv10.5b-028", 1, _blizzard_burst)            # Kyurem ex — Blizzard Burst
    registry.register_attack("sv10.5b-029", 0, _call_for_family)           # Emolga — Call for Family
    registry.register_attack("sv10.5b-030", 0, _hold_still)                # Tynamo — Hold Still
    registry.register_attack("sv10.5b-032", 0, _stun_spore)                # Eelektross — Thunder Fang (flip paralyzed)
    registry.register_attack("sv10.5b-032", 1, _buzz_flip)                 # Eelektross — Buzz Flip
    registry.register_attack("sv10.5b-033", 0, _charge_thundurus)          # Thundurus — Charge
    registry.register_attack("sv10.5b-033", 1, _disaster_volt)             # Thundurus — Disaster Volt
    registry.register_attack("sv10.5b-034", 1, _voltage_burst)             # Zekrom ex — Voltage Burst
    registry.register_attack("sv10.5b-035", 0, _rest_munna)                # Munna — Rest
    registry.register_attack("sv10.5b-036", 0, _dream_calling)             # Musharna — Dream Calling
    registry.register_attack("sv10.5b-036", 1, _sleep_pulse)               # Musharna — Sleep Pulse
    registry.register_attack("sv10.5b-038", 0, _cellular_evolution_noop)   # Duosion — Cellular Evolution (FLAGGED)
    registry.register_attack("sv10.5b-039", 0, _cellular_ascension_noop)   # Reuniclus — Cellular Ascension (FLAGGED)
    registry.register_attack("sv10.5b-039", 1, _evo_lariat)                # Reuniclus — Evo-Lariat
    registry.register_attack("sv10.5b-040", 0, _slight_shift)              # Elgyem — Slight Shift
    registry.register_attack("sv10.5b-041", 0, _calm_mind)                 # Beheeyem — Calm Mind
    registry.register_attack("sv10.5b-041", 1, _beheeyem_psychic)          # Beheeyem — Psychic
    registry.register_attack("sv10.5b-042", 0, _golett_best_punch)         # Golett — Best Punch
    registry.register_attack("sv10.5b-043", 0, _double_smash)              # Golurk — Double Smash
    registry.register_attack("sv10.5b-044", 0, _echoed_voice)              # Meloetta ex — Echoed Voice
    registry.register_attack("sv10.5b-046", 0, _piercing_drill)            # Excadrill ex — Piercing Drill
    registry.register_attack("sv10.5b-046", 1, _excadrill_rock_tumble)     # Excadrill ex — Rock Tumble
    registry.register_attack("sv10.5b-048", 1, _hammer_arm)                # Gurdurr — Hammer Arm
    registry.register_attack("sv10.5b-049", 0, _swing_around)              # Conkeldurr — Swing Around
    registry.register_attack("sv10.5b-050", 0, _shoulder_throw)            # Throh — Shoulder Throw
    registry.register_attack("sv10.5b-051", 0, _flail_dwebble)             # Dwebble — Flail
    registry.register_attack("sv10.5b-052", 0, _stone_edge)                # Crustle — Stone Edge
    registry.register_attack("sv10.5b-053", 0, _abundant_harvest)          # Landorus — Abundant Harvest
    registry.register_attack("sv10.5b-053", 1, _earthquake_landorus)       # Landorus — Earthquake
    registry.register_attack("sv10.5b-054", 0, _poison_powder_tangela)     # Venipede — Poison Spray
    registry.register_attack("sv10.5b-055", 0, _venoshock_30)              # Whirlipede — Venoshock
    registry.register_attack("sv10.5b-056", 0, _venoshock_90)              # Scolipede — Venoshock
    registry.register_attack("sv10.5b-057", 0, _sandile_tighten_up)        # Sandile — Tighten Up
    registry.register_attack("sv10.5b-058", 0, _krokorok_tighten_up)       # Krokorok — Tighten Up

    # ── Batch 6: BLK/WHT/DRI attack registrations ─────────────────────────────
    # BLK (sv10.5b)
    registry.register_attack("sv10.5b-059", 0, _krokorok_tighten_up)       # Krookodile — Tighten Up (reuse)
    registry.register_attack("sv10.5b-059", 1, _cursed_slug)               # Krookodile — Cursed Slug
    registry.register_attack("sv10.5b-060", 0, _wild_lances)               # Escavalier — Wild Lances
    registry.register_attack("sv10.5b-061", 0, _klink_hard_gears)          # Klink — Hard Gears
    registry.register_attack("sv10.5b-062", 0, _klang_hard_gears)          # Klang — Hard Gears
    # sv10.5b-063 Klinklang Hammer In (flat); Gear Coating handled in _apply_damage
    registry.register_attack("sv10.5b-064", 0, _gooey_thread)              # Pawniard — Corner (reuse)
    # sv10.5b-065 Bisharp Cut Up (flat ATK0)
    registry.register_attack("sv10.5b-065", 1, _finishing_blow)            # Bisharp — Finishing Blow
    registry.register_attack("sv10.5b-066", 0, _righteous_edge)            # Cobalion — Righteous Edge
    registry.register_attack("sv10.5b-066", 1, _metal_arms)                # Cobalion — Metal Arms
    registry.register_attack("sv10.5b-067", 0, _protect_charge)            # Genesect ex — Protect Charge
    registry.register_attack("sv10.5b-068", 0, _gather_strength)           # Axew — Gather Strength
    # sv10.5b-069 Fraxure Bite (flat ATK0)
    registry.register_attack("sv10.5b-069", 1, _boundless_power)           # Fraxure — Boundless Power (reuse)
    registry.register_attack("sv10.5b-070", 0, _cross_cut)                 # Haxorus — Cross-Cut
    registry.register_attack("sv10.5b-070", 1, _axe_blast)                 # Haxorus — Axe Blast
    registry.register_attack("sv10.5b-071", 0, _scout)                     # Pidove — Scout
    registry.register_attack("sv10.5b-072", 0, _fly_tranquill)             # Tranquill — Fly
    registry.register_attack("sv10.5b-073", 0, _add_on)                    # Unfezant — Add On
    registry.register_attack("sv10.5b-073", 1, _swift_flight)              # Unfezant — Swift Flight
    registry.register_attack("sv10.5b-074", 0, _return_audino)             # Audino — Return
    registry.register_attack("sv10.5b-075", 0, _tail_slap)                 # Minccino — Tail Slap
    registry.register_attack("sv10.5b-076", 0, _do_the_wave)               # Cinccino — Do the Wave
    # sv10.5b-077 Rufflet (both flat)
    registry.register_attack("sv10.5b-078", 0, _aerial_ace)                # Braviary — Aerial Ace
    registry.register_attack("sv10.5b-171", 0, _v_force)                   # Victini — V-Force (reuse)
    # sv10.5b-172 Zekrom ex Slash (flat ATK0)
    registry.register_attack("sv10.5b-172", 1, _voltage_burst)             # Zekrom ex — Voltage Burst (reuse)
    # WHT (sv10.5w)
    # sv10.5w-001 Sewaddle Bug Bite (flat)
    # sv10.5w-002 Swadloon Bug Buzz (flat); Healing Leaves ability handled separately
    registry.register_attack("sv10.5w-003", 0, _healing_wrapping)          # Leavanny — Healing Wrapping
    registry.register_attack("sv10.5w-003", 1, _x_scissor)                 # Leavanny — X-Scissor
    registry.register_attack("sv10.5w-004", 0, _absorb)                    # Cottonee — Absorb
    registry.register_attack("sv10.5w-005", 0, _energy_gift_whimsicott)    # Whimsicott ex — Energy Gift
    registry.register_attack("sv10.5w-005", 1, _wondrous_cotton)           # Whimsicott ex — Wondrous Cotton
    # sv10.5w-006 Deerling Rear Kick (flat)
    registry.register_attack("sv10.5w-007", 0, _push_down)                 # Sawsbuck — Push Down (reuse)
    # sv10.5w-007 ATK1 Solar Beam (flat)
    # sv10.5w-008 Shelmet flat + Stimulated Evolution ability FLAGGED
    registry.register_attack("sv10.5w-009", 0, _acid_spray)                # Accelgor — Acid Spray
    registry.register_attack("sv10.5w-010", 0, _giga_drain)                # Virizion — Giga Drain
    registry.register_attack("sv10.5w-010", 1, _prism_edge)                # Virizion — Emerald Blade (reuse)
    # sv10.5w-011 Tepig both flat
    # sv10.5w-012 Pignite both flat
    # sv10.5w-013 Emboar Heat Crash (flat ATK0); Inferno Fandango FLAGGED
    registry.register_attack("sv10.5w-014", 0, _collect)                   # Pansear — Collect (reuse)
    # sv10.5w-015 Simisear Gentle Slap (flat)
    registry.register_attack("sv10.5w-016", 0, _brighten_and_burn)         # Litwick — Brighten and Burn
    registry.register_attack("sv10.5w-017", 0, _lampent_fire_blast)        # Lampent — Fire Blast
    registry.register_attack("sv10.5w-018", 0, _incendiary_pillar)         # Chandelure — Incendiary Pillar
    registry.register_attack("sv10.5w-018", 1, _burn_it_all_up)            # Chandelure — Burn It All Up
    registry.register_attack("sv10.5w-019", 0, _licking_catch)             # Heatmor — Licking Catch
    # sv10.5w-019 ATK1 Fire Claws (flat)
    registry.register_attack("sv10.5w-020", 1, _blazing_burst)             # Reshiram ex — Blazing Burst
    # sv10.5w-020 ATK0 Slash (flat)
    # sv10.5w-021 Oshawott both flat
    registry.register_attack("sv10.5w-022", 0, _energized_shell)           # Dewott — Energized Shell
    registry.register_attack("sv10.5w-023", 0, _energized_slash)           # Samurott — Energized Slash
    # sv10.5w-023 Torrential Whirlpool ability handled separately
    registry.register_attack("sv10.5w-024", 1, _bared_fangs)               # Basculin — Bared Fangs
    # sv10.5w-024 ATK0 Bite (flat)
    registry.register_attack("sv10.5w-025", 0, _ducklett_firefighting)     # Ducklett — Firefighting
    # sv10.5w-025 ATK1 Wing Attack (flat)
    # sv10.5w-026 Swanna Flap (flat ATK0)
    registry.register_attack("sv10.5w-026", 1, _swanna_air_slash)          # Swanna — Air Slash
    registry.register_attack("sv10.5w-027", 1, _ice_edge)                  # Vanillite — Ice Edge
    # sv10.5w-027 ATK0 Beat (flat)
    # sv10.5w-028 ATK0 Ram (flat)
    registry.register_attack("sv10.5w-028", 1, _ice_beam_vanillish)        # Vanillish — Ice Beam
    # sv10.5w-029 ATK0 Ram (flat)
    registry.register_attack("sv10.5w-029", 1, _double_freeze)             # Vanilluxe — Double Freeze
    registry.register_attack("sv10.5w-030", 0, _keldeo_gale_thrust)        # Keldeo ex — Gale Thrust
    registry.register_attack("sv10.5w-030", 1, _sonic_edge)                # Keldeo ex — Sonic Edge
    # sv10.5w-031 Blitzle both flat
    # sv10.5w-032 ATK0 Smash Kick (flat)
    registry.register_attack("sv10.5w-032", 1, _zebstrika_electrobullet)   # Zebstrika — Electrobullet
    registry.register_attack("sv10.5w-033", 0, _joltik_surprise)           # Joltik — Surprise Attack
    registry.register_attack("sv10.5w-034", 0, _galvantula_discharge)      # Galvantula — Discharge
    registry.register_attack("sv10.5w-035", 0, _stunfisk_muddy_bolt)       # Stunfisk — Muddy Bolt
    # sv10.5w-035 ATK1 Flop (flat)
    # sv10.5w-036 Woobat Heart Stamp (flat)
    registry.register_attack("sv10.5w-037", 0, _swoobat_happy_return)      # Swoobat — Happy Return
    # sv10.5w-037 ATK1 Gust (flat)
    registry.register_attack("sv10.5w-038", 0, _sigilyph_reflect)          # Sigilyph — Reflect
    registry.register_attack("sv10.5w-038", 1, _sigilyph_telekinesis)      # Sigilyph — Telekinesis
    registry.register_attack("sv10.5w-039", 0, _ice_edge)                  # Yamask — Focused Wish (reuse)
    registry.register_attack("sv10.5w-040", 0, _cofagrigus_extended_damagriiigus)  # Cofagrigus — Extended Damagriiigus
    registry.register_attack("sv10.5w-040", 1, _cofagrigus_perplex)        # Cofagrigus — Perplex
    # sv10.5w-041 Gothita Super Psy Bolt (flat)
    registry.register_attack("sv10.5w-042", 0, _gothorita_fortunate_eye)   # Gothorita — Fortunate Eye
    # sv10.5w-042 ATK1 Psyshot (flat)
    registry.register_attack("sv10.5w-043", 0, _synchro_shot)              # Gothitelle — Synchro Shot
    registry.register_attack("sv10.5w-044", 0, _oceanic_gloom)             # Frillish — Oceanic Gloom
    registry.register_attack("sv10.5w-045", 0, _power_press)               # Jellicent ex — Power Press
    # sv10.5w-045 Oceanic Curse FLAGGED
    registry.register_attack("sv10.5w-046", 0, _roggenrola_harden)         # Roggenrola — Harden
    # sv10.5w-046 ATK1 Rolling Rocks (flat)
    registry.register_attack("sv10.5w-047", 0, _boldore_smack_down)        # Boldore — Smack Down
    # sv10.5w-047 ATK1 Power Gem (flat)
    registry.register_attack("sv10.5w-048", 0, _gigalith_vengeful_cannon)  # Gigalith — Vengeful Cannon
    # sv10.5w-048 ATK1 Heavy Impact (flat)
    # sv10.5w-049 ATK0 Elbow Strike (flat)
    registry.register_attack("sv10.5w-049", 1, _sawk_rising_chop)          # Sawk — Rising Chop
    registry.register_attack("sv10.5w-050", 0, _archen_acrobatics)         # Archen — Acrobatics
    # sv10.5w-051 Archeops Rock Throw (flat); Ancient Wing FLAGGED
    # sv10.5w-052 Mienfoo Kick (flat)
    # sv10.5w-053 ATK0 Low Sweep (flat)
    registry.register_attack("sv10.5w-053", 1, _mienshao_smash_uppercut)   # Mienshao — Smash Uppercut
    # sv10.5w-054 ATK0 Retaliate FLAGGED; ATK1 Land Crush (flat)
    registry.register_attack("sv10.5w-055", 0, _purrloin_invite_evil)      # Purrloin — Invite Evil
    registry.register_attack("sv10.5w-056", 0, _liepard_knock_off)         # Liepard — Knock Off
    # sv10.5w-057 Scraggy both flat
    registry.register_attack("sv10.5w-058", 0, _scrafty_ruffians)          # Scrafty — Ruffians Attack
    # sv10.5w-059 Trubbish both flat
    # sv10.5w-060 ATK0 Suffocating Gas (flat)
    registry.register_attack("sv10.5w-060", 1, _gunk_shot)                 # Garbodor — Gunk Shot
    registry.register_attack("sv10.5w-061", 0, _zorua_take_down)           # Zorua — Take Down
    registry.register_attack("sv10.5w-062", 0, _zoroark_mind_jack)         # Zoroark — Mind Jack
    registry.register_attack("sv10.5w-062", 1, _zoroark_foul_play)         # Zoroark — Foul Play
    # sv10.5w-063 Vullaby Playful Kick (flat)
    # sv10.5w-064 Mandibuzz Cutting Wind (flat ATK0); Look for Prey ability handled separately
    registry.register_attack("sv10.5w-065", 0, _body_slam_deino)           # Deino — Body Slam
    # sv10.5w-065 ATK1 Darkness Fang (flat)
    registry.register_attack("sv10.5w-066", 0, _double_hit_zweilous)       # Zweilous — Double Hit
    # sv10.5w-066 ATK1 Pitch-Black Fangs (flat)
    registry.register_attack("sv10.5w-067", 0, _hydreigon_dark_bite)       # Hydreigon ex — Dark Bite
    # sv10.5w-067 Greedy Eater FLAGGED
    # sv10.5w-068 Ferroseed both flat
    registry.register_attack("sv10.5w-069", 0, _ferrothorn_power_whip)     # Ferrothorn — Power Whip
    # sv10.5w-069 ATK1 Metal Claw (flat)
    registry.register_attack("sv10.5w-070", 0, _durant_bite_together)      # Durant — Bite Together
    # sv10.5w-070 ATK1 Vise Grip (flat)
    registry.register_attack("sv10.5w-071", 0, _druddigon_shred)           # Druddigon — Shred
    registry.register_attack("sv10.5w-071", 1, _druddigon_ambush)          # Druddigon — Ambush
    registry.register_attack("sv10.5w-072", 0, _patrat_procurement)        # Patrat — Procurement
    # sv10.5w-072 ATK1 Gnaw (flat)
    # sv10.5w-073 Watchog Focus Energy FLAGGED
    registry.register_attack("sv10.5w-073", 1, _watchog_hyper_fang)        # Watchog — Hyper Fang
    registry.register_attack("sv10.5w-074", 0, _lillipup_play_rough)       # Lillipup — Play Rough
    registry.register_attack("sv10.5w-075", 0, _force_switch_no_damage)    # Herdier — Roar
    # sv10.5w-075 ATK1 Lunge Out (flat)
    registry.register_attack("sv10.5w-076", 0, _stoutland_odor_sleuth)     # Stoutland — Odor Sleuth
    registry.register_attack("sv10.5w-076", 1, _stoutland_special_fang)    # Stoutland — Special Fang
    registry.register_attack("sv10.5w-077", 0, _bouffalant_gold_breaker)   # Bouffalant ex — Gold Breaker
    # sv10.5w-077 Bouffer ability handled in _apply_damage
    registry.register_attack("sv10.5w-078", 0, _tornadus_wrapped_in_wind)  # Tornadus — Wrapped in Wind
    registry.register_attack("sv10.5w-078", 1, _tornadus_hurricane)        # Tornadus — Hurricane
    # DRI (sv10)
    registry.register_attack("sv10-002", 0, _force_switch_no_damage)       # Yanma — Whirlwind
    # sv10-002 ATK1 Razor Wing (flat)