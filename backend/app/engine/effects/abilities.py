"""Ability effect handlers — Phase 2 implementation.

Handler contract (same as trainers/energies):
  - Regular functions: handler(state, action) -> None
  - Generator functions: handler(state, action) -> Generator  (yield ChoiceRequest)

On-bench and on-evolve triggers are registered normally via register_ability()
and called from _play_basic / _evolve in transitions.py.

Passive abilities (Wild Growth, Skyliner, etc.) have no USE_ABILITY handler;
their logic lives in base.py helpers and actions.py checks.

Public passive helpers exported from this module:
  has_wild_growth, wild_growth_bonus_grass
  has_skyliner, has_fairy_zone, has_flower_curtain
  has_psyduck_damp, get_froslass_players, apply_froslass_shroud
  has_cornerstone_stance, has_mysterious_rock_inn
  has_adrena_power, has_adrena_pheromone
  has_repelling_veil, repelling_veil_protects
  power_saver_blocks_attack
"""

from __future__ import annotations

import logging
import random
from typing import TYPE_CHECKING

from app.engine.state import (
    EnergyAttachment,
    EnergyType,
    GameState,
    StatusCondition,
    Zone,
)
from app.engine.effects.base import ChoiceRequest, check_ko, draw_cards
from app.engine.effects.registry import EffectRegistry
from app.cards import registry as card_registry

if TYPE_CHECKING:
    from app.engine.actions import Action

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _in_play(player) -> list:
    result = []
    if player.active:
        result.append(player.active)
    result.extend(player.bench)
    return result


def _has_d_energy(pokemon) -> bool:
    return any(att.energy_type == EnergyType.DARKNESS for att in pokemon.energy_attached)


def _is_tr_pokemon(pokemon) -> bool:
    return pokemon.card_name.startswith("Team Rocket's")


def _find_in_play(player, iid):
    if player.active and player.active.instance_id == iid:
        return player.active
    return next((b for b in player.bench if b.instance_id == iid), None)


def _switch_active_with_bench(player, bench_poke) -> None:
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


def _pokemon_has_type(pokemon, type_str: str) -> bool:
    cdef = card_registry.get(pokemon.card_def_id)
    return bool(cdef and type_str in (cdef.types or []))


def _attach_from_hand_or_discard(player, poke, energy_card) -> None:
    """Move energy_card from wherever it is to poke's attached list."""
    if energy_card in player.hand:
        player.hand.remove(energy_card)
    elif energy_card in player.discard:
        player.discard.remove(energy_card)

    energy_card.zone = poke.zone
    cdef = card_registry.get(energy_card.card_def_id)
    provides_strs = cdef.energy_provides if cdef and cdef.energy_provides else ["Colorless"]
    provides = [EnergyType.from_str(t) for t in provides_strs]
    primary = provides[0] if provides else EnergyType.COLORLESS
    poke.energy_attached.append(EnergyAttachment(
        energy_type=primary,
        source_card_id=energy_card.instance_id,
        card_def_id=energy_card.card_def_id,
        provides=provides,
    ))


# ──────────────────────────────────────────────────────────────────────────────
# Passive ability helpers — imported by registry.py, actions.py, base.py
# ──────────────────────────────────────────────────────────────────────────────

# Wild Growth (me01-010 Meganium) ─────────────────────────────────────────────

def has_wild_growth(state: GameState, player_id: str) -> bool:
    """True if player has Meganium (Wild Growth) in play."""
    player = state.get_player(player_id)
    return any(p.card_def_id == "me01-010" for p in _in_play(player))


def wild_growth_bonus_grass(pokemon) -> int:
    """Return the number of extra Grass energy provided by Wild Growth.

    Each Basic Grass Energy attached to your Pokémon provides GG instead of G.
    Returns the count of extra G energy symbols produced (1 per Basic G card).
    """
    bonus = 0
    for att in pokemon.energy_attached:
        cdef = card_registry.get(att.card_def_id) if att.card_def_id else None
        if (cdef
                and cdef.category.lower() == "energy"
                and cdef.subcategory.lower() == "basic"
                and att.energy_type == EnergyType.GRASS):
            bonus += 1  # This one card now provides 2G instead of 1G
    return bonus


# Skyliner (sv08-076 Latias ex) ───────────────────────────────────────────────

def has_skyliner(state: GameState, player_id: str) -> bool:
    """True if player has Latias ex (sv08-076) in play: all Basic Pokémon have free retreat."""
    player = state.get_player(player_id)
    return any(p.card_def_id == "sv08-076" for p in _in_play(player))


# Fairy Zone (sv09-056 Lillie's Clefairy ex) ──────────────────────────────────

def has_fairy_zone(state: GameState, attacker_player_id: str) -> bool:
    """True if the attacking player's opponent has Lillie's Clefairy ex in play.

    Fairy Zone: opponent's Colorless ({N}) Pokémon have Weakness Psychic ×2.
    Checked from the attacker's side — the *attacker's opponent* has Clefairy ex.
    """
    defender_player_id = state.opponent_id(attacker_player_id)
    defender_player = state.get_player(defender_player_id)
    return any(p.card_def_id == "sv09-056" for p in _in_play(defender_player))


# Flower Curtain (sv10-010 Shaymin) ──────────────────────────────────────────

def has_flower_curtain(state: GameState, player_id: str) -> bool:
    """True if player has Shaymin (sv10-010) in play.

    Prevents damage done to benched non-rule-box Pokémon from opponent's attacks.
    Checked from the DEFENDING player's side.
    """
    player = state.get_player(player_id)
    return any(p.card_def_id == "sv10-010" for p in _in_play(player))


# Psyduck Damp (me02.5-039) ───────────────────────────────────────────────────

def has_psyduck_damp(state: GameState) -> bool:
    """True if either player has Psyduck in play. Prevents KO-self abilities."""
    for pid in ("p1", "p2"):
        player = state.get_player(pid)
        if any(p.card_def_id == "me02.5-039" for p in _in_play(player)):
            return True
    return False


# Froslass Freezing Shroud (sv06-053) ─────────────────────────────────────────

def get_froslass_players(state: GameState) -> list[str]:
    """Return player IDs that have Froslass in play."""
    result = []
    for pid in ("p1", "p2"):
        player = state.get_player(pid)
        if any(p.card_def_id == "sv06-053" for p in _in_play(player)):
            result.append(pid)
    return result


def apply_froslass_shroud(state: GameState) -> None:
    """Pokémon Checkup: put 1 damage counter on each Pokémon with an Ability (except Froslass)."""
    if not get_froslass_players(state):
        return
    for pid in ("p1", "p2"):
        player = state.get_player(pid)
        for pokemon in list(_in_play(player)):
            if pokemon.card_def_id == "sv06-053":
                continue
            cdef = card_registry.get(pokemon.card_def_id)
            if cdef and cdef.abilities:
                pokemon.current_hp -= 10
                pokemon.damage_counters += 1
                state.emit_event("freezing_shroud", player=pid, card=pokemon.card_name)
                check_ko(state, pokemon, pid)
                if state.phase.name == "GAME_OVER":
                    return


# Cornerstone Stance (sv06-112 Cornerstone Mask Ogerpon ex) ───────────────────

def has_cornerstone_stance(defender, attacker) -> bool:
    """True if defender is Cornerstone Mask Ogerpon ex AND attacker has an Ability."""
    if defender.card_def_id != "sv06-112":
        return False
    attacker_def = card_registry.get(attacker.card_def_id)
    return bool(attacker_def and attacker_def.abilities)


# Mysterious Rock Inn (sv10-012 Crustle) ──────────────────────────────────────

def has_mysterious_rock_inn(defender, attacker) -> bool:
    """True if defender is Crustle AND attacker is a Pokémon ex."""
    if defender.card_def_id != "sv10-012":
        return False
    attacker_def = card_registry.get(attacker.card_def_id)
    return bool(attacker_def and attacker_def.is_ex)


# Adrena-Power (sv06-111 Okidogi) ─────────────────────────────────────────────

def has_adrena_power(pokemon) -> bool:
    """True if pokemon is Okidogi with at least one Darkness Energy attached."""
    return pokemon.card_def_id == "sv06-111" and _has_d_energy(pokemon)


# Adrena-Pheromone (sv06-096 Fezandipiti) ────────────────────────────────────

def has_adrena_pheromone(pokemon) -> bool:
    """True if pokemon is Fezandipiti with at least one Darkness Energy attached."""
    return pokemon.card_def_id == "sv06-096" and _has_d_energy(pokemon)


# Repelling Veil (sv10-051 TR Articuno) ───────────────────────────────────────

def has_repelling_veil(state: GameState, player_id: str) -> bool:
    """True if player has TR Articuno in play."""
    player = state.get_player(player_id)
    return any(p.card_def_id == "sv10-051" for p in _in_play(player))


def repelling_veil_protects(pokemon, state: GameState, player_id: str) -> bool:
    """True if Repelling Veil protects this specific Pokémon from attack effects."""
    if not has_repelling_veil(state, player_id):
        return False
    cdef = card_registry.get(pokemon.card_def_id)
    return bool(
        cdef
        and cdef.stage.lower() == "basic"
        and _is_tr_pokemon(pokemon)
    )


# Power Saver (sv10-081 TR Mewtwo ex) ─────────────────────────────────────────

def power_saver_blocks_attack(state: GameState, pokemon, player_id: str) -> bool:
    """True if Power Saver prevents this Pokémon from attacking (fewer than 4 TR Pokémon)."""
    if pokemon.card_def_id != "sv10-081":
        return False
    player = state.get_player(player_id)
    tr_count = sum(1 for p in _in_play(player) if _is_tr_pokemon(p))
    return tr_count < 4


def has_battle_cage(state: GameState) -> bool:
    """True if Battle Cage stadium (me02-085) is active — blocks all bench damage."""
    return bool(state.active_stadium and state.active_stadium.card_def_id == "me02-085")


# ──────────────────────────────────────────────────────────────────────────────
# On-bench trigger handlers
# ──────────────────────────────────────────────────────────────────────────────

# Rapid Vernier (sv05-025 Iron Leaves ex) ─────────────────────────────────────

def _rapid_vernier(state: GameState, action):
    """On-bench: may switch with active, then move energy from other Pokémon to self."""
    player_id = action.player_id
    player = state.get_player(player_id)
    poke = _find_in_play(player, action.card_instance_id)
    if poke is None or poke not in player.bench:
        return

    req = ChoiceRequest(
        "choose_option", player_id,
        "Rapid Vernier: Switch Iron Leaves ex with your Active Pokémon?",
        options=["Yes, switch", "No, stay on Bench"],
    )
    resp = yield req
    if resp is None or (resp.selected_option or 0) != 0:
        return

    _switch_active_with_bench(player, poke)
    state.emit_event("rapid_vernier_switch", player=player_id, card=poke.card_name)

    # Optionally move energy from another Pokémon
    donors = [p for p in _in_play(player)
              if p.instance_id != poke.instance_id and p.energy_attached]
    if not donors:
        return

    req2 = ChoiceRequest(
        "choose_option", player_id,
        "Rapid Vernier: Move energy from another Pokémon to Iron Leaves ex?",
        options=["Yes, move energy", "No"],
    )
    resp2 = yield req2
    if resp2 is None or (resp2.selected_option or 0) != 0:
        return

    req3 = ChoiceRequest(
        "choose_target", player_id,
        "Rapid Vernier: Which Pokémon to take energy FROM?",
        targets=donors,
    )
    resp3 = yield req3
    src = None
    if resp3 and resp3.target_instance_id:
        src = next((p for p in donors if p.instance_id == resp3.target_instance_id), None)
    if src is None:
        src = donors[0]

    # Move all energy from src to poke
    poke.energy_attached.extend(src.energy_attached)
    src.energy_attached = []
    state.emit_event("rapid_vernier_energy", player=player_id,
                     from_card=src.card_name, to_card=poke.card_name)


# Snow Sink (sv08-056 Chien-Pao) ──────────────────────────────────────────────

def _snow_sink(state: GameState, action):
    """On-bench: may discard a Stadium in play."""
    if not state.active_stadium:
        return

    player_id = action.player_id
    req = ChoiceRequest(
        "choose_option", player_id,
        f"Snow Sink: Discard {state.active_stadium.card_name}?",
        options=["Yes, discard Stadium", "No"],
    )
    resp = yield req
    if resp is None or (resp.selected_option or 0) != 0:
        return

    stadium_name = state.active_stadium.card_name
    state.active_stadium.zone = Zone.DISCARD
    # Put in active player's discard (we don't track who played the stadium)
    state.get_player(player_id).discard.append(state.active_stadium)
    state.active_stadium = None
    state.emit_event("snow_sink", player=player_id, discarded=stadium_name)


# Battle-Hardened (sv08.5-054 Bloodmoon Ursaluna) ────────────────────────────

def _battle_hardened(state: GameState, action):
    """On-bench: attach up to 2 Basic {F} Energy cards from hand to this Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)
    poke = _find_in_play(player, action.card_instance_id)
    if poke is None:
        return

    f_energy = [c for c in player.hand
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Fighting" in (c.energy_provides or [])]
    if not f_energy:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Battle-Hardened: Attach up to 2 Basic {F} Energy to this Pokémon.",
        cards=f_energy, min_count=0, max_count=2,
    )
    resp = yield req
    chosen_ids = resp.selected_cards if resp and resp.selected_cards else []

    for iid in chosen_ids[:2]:
        card = next((c for c in player.hand if c.instance_id == iid), None)
        if card:
            _attach_from_hand_or_discard(player, poke, card)
            state.emit_event("battle_hardened_attach", player=player_id,
                             card=card.card_name, target=poke.card_name)


# Toxic Subjugation (svp-149 Pecharunt) ───────────────────────────────────────

def _toxic_subjugation(state: GameState, action):
    """On-bench: may put Poison + Confusion on opponent's Active Pokémon."""
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_player(opp_id)
    if not opp.active:
        return

    player_id = action.player_id
    req = ChoiceRequest(
        "choose_option", player_id,
        "Toxic Subjugation: Poison and Confuse opponent's Active Pokémon?",
        options=["Yes", "No"],
    )
    resp = yield req
    if resp is None or (resp.selected_option or 0) != 0:
        return

    opp.active.status_conditions.add(StatusCondition.POISONED)
    opp.active.status_conditions.add(StatusCondition.CONFUSED)
    state.emit_event("toxic_subjugation", player=player_id, target=opp.active.card_name)


# Last-Ditch Catch (me03-062 Meowth ex) ───────────────────────────────────────

def _last_ditch_catch(state: GameState, action):
    """On-bench: search deck for a Supporter card, put in hand."""
    player_id = action.player_id
    player = state.get_player(player_id)

    supporters = [c for c in player.deck if c.card_subtype.lower() == "supporter"]
    if not supporters:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Last-Ditch Catch: Search deck for a Supporter card.",
        cards=supporters, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [supporters[0].instance_id])

    for iid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)

    random.shuffle(player.deck)
    state.emit_event("last_ditch_catch", player=player_id,
                     card=player.hand[-1].card_name if player.hand else "")


# ──────────────────────────────────────────────────────────────────────────────
# On-evolve trigger handlers
# ──────────────────────────────────────────────────────────────────────────────

# Psychic Draw (me01-055 Kadabra: draw 2 / me01-056 Alakazam: draw 3) ─────────

def _psychic_draw_kadabra(state: GameState, action):
    """On-evolve to Kadabra: may draw 2 cards."""
    player_id = action.player_id
    req = ChoiceRequest(
        "choose_option", player_id,
        "Psychic Draw: Draw 2 cards?",
        options=["Yes, draw 2", "No"],
    )
    resp = yield req
    if resp is None or (resp.selected_option or 0) != 0:
        return
    drawn = draw_cards(state, player_id, 2)
    state.emit_event("psychic_draw", player=player_id, cards_drawn=drawn)


def _psychic_draw_alakazam(state: GameState, action):
    """On-evolve to Alakazam: may draw 3 cards."""
    player_id = action.player_id
    req = ChoiceRequest(
        "choose_option", player_id,
        "Psychic Draw: Draw 3 cards?",
        options=["Yes, draw 3", "No"],
    )
    resp = yield req
    if resp is None or (resp.selected_option or 0) != 0:
        return
    drawn = draw_cards(state, player_id, 3)
    state.emit_event("psychic_draw", player=player_id, cards_drawn=drawn)


# Punk Up (sv10-136 Marnie's Grimmsnarl ex) ───────────────────────────────────

def _punk_up(state: GameState, action):
    """On-evolve: search deck for up to 5 Basic {D} Energy, attach to Marnie's Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)

    d_energy = [c for c in player.deck
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Darkness" in (c.energy_provides or [])]
    if not d_energy:
        random.shuffle(player.deck)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Punk Up: Choose up to 5 Basic {D} Energy to attach to your Marnie's Pokémon.",
        cards=d_energy, min_count=0, max_count=5,
    )
    resp = yield req
    chosen_ids = resp.selected_cards if resp and resp.selected_cards else []

    marnies = [p for p in _in_play(player) if "Marnie's" in p.card_name]
    if not marnies or not chosen_ids:
        random.shuffle(player.deck)
        return

    for i, iid in enumerate(chosen_ids[:5]):
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if not card:
            continue
        target = marnies[i % len(marnies)]
        player.deck.remove(card)
        _attach_from_hand_or_discard(player, target, card)
        state.emit_event("punk_up_attach", player=player_id,
                         card=card.card_name, target=target.card_name)

    random.shuffle(player.deck)


# ──────────────────────────────────────────────────────────────────────────────
# Active-use ability handlers
# ──────────────────────────────────────────────────────────────────────────────

# Lunar Cycle (me01-074 Lunatone) ─────────────────────────────────────────────

def _lunar_cycle(state: GameState, action):
    """Condition: Solrock in play. Cost: discard 1 Basic {F} from hand. Draw 3."""
    player_id = action.player_id
    player = state.get_player(player_id)

    # Condition: Solrock in play (not in card pool; ability will never trigger)
    if not any("Solrock" in p.card_name for p in _in_play(player)):
        return

    f_energy = [c for c in player.hand
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Fighting" in (c.energy_provides or [])]
    if not f_energy:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Lunar Cycle: Discard 1 Basic {F} Energy from hand (cost).",
        cards=f_energy, min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [f_energy[0].instance_id])

    for iid in chosen_ids[:1]:
        card = next((c for c in player.hand if c.instance_id == iid), None)
        if card:
            player.hand.remove(card)
            card.zone = Zone.DISCARD
            player.discard.append(card)

    drawn = draw_cards(state, player_id, 3)
    state.emit_event("lunar_cycle", player=player_id, cards_drawn=drawn)


# Run Errand (me01-104 Mega Kangaskhan ex) ────────────────────────────────────

def _run_errand(state: GameState, action) -> None:
    """Active Spot only: draw 2 cards."""
    player_id = action.player_id
    player = state.get_player(player_id)
    poke = _find_in_play(player, action.card_instance_id)
    if poke is None or poke is not player.active:
        return
    drawn = draw_cards(state, player_id, 2)
    state.emit_event("run_errand", player=player_id, cards_drawn=drawn)


# Sinister Surge (me02-068 Toxtricity) ────────────────────────────────────────

def _sinister_surge(state: GameState, action):
    """Search deck for Basic {D} Energy, attach to benched {D} Pokémon, place 2 damage counters."""
    player_id = action.player_id
    player = state.get_player(player_id)

    d_energy = [c for c in player.deck
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Darkness" in (c.energy_provides or [])]
    d_bench = [p for p in player.bench if _pokemon_has_type(p, "Darkness")]
    if not d_energy or not d_bench:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Sinister Surge: Choose a Basic {D} Energy to attach to a Benched {D} Pokémon.",
        cards=d_energy, min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [d_energy[0].instance_id])
    energy_card = next((c for c in player.deck
                        if c.instance_id in chosen_ids), d_energy[0])

    req2 = ChoiceRequest(
        "choose_target", player_id,
        "Sinister Surge: Choose a Benched {D} Pokémon to attach to.",
        targets=d_bench,
    )
    resp2 = yield req2
    target = None
    if resp2 and resp2.target_instance_id:
        target = next((p for p in d_bench if p.instance_id == resp2.target_instance_id), None)
    if target is None:
        target = d_bench[0]

    player.deck.remove(energy_card)
    _attach_from_hand_or_discard(player, target, energy_card)

    target.current_hp -= 20
    target.damage_counters += 2
    random.shuffle(player.deck)
    state.emit_event("sinister_surge", player=player_id, target=target.card_name)
    check_ko(state, target, player_id)


# Flip the Script (me02.5-142 Fezandipiti ex) ─────────────────────────────────

def _flip_the_script(state: GameState, action) -> None:
    """If your Pokémon were KO'd during opponent's last turn: draw 3."""
    player_id = action.player_id
    opp_turn = state.turn_number - 1
    ko_happened = any(
        e.get("event") == "ko"
        and e.get("ko_player") == player_id
        and e.get("turn", -1) == opp_turn
        for e in state.events
    )
    if not ko_happened:
        return
    drawn = draw_cards(state, player_id, 3)
    state.emit_event("flip_the_script", player=player_id, cards_drawn=drawn)


# Stone Arms (me03-043 Barbaracle) ────────────────────────────────────────────

def _stone_arms(state: GameState, action):
    """Attach 1 Basic {F} Energy from hand to a {F} Pokémon in play."""
    player_id = action.player_id
    player = state.get_player(player_id)

    f_energy = [c for c in player.hand
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Fighting" in (c.energy_provides or [])]
    f_pokes = [p for p in _in_play(player) if _pokemon_has_type(p, "Fighting")]
    if not f_energy or not f_pokes:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Stone Arms: Choose a Basic {F} Energy from hand to attach.",
        cards=f_energy, min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [f_energy[0].instance_id])
    energy_card = next((c for c in player.hand if c.instance_id in chosen_ids), f_energy[0])

    req2 = ChoiceRequest(
        "choose_target", player_id,
        "Stone Arms: Choose a {F} Pokémon to attach to.",
        targets=f_pokes,
    )
    resp2 = yield req2
    target = None
    if resp2 and resp2.target_instance_id:
        target = next((p for p in f_pokes if p.instance_id == resp2.target_instance_id), None)
    if target is None:
        target = f_pokes[0]

    _attach_from_hand_or_discard(player, target, energy_card)
    state.emit_event("stone_arms", player=player_id, target=target.card_name)


# Run Away Draw (sv05-129 Dudunsparce) ────────────────────────────────────────

def _run_away_draw(state: GameState, action) -> None:
    """Draw 3 cards; if any drawn, shuffle this Pokémon + attached into deck."""
    player_id = action.player_id
    player = state.get_player(player_id)
    poke = _find_in_play(player, action.card_instance_id)
    if poke is None:
        return

    drawn = draw_cards(state, player_id, 3)
    if drawn == 0:
        return

    # Remove from play
    was_active = player.active and player.active.instance_id == poke.instance_id
    if was_active:
        player.active = None
    else:
        player.bench = [b for b in player.bench if b.instance_id != poke.instance_id]

    # Move attached energy source cards back to deck
    for att in poke.energy_attached:
        energy_card = next(
            (c for c in player.discard if c.instance_id == att.source_card_id), None
        )
        if energy_card:
            player.discard.remove(energy_card)
            energy_card.zone = Zone.DECK
            player.deck.append(energy_card)
    poke.energy_attached = []

    poke.zone = Zone.DECK
    player.deck.append(poke)
    random.shuffle(player.deck)
    state.emit_event("run_away_draw", player=player_id,
                     cards_drawn=drawn, card=poke.card_name)


# Teal Dance (sv06-025 Teal Mask Ogerpon ex) ──────────────────────────────────

def _teal_dance(state: GameState, action):
    """Attach 1 Basic {G} Energy from hand to self (extra attach); if attached, draw 1."""
    player_id = action.player_id
    player = state.get_player(player_id)
    poke = _find_in_play(player, action.card_instance_id)
    if poke is None:
        return

    g_energy = [c for c in player.hand
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Grass" in (c.energy_provides or [])]
    if not g_energy:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Teal Dance: Choose a Basic {G} Energy from hand to attach to this Pokémon.",
        cards=g_energy, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [g_energy[0].instance_id])
    if not chosen_ids:
        return

    energy_card = next((c for c in player.hand if c.instance_id in chosen_ids), None)
    if energy_card is None:
        return

    _attach_from_hand_or_discard(player, poke, energy_card)
    # Does NOT consume energy_attached_this_turn
    drawn = draw_cards(state, player_id, 1)
    state.emit_event("teal_dance", player=player_id, cards_drawn=drawn)


# Adrena-Brain (sv06-095 Munkidori) ──────────────────────────────────────────

def _adrena_brain(state: GameState, action):
    """If has {D} energy: move up to 3 damage counters from your Pokémon to opponent's."""
    player_id = action.player_id
    player = state.get_player(player_id)
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)

    poke = _find_in_play(player, action.card_instance_id)
    if poke is None or not _has_d_energy(poke):
        return

    your_damaged = [p for p in _in_play(player) if p.damage_counters > 0]
    opp_targets = _in_play(opp)
    if not your_damaged or not opp_targets:
        return

    req = ChoiceRequest(
        "choose_target", player_id,
        "Adrena-Brain: Choose your Pokémon to move damage counters FROM.",
        targets=your_damaged,
    )
    resp = yield req
    source = None
    if resp and resp.target_instance_id:
        source = next((p for p in your_damaged if p.instance_id == resp.target_instance_id), None)
    if source is None:
        source = your_damaged[0]

    req2 = ChoiceRequest(
        "choose_target", player_id,
        "Adrena-Brain: Choose opponent's Pokémon to put damage counters on.",
        targets=opp_targets,
    )
    resp2 = yield req2
    dest = None
    if resp2 and resp2.target_instance_id:
        dest = next((p for p in opp_targets if p.instance_id == resp2.target_instance_id), None)
    if dest is None:
        dest = min(opp_targets, key=lambda p: p.current_hp)

    move_count = min(3, source.damage_counters)
    source.damage_counters -= move_count
    source.current_hp += move_count * 10
    dest.damage_counters += move_count
    dest.current_hp -= move_count * 10
    state.emit_event("adrena_brain", player=player_id, counters_moved=move_count,
                     from_card=source.card_name, to_card=dest.card_name)
    check_ko(state, dest, opp_id)


# Recon Directive (sv06-129 Drakloak) ─────────────────────────────────────────

def _recon_directive(state: GameState, action):
    """Look at top 2 deck cards; put 1 in hand, other on bottom of deck."""
    player_id = action.player_id
    player = state.get_player(player_id)

    if not player.deck:
        return

    top2 = player.deck[:min(2, len(player.deck))]
    player.deck = player.deck[len(top2):]

    if len(top2) == 1:
        top2[0].zone = Zone.HAND
        player.hand.append(top2[0])
        state.emit_event("recon_directive", player=player_id, kept=top2[0].card_name)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Recon Directive: Choose 1 card to put in hand (other goes to bottom of deck).",
        cards=top2, min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [top2[0].instance_id])

    chosen = next((c for c in top2 if c.instance_id in chosen_ids), top2[0])
    other = next((c for c in top2 if c.instance_id != chosen.instance_id), None)

    chosen.zone = Zone.HAND
    player.hand.append(chosen)
    if other:
        other.zone = Zone.DECK
        player.deck.append(other)  # Bottom
    state.emit_event("recon_directive", player=player_id, kept=chosen.card_name)


# Subjugating Chains (sv06.5-039 Pecharunt ex) ───────────────────────────────

def _subjugating_chains(state: GameState, action):
    """Switch a Benched {D} Pokémon (not Pecharunt ex) to Active; new Active is Poisoned."""
    player_id = action.player_id
    player = state.get_player(player_id)

    eligible = [p for p in player.bench
                if _pokemon_has_type(p, "Darkness") and p.card_def_id != "sv06.5-039"]
    if not eligible:
        return

    req = ChoiceRequest(
        "choose_target", player_id,
        "Subjugating Chains: Switch a Benched {D} Pokémon (not Pecharunt ex) to Active.",
        targets=eligible,
    )
    resp = yield req
    target = None
    if resp and resp.target_instance_id:
        target = next((p for p in eligible if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = eligible[0]

    _switch_active_with_bench(player, target)
    target.status_conditions.add(StatusCondition.POISONED)
    state.emit_event("subjugating_chains", player=player_id, new_active=target.card_name)


# Cursed Blast (sv08.5-036 Dusclops / sv08.5-037 Dusknoir) ─────────────────

def _cursed_blast(state: GameState, action, counters: int):
    """Place N damage counters on opponent's Pokémon; then KO this Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)

    # Damp: Psyduck prevents KO-self abilities
    if has_psyduck_damp(state):
        state.emit_event("damp_blocked", player=player_id, ability="Cursed Blast")
        return

    opp_targets = _in_play(opp)
    if not opp_targets:
        return

    req = ChoiceRequest(
        "choose_target", player_id,
        f"Cursed Blast: Put {counters} damage counters on one of opponent's Pokémon.",
        targets=opp_targets,
    )
    resp = yield req
    target = None
    if resp and resp.target_instance_id:
        target = next((p for p in opp_targets if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = min(opp_targets, key=lambda p: p.current_hp)

    target.current_hp -= counters * 10
    target.damage_counters += counters
    state.emit_event("cursed_blast", player=player_id,
                     target=target.card_name, counters=counters)
    check_ko(state, target, opp_id)

    if state.phase.name == "GAME_OVER":
        return

    # KO this Pokémon
    poke = _find_in_play(player, action.card_instance_id)
    if poke:
        poke.current_hp = 0
        check_ko(state, poke, player_id)


def _cursed_blast_dusclops(state: GameState, action):
    """Cursed Blast (Dusclops): 5 damage counters, then self KO."""
    yield from _cursed_blast(state, action, counters=5)


def _cursed_blast_dusknoir(state: GameState, action):
    """Cursed Blast (Dusknoir): 13 damage counters, then self KO."""
    yield from _cursed_blast(state, action, counters=13)


# Seething Spirit (sv09-024 Blaziken ex) ──────────────────────────────────────

def _seething_spirit(state: GameState, action):
    """Attach 1 Basic Energy from discard pile to 1 of your Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)

    basic_energy = [c for c in player.discard
                    if c.card_type.lower() == "energy"
                    and c.card_subtype.lower() == "basic"]
    all_pokes = _in_play(player)
    if not basic_energy or not all_pokes:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Seething Spirit: Choose a Basic Energy from discard to attach to a Pokémon.",
        cards=basic_energy, min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [basic_energy[0].instance_id])
    energy_card = next((c for c in player.discard if c.instance_id in chosen_ids), basic_energy[0])

    req2 = ChoiceRequest(
        "choose_target", player_id,
        "Seething Spirit: Choose a Pokémon to attach to.",
        targets=all_pokes,
    )
    resp2 = yield req2
    target = None
    if resp2 and resp2.target_instance_id:
        target = next((p for p in all_pokes if p.instance_id == resp2.target_instance_id), None)
    if target is None:
        target = all_pokes[0]

    _attach_from_hand_or_discard(player, target, energy_card)
    state.emit_event("seething_spirit", player=player_id,
                     card=energy_card.card_name, target=target.card_name)


# Trade (sv09-098 N's Zoroark ex) ─────────────────────────────────────────────

def _trade(state: GameState, action):
    """Discard 1 card from hand (cost), then draw 2 cards."""
    player_id = action.player_id
    player = state.get_player(player_id)
    if not player.hand:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Trade: Discard 1 card from hand, then draw 2.",
        cards=list(player.hand), min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [player.hand[0].instance_id])

    for iid in chosen_ids[:1]:
        card = next((c for c in player.hand if c.instance_id == iid), None)
        if card:
            player.hand.remove(card)
            card.zone = Zone.DISCARD
            player.discard.append(card)

    drawn = draw_cards(state, player_id, 2)
    state.emit_event("trade", player=player_id, cards_drawn=drawn)


# Charging Up (sv10-020 Team Rocket's Spidops) ────────────────────────────────

def _charging_up(state: GameState, action):
    """Attach 1 Basic Energy from discard pile to this Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)
    poke = _find_in_play(player, action.card_instance_id)
    if poke is None:
        return

    basic_energy = [c for c in player.discard
                    if c.card_type.lower() == "energy"
                    and c.card_subtype.lower() == "basic"]
    if not basic_energy:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Charging Up: Choose a Basic Energy from discard to attach to this Pokémon.",
        cards=basic_energy, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.selected_cards if resp and resp.selected_cards
                  else [basic_energy[0].instance_id])
    if not chosen_ids:
        return

    energy_card = next((c for c in player.discard if c.instance_id in chosen_ids), None)
    if energy_card is None:
        return

    _attach_from_hand_or_discard(player, poke, energy_card)
    state.emit_event("charging_up", player=player_id, target=poke.card_name)


# ──────────────────────────────────────────────────────────────────────────────
# register_all
# ──────────────────────────────────────────────────────────────────────────────

#: Ability names that trigger automatically when a Pokémon is played to bench.
BENCH_TRIGGER_ABILITIES: frozenset[str] = frozenset({
    "Rapid Vernier",       # sv05-025 Iron Leaves ex
    "Snow Sink",           # sv08-056 Chien-Pao
    "Battle-Hardened",     # sv08.5-054 Bloodmoon Ursaluna
    "Toxic Subjugation",   # svp-149 Pecharunt
    "Last-Ditch Catch",    # me03-062 Meowth ex
})

#: Ability names that trigger automatically when a Pokémon evolves.
EVOLVE_TRIGGER_ABILITIES: frozenset[str] = frozenset({
    "Psychic Draw",  # me01-055 Kadabra / me01-056 Alakazam
    "Punk Up",       # sv10-136 Marnie's Grimmsnarl ex
})


def register_all(registry: EffectRegistry) -> None:
    """Register all ability effect handlers with the registry."""

    # ── On-bench triggers ────────────────────────────────────────────────────
    registry.register_ability("sv05-025", "Rapid Vernier", _rapid_vernier)
    registry.register_ability("sv08-056", "Snow Sink", _snow_sink)
    registry.register_ability("sv08.5-054", "Battle-Hardened", _battle_hardened)
    registry.register_ability("svp-149", "Toxic Subjugation", _toxic_subjugation)
    registry.register_ability("me03-062", "Last-Ditch Catch", _last_ditch_catch)

    # ── On-evolve triggers ───────────────────────────────────────────────────
    registry.register_ability("me01-055", "Psychic Draw", _psychic_draw_kadabra)
    registry.register_ability("me01-056", "Psychic Draw", _psychic_draw_alakazam)
    registry.register_ability("sv10-136", "Punk Up", _punk_up)

    # ── Active-use abilities ─────────────────────────────────────────────────

    # Lunar Cycle: requires Solrock in play + Basic {F} energy in hand.
    def _cond_lunar_cycle(state, player_id):
        p = state.get_player(player_id)
        has_solrock = any("Solrock" in pk.card_name for pk in _in_play(p))
        has_f_energy = any(
            c.card_type.lower() == "energy"
            and c.card_subtype.lower() == "basic"
            and "Fighting" in (c.energy_provides or [])
            for c in p.hand
        )
        return has_solrock and has_f_energy

    registry.register_ability("me01-074", "Lunar Cycle", _lunar_cycle,
                               condition=_cond_lunar_cycle)
    registry.register_ability("me01-104", "Run Errand", _run_errand)

    # Sinister Surge: requires Basic {D} energy in deck + {D} Pokémon on bench.
    def _cond_sinister_surge(state, player_id):
        p = state.get_player(player_id)
        has_d_energy = any(
            c.card_type.lower() == "energy"
            and c.card_subtype.lower() == "basic"
            and "Darkness" in (c.energy_provides or [])
            for c in p.deck
        )
        has_d_bench = any(_pokemon_has_type(pk, "Darkness") for pk in p.bench)
        return has_d_energy and has_d_bench

    registry.register_ability("me02-068", "Sinister Surge", _sinister_surge,
                               condition=_cond_sinister_surge)

    # Flip the Script: only useful if a Pokémon was KO'd on the opponent's last turn.
    def _cond_flip_the_script(state, player_id):
        opp_turn = state.turn_number - 1
        return any(
            e.get("event") == "ko"
            and e.get("ko_player") == player_id
            and e.get("turn", -1) == opp_turn
            for e in state.events
        )

    registry.register_ability("me02.5-142", "Flip the Script", _flip_the_script,
                               condition=_cond_flip_the_script)

    # Stone Arms: requires Basic {F} energy in hand + {F} Pokémon in play.
    def _cond_stone_arms(state, player_id):
        p = state.get_player(player_id)
        has_f_energy = any(
            c.card_type.lower() == "energy"
            and c.card_subtype.lower() == "basic"
            and "Fighting" in (c.energy_provides or [])
            for c in p.hand
        )
        has_f_poke = any(_pokemon_has_type(pk, "Fighting") for pk in _in_play(p))
        return has_f_energy and has_f_poke

    registry.register_ability("me03-043", "Stone Arms", _stone_arms,
                               condition=_cond_stone_arms)
    registry.register_ability("sv05-129", "Run Away Draw", _run_away_draw)
    registry.register_ability("sv06-025", "Teal Dance", _teal_dance)

    # Adrena-Brain: requires {D} energy on this Munkidori + your Pokémon with damage counters.
    def _cond_adrena_brain(state, player_id, poke=None):
        if poke is not None and not _has_d_energy(poke):
            return False
        p = state.get_player(player_id)
        return any(pk.damage_counters > 0 for pk in _in_play(p))

    registry.register_ability("sv06-095", "Adrena-Brain", _adrena_brain,
                               condition=_cond_adrena_brain)
    registry.register_ability("sv06-129", "Recon Directive", _recon_directive)
    registry.register_ability("sv06.5-039", "Subjugating Chains", _subjugating_chains)
    registry.register_ability("sv08.5-036", "Cursed Blast", _cursed_blast_dusclops,
                               condition=lambda state, pid: not has_psyduck_damp(state))
    registry.register_ability("sv08.5-037", "Cursed Blast", _cursed_blast_dusknoir,
                               condition=lambda state, pid: not has_psyduck_damp(state))
    registry.register_ability("sv09-024", "Seething Spirit", _seething_spirit)
    registry.register_ability("sv09-098", "Trade", _trade)
    registry.register_ability("sv10-020", "Charging Up", _charging_up)

    # ── Passive abilities (no USE_ABILITY handler needed) ────────────────────
    # me01-010  Meganium          Wild Growth        → actions.py _can_pay_energy_cost
    # me02.5-039 Psyduck          Damp               → _cursed_blast handler above
    # sv06-053  Froslass          Freezing Shroud    → runner.py _handle_between_turns
    # sv06-096  Fezandipiti       Adrena-Pheromone   → registry.py _default_damage
    # sv06-111  Okidogi           Adrena-Power       → registry.py _default_damage + check_ko
    # sv06-112  Cornerstone …ex   Cornerstone Stance → registry.py _default_damage
    # sv06-141  Bloodmoon Ursaluna ex  Seasoned Skill → attacks.py Blood Moon handler
    # sv08-076  Latias ex         Skyliner           → base.py get_retreat_cost_reduction
    # sv09-056  Lillie's Clefairy ex  Fairy Zone     → base.py apply_weakness_resistance
    # sv10-010  Shaymin           Flower Curtain     → bench-hit attack handlers in attacks.py
    # sv10-012  Crustle           Mysterious Rock Inn → registry.py _default_damage
    # sv10-051  TR Articuno       Repelling Veil     → attack effect handlers in attacks.py
    # sv10-081  TR Mewtwo ex      Power Saver        → actions.py _get_attack_actions
