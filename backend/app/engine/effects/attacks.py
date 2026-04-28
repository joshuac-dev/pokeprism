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

    total = base_damage + state.active_player_damage_bonus
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
    """Apply flat bench damage (no W/R), respecting Battle Cage and Flower Curtain."""
    if damage <= 0:
        return
    if has_battle_cage(state):
        state.emit_event("bench_damage_blocked", reason="battle_cage",
                         card=target.card_name)
        return
    cdef = card_registry.get(target.card_def_id)
    if has_flower_curtain(state, target_player_id):
        if cdef and not cdef.has_rule_box:
            state.emit_event("bench_damage_blocked", reason="flower_curtain",
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


# ──────────────────────────────────────────────────────────────────────────────
# Registration
# ──────────────────────────────────────────────────────────────────────────────

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
    registry.register_attack("sv06-118", 0, _poison_spray)
    registry.register_attack("svp-149", 0, _poison_chain)

    # Category 4: Draw and search effects
    registry.register_attack("me03-042", 0, _double_draw)
    registry.register_attack("sv06-039", 0, _allure)
    registry.register_attack("sv10-040", 0, _collect)
    registry.register_attack("sv10-134", 0, _filch)
    registry.register_attack("sv06-106", 0, _shinobi_blade)
    registry.register_attack("me02-067", 0, _call_for_family)
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
    registry.register_attack("sv09-116", 0, _powerful_rage)
    registry.register_attack("sv10-012", 0, _superb_scissors)
    registry.register_attack("sv10-020", 0, _rocket_rush)
    registry.register_attack("sv10-041", 1, _double_kick)
    registry.register_attack("sv10-051", 0, _dark_frost)

    # Category 6: Bench damage
    registry.register_attack("sv06-064", 1, _torrential_pump)
    registry.register_attack("sv06-106", 1, _mirage_barrage)
    registry.register_attack("sv06-130", 1, _phantom_dive)
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

    # Category 9: Copy-attack stubs
    registry.register_attack("sv09-098", 0, _night_joker)
    registry.register_attack("sv10-087", 0, _gemstone_mimicry)
