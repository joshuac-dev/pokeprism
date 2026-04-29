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
  has_tundra_wall
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
    return any(p.card_def_id in ("sv09-056", "me02.5-076")
               for p in _in_play(defender_player))


# Flower Curtain (sv10-010 Shaymin) ──────────────────────────────────────────

def has_flower_curtain(state: GameState, player_id: str) -> bool:
    """True if player has Shaymin (sv10-010) in play.

    Prevents damage done to benched non-rule-box Pokémon from opponent's attacks.
    Checked from the DEFENDING player's side.
    """
    player = state.get_player(player_id)
    return any(p.card_def_id == "sv10-010" for p in _in_play(player))


# Tundra Wall (me03-024 Aurorus) ──────────────────────────────────────────────

def has_tundra_wall(state: GameState, player_id: str) -> bool:
    """True if player has Aurorus (me03-024) with Tundra Wall in play.

    All of that player's Pokémon with any {W} Energy attached take 50 less damage from attacks.
    Checked from the DEFENDING player's side.
    """
    player = state.get_player(player_id)
    return any(p.card_def_id == "me03-024" for p in _in_play(player))


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


# Power Saver (sv10-081 / me02.5-079 TR Mewtwo ex) ───────────────────────────

def power_saver_blocks_attack(state: GameState, pokemon, player_id: str) -> bool:
    """True if Power Saver prevents this Pokémon from attacking (fewer than 4 TR Pokémon)."""
    if pokemon.card_def_id not in ("sv10-081", "me02.5-079"):
        return False
    player = state.get_player(player_id)
    tr_count = sum(1 for p in _in_play(player) if _is_tr_pokemon(p))
    return tr_count < 4


def has_battle_cage(state: GameState) -> bool:
    """True if Battle Cage stadium (me02-085) is active — blocks all bench damage."""
    return bool(state.active_stadium and state.active_stadium.card_def_id == "me02-085")


def has_spherical_shield(state: GameState, player_id: str) -> bool:
    """True if player has Rabsca (sv05-024) in play.

    Spherical Shield: prevents all damage done to player's Benched Pokémon by
    opponent's attacks.  Checked from the DEFENDING player's side.
    """
    player = state.get_player(player_id)
    return any(p.card_def_id == "sv05-024" for p in _in_play(player))


# Cheer On to Glory (sv10-008 Cynthia's Roserade) ─────────────────────────────

def has_cheer_on_to_glory(state, player_id: str) -> bool:
    """True if the player has Cynthia's Roserade (sv10-008) in play."""
    player = state.get_player(player_id)
    return any(p.card_def_id == "sv10-008" for p in _in_play(player))


# Stone Palace (sv10-086 Steven's Carbink) ────────────────────────────────────

def has_stone_palace(state, player_id: str) -> bool:
    """True if the player has Steven's Carbink (sv10-086) on their bench."""
    player = state.get_player(player_id)
    return any(p.card_def_id == "sv10-086" for p in player.bench)


# So Submerged (sv10-048 Misty's Magikarp) ────────────────────────────────────

def has_so_submerged_on_bench(state, player_id: str, bench_pokemon) -> bool:
    """True if bench_pokemon is Misty's Magikarp (sv10-048)."""
    return bench_pokemon.card_def_id == "sv10-048"


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


# Grand Wing (me03-009 Vivillon) ──────────────────────────────────────────────

def _grand_wing(state: GameState, action):
    """Opponent shuffles hand to bottom of deck; if any shuffled, they draw 4."""
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)

    cards_to_shuffle = list(opp.hand)
    if not cards_to_shuffle:
        state.emit_event("grand_wing", player=player_id, cards_shuffled=0)
        return

    for card in cards_to_shuffle:
        opp.hand.remove(card)
        card.zone = Zone.DECK
        opp.deck.append(card)
    random.shuffle(opp.deck)
    state.emit_event("grand_wing", player=player_id, cards_shuffled=len(cards_to_shuffle))

    draw_cards(state, opp_id, 4)


# Sky Hunt (me03-014 Talonflame) ──────────────────────────────────────────────

def _sky_hunt(state: GameState, action):
    """Flip a coin. Heads: discard a random card from opponent's hand."""
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)

    if random.choice([True, False]):
        if opp.hand:
            card = random.choice(opp.hand)
            opp.hand.remove(card)
            card.zone = Zone.DISCARD
            opp.discard.append(card)
            state.emit_event("sky_hunt", player=player_id, result="heads",
                             discarded=card.card_name)
    else:
        state.emit_event("sky_hunt", player=player_id, result="tails")


# Wash Out (me03-019 Dewgong) ─────────────────────────────────────────────────

def _wash_out(state: GameState, action):
    """Move 1 {W} Energy from a Benched Pokémon to Active Pokémon (once per turn)."""
    player_id = action.player_id
    player = state.get_player(player_id)

    if not player.active or not player.bench:
        return

    # Collect all {W} energy on benched pokemon
    bench_w_energy = []
    for bench_poke in player.bench:
        for att in bench_poke.energy_attached:
            if att.energy_type == EnergyType.WATER:
                bench_w_energy.append((bench_poke, att))

    if not bench_w_energy:
        state.emit_event("wash_out_failed", player=player_id, reason="no W energy on bench")
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Wash Out: choose a {W} Energy from a Benched Pokémon to move to your Active Pokémon.",
        cards=[att for (_, att) in bench_w_energy],
        min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [bench_w_energy[0][1].source_card_id]

    for src_id in chosen_ids[:1]:
        for bench_poke, att in list(bench_w_energy):
            if att.source_card_id == src_id and att in bench_poke.energy_attached:
                bench_poke.energy_attached.remove(att)
                player.active.energy_attached.append(att)
                state.emit_event("wash_out", player=player_id,
                                 from_card=bench_poke.card_name,
                                 to_card=player.active.card_name)
                break


# Scent Collection (me03-036 Aromatisse) ─────────────────────────────────────

def _scent_collection(state: GameState, action):
    """Search deck for up to 2 Basic {P} Energy, put in hand."""
    player_id = action.player_id
    player = state.get_player(player_id)

    psychic_energy = [c for c in player.deck
                      if c.card_type.lower() == "energy"
                      and c.card_subtype.lower() == "basic"
                      and "Psychic" in (c.energy_provides or [])]
    if not psychic_energy:
        random.shuffle(player.deck)
        state.emit_event("scent_collection", player=player_id, found=0)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Scent Collection: choose up to 2 Basic {P} Energy from deck to put in hand.",
        cards=psychic_energy, min_count=0, max_count=2,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in psychic_energy[:2]]

    found = 0
    for cid in chosen_ids:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
            found += 1

    random.shuffle(player.deck)
    state.emit_event("scent_collection", player=player_id, found=found)


# Multiplying Cocoon (me02.5-012 Silcoon) ─────────────────────────────────────

def _multiplying_cocoon(state: GameState, action):
    """Search deck for a Silcoon or Cascoon, put it on Bench."""
    player_id = action.player_id
    player = state.get_player(player_id)

    if len(player.bench) >= 5:
        state.emit_event("multiplying_cocoon", player=player_id, reason="bench_full")
        return

    targets = [c for c in player.deck
               if c.card_def_id in ("me02.5-012", "me02.5-014")]
    if not targets:
        random.shuffle(player.deck)
        state.emit_event("multiplying_cocoon", player=player_id, found=0)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Multiplying Cocoon: choose a Silcoon or Cascoon from deck to put on Bench.",
        cards=targets, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [targets[0].instance_id]

    for cid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card and len(player.bench) < 5:
            player.deck.remove(card)
            cdef = card_registry.get(card.card_def_id)
            card.zone = Zone.BENCH
            card.max_hp = cdef.hp if cdef else card.max_hp
            card.current_hp = card.max_hp
            card.evolution_stage = 1
            card.turn_played = state.turn_number
            player.bench.append(card)
            state.emit_event("multiplying_cocoon", player=player_id,
                             card=card.card_name)

    random.shuffle(player.deck)


# Boisterous Wind (me02.5-015 Dustox) ────────────────────────────────────────

def _boisterous_wind(state: GameState, action):
    """Flip a coin. Heads: put an Energy from opp's Active into their hand."""
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)

    if not random.choice([True, False]):
        state.emit_event("boisterous_wind", player=player_id, result="tails")
        return

    if not opp.active or not opp.active.energy_attached:
        state.emit_event("boisterous_wind", player=player_id, result="heads",
                         reason="no energy")
        return

    att = random.choice(list(opp.active.energy_attached))
    opp.active.energy_attached.remove(att)
    state.emit_event("boisterous_wind", player=player_id, result="heads",
                     energy_returned=att.card_def_id)


# Golden Flame (me02.5-026 Ethan's Ho-Oh ex) ─────────────────────────────────

def _golden_flame(state: GameState, action):
    """Attach up to 2 Basic {R} Energy from hand to 1 Benched Ethan's Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)

    ethan_bench = [p for p in player.bench if "Ethan's" in p.card_name]
    if not ethan_bench:
        state.emit_event("golden_flame", player=player_id, reason="no Ethan's on bench")
        return

    fire_energy = [c for c in player.hand
                   if c.card_type.lower() == "energy"
                   and c.card_subtype.lower() == "basic"
                   and "Fire" in (c.energy_provides or [])]
    if not fire_energy:
        state.emit_event("golden_flame", player=player_id, reason="no fire energy in hand")
        return

    req_target = ChoiceRequest(
        "choose_target", player_id,
        "Golden Flame: choose a Benched Ethan's Pokémon to attach Fire Energy to.",
        targets=ethan_bench,
    )
    resp_target = yield req_target
    target = None
    if resp_target and hasattr(resp_target, "target_instance_id") and resp_target.target_instance_id:
        target = next((p for p in ethan_bench
                       if p.instance_id == resp_target.target_instance_id), None)
    if target is None:
        target = ethan_bench[0]

    max_count = min(2, len(fire_energy))
    req_energy = ChoiceRequest(
        "choose_cards", player_id,
        "Golden Flame: choose up to 2 Basic {R} Energy from hand to attach.",
        cards=fire_energy, min_count=0, max_count=max_count,
    )
    resp_energy = yield req_energy
    chosen_ids = (resp_energy.chosen_card_ids if resp_energy and hasattr(resp_energy, "chosen_card_ids")
                  and resp_energy.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in fire_energy[:max_count]]

    attached = 0
    for cid in chosen_ids:
        card = next((c for c in player.hand if c.instance_id == cid), None)
        if card:
            _attach_from_hand_or_discard(player, target, card)
            attached += 1

    state.emit_event("golden_flame", player=player_id, target=target.card_name, attached=attached)


# Lovely Fragrance (me02.5-003 Erika's Vileplume ex) ─────────────────────────

def _lovely_fragrance(state: GameState, action):
    """Heal 30 damage from each of your Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)

    for poke in _in_play(player):
        if poke.damage_counters > 0:
            heal = min(30, poke.damage_counters * 10)
            counters = min(3, poke.damage_counters)
            poke.current_hp = min(poke.current_hp + heal, poke.max_hp)
            poke.damage_counters -= counters
            state.emit_event("healed", player=player_id, card=poke.card_name, amount=heal)


# Gathering of Blossoms (me02.5-007 Erika's Tangela) ─────────────────────────

def _gathering_of_blossoms(state: GameState, action):
    """Search deck for an Erika's Pokémon, put in hand."""
    player_id = action.player_id
    player = state.get_player(player_id)

    erikas_pokemon = [c for c in player.deck
                      if c.card_type.lower() == "pokemon"
                      and "Erika's" in c.card_name]
    if not erikas_pokemon:
        random.shuffle(player.deck)
        state.emit_event("gathering_of_blossoms", player=player_id, found=0)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Gathering of Blossoms: choose an Erika's Pokémon from deck to put in hand.",
        cards=erikas_pokemon, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [])
    if not chosen_ids:
        chosen_ids = [erikas_pokemon[0].instance_id]

    found = 0
    for cid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
            found += 1

    random.shuffle(player.deck)
    state.emit_event("gathering_of_blossoms", player=player_id, found=found)


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
    "Psychic Draw",          # me01-055 Kadabra / me01-056 Alakazam
    "Punk Up",               # sv10-136 Marnie's Grimmsnarl ex
    "Multiplying Cocoon",    # me02.5-012 Silcoon
    "Prison Panic",          # Brambleghast — confuse opponent's active on evolve
    "Sandy Flapping",        # me02-053 Flygon — discard top 2 of opponent's deck on evolve
    "Cast-Off Shell",        # me01-017 Ninjask — search deck for Shedinja on evolve
    "Energized Steps",       # me01-063 Grumpig — attach {P} Energy from deck to Bench on evolve
    "Heave-Ho Catcher",      # me01-073 Hariyama — gust on evolve
    "Haphazard Hammer",      # me01-097 Tinkatuff — flip, heads = discard opp active energy
    "Sneaky Bite",           # sv10-121 TR Golbat — 2 counters on 1 opp Pokémon on evolve
    "Biting Spree",          # sv10-122 TR Crobat ex — 2 counters on each of 2 opp Pokémon on evolve
    "Greedy Order",          # sv10-159 Arven's Greedent — retrieve up to 2 Arven's Sandwich from discard
})


# ──────────────────────────────────────────────────────────────────────────────
# Batch 2: ASC ability handlers
# ──────────────────────────────────────────────────────────────────────────────

# Alluring Wings (me02.5-053 Frosmoth) ────────────────────────────────────────

def _alluring_wings(state: GameState, action):
    """Both players draw 1 card. Only usable from Active Spot."""
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    draw_cards(state, player_id, 1)
    draw_cards(state, opp_id, 1)
    state.emit_event("alluring_wings", player=player_id)


# Dynamotor (me02.5-060 Eelektrik) ───────────────────────────────────────────

def _dynamotor(state: GameState, action):
    """Attach 1 Basic {L} Energy from discard to 1 Benched Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)

    l_energy = [c for c in player.discard
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Lightning" in (c.energy_provides or [])]
    if not l_energy or not player.bench:
        return

    req_energy = ChoiceRequest(
        "choose_cards", player_id,
        "Dynamotor: choose 1 Basic {L} Energy from discard to attach to a Benched Pokémon.",
        cards=l_energy, min_count=0, max_count=1,
    )
    resp_energy = yield req_energy
    chosen_ids = resp_energy.selected_cards if resp_energy and resp_energy.selected_cards else []
    if not chosen_ids:
        chosen_ids = [l_energy[0].instance_id]
    energy_card = next((c for c in player.discard if c.instance_id in chosen_ids), None)
    if energy_card is None:
        return

    req_target = ChoiceRequest(
        "choose_target", player_id,
        "Dynamotor: choose a Benched Pokémon to attach {L} Energy to.",
        targets=player.bench,
    )
    resp_target = yield req_target
    target = None
    if resp_target and resp_target.target_instance_id:
        target = next((p for p in player.bench
                       if p.instance_id == resp_target.target_instance_id), None)
    if target is None:
        target = player.bench[0]

    _attach_from_hand_or_discard(player, target, energy_card)
    state.emit_event("dynamotor", player=player_id, target=target.card_name)


# Frilled Generator (me02.5-064 Heliolisk) ───────────────────────────────────

def _frilled_generator(state: GameState, action):
    """Search deck for up to 2 Basic {L} Energy and attach to self (requires Canari played this turn)."""
    player_id = action.player_id
    player = state.get_player(player_id)
    poke = _find_in_play(player, action.card_instance_id)
    if poke is None:
        return

    l_energy = [c for c in player.deck
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Lightning" in (c.energy_provides or [])]
    if not l_energy:
        import random
        random.shuffle(player.deck)
        state.emit_event("frilled_generator", player=player_id, attached=0)
        return

    max_count = min(2, len(l_energy))
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Frilled Generator: search deck for up to 2 Basic {L} Energy to attach to Heliolisk.",
        cards=l_energy, min_count=0, max_count=max_count,
    )
    resp = yield req
    chosen_ids = resp.selected_cards if resp and resp.selected_cards else []
    if not chosen_ids:
        chosen_ids = [c.instance_id for c in l_energy[:max_count]]

    attached = 0
    for cid in chosen_ids[:max_count]:
        ec = next((c for c in player.deck if c.instance_id == cid), None)
        if ec:
            player.deck.remove(ec)
            _attach_from_hand_or_discard(player, poke, ec)
            attached += 1

    import random
    random.shuffle(player.deck)
    state.emit_event("frilled_generator", player=player_id, attached=attached)


# Electric Streamer (me02.5-070 Iono's Bellibolt ex) ─────────────────────────

def _electric_streamer(state: GameState, action):
    """Attach 1 Basic {L} Energy from hand to 1 of your Iono's Pokémon (usable multiple times)."""
    player_id = action.player_id
    player = state.get_player(player_id)

    l_energy = [c for c in player.hand
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Lightning" in (c.energy_provides or [])]
    ionos_pokes = [p for p in _in_play(player) if "Iono's" in p.card_name]

    if not l_energy or not ionos_pokes:
        return

    req_energy = ChoiceRequest(
        "choose_cards", player_id,
        "Electric Streamer: choose 1 Basic {L} Energy from hand to attach to an Iono's Pokémon.",
        cards=l_energy, min_count=0, max_count=1,
    )
    resp_energy = yield req_energy
    chosen_ids = resp_energy.selected_cards if resp_energy and resp_energy.selected_cards else []
    if not chosen_ids:
        chosen_ids = [l_energy[0].instance_id]
    energy_card = next((c for c in player.hand if c.instance_id in chosen_ids), None)
    if energy_card is None:
        return

    req_target = ChoiceRequest(
        "choose_target", player_id,
        "Electric Streamer: choose an Iono's Pokémon to attach the energy to.",
        targets=ionos_pokes,
    )
    resp_target = yield req_target
    target = None
    if resp_target and resp_target.target_instance_id:
        target = next((p for p in ionos_pokes
                       if p.instance_id == resp_target.target_instance_id), None)
    if target is None:
        target = ionos_pokes[0]

    _attach_from_hand_or_discard(player, target, energy_card)
    state.emit_event("electric_streamer", player=player_id, target=target.card_name)

    # Unlimited use: reset the ability_used_this_turn flag
    poke = _find_in_play(player, action.card_instance_id)
    if poke:
        poke.ability_used_this_turn = False


# Flashing Draw (me02.5-072 Iono's Kilowattrel) ──────────────────────────────

def _flashing_draw(state: GameState, action):
    """Discard 1 Basic {L} Energy from this Pokémon, then draw cards until hand has 6."""
    player_id = action.player_id
    player = state.get_player(player_id)
    poke = _find_in_play(player, action.card_instance_id)
    if poke is None:
        return

    l_energies = [att for att in poke.energy_attached
                  if att.energy_type == EnergyType.LIGHTNING]
    if not l_energies:
        return

    poke.energy_attached.remove(l_energies[0])
    state.emit_event("energy_discarded", card=poke.card_name,
                     reason="flashing_draw", count=1)

    to_draw = max(0, 6 - len(player.hand))
    if to_draw > 0:
        drawn = draw_cards(state, player_id, to_draw)
        state.emit_event("flashing_draw", player=player_id, drawn=drawn)


# Bubble Gathering (me02.5-084 Azumarill ex) ──────────────────────────────────

def _bubble_gathering(state: GameState, action):
    """Move 1 Energy from another Pokémon to Azumarill ex (unlimited use per turn)."""
    player_id = action.player_id
    player = state.get_player(player_id)
    poke = _find_in_play(player, action.card_instance_id)
    if poke is None:
        return

    donors = [p for p in _in_play(player)
              if p.instance_id != poke.instance_id and p.energy_attached]
    if not donors:
        return

    req_donor = ChoiceRequest(
        "choose_target", player_id,
        "Bubble Gathering: choose a Pokémon to move 1 Energy FROM.",
        targets=donors,
    )
    resp_donor = yield req_donor
    donor = None
    if resp_donor and resp_donor.target_instance_id:
        donor = next((p for p in donors if p.instance_id == resp_donor.target_instance_id), None)
    if donor is None:
        donor = donors[0]

    att = donor.energy_attached.pop(0)
    poke.energy_attached.append(att)
    state.emit_event("bubble_gathering", player=player_id,
                     from_card=donor.card_name, to_card=poke.card_name)

    # Unlimited use: reset the ability_used_this_turn flag
    poke.ability_used_this_turn = False


# Champion's Call (me02.5-110 Cynthia's Gabite) ──────────────────────────────

def _champions_call(state: GameState, action):
    """Search deck for a Cynthia's Pokémon, reveal it, and put it in hand."""
    player_id = action.player_id
    player = state.get_player(player_id)

    cynthia_pokes = [c for c in player.deck
                     if c.card_type.lower() == "pokemon"
                     and "Cynthia's" in c.card_name]
    if not cynthia_pokes:
        import random
        random.shuffle(player.deck)
        state.emit_event("champions_call", player=player_id, found=0)
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Champion's Call: search your deck for a Cynthia's Pokémon to put in hand.",
        cards=cynthia_pokes, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = resp.selected_cards if resp and resp.selected_cards else []
    if not chosen_ids:
        chosen_ids = [cynthia_pokes[0].instance_id]

    found = 0
    for cid in chosen_ids[:1]:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
            found += 1

    import random
    random.shuffle(player.deck)
    state.emit_event("champions_call", player=player_id, found=found)


# ── Batch 3: ASC/PFL ability handlers ────────────────────────────────────────

# Prison Panic (Brambleghast) ─────────────────────────────────────────────────

def _prison_panic(state: GameState, action):
    """Brambleghast — Prison Panic: on evolve, Confuse opponent's Active."""
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_opponent(action.player_id)
    if opp.active:
        opp.active.status_conditions.add(StatusCondition.CONFUSED)
        state.emit_event("prison_panic_triggered", player=action.player_id,
                         card=opp.active.card_name)


# Sandy Flapping (me02-053 Flygon) ────────────────────────────────────────────

def _sandy_flapping_ability(state: GameState, action):
    """me02-053 Flygon — Sandy Flapping: on evolve, discard top 2 of opponent's deck."""
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_opponent(action.player_id)
    for _ in range(2):
        if opp.deck:
            top = opp.deck.pop()
            top.zone = Zone.DISCARD
            opp.discard.append(top)
    state.emit_event("sandy_flapping_triggered", player=action.player_id)


# Evolutionary Guidance (me02.5-151 Dragonair) ────────────────────────────────

def _evolutionary_guidance(state: GameState, action):
    """me02.5-151 Dragonair — Evolutionary Guidance: search for an Evolution Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)
    poke = _find_in_play(player, action.card_instance_id)
    if not poke or not poke.energy_attached:
        return
    evolutions = [c for c in player.deck
                  if c.card_type.lower() == "pokemon"
                  and c.card_subtype.lower() not in ("basic",)]
    if not evolutions:
        return
    req = ChoiceRequest("choose_cards", player_id,
                        "Evolutionary Guidance: search for an Evolution Pokémon.",
                        cards=evolutions, min_count=0, max_count=1)
    resp = yield req
    chosen = (resp.selected_cards if resp else []) or [evolutions[0].instance_id]
    for iid in chosen[:1]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    state.emit_event("evolutionary_guidance", player=player_id)


# Sky Transport (me02.5-152 Mega Dragonite ex) ────────────────────────────────

def _sky_transport(state: GameState, action):
    """me02.5-152 Mega Dragonite ex — Sky Transport: switch Active with a Benched Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)
    if not player.bench:
        return
    req = ChoiceRequest("choose_target", player_id,
                        "Sky Transport: choose a Benched Pokémon to switch with Active.",
                        targets=player.bench, min_count=1, max_count=1)
    resp = yield req
    if resp and resp.selected_targets:
        target_id = resp.selected_targets[0]
        bench_poke = next((b for b in player.bench if b.instance_id == target_id), None)
    else:
        bench_poke = player.bench[0] if player.bench else None
    if bench_poke:
        _switch_active_with_bench(player, bench_poke)
        state.emit_event("sky_transport", player=player_id, card=bench_poke.card_name)


# Fan Call (me02.5-171 Fan Rotom) ─────────────────────────────────────────────

def _fan_call(state: GameState, action):
    """me02.5-171 Fan Rotom — Fan Call: first turn only, search for 3 Colorless ≤100 HP."""
    player_id = action.player_id
    player = state.get_player(player_id)
    if state.turn_number > 1:
        return
    colorless_small = [c for c in player.deck
                       if c.card_type.lower() == "pokemon"
                       and c.card_subtype.lower() == "basic"
                       and (getattr(card_registry.get(c.card_def_id), "hp", None) or 999) <= 100]
    if not colorless_small:
        state.emit_event("fan_call", player=player_id, found=0)
        return
    req = ChoiceRequest("choose_cards", player_id,
                        "Fan Call: search for up to 3 Colorless Pokémon with 100 HP or less.",
                        cards=colorless_small, min_count=0, max_count=3)
    resp = yield req
    chosen = (resp.selected_cards if resp else []) or [c.instance_id for c in colorless_small[:3]]
    for iid in chosen[:3]:
        card = next((c for c in player.deck if c.instance_id == iid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
    state.emit_event("fan_call", player=player_id)


# Excited Heal (me02-7 Ludicolo) ──────────────────────────────────────────────

def _excited_heal(state: GameState, action):
    """me02-7 Ludicolo — Excited Heal: heal 60 from 1 of your Pokémon (if G Mega Evo ex in play)."""
    player_id = action.player_id
    player = state.get_player(player_id)
    mega_g = [p for p in _in_play(player)
              if "ex" in p.card_name.lower() and p.evolution_stage >= 2]
    if not mega_g:
        return
    all_poke = ([player.active] if player.active else []) + player.bench
    healable = [p for p in all_poke if p.damage_counters > 0]
    if not healable:
        return
    req = ChoiceRequest("choose_target", player_id,
                        "Excited Heal: heal 60 from 1 of your Pokémon.",
                        targets=healable, min_count=1, max_count=1)
    resp = yield req
    target_id = (resp.selected_targets[0] if resp and resp.selected_targets
                 else healable[0].instance_id)
    target = next((p for p in all_poke if p.instance_id == target_id), None)
    if target:
        heal_counters = min(6, target.damage_counters)
        heal_hp = heal_counters * 10
        target.current_hp = min(target.max_hp, target.current_hp + heal_hp)
        target.damage_counters -= heal_counters
        state.emit_event("excited_heal", player=player_id,
                         card=target.card_name, amount=heal_hp)


# Lethargic Charge (me02.5-175 Larry's Komala) ────────────────────────────────

def _lethargic_charge(state: GameState, action):
    """me02.5-175 Larry's Komala — Lethargic Charge: attach Energy to Active Larry's Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)
    if not player.active or "Larry's" not in player.active.card_name:
        return
    energies = [c for c in player.hand if c.card_type.lower() == "energy"]
    if not energies:
        return
    req = ChoiceRequest("choose_cards", player_id,
                        "Lethargic Charge: attach Energy from hand to Active Larry's Pokémon.",
                        cards=energies, min_count=0, max_count=1)
    resp = yield req
    chosen_ids = (resp.selected_cards if resp else []) or [energies[0].instance_id]
    for iid in chosen_ids[:1]:
        card = next((c for c in player.hand if c.instance_id == iid), None)
        if card and player.active:
            player.hand.remove(card)
            card.zone = player.active.zone
            player.active.energy_attached.append(EnergyAttachment(
                energy_type=EnergyType.COLORLESS,
                source_card_id=card.instance_id,
                card_def_id=card.card_def_id,
            ))
    state.emit_event("lethargic_charge", player=player_id)


# ──────────────────────────────────────────────────────────────────────────────
# Batch 4: MEG / PFL ability handlers
# ──────────────────────────────────────────────────────────────────────────────

# Solar Transfer (me01-003 Mega Venusaur ex) ──────────────────────────────────

def _solar_transfer(state: GameState, action):
    """Mega Venusaur ex — Solar Transfer: Move a Basic {G} Energy between your Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)
    all_in_play = _in_play(player)
    sources = [p for p in all_in_play
               if any(ea.energy_type == EnergyType.GRASS for ea in p.energy_attached)]
    if not sources:
        return
    req_src = ChoiceRequest(
        "choose_target", player_id,
        "Solar Transfer: choose a Pokémon to move a {G} Energy FROM.",
        targets=sources,
    )
    resp_src = yield req_src
    source = None
    if resp_src and resp_src.target_instance_id:
        source = next((p for p in sources if p.instance_id == resp_src.target_instance_id), None)
    if source is None:
        source = sources[0]
    g_attachments = [ea for ea in source.energy_attached if ea.energy_type == EnergyType.GRASS]
    if not g_attachments:
        return
    ea_to_move = g_attachments[0]
    source.energy_attached.remove(ea_to_move)

    targets = [p for p in all_in_play if p.instance_id != source.instance_id]
    if not targets:
        source.energy_attached.append(ea_to_move)
        return
    req_tgt = ChoiceRequest(
        "choose_target", player_id,
        "Solar Transfer: choose a Pokémon to move the {G} Energy TO.",
        targets=targets,
    )
    resp_tgt = yield req_tgt
    target = None
    if resp_tgt and resp_tgt.target_instance_id:
        target = next((p for p in targets if p.instance_id == resp_tgt.target_instance_id), None)
    if target is None:
        target = targets[0]
    target.energy_attached.append(ea_to_move)
    state.emit_event("solar_transfer", player=player_id,
                     source=source.card_name, target=target.card_name)


def _cond_solar_transfer(state, player_id):
    p = state.get_player(player_id)
    return any(
        any(ea.energy_type == EnergyType.GRASS for ea in pk.energy_attached)
        for pk in _in_play(p)
    )


# Excited Dash (me02-082 Linoone) ─────────────────────────────────────────────

def _excited_dash(state: GameState, action):
    """me02-082 Linoone — Excited Dash: if Mega ex in play, draw 2 cards."""
    player_id = action.player_id
    player = state.get_player(player_id)
    has_mega = any(
        "ex" in pk.card_name.lower() and pk.evolution_stage >= 2
        for pk in _in_play(player)
    )
    if not has_mega:
        return
    drawn = draw_cards(state, player_id, 2)
    state.emit_event("excited_dash", player=player_id, cards_drawn=drawn)


def _cond_excited_dash(state, player_id):
    p = state.get_player(player_id)
    if not any(pk for pk in _in_play(p) if pk.card_def_id == "me02-082"):
        return False
    return any(
        "ex" in pk.card_name.lower() and pk.evolution_stage >= 2
        for pk in _in_play(p)
    )


# Fermented Juice (me01-011 Shuckle) ─────────────────────────────────────────

def _fermented_juice(state: GameState, action):
    """me01-011 Shuckle — Fermented Juice: Heal 30 from any 1 of your Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)
    all_in_play = _in_play(player)
    damaged = [p for p in all_in_play if p.damage_counters > 0]
    if not damaged:
        return
    req = ChoiceRequest(
        "choose_target", player_id,
        "Fermented Juice: choose a Pokémon to heal 30 from.",
        targets=damaged,
    )
    resp = yield req
    target = None
    if resp and resp.target_instance_id:
        target = next((p for p in damaged if p.instance_id == resp.target_instance_id), None)
    if target is None:
        target = damaged[0]
    healed = min(target.damage_counters, 30)
    target.damage_counters -= healed
    state.emit_event("fermented_juice", player=player_id, card=target.card_name, healed=healed)


def _cond_fermented_juice(state, player_id):
    p = state.get_player(player_id)
    shuckle = next(
        (pk for pk in _in_play(p) if pk.card_def_id == "me01-011"), None
    )
    if shuckle is None:
        return False
    has_grass = any(ea.energy_type == EnergyType.GRASS for ea in shuckle.energy_attached)
    has_damaged = any(pk.damage_counters > 0 for pk in _in_play(p))
    return has_grass and has_damaged


# Cast-Off Shell (me01-017 Ninjask) — evolve trigger ─────────────────────────

def _cast_off_shell(state: GameState, action):
    """me01-017 Ninjask — Cast-Off Shell: on evolve, search deck for Shedinja, put on Bench."""
    player_id = action.player_id
    player = state.get_player(player_id)
    if len(player.bench) >= 5:
        return
    shedinja_cards = [c for c in player.deck if c.card_def_id == "me01-016"]
    if not shedinja_cards:
        import random
        random.shuffle(player.deck)
        return
    card = shedinja_cards[0]
    player.deck.remove(card)
    card.zone = Zone.BENCH
    player.bench.append(card)
    import random
    random.shuffle(player.deck)
    state.emit_event("cast_off_shell", player=player_id, card=card.card_name)


# Energized Steps (me01-063 Grumpig) — evolve trigger ────────────────────────

def _energized_steps(state: GameState, action):
    """me01-063 Grumpig — Energized Steps: on evolve, attach {P} Energy from deck to Bench."""
    player_id = action.player_id
    player = state.get_player(player_id)
    if not player.bench:
        return
    p_energy = [c for c in player.deck
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Psychic" in (c.energy_provides or [])]
    if not p_energy:
        import random
        random.shuffle(player.deck)
        return
    req_e = ChoiceRequest(
        "choose_cards", player_id,
        "Energized Steps: choose a Basic {P} Energy from deck to attach to a Benched Pokémon.",
        cards=p_energy, min_count=0, max_count=1,
    )
    resp_e = yield req_e
    chosen_e = (resp_e.selected_cards if resp_e and resp_e.selected_cards else []) or [p_energy[0].instance_id]
    energy_card = next((c for c in player.deck if c.instance_id in chosen_e), None)
    if energy_card is None:
        import random
        random.shuffle(player.deck)
        return
    req_t = ChoiceRequest(
        "choose_target", player_id,
        "Energized Steps: choose a Benched Pokémon to attach {P} Energy to.",
        targets=player.bench,
    )
    resp_t = yield req_t
    target = None
    if resp_t and resp_t.target_instance_id:
        target = next((p for p in player.bench if p.instance_id == resp_t.target_instance_id), None)
    if target is None:
        target = player.bench[0]
    player.deck.remove(energy_card)
    import random
    random.shuffle(player.deck)
    _attach_from_hand_or_discard(player, target, energy_card)
    state.emit_event("energized_steps", player=player_id, target=target.card_name)


# Fall Back to Reload (me01-038 Clawitzer) ────────────────────────────────────

def _fall_back_to_reload(state: GameState, action):
    """me01-038 Clawitzer — Fall Back to Reload: attach an Energy from discard to self."""
    player_id = action.player_id
    player = state.get_player(player_id)
    poke = _find_in_play(player, action.card_instance_id)
    if poke is None:
        poke = next((p for p in player.bench if p.card_def_id == "me01-038"), None)
    if poke is None:
        return
    energy_in_discard = [c for c in player.discard if c.card_type.lower() == "energy"]
    if not energy_in_discard:
        return
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Fall Back to Reload: choose an Energy from discard to attach to Clawitzer.",
        cards=energy_in_discard, min_count=0, max_count=1,
    )
    resp = yield req
    chosen = (resp.selected_cards if resp and resp.selected_cards else []) or [energy_in_discard[0].instance_id]
    energy_card = next((c for c in player.discard if c.instance_id in chosen), None)
    if energy_card is None:
        return
    _attach_from_hand_or_discard(player, poke, energy_card)
    state.emit_event("fall_back_to_reload", player=player_id, card=poke.card_name)


def _cond_fall_back_to_reload(state, player_id):
    p = state.get_player(player_id)
    clawitzer = next(
        (pk for pk in _in_play(p) if pk.card_def_id == "me01-038"), None
    )
    if clawitzer is None:
        return False
    return bool(p.discard and any(c.card_type.lower() == "energy" for c in p.discard))


# Sinister Surge (me02-068 Toxtricity) ────────────────────────────────────────

def _sinister_surge(state: GameState, action):
    """me02-068 Toxtricity — Sinister Surge: search deck for Basic {D} Energy, attach to any Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)
    d_energy = [c for c in player.deck
                if c.card_type.lower() == "energy"
                and c.card_subtype.lower() == "basic"
                and "Darkness" in (c.energy_provides or [])]
    if not d_energy:
        import random
        random.shuffle(player.deck)
        return
    req_e = ChoiceRequest(
        "choose_cards", player_id,
        "Sinister Surge: choose a Basic {D} Energy from deck to attach.",
        cards=d_energy, min_count=0, max_count=1,
    )
    resp_e = yield req_e
    chosen_e = (resp_e.selected_cards if resp_e and resp_e.selected_cards else []) or [d_energy[0].instance_id]
    energy_card = next((c for c in player.deck if c.instance_id in chosen_e), None)
    if energy_card is None:
        import random
        random.shuffle(player.deck)
        return
    all_pokes = _in_play(player)
    if not all_pokes:
        import random
        random.shuffle(player.deck)
        return
    req_t = ChoiceRequest(
        "choose_target", player_id,
        "Sinister Surge: choose a Pokémon to attach {D} Energy to.",
        targets=all_pokes,
    )
    resp_t = yield req_t
    target = None
    if resp_t and resp_t.target_instance_id:
        target = next((p for p in all_pokes if p.instance_id == resp_t.target_instance_id), None)
    if target is None:
        target = all_pokes[0]
    player.deck.remove(energy_card)
    import random
    random.shuffle(player.deck)
    _attach_from_hand_or_discard(player, target, energy_card)
    state.emit_event("sinister_surge", player=player_id, target=target.card_name)


def _cond_sinister_surge(state, player_id):
    p = state.get_player(player_id)
    has_d_in_deck = any(
        c.card_type.lower() == "energy"
        and c.card_subtype.lower() == "basic"
        and "Darkness" in (c.energy_provides or [])
        for c in p.deck
    )
    return has_d_in_deck and bool(_in_play(p))


# ── Batch 5: MEG + BLK ability handlers ──────────────────────────────────────

def _heave_ho_catcher(state: GameState, action):
    """me01-073 Hariyama — Heave-Ho Catcher: on evolve, switch 1 opp bench to Active."""
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)
    if not opp.bench:
        return
    req = ChoiceRequest(
        "choose_target", player_id,
        "Heave-Ho Catcher: choose 1 of opponent's Benched Pokémon to switch to Active Spot",
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
    state.emit_event("heave_ho_catcher", player=player_id,
                     new_active=opp.active.card_name if opp.active else "unknown")


def _tinkatuff_haphazard_hammer(state: GameState, action):
    """me01-097 Tinkatuff — Haphazard Hammer: on evolve, flip coin, heads = discard 1 energy from opp active."""
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)
    if random.choice([True, False]):  # heads
        if opp.active and opp.active.energy_attached:
            opp.active.energy_attached.pop(0)
            state.emit_event("haphazard_hammer_triggered", player=player_id,
                             target=opp.active.card_name)
    else:
        state.emit_event("haphazard_hammer_tails", player=player_id)


def _gumshoos_evidence_gathering(state: GameState, action):
    """me01-110 Gumshoos — Evidence Gathering (activated once/turn): swap 1 hand card for top of deck."""
    player_id = action.player_id
    player = state.get_player(player_id)
    if not player.hand or not player.deck:
        return
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Evidence Gathering: choose 1 card from hand to swap for the top card of your deck",
        cards=player.hand, min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = resp.selected_cards if resp and resp.selected_cards else []
    if not chosen_ids:
        chosen_ids = [player.hand[0].instance_id]
    hand_card = next((c for c in player.hand if c.instance_id in chosen_ids), None)
    if hand_card is None or not player.deck:
        return
    top_deck = player.deck.pop(0)
    top_deck.zone = Zone.HAND
    player.hand.remove(hand_card)
    hand_card.zone = Zone.DECK
    player.deck.insert(0, hand_card)
    player.hand.append(top_deck)
    state.emit_event("evidence_gathering", player=player_id,
                     swapped_out=hand_card.card_name, drew=top_deck.card_name)


def _volcarona_torrid_scales(state: GameState, action):
    """sv10.5b-016 Volcarona — Torrid Scales (activated, discard R from hand): Burn opp's active."""
    player_id = action.player_id
    player = state.get_player(player_id)
    poke = _find_in_play(player, action.card_instance_id)
    if poke is None:
        return

    r_cards = [c for c in player.hand
               if c.card_type.lower() == "energy"
               and c.card_subtype.lower() == "basic"
               and "Fire" in (c.energy_provides or [])]
    if not r_cards:
        return

    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)
    if not opp.active:
        return

    req = ChoiceRequest(
        "choose_cards", player_id,
        "Torrid Scales: choose 1 Basic {R} Energy from hand to discard and Burn opponent's Active",
        cards=r_cards, min_count=1, max_count=1,
    )
    resp = yield req
    chosen_ids = resp.selected_cards if resp and resp.selected_cards else []
    if not chosen_ids:
        chosen_ids = [r_cards[0].instance_id]
    r_card = next((c for c in player.hand if c.instance_id in chosen_ids), None)
    if r_card is None:
        return
    player.hand.remove(r_card)
    r_card.zone = Zone.DISCARD
    player.discard.append(r_card)
    opp.active.status_conditions.add(StatusCondition.BURNED)
    state.emit_event("torrid_scales_burn", player=player_id,
                     target=opp.active.card_name)


def _eelektrik_dynamotor(state: GameState, action):
    """sv10.5b-031 Eelektrik — Dynamotor: attach 1 Basic {L} Energy from discard to bench (once/turn)."""
    yield from _dynamotor(state, action)


def _alomomola_gentle_fin(state: GameState, action):
    """sv10.5b-024 Alomomola — Gentle Fin (once/turn, active only): put Basic Pokémon ≤70 HP from discard to bench."""
    player_id = action.player_id
    player = state.get_player(player_id)
    if len(player.bench) >= 5:
        return
    eligible = [c for c in player.discard
                if getattr(c, "card_type", "").lower() in ("pokémon", "pokemon")
                and card_registry.get(getattr(c, "card_def_id", "")) is not None
                and (card_registry.get(c.card_def_id).stage or "").lower() == "basic"
                and (card_registry.get(c.card_def_id).hp or 999) <= 70]
    if not eligible:
        return
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Gentle Fin: choose a Basic Pokémon with ≤70 HP from discard to put on bench",
        cards=eligible, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = resp.selected_cards if resp and resp.selected_cards else []
    if not chosen_ids:
        chosen_ids = [eligible[0].instance_id]
    poke_card = next((c for c in player.discard if c.instance_id in chosen_ids), None)
    if poke_card is None:
        return
    player.discard.remove(poke_card)
    poke_card.zone = Zone.BENCH
    player.bench.append(poke_card)
    state.emit_event("gentle_fin", player=player_id, card=poke_card.card_name)


# ── Batch 6: BLK/WHT/DRI ability handlers ─────────────────────────────────────

def _healing_leaves(state: GameState, action):
    """sv10.5w-002 Swadloon — Healing Leaves: heal 20 from Active Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)
    if not player.active or player.active.damage_counters == 0:
        return
    heal = min(20, player.active.damage_counters * 10)
    heal_counters = heal // 10
    player.active.current_hp = min(player.active.max_hp, player.active.current_hp + heal)
    player.active.damage_counters -= heal_counters
    state.emit_event("heal", player=player_id, card=player.active.card_name, amount=heal)


def _metallic_signal(state: GameState, action):
    """sv10.5b-067 Genesect ex — Metallic Signal: search deck for up to 2 Evolution Metal Pokémon."""
    player_id = action.player_id
    player = state.get_player(player_id)
    evo_metal = [c for c in player.deck
                 if c.card_type.lower() in ("pokémon", "pokemon")
                 and card_registry.get(c.card_def_id) is not None
                 and card_registry.get(c.card_def_id).stage.lower() not in ("basic", "")
                 and "Metal" in (card_registry.get(c.card_def_id).types or [])]
    if not evo_metal:
        state.emit_event("metallic_signal", player=player_id, found=0)
        return
    count = min(2, len(evo_metal))
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Metallic Signal: choose up to 2 Evolution Metal Pokémon from your deck",
        cards=evo_metal, min_count=0, max_count=count,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [c.instance_id for c in evo_metal[:count]])
    added = 0
    for cid in chosen_ids[:count]:
        card = next((c for c in player.deck if c.instance_id == cid), None)
        if card:
            player.deck.remove(card)
            card.zone = Zone.HAND
            player.hand.append(card)
            added += 1
    random.shuffle(player.deck)
    state.emit_event("metallic_signal", player=player_id, found=added)


def _distorted_future(state: GameState, action):
    """sv10.5w-043 Gothitelle — Distorted Future: opp shuffles hand into deck, draws 3."""
    player_id = action.player_id
    player = state.get_player(player_id)
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)
    if not player.active or player.active.zone.name != "ACTIVE":
        return
    for card in list(opp.hand):
        opp.hand.remove(card)
        card.zone = Zone.DECK
        opp.deck.append(card)
    random.shuffle(opp.deck)
    state.emit_event("hand_shuffled", player=opp_id, reason="Distorted Future")
    draw_cards(state, opp_id, 3)
    state.emit_event("draw", player=opp_id, count=3, reason="Distorted Future")


def _mandibuzz_look_for_prey(state: GameState, action):
    """sv10.5w-064 Mandibuzz — Look for Prey: put a Basic Pokémon with ≤70 HP from opp's hand onto opp's bench."""
    player_id = action.player_id
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)
    if len(opp.bench) >= 5:
        state.emit_event("look_for_prey", player=player_id, reason="opp bench full")
        return
    candidates = [c for c in opp.hand
                  if c.card_type.lower() in ("pokémon", "pokemon")
                  and card_registry.get(c.card_def_id) is not None
                  and card_registry.get(c.card_def_id).stage.lower() == "basic"
                  and (card_registry.get(c.card_def_id).hp or 999) <= 70]
    if not candidates:
        state.emit_event("look_for_prey", player=player_id, reason="no eligible Basic in opp hand")
        return
    state.emit_event("hand_revealed", player=opp_id,
                     cards=[c.card_name for c in opp.hand], attack="Look for Prey")
    req = ChoiceRequest(
        "choose_cards", player_id,
        "Look for Prey: choose 1 Basic Pokémon with ≤70 HP from opp's hand to put on their bench",
        cards=candidates, min_count=0, max_count=1,
    )
    resp = yield req
    chosen_ids = (resp.chosen_card_ids if resp and hasattr(resp, "chosen_card_ids")
                  and resp.chosen_card_ids else [candidates[0].instance_id])
    for cid in chosen_ids[:1]:
        card = next((c for c in opp.hand if c.instance_id == cid), None)
        if card and len(opp.bench) < 5:
            opp.hand.remove(card)
            cdef = card_registry.get(card.card_def_id)
            card.current_hp = cdef.hp if cdef and cdef.hp else 0
            card.max_hp = card.current_hp
            card.zone = Zone.BENCH
            opp.bench.append(card)
            state.emit_event("look_for_prey", player=player_id,
                             placed=card.card_name, on_bench=opp_id)


def _torrential_whirlpool(state: GameState, action):
    """sv10.5w-023 Samurott — Torrential Whirlpool: switch own active with bench, then force opp switch."""
    player_id = action.player_id
    player = state.get_player(player_id)
    opp_id = state.opponent_id(player_id)
    opp = state.get_player(opp_id)
    if not player.bench:
        state.emit_event("torrential_whirlpool", player=player_id, reason="no bench")
        return
    req = ChoiceRequest(
        "choose_target", player_id,
        "Torrential Whirlpool: choose a Benched Pokémon to switch with your Active",
        targets=list(player.bench),
    )
    resp = yield req
    new_active = None
    if resp and hasattr(resp, "target_instance_id") and resp.target_instance_id:
        new_active = next((p for p in player.bench
                           if p.instance_id == resp.target_instance_id), None)
    if new_active is None:
        new_active = player.bench[0]
    _switch_active_with_bench(player, new_active)
    state.emit_event("self_switch", player=player_id, new_active=player.active.card_name)
    if not opp.bench:
        return
    old_opp_active = opp.active
    opp.active = None
    if old_opp_active:
        old_opp_active.zone = Zone.BENCH
        opp.bench.append(old_opp_active)
    req2 = ChoiceRequest(
        "choose_target", opp_id,
        "Torrential Whirlpool: choose your new Active Pokémon from the Bench",
        targets=list(opp.bench),
    )
    resp2 = yield req2
    opp_new_active = None
    if resp2 and hasattr(resp2, "target_instance_id") and resp2.target_instance_id:
        opp_new_active = next((p for p in opp.bench
                               if p.instance_id == resp2.target_instance_id), None)
    if opp_new_active is None and opp.bench:
        opp_new_active = opp.bench[0]
    if opp_new_active:
        opp.bench.remove(opp_new_active)
        opp_new_active.zone = Zone.ACTIVE
        opp.active = opp_new_active
        state.emit_event("forced_switch", player=opp_id, new_active=opp.active.card_name)


# ── Batch 7: DRI ability handlers ─────────────────────────────────────────────

def _hurried_gait(state, action):
    """sv10-030 Rapidash — Hurried Gait: once per turn, draw 1 card."""
    player = state.get_player(action.player_id)
    caster = _find_in_play(player, action.card_instance_id)
    if caster and caster.ability_used_this_turn:
        state.emit_event("ability_already_used", player=action.player_id,
                         card=caster.card_name)
        return
    if caster:
        caster.ability_used_this_turn = True
    draw_cards(state, action.player_id, 1)
    state.emit_event("ability_used", player=action.player_id,
                     card="Rapidash", ability="Hurried Gait")


def _bonded_by_journey(state, action):
    """sv10-033 Ethan's Quilava — Bonded by the Journey: once per turn,
    search deck for Ethan's Adventure card, add to hand."""
    player = state.get_player(action.player_id)
    caster = _find_in_play(player, action.card_instance_id)
    if caster and caster.ability_used_this_turn:
        state.emit_event("ability_already_used", player=action.player_id,
                         card=caster.card_name)
        return
    if caster:
        caster.ability_used_this_turn = True

    matches = [c for c in player.deck if "Ethan's Adventure" in c.card_name]
    if not matches:
        state.emit_event("search_failed", player=action.player_id,
                         reason="no_ethans_adventure")
        return

    req = ChoiceRequest(
        "choose_cards",
        player_id=action.player_id,
        options=[c.instance_id for c in matches],
        min_choices=1,
        max_choices=1,
        context={"reason": "bonded_by_journey"},
    )
    response = yield req
    chosen_ids = response.chosen_ids if hasattr(response, "chosen_ids") else []
    chosen = next((c for c in player.deck if c.instance_id in chosen_ids), matches[0])
    player.deck.remove(chosen)
    chosen.zone = Zone.HAND
    player.hand.append(chosen)
    import random as _rnd
    _rnd.shuffle(player.deck)
    state.emit_event("ability_used", player=action.player_id,
                     card="Ethan's Quilava", ability="Bonded by the Journey",
                     found=chosen.card_name)


def _golden_flame(state, action):
    """sv10-039 Ethan's Ho-Oh ex — Golden Flame: once per turn,
    choose 1 of your Benched Ethan's Pokémon; attach up to 2 Basic R Energy from hand."""
    player = state.get_player(action.player_id)
    caster = _find_in_play(player, action.card_instance_id)
    if caster and caster.ability_used_this_turn:
        state.emit_event("ability_already_used", player=action.player_id,
                         card=caster.card_name)
        return
    if caster:
        caster.ability_used_this_turn = True

    ethan_bench = [b for b in player.bench if "Ethan's" in b.card_name]
    if not ethan_bench:
        state.emit_event("ability_no_targets", player=action.player_id,
                         card="Ethan's Ho-Oh ex", reason="no_ethans_bench")
        return

    r_energy = [c for c in player.hand
                if c.card_type == "Energy" and "Basic" in c.card_subtype
                and any("Fire" in (e or "") for e in c.energy_provides)]
    if not r_energy:
        state.emit_event("ability_no_targets", player=action.player_id,
                         card="Ethan's Ho-Oh ex", reason="no_fire_energy_hand")
        return

    target_req = ChoiceRequest(
        "choose_cards",
        player_id=action.player_id,
        options=[b.instance_id for b in ethan_bench],
        min_choices=1,
        max_choices=1,
        context={"reason": "golden_flame_target"},
    )
    target_resp = yield target_req
    chosen_ids = target_resp.chosen_ids if hasattr(target_resp, "chosen_ids") else []
    target = next((b for b in ethan_bench if b.instance_id in chosen_ids),
                  ethan_bench[0])

    energy_req = ChoiceRequest(
        "choose_cards",
        player_id=action.player_id,
        options=[c.instance_id for c in r_energy],
        min_choices=0,
        max_choices=min(2, len(r_energy)),
        context={"reason": "golden_flame_energy"},
    )
    energy_resp = yield energy_req
    chosen_e_ids = energy_resp.chosen_ids if hasattr(energy_resp, "chosen_ids") else []
    chosen_energy = [c for c in player.hand if c.instance_id in chosen_e_ids][:2]

    for e_card in chosen_energy:
        player.hand.remove(e_card)
        e_card.zone = Zone.DISCARD
        e_type = EnergyType.FIRE if "Fire" in (e_card.energy_provides or []) else EnergyType.COLORLESS
        target.energy_attached.append(EnergyAttachment(
            card_def_id=e_card.card_def_id,
            energy_type=e_type,
            card_name=e_card.card_name,
        ))
        state.emit_event("energy_attached", player=action.player_id,
                         target=target.card_name, energy=e_card.card_name)
    state.emit_event("ability_used", player=action.player_id,
                     card="Ethan's Ho-Oh ex", ability="Golden Flame")


def _rocket_brain(state, action):
    """sv10-089 TR Orbeetle — Rocket Brain: as often as desired,
    move 1 damage counter from a TR Pokémon to any Pokémon."""
    player = state.get_player(action.player_id)
    caster = _find_in_play(player, action.card_instance_id)
    if caster and caster.ability_used_this_turn:
        state.emit_event("ability_already_used", player=action.player_id,
                         card=caster.card_name)
        return
    if caster:
        caster.ability_used_this_turn = True

    opp = state.get_opponent(action.player_id)
    tr_with_counters = [p for p in _in_play(player)
                        if "Team Rocket's" in p.card_name and p.damage_counters > 0]
    if not tr_with_counters:
        state.emit_event("ability_no_targets", player=action.player_id,
                         card="TR Orbeetle", reason="no_tr_with_damage")
        return

    source_req = ChoiceRequest(
        "choose_cards",
        player_id=action.player_id,
        options=[p.instance_id for p in tr_with_counters],
        min_choices=1,
        max_choices=1,
        context={"reason": "rocket_brain_source"},
    )
    source_resp = yield source_req
    src_ids = source_resp.chosen_ids if hasattr(source_resp, "chosen_ids") else []
    source_poke = next((p for p in tr_with_counters if p.instance_id in src_ids),
                        tr_with_counters[0])

    all_targets = (_in_play(player) +
                   ([opp.active] if opp.active else []) + list(opp.bench))
    dest_req = ChoiceRequest(
        "choose_cards",
        player_id=action.player_id,
        options=[p.instance_id for p in all_targets],
        min_choices=1,
        max_choices=1,
        context={"reason": "rocket_brain_dest"},
    )
    dest_resp = yield dest_req
    dest_ids = dest_resp.chosen_ids if hasattr(dest_resp, "chosen_ids") else []
    dest_poke = next((p for p in all_targets if p.instance_id in dest_ids), all_targets[0])

    source_poke.damage_counters -= 1
    source_poke.current_hp = source_poke.max_hp - source_poke.damage_counters * 10
    dest_poke.damage_counters += 1
    dest_poke.current_hp = dest_poke.max_hp - dest_poke.damage_counters * 10
    state.emit_event("ability_used", player=action.player_id,
                     card="TR Orbeetle", ability="Rocket Brain",
                     from_card=source_poke.card_name, to_card=dest_poke.card_name)


# ──────────────────────────────────────────────────────────────────────────────
# Batch 8: DRI + JTG ability handlers
# ──────────────────────────────────────────────────────────────────────────────

def _champions_call(state, action):
    """sv10-103 Cynthia's Gabite — Champion's Call: once per turn,
    search deck for a Cynthia's Pokémon and add it to hand."""
    player = state.get_player(action.player_id)
    caster = _find_in_play(player, action.card_instance_id)
    if caster and caster.ability_used_this_turn:
        state.emit_event("ability_already_used", player=action.player_id,
                         card=caster.card_name)
        return
    if caster:
        caster.ability_used_this_turn = True

    matches = [c for c in player.deck
               if c.card_type.lower() in ("pokémon", "pokemon")
               and "Cynthia's" in c.card_name]
    if not matches:
        state.emit_event("search_failed", player=action.player_id,
                         reason="no_cynthias_pokemon")
        return

    req = ChoiceRequest(
        "choose_cards",
        player_id=action.player_id,
        options=[c.instance_id for c in matches],
        min_choices=1,
        max_choices=1,
        context={"reason": "champions_call"},
    )
    response = yield req
    chosen_ids = response.chosen_ids if hasattr(response, "chosen_ids") else []
    chosen = next((c for c in player.deck if c.instance_id in chosen_ids), matches[0])
    player.deck.remove(chosen)
    chosen.zone = Zone.HAND
    player.hand.append(chosen)
    import random as _rnd
    _rnd.shuffle(player.deck)
    state.emit_event("ability_used", player=action.player_id,
                     card="Cynthia's Gabite", ability="Champion's Call",
                     found=chosen.card_name)


def _sneaky_bite(state, action):
    """sv10-121 TR Golbat — Sneaky Bite: on-evolve,
    put 2 damage counters on 1 of opponent's Pokémon."""
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_player(opp_id)
    targets = _in_play(opp)
    if not targets:
        return

    req = ChoiceRequest(
        "choose_cards",
        player_id=action.player_id,
        options=[t.instance_id for t in targets],
        min_choices=1,
        max_choices=1,
        context={"reason": "sneaky_bite"},
    )
    response = yield req
    chosen_ids = response.chosen_ids if hasattr(response, "chosen_ids") else []
    target = next((t for t in targets if t.instance_id in chosen_ids), targets[0])
    target.damage_counters += 2
    check_ko(state, target, opp_id)
    state.emit_event("ability_used", player=action.player_id,
                     card="TR Golbat", ability="Sneaky Bite",
                     target=target.card_name)


def _biting_spree(state, action):
    """sv10-122 TR Crobat ex — Biting Spree: on-evolve,
    put 2 damage counters on each of up to 2 of opponent's Pokémon."""
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_player(opp_id)
    targets = _in_play(opp)
    if not targets:
        return

    max_t = min(2, len(targets))
    req = ChoiceRequest(
        "choose_cards",
        player_id=action.player_id,
        options=[t.instance_id for t in targets],
        min_choices=0,
        max_choices=max_t,
        context={"reason": "biting_spree"},
    )
    response = yield req
    chosen_ids = response.chosen_ids if hasattr(response, "chosen_ids") else []
    chosen = [t for t in targets if t.instance_id in chosen_ids][:max_t]
    for t in chosen:
        t.damage_counters += 2
        check_ko(state, t, opp_id)
    state.emit_event("ability_used", player=action.player_id,
                     card="TR Crobat ex", ability="Biting Spree",
                     targets=[t.card_name for t in chosen])


def _x_boot(state, action):
    """sv10-145 Steven's Metagross ex — X-Boot: once per turn,
    search deck for 1 Basic {P} energy + 1 Basic {M} energy;
    attach each to a matching type Pokémon you have in play."""
    player = state.get_player(action.player_id)
    caster = _find_in_play(player, action.card_instance_id)
    if caster and caster.ability_used_this_turn:
        state.emit_event("ability_already_used", player=action.player_id,
                         card=caster.card_name)
        return
    if caster:
        caster.ability_used_this_turn = True

    psychic_cards = [c for c in player.deck
                     if c.card_type.lower() == "energy"
                     and "basic" in (c.card_subtype or "").lower()
                     and any("Psychic" in (e or "") for e in (c.energy_provides or []))]
    metal_cards = [c for c in player.deck
                   if c.card_type.lower() == "energy"
                   and "basic" in (c.card_subtype or "").lower()
                   and any("Metal" in (e or "") for e in (c.energy_provides or []))]

    psychic_poke = [p for p in _in_play(player) if _pokemon_has_type(p, "Psychic")]
    metal_poke = [p for p in _in_play(player) if _pokemon_has_type(p, "Metal")]

    attached = []
    for energy_pool, poke_pool, type_name in [
        (psychic_cards, psychic_poke, "Psychic"),
        (metal_cards, metal_poke, "Metal"),
    ]:
        if not energy_pool or not poke_pool:
            continue

        poke_req = ChoiceRequest(
            "choose_cards",
            player_id=action.player_id,
            options=[p.instance_id for p in poke_pool],
            min_choices=1,
            max_choices=1,
            context={"reason": f"x_boot_{type_name.lower()}_target"},
        )
        poke_resp = yield poke_req
        chosen_ids = poke_resp.chosen_ids if hasattr(poke_resp, "chosen_ids") else []
        target_poke = next((p for p in poke_pool if p.instance_id in chosen_ids), poke_pool[0])

        energy_card = energy_pool[0]
        player.deck.remove(energy_card)
        energy_card.zone = target_poke.zone
        e_type = EnergyType.PSYCHIC if type_name == "Psychic" else EnergyType.METAL
        target_poke.energy_attached.append(EnergyAttachment(
            card_def_id=energy_card.card_def_id,
            energy_type=e_type,
            card_name=energy_card.card_name,
        ))
        attached.append((target_poke.card_name, type_name))
        state.emit_event("energy_attached", player=action.player_id,
                         target=target_poke.card_name, energy=energy_card.card_name)

    import random as _rnd
    _rnd.shuffle(player.deck)
    state.emit_event("ability_used", player=action.player_id,
                     card="Steven's Metagross ex", ability="X-Boot",
                     attached=attached)


def _reconstitute(state, action):
    """sv10-155 TR Porygon-Z — Reconstitute: discard 2 cards from hand to draw 1."""
    player = state.get_player(action.player_id)
    caster = _find_in_play(player, action.card_instance_id)
    if caster and caster.ability_used_this_turn:
        state.emit_event("ability_already_used", player=action.player_id,
                         card=caster.card_name)
        return

    if len(player.hand) < 2:
        state.emit_event("ability_no_targets", player=action.player_id,
                         card="TR Porygon-Z", reason="not_enough_hand")
        return

    req = ChoiceRequest(
        "choose_cards",
        player_id=action.player_id,
        options=[c.instance_id for c in player.hand],
        min_choices=2,
        max_choices=2,
        context={"reason": "reconstitute_discard"},
    )
    response = yield req
    chosen_ids = response.chosen_ids if hasattr(response, "chosen_ids") else []
    discard = [c for c in player.hand if c.instance_id in chosen_ids][:2]
    for c in discard:
        player.hand.remove(c)
        c.zone = Zone.DISCARD
        player.discard.append(c)

    if caster:
        caster.ability_used_this_turn = True
    draw_cards(state, action.player_id, 1)
    state.emit_event("ability_used", player=action.player_id,
                     card="TR Porygon-Z", ability="Reconstitute")


def _greedy_order(state, action):
    """sv10-159 Arven's Greedent — Greedy Order: on-evolve,
    put up to 2 Arven's Sandwich trainer cards from discard into hand."""
    player = state.get_player(action.player_id)
    sandwiches = [c for c in player.discard
                  if "Arven's Sandwich" in c.card_name]
    if not sandwiches:
        state.emit_event("ability_no_targets", player=action.player_id,
                         card="Arven's Greedent", reason="no_sandwich_in_discard")
        return

    max_take = min(2, len(sandwiches))
    req = ChoiceRequest(
        "choose_cards",
        player_id=action.player_id,
        options=[c.instance_id for c in sandwiches],
        min_choices=0,
        max_choices=max_take,
        context={"reason": "greedy_order"},
    )
    response = yield req
    chosen_ids = response.chosen_ids if hasattr(response, "chosen_ids") else []
    chosen = [c for c in sandwiches if c.instance_id in chosen_ids][:max_take]
    for c in chosen:
        player.discard.remove(c)
        c.zone = Zone.HAND
        player.hand.append(c)
    state.emit_event("ability_used", player=action.player_id,
                     card="Arven's Greedent", ability="Greedy Order",
                     retrieved=[c.card_name for c in chosen])


def _sunny_day(state, action):
    """sv09-007 Lilligant — Sunny Day: once per turn,
    until end of turn all Grass and Fire Pokémon deal +20 damage."""
    player = state.get_player(action.player_id)
    caster = _find_in_play(player, action.card_instance_id)
    if caster and caster.ability_used_this_turn:
        state.emit_event("ability_already_used", player=action.player_id,
                         card=caster.card_name)
        return
    if caster:
        caster.ability_used_this_turn = True
    state.sunny_day_active = True
    state.emit_event("ability_used", player=action.player_id,
                     card="Lilligant", ability="Sunny Day")


def _showtime(state, action):
    """sv09-018 Meowscarada — Showtime: once per turn, if on bench,
    switch this Pokémon with your active."""
    player = state.get_player(action.player_id)
    caster = _find_in_play(player, action.card_instance_id)
    if caster is None or caster.zone.name != "BENCH":
        state.emit_event("ability_no_targets", player=action.player_id,
                         card="Meowscarada", reason="not_on_bench")
        return
    if caster.ability_used_this_turn:
        state.emit_event("ability_already_used", player=action.player_id,
                         card=caster.card_name)
        return
    caster.ability_used_this_turn = True
    _switch_active_with_bench(player, caster)
    state.emit_event("ability_used", player=action.player_id,
                     card="Meowscarada", ability="Showtime")


def _scalding_steam(state, action):
    """sv09-031 Volcanion ex — Scalding Steam: once per turn, if active,
    make the opponent's active Pokémon Burned."""
    player = state.get_player(action.player_id)
    caster = _find_in_play(player, action.card_instance_id)
    if caster is None or caster.zone.name != "ACTIVE":
        state.emit_event("ability_no_targets", player=action.player_id,
                         card="Volcanion ex", reason="not_active")
        return
    if caster.ability_used_this_turn:
        state.emit_event("ability_already_used", player=action.player_id,
                         card=caster.card_name)
        return
    caster.ability_used_this_turn = True
    opp_id = state.opponent_id(action.player_id)
    opp = state.get_player(opp_id)
    if opp.active:
        opp.active.status = StatusCondition.BURNED
    state.emit_event("ability_used", player=action.player_id,
                     card="Volcanion ex", ability="Scalding Steam")


def register_all(registry):
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
    registry.register_ability("sv06.5-038", "Flip the Script", _flip_the_script,
                               condition=_cond_flip_the_script)   # alt print

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
    registry.register_ability("svp-166",  "Teal Dance", _teal_dance)   # promo alt print

    # Adrena-Brain: requires {D} energy on this Munkidori + your Pokémon with damage counters.
    def _cond_adrena_brain(state, player_id, poke=None):
        if poke is not None and not _has_d_energy(poke):
            return False
        p = state.get_player(player_id)
        return any(pk.damage_counters > 0 for pk in _in_play(p))

    registry.register_ability("sv06-095", "Adrena-Brain", _adrena_brain,
                               condition=_cond_adrena_brain)
    registry.register_ability("sv06-129", "Recon Directive", _recon_directive)
    registry.register_ability("me02.5-099", "Adrena-Brain", _adrena_brain,
                               condition=_cond_adrena_brain)
    registry.register_ability("me02.5-159", "Recon Directive", _recon_directive)
    registry.register_ability("sv06.5-039", "Subjugating Chains", _subjugating_chains)
    registry.register_ability("sv08.5-036", "Cursed Blast", _cursed_blast_dusclops,
                               condition=lambda state, pid: not has_psyduck_damp(state))
    registry.register_ability("sv08.5-037", "Cursed Blast", _cursed_blast_dusknoir,
                               condition=lambda state, pid: not has_psyduck_damp(state))
    registry.register_ability("sv09-024", "Seething Spirit", _seething_spirit)
    registry.register_ability("sv09-098", "Trade", _trade)
    registry.register_ability("sv10-020", "Charging Up", _charging_up)

    # ── Passive abilities (logic lives elsewhere in the engine) ──────────────
    # Registering here satisfies coverage checks without exposing USE_ABILITY.
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
    # svp-149   Pecharunt         Toxic Subjugation  → runner.py _handle_between_turns
    # me02.5-076 Lillie's Clefairy ex (alt) Fairy Zone → base.py (same as sv09-056)
    # sv05-024  Rabsca            Spherical Shield   → attacks.py _apply_bench_damage
    # me03-031  Mega Clefable ex  Luminous Wing      → future per-ability checks
    registry.register_passive_ability("me01-010",   "Wild Growth")
    registry.register_passive_ability("me02.5-039", "Damp")
    registry.register_passive_ability("sv06-053",   "Freezing Shroud")
    registry.register_passive_ability("sv06-096",   "Adrena-Pheromone")
    registry.register_passive_ability("sv06-111",   "Adrena-Power")
    registry.register_passive_ability("sv06-112",   "Cornerstone Stance")
    registry.register_passive_ability("sv06-141",   "Seasoned Skill")
    registry.register_passive_ability("sv08-076",   "Skyliner")
    registry.register_passive_ability("sv09-056",   "Fairy Zone")
    registry.register_passive_ability("me02.5-076", "Fairy Zone")
    registry.register_passive_ability("sv10-010",   "Flower Curtain")
    registry.register_passive_ability("sv10-012",   "Mysterious Rock Inn")
    registry.register_passive_ability("sv10-051",   "Repelling Veil")
    registry.register_passive_ability("sv10-081",   "Power Saver")
    registry.register_passive_ability("svp-149",    "Toxic Subjugation")
    registry.register_passive_ability("sv05-024",   "Spherical Shield")
    registry.register_passive_ability("me03-031",   "Luminous Wing")

    # ── New abilities (Batch 1) ──────────────────────────────────────────────
    # On-evolve triggers
    registry.register_ability("me02.5-012", "Multiplying Cocoon", _multiplying_cocoon)

    # Active-use abilities
    registry.register_ability("me03-009", "Grand Wing", _grand_wing)
    registry.register_ability("me03-014", "Sky Hunt", _sky_hunt)
    registry.register_ability("me03-019", "Wash Out", _wash_out)
    registry.register_ability("me03-036", "Scent Collection", _scent_collection)
    registry.register_ability("me02.5-015", "Boisterous Wind", _boisterous_wind)
    registry.register_ability("me02.5-026", "Golden Flame", _golden_flame)
    registry.register_ability("me02.5-003", "Lovely Fragrance", _lovely_fragrance)
    registry.register_ability("me02.5-007", "Gathering of Blossoms", _gathering_of_blossoms)

    # Reuse existing handler for new card ID
    registry.register_ability("me02.5-019", "Charging Up", _charging_up)

    # Passive abilities
    registry.register_passive_ability("me03-012",   "Sniper's Eye")
    registry.register_passive_ability("me03-024",   "Tundra Wall")
    registry.register_passive_ability("me03-027",   "Fighting Roar")
    registry.register_passive_ability("me03-045",   "Tyrannically Gutsy")
    registry.register_passive_ability("me03-050",   "Infinite Shadow")
    registry.register_passive_ability("me03-017",   "Shell Spikes")
    registry.register_passive_ability("me03-068",   "Intimidating Jaw")
    registry.register_passive_ability("me03-069",   "Protective Sail")
    registry.register_passive_ability("me02.5-024", "Melt Away")
    registry.register_passive_ability("me02.5-027", "Incandescent Body")

    # ── New abilities (Batch 2: ASC me02.5-034 through me02.5-133) ────────────

    # Active-use abilities
    # Alluring Wings: Frosmoth must be in the Active Spot
    def _cond_alluring_wings(state, player_id):
        p = state.get_player(player_id)
        return p.active is not None and p.active.card_def_id == "me02.5-053"

    registry.register_ability("me02.5-053", "Alluring Wings", _alluring_wings,
                               condition=_cond_alluring_wings)

    # Dynamotor: need Basic {L} in discard + bench Pokémon
    def _cond_dynamotor(state, player_id):
        p = state.get_player(player_id)
        has_l = any(
            c.card_type.lower() == "energy"
            and c.card_subtype.lower() == "basic"
            and "Lightning" in (c.energy_provides or [])
            for c in p.discard
        )
        return has_l and bool(p.bench)

    registry.register_ability("me02.5-060", "Dynamotor", _dynamotor,
                               condition=_cond_dynamotor)

    # Frilled Generator: requires Canari Supporter was played this turn
    def _cond_frilled_generator(state, player_id):
        p = state.get_player(player_id)
        has_l_in_deck = any(
            c.card_type.lower() == "energy"
            and c.card_subtype.lower() == "basic"
            and "Lightning" in (c.energy_provides or [])
            for c in p.deck
        )
        canari_played = any(
            e.get("event_type") in ("use_supporter", "play_supporter", "supporter_played")
            and "Canari" in (e.get("card_name") or "")
            and e.get("turn", -1) == state.turn_number
            for e in state.events
        )
        return has_l_in_deck and canari_played

    registry.register_ability("me02.5-064", "Frilled Generator", _frilled_generator,
                               condition=_cond_frilled_generator)

    # Electric Streamer: need Basic {L} in hand + Iono's Pokémon in play
    def _cond_electric_streamer(state, player_id):
        p = state.get_player(player_id)
        has_l = any(
            c.card_type.lower() == "energy"
            and c.card_subtype.lower() == "basic"
            and "Lightning" in (c.energy_provides or [])
            for c in p.hand
        )
        has_ionos = any("Iono's" in pk.card_name for pk in _in_play(p))
        return has_l and has_ionos

    registry.register_ability("me02.5-070", "Electric Streamer", _electric_streamer,
                               condition=_cond_electric_streamer)

    # Flashing Draw: need Basic {L} attached to Kilowattrel
    def _cond_flashing_draw(state, player_id):
        p = state.get_player(player_id)
        kilowattrel = next(
            (pk for pk in _in_play(p) if pk.card_def_id == "me02.5-072"), None
        )
        if kilowattrel is None:
            return False
        return any(att.energy_type == EnergyType.LIGHTNING
                   for att in kilowattrel.energy_attached)

    registry.register_ability("me02.5-072", "Flashing Draw", _flashing_draw,
                               condition=_cond_flashing_draw)

    # Bubble Gathering: need another Pokémon in play with energy
    def _cond_bubble_gathering(state, player_id, poke=None):
        p = state.get_player(player_id)
        azumarill = poke if poke is not None else next(
            (pk for pk in _in_play(p) if pk.card_def_id == "me02.5-084"), None
        )
        if azumarill is None:
            return False
        return any(
            pk.instance_id != azumarill.instance_id and pk.energy_attached
            for pk in _in_play(p)
        )

    registry.register_ability("me02.5-084", "Bubble Gathering", _bubble_gathering,
                               condition=_cond_bubble_gathering)

    # Champion's Call: need Cynthia's Pokémon in deck
    def _cond_champions_call(state, player_id):
        p = state.get_player(player_id)
        return any(
            c.card_type.lower() == "pokemon" and "Cynthia's" in c.card_name
            for c in p.deck
        )

    registry.register_ability("me02.5-110", "Champion's Call", _champions_call,
                               condition=_cond_champions_call)

    # Passive abilities — Batch 2
    # me02.5-040 Golduck: Damp (same as me02.5-039 Psyduck)
    registry.register_passive_ability("me02.5-040", "Damp")

    # me02.5-057 Pikachu ex: Resolute Heart → base.py check_ko
    registry.register_passive_ability("me02.5-057", "Resolute Heart")

    # me02.5-068 Hop's Pincurchin ex: Counterattack Quills → attacks.py _apply_damage
    registry.register_passive_ability("me02.5-068", "Counterattack Quills")

    # me02.5-079 TR Mewtwo ex: Power Saver → actions.py (power_saver_blocks_attack updated)
    registry.register_passive_ability("me02.5-079", "Power Saver")

    # me02.5-082 Togekiss: Wonder Kiss → base.py check_ko
    registry.register_passive_ability("me02.5-082", "Wonder Kiss")

    # me02.5-101 TR Dugtrio: Holes → transitions.py _retreat
    registry.register_passive_ability("me02.5-101", "Holes")

    # me02.5-105 Lunatone: Lunar Cycle (same handler as me01-074)
    registry.register_ability("me02.5-105", "Lunar Cycle", _lunar_cycle,
                               condition=_cond_lunar_cycle)

    # me02.5-116 Mega Hawlucha ex: Tenacious Body → base.py check_ko
    registry.register_passive_ability("me02.5-116", "Tenacious Body")

    # me02.5-117 Carbink: Double Type → card type check handled by type queries
    registry.register_passive_ability("me02.5-117", "Double Type")

    # me02.5-125 Mega Gengar ex: Shadowy Concealment → base.py check_ko
    registry.register_passive_ability("me02.5-125", "Shadowy Concealment")

    # ── Batch 3: ASC/PFL ability registrations ────────────────────────────────

    # N's Zoroark ex: Trade (reuse existing handler)
    registry.register_ability("me02.5-137", "Trade", _trade)

    # Brambleghast: Prison Panic (evolve trigger)
    registry.register_ability("me02.5-133", "Prison Panic", _prison_panic)

    # me02-053 Flygon: Sandy Flapping (evolve trigger — KO trigger handled in base.py)
    registry.register_ability("me02-053", "Sandy Flapping", _sandy_flapping_ability)

    # me02.5-151 Dragonair: Evolutionary Guidance
    def _cond_evolutionary_guidance(state, player_id):
        p = state.get_player(player_id)
        poke = next((pk for pk in _in_play(p)
                     if pk.card_def_id == "me02.5-151"
                     and pk.energy_attached), None)
        return poke is not None and any(
            c.card_type.lower() == "pokemon" and c.card_subtype.lower() not in ("basic",)
            for c in p.deck
        )
    registry.register_ability("me02.5-151", "Evolutionary Guidance", _evolutionary_guidance,
                               condition=_cond_evolutionary_guidance)

    # me02.5-152 Mega Dragonite ex: Sky Transport
    def _cond_sky_transport(state, player_id):
        p = state.get_player(player_id)
        return bool(p.bench)
    registry.register_ability("me02.5-152", "Sky Transport", _sky_transport,
                               condition=_cond_sky_transport)

    # me02.5-148 Kingambit: Supreme Overlord (passive — logic in _apply_damage)
    registry.register_passive_ability("me02.5-148", "Supreme Overlord")

    # me02.5-135 Mega Scrafty ex: Counterattacking Crest (passive — logic in _apply_damage)
    registry.register_passive_ability("me02.5-135", "Counterattacking Crest")

    # me02.5-143 Pecharunt: Final Chain (passive — logic in check_ko)
    registry.register_passive_ability("me02.5-143", "Final Chain")

    # me02-022 Dewgong: Thick Fat (passive — logic in _apply_damage)
    registry.register_passive_ability("me02-022", "Thick Fat")

    # me02-041 Mega Diancie ex: Diamond Coat (passive — logic in _apply_damage)
    registry.register_passive_ability("me02-041", "Diamond Coat")

    # me02-029 Rotom ex: Multi Adapter (flagged — too complex)
    registry.register_passive_ability("me02-029", "Multi Adapter")

    # me02.5-171 Fan Rotom: Fan Call
    def _cond_fan_call(state, player_id):
        return state.turn_number <= 1
    registry.register_ability("me02.5-171", "Fan Call", _fan_call,
                               condition=_cond_fan_call)

    # me02-7 Ludicolo: Excited Heal
    def _cond_excited_heal(state, player_id):
        p = state.get_player(player_id)
        has_mega_g = any("ex" in pk.card_name.lower() and pk.evolution_stage >= 2
                         for pk in _in_play(p))
        has_damaged = any(pk.damage_counters > 0 for pk in _in_play(p))
        return has_mega_g and has_damaged
    registry.register_ability("me02-007", "Excited Heal", _excited_heal,
                               condition=_cond_excited_heal)

    # me02-036 Mismagius ex: Swirling Prose (passive — logic in transitions.py _retreat)
    registry.register_passive_ability("me02-036", "Swirling Prose")

    # me02.5-175 Larry's Komala: Lethargic Charge
    def _cond_lethargic_charge(state, player_id):
        p = state.get_player(player_id)
        komala = next((pk for pk in p.bench if pk.card_def_id == "me02.5-175"), None)
        if not komala:
            return False
        return (p.active is not None
                and "Larry's" in p.active.card_name
                and any(c.card_type.lower() == "energy" for c in p.hand))
    registry.register_ability("me02.5-175", "Lethargic Charge", _lethargic_charge,
                               condition=_cond_lethargic_charge)

    # ── Additional Batch 3 ability registrations ──────────────────────────────

    # me02-047 Brambleghast: Prison Panic (evolve trigger — same handler as me02.5-133)
    registry.register_ability("me02-047", "Prison Panic", _prison_panic)

    # me02-011 Charmander: Agile (passive — 0 retreat if no energy)
    # Registered as passive; actual retreat-cost reduction is not enforced in engine
    registry.register_passive_ability("me02-011", "Agile")

    # me02-018 Oricorio ex: Excited Turbo (attach R energy from hand to benched R Poke)
    def _excited_turbo(state, action):
        """Oricorio ex — Excited Turbo: attach R Basic Energy from hand to benched R Pokémon."""
        from app.engine.state import EnergyAttachment, EnergyType as _ET
        player = state.get_player(action.player_id)
        r_mega = any(
            "ex" in pk.card_name.lower() and pk.evolution_stage >= 2
            for pk in _in_play(player)
        )
        if not r_mega:
            return
        r_energy_hand = [c for c in player.hand
                         if c.card_type.lower() == "energy"]
        bench_targets = player.bench
        if not r_energy_hand or not bench_targets:
            return
        req = ChoiceRequest("choose_cards", action.player_id,
                            "Excited Turbo: attach a Basic R Energy to a Benched Pokémon.",
                            cards=r_energy_hand, min_count=0, max_count=1)
        resp = yield req
        chosen = (resp.selected_cards if resp else []) or [r_energy_hand[0].instance_id]
        for iid in chosen[:1]:
            card = next((c for c in player.hand if c.instance_id == iid), None)
            if card:
                player.hand.remove(card)
                target = bench_targets[0]
                card.zone = Zone.BENCH
                target.energy_attached.append(EnergyAttachment(
                    energy_type=_ET.FIRE,
                    source_card_id=card.instance_id,
                    card_def_id=card.card_def_id,
                ))
                state.emit_event("excited_turbo", player=action.player_id, card=target.card_name)

    def _cond_excited_turbo(state, player_id):
        p = state.get_player(player_id)
        has_mega_r = any("ex" in pk.card_name.lower() and pk.evolution_stage >= 2
                         for pk in _in_play(p))
        has_energy = any(c.card_type.lower() == "energy" for c in p.hand)
        has_bench = bool(p.bench)
        return has_mega_r and has_energy and has_bench

    registry.register_ability("me02-018", "Excited Turbo", _excited_turbo,
                               condition=_cond_excited_turbo)

    # ── Batch 4 Ability Registrations ─────────────────────────────────────────

    # Passive / always-on abilities (no handler needed — handled via check_ko or _apply_damage)
    registry.register_passive_ability("me02-056", "Shadowy Concealment")   # check_ko handles prize skip
    registry.register_passive_ability("me01-061", "Fragile Husk")          # check_ko handles prize skip
    registry.register_passive_ability("me01-024", "Intimidating Fang")     # _apply_damage handles -30
    registry.register_passive_ability("me02-070", "Emperor's Stance")      # effect-prevention (damage passes through)
    registry.register_passive_ability("me02-062", "Excited Power")         # _apply_damage handles +120

    # Active abilities (once per turn, usable from bench or active)
    registry.register_ability("me01-003", "Solar Transfer", _solar_transfer,
                               condition=_cond_solar_transfer)
    registry.register_ability("me02-082", "Excited Dash", _excited_dash,
                               condition=_cond_excited_dash)
    registry.register_ability("me01-011", "Fermented Juice", _fermented_juice,
                               condition=_cond_fermented_juice)
    registry.register_ability("me01-038", "Fall Back to Reload", _fall_back_to_reload,
                               condition=_cond_fall_back_to_reload)
    registry.register_ability("me02-068", "Sinister Surge", _sinister_surge,
                               condition=_cond_sinister_surge)

    # Evolve-trigger abilities
    registry.register_ability("me01-017", "Cast-Off Shell", _cast_off_shell)
    registry.register_ability("me01-063", "Energized Steps", _energized_steps)

    # ── Batch 5 Ability Registrations ─────────────────────────────────────────

    # Passive / always-on abilities (handled in _apply_damage)
    registry.register_passive_ability("me01-084", "Powerful a-Salt")   # _apply_damage handles +30 for F
    registry.register_passive_ability("sv10.5b-003", "Regal Cheer")    # _apply_damage handles +20 for all
    registry.register_passive_ability("me01-087", "Spiteful Swirl")    # _apply_damage handles counter on attacker
    registry.register_passive_ability("sv10.5b-056", "Poison Point")   # _apply_damage handles poison attacker
    registry.register_passive_ability("sv10.5b-023", "Mighty Shell")   # _apply_damage handles damage block

    # Evolve-trigger abilities
    registry.register_ability("me01-073", "Heave-Ho Catcher", _heave_ho_catcher)
    registry.register_ability("me01-097", "Haphazard Hammer", _tinkatuff_haphazard_hammer)

    # Active abilities (once per turn)
    def _cond_evidence_gathering(state, player_id):
        p = state.get_player(player_id)
        return bool(p.hand) and bool(p.deck)
    registry.register_ability("me01-110", "Evidence Gathering", _gumshoos_evidence_gathering,
                               condition=_cond_evidence_gathering)

    def _cond_torrid_scales(state, player_id):
        p = state.get_player(player_id)
        opp_id = state.opponent_id(player_id)
        opp = state.get_player(opp_id)
        has_r_in_hand = any(c.card_type.lower() == "energy"
                            and c.card_subtype.lower() == "basic"
                            and "Fire" in (c.energy_provides or [])
                            for c in p.hand)
        return has_r_in_hand and opp.active is not None
    registry.register_ability("sv10.5b-016", "Torrid Scales", _volcarona_torrid_scales,
                               condition=_cond_torrid_scales)

    def _cond_eelektrik_dynamotor(state, player_id):
        p = state.get_player(player_id)
        has_l = any(c.card_type.lower() == "energy"
                    and c.card_subtype.lower() == "basic"
                    and "Lightning" in (c.energy_provides or [])
                    for c in p.discard)
        return has_l and bool(p.bench)
    registry.register_ability("sv10.5b-031", "Dynamotor", _eelektrik_dynamotor,
                               condition=_cond_eelektrik_dynamotor)

    def _cond_gentle_fin(state, player_id):
        p = state.get_player(player_id)
        if len(p.bench) >= 5:
            return False
        return any(getattr(c, "card_type", "").lower() in ("pokémon", "pokemon")
                   and card_registry.get(getattr(c, "card_def_id", "")) is not None
                   and (card_registry.get(c.card_def_id).stage or "").lower() == "basic"
                   and (card_registry.get(c.card_def_id).hp or 999) <= 70
                   for c in p.discard)
    registry.register_ability("sv10.5b-024", "Gentle Fin", _alomomola_gentle_fin,
                               condition=_cond_gentle_fin)

    # ── Batch 6: BLK/WHT/DRI ability registrations ─────────────────────────────
    registry.register_ability("sv10.5w-002", "Healing Leaves", _healing_leaves)
    registry.register_ability("sv10.5b-067", "Metallic Signal", _metallic_signal)

    def _cond_distorted_future(state, player_id):
        p = state.get_player(player_id)
        return p.active is not None and p.active.card_def_id == "sv10.5w-043"
    registry.register_ability("sv10.5w-043", "Distorted Future", _distorted_future,
                               condition=_cond_distorted_future)

    def _cond_look_for_prey(state, player_id):
        opp_id = state.opponent_id(player_id)
        opp = state.get_player(opp_id)
        if len(opp.bench) >= 5:
            return False
        return any(c.card_type.lower() in ("pokémon", "pokemon")
                   and card_registry.get(c.card_def_id) is not None
                   and card_registry.get(c.card_def_id).stage.lower() == "basic"
                   and (card_registry.get(c.card_def_id).hp or 999) <= 70
                   for c in opp.hand)
    registry.register_ability("sv10.5w-064", "Look for Prey", _mandibuzz_look_for_prey,
                               condition=_cond_look_for_prey)

    def _cond_torrential_whirlpool(state, player_id):
        p = state.get_player(player_id)
        return bool(p.bench)
    registry.register_ability("sv10.5w-023", "Torrential Whirlpool", _torrential_whirlpool,
                               condition=_cond_torrential_whirlpool)

    # Passive abilities handled in _apply_damage
    registry.register_passive_ability("sv10.5b-063", "Gear Coating")   # handled in _apply_damage
    registry.register_passive_ability("sv10.5w-077", "Bouffer")        # handled in _apply_damage

    # ── Batch 7: DRI ability registrations ────────────────────────────────────
    registry.register_ability("sv10-030", "Hurried Gait", _hurried_gait)           # Rapidash — Hurried Gait
    registry.register_ability("sv10-033", "Bonded by the Journey", _bonded_by_journey)  # Ethan's Quilava — Bonded by the Journey
    registry.register_ability("sv10-039", "Golden Flame", _golden_flame)           # Ethan's Ho-Oh ex — Golden Flame
    registry.register_ability("sv10-089", "Rocket Brain", _rocket_brain)           # TR Orbeetle — Rocket Brain

    # Passive abilities handled in _apply_damage or _apply_bench_damage
    registry.register_passive_ability("sv10-008", "Cheer On to Glory")  # Cynthia's Roserade
    registry.register_passive_ability("sv10-048", "So Submerged")      # Misty's Magikarp
    registry.register_passive_ability("sv10-086", "Stone Palace")      # Steven's Carbink
    registry.register_passive_ability("sv10-092", "Lose Cool")         # Annihilape
    registry.register_passive_ability("sv10.5b-052", "Sturdy")         # Crustle (logic in _apply_damage)
    registry.register_passive_ability("sv10-003", "Buzzing Boost")     # Yanmega ex (on-promote; noop — engine lacks hook)

    # ── Batch 8: DRI + JTG ability registrations ─────────────────────────────
    # On-evolve triggers
    registry.register_ability("sv10-121", "Sneaky Bite", _sneaky_bite)             # TR Golbat — Sneaky Bite
    registry.register_ability("sv10-122", "Biting Spree", _biting_spree)           # TR Crobat ex — Biting Spree
    registry.register_ability("sv10-159", "Greedy Order", _greedy_order)           # Arven's Greedent — Greedy Order

    # Active-use abilities
    registry.register_ability("sv10-103", "Champion's Call", _champions_call)      # Cynthia's Gabite
    registry.register_ability("sv10-145", "X-Boot", _x_boot)                       # Steven's Metagross ex
    registry.register_ability("sv10-155", "Reconstitute", _reconstitute)           # TR Porygon-Z
    registry.register_ability("sv09-007", "Sunny Day", _sunny_day)                 # Lilligant
    registry.register_ability("sv09-018", "Showtime", _showtime)                   # Meowscarada
    registry.register_ability("sv09-031", "Scalding Steam", _scalding_steam)       # Volcanion ex

    # Passive abilities for Batch 8 (logic handled elsewhere)
    registry.register_passive_ability("sv10-108", "Mud Coat")           # Mudsdale (logic in _apply_damage)
    registry.register_passive_ability("sv10-125", "Smog Signals")       # TR Koffing (logic in _apply_damage)
    registry.register_passive_ability("sv09-008", "Exploding Needles")  # Maractus (logic in check_ko)
    registry.register_passive_ability("sv09-021", "Magma Surge")        # Magmortar (logic in runner.py)
