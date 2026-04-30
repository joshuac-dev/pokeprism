"""Shared helpers for effect implementations.

These are pure functions used by both the EffectRegistry's default resolver
and by individual card effect handlers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.engine.state import CardInstance

from app.engine.state import (
    CardInstance,
    EnergyType,
    GameState,
    Phase,
    PlayerState,
    Zone,
)
from app.cards import registry as card_registry


# ──────────────────────────────────────────────────────────────────────────────
# Choice request (yielded by generator-based effect handlers)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ChoiceRequest:
    """Emitted by effect handlers (via ``yield``) to request a player decision.

    Effect handlers that need choices are Python generators.  They ``yield``
    a ChoiceRequest and receive back the Action the chosen player selected.

    The runner drives the generator via :func:`_drive_effect` in the registry,
    asking the appropriate player object for each choice.
    """

    choice_type: str        # "choose_cards" | "choose_target" | "choose_option"
    player_id: str          # Which player makes this choice
    prompt: str             # Human-readable label (used by AI players for reasoning)

    # For "choose_cards":
    cards: list = field(default_factory=list)    # CardInstance objects available
    min_count: int = 0
    max_count: int = 1

    # For "choose_target":
    targets: list = field(default_factory=list)  # CardInstance objects

    # For "choose_option":
    options: list = field(default_factory=list)  # str labels for each option


# ──────────────────────────────────────────────────────────────────────────────
# Damage parsing
# ──────────────────────────────────────────────────────────────────────────────

def parse_damage(damage_str: str) -> int:
    """Extract the base numeric damage from a TCGDex damage string.

    Examples:
      "60"   → 60
      "60+"  → 60   (effect handler adds extra)
      "30×"  → 0    (multiplicative — effect handler must compute)
      ""     → 0
    """
    if not damage_str:
        return 0
    m = re.match(r"(\d+)", damage_str.strip())
    if m:
        val = int(m.group(1))
        # If it's a multiplier attack, return 0 — the effect handler resolves it
        if "×" in damage_str or "x" in damage_str.lower():
            return 0
        return val
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Damage calculation (Appendix A)
# ──────────────────────────────────────────────────────────────────────────────

def apply_weakness_resistance(
    base_damage: int,
    attacker: CardInstance,
    defender: CardInstance,
    state: "GameState" = None,
    defender_player_id: str = None,
    skip_resistance: bool = False,
) -> int:
    """Apply weakness and resistance to base damage.

    Formula (Appendix A):
      base_damage
      × 2   if attacker's type is in defender's weakness
      - 30  if attacker's type is in defender's resistance
      (minimum 0)
    Fairy Zone (sv09-056 Lillie's Clefairy ex): Colorless Pokémon have
    Psychic × 2 weakness (applied here if not already on the card).
    """
    attacker_def = card_registry.get(attacker.card_def_id)
    defender_def = card_registry.get(defender.card_def_id)

    if not attacker_def or not defender_def:
        return base_damage

    attacker_types = {t.lower() for t in attacker_def.types}

    damage = base_damage

    # no_weakness_one_turn (Metal Defender sv08-130): skip weakness
    if getattr(defender, "no_weakness_one_turn", False):
        return max(0, damage)

    # Weakness × 2
    weakness_applied = False
    for weakness in defender_def.weaknesses:
        if weakness.type.lower() in attacker_types:
            mult_str = weakness.value  # e.g. "×2"
            try:
                mult = float(re.sub(r"[×x*]", "", mult_str)) if mult_str else 2.0
            except ValueError:
                mult = 2.0
            damage = int(damage * mult)
            weakness_applied = True
            break

    # Fairy Zone (sv09-056 Lillie's Clefairy ex): Colorless Pokémon have Psychic × 2
    if not weakness_applied and state is not None and defender_player_id is not None:
        from app.engine.effects.abilities import has_fairy_zone
        attacker_player_id = state.opponent_id(defender_player_id)
        defender_types = {t.lower() for t in (defender_def.types or [])}
        if (
            "psychic" in attacker_types
            and "colorless" in defender_types
            and has_fairy_zone(state, attacker_player_id)
        ):
            damage = int(damage * 2)

    if not skip_resistance:
        # Resistance − value
        for resistance in defender_def.resistances:
            if resistance.type.lower() in attacker_types:
                sub_str = resistance.value  # e.g. "-30"
                try:
                    sub = int(re.sub(r"[^0-9]", "", sub_str))
                except ValueError:
                    sub = 30
                damage -= sub
                break

    return max(0, damage)


# ──────────────────────────────────────────────────────────────────────────────
# KO checking and prize taking
# ──────────────────────────────────────────────────────────────────────────────

def draw_cards(state: GameState, player_id: str, count: int) -> int:
    """Draw `count` cards from deck to hand for player_id.

    Returns the number of cards actually drawn (may be less than count if deck
    runs out — the deck-out check in the runner handles win condition).
    """
    player = state.get_player(player_id)
    drawn = 0
    for _ in range(count):
        if not player.deck:
            break
        card = player.deck.pop(0)
        card.zone = Zone.HAND
        player.hand.append(card)
        drawn += 1
    if drawn > 0:
        state.emit_event("draw", player=player_id, count=drawn,
                         hand_size=len(player.hand))
    return drawn


def check_ko(
    state: GameState,
    target: CardInstance,
    target_player_id: str,
) -> None:
    """Check if target is KO'd and process the aftermath.

    Mutates state in place:
    - Moves KO'd Pokémon to discard
    - Awards prizes to the attacker
    - Sets winner/win_condition if game ends
    """
    import random as _random

    # Adrena-Power (sv06-111 Okidogi): +100 effective HP when {D} energy attached
    effective_hp = target.current_hp
    if target.card_def_id == "sv06-111":
        from app.engine.effects.abilities import has_adrena_power
        if has_adrena_power(target):
            effective_hp += 100
    if effective_hp > 0:
        return  # Still alive

    # Resolute Heart (me02.5-057 Pikachu ex): if at full HP when KO'd, survive with 10 HP
    if target.resolute_heart_eligible:
        target.resolute_heart_eligible = False
        target.current_hp = 10
        target.damage_counters = (target.max_hp - 10) // 10
        state.emit_event("resolute_heart_triggered",
                         ko_player=target_player_id,
                         card_name=target.card_name)
        return  # Survived

    # Tenacious Body (me02.5-116 Mega Hawlucha ex): flip coin, heads = survive with 10 HP
    if target.card_def_id == "me02.5-116":
        if _random.choice([True, False]):  # heads
            target.current_hp = 10
            target.damage_counters = (target.max_hp - 10) // 10
            state.emit_event("tenacious_body_triggered",
                             ko_player=target_player_id,
                             card_name=target.card_name)
            return  # Survived

    target_player = state.get_player(target_player_id)
    attacker_id = state.opponent_id(target_player_id)
    attacker_player = state.get_player(attacker_id)

    # Track that this player had a Pokémon KO'd (for Retaliate effects)
    target_player.ko_taken_last_turn = True
    if "Ethan's" in target.card_name:
        target_player.ethans_pokemon_ko_last_turn = True

    # Determine prize count
    cdef = card_registry.get(target.card_def_id)
    prizes_to_take = cdef.prize_value if cdef else 1

    # Legacy Energy (sv06-167): take 1 fewer prize (once per game)
    _LEGACY_ENERGY_ID = "sv06-167"
    for att in target.energy_attached:
        if att.card_def_id == _LEGACY_ENERGY_ID and not state.legacy_prize_reduction_used:
            prizes_to_take = max(0, prizes_to_take - 1)
            state.legacy_prize_reduction_used = True
            state.emit_event("legacy_energy_triggered",
                             ko_player=target_player_id,
                             card_name=target.card_name)
            break

    # Lillie's Pearl (sv09-151): take 1 fewer prize (per KO, not once per game)
    _LILLIES_PEARL_ID = "sv09-151"
    if _LILLIES_PEARL_ID in target.tools_attached:
        prizes_to_take = max(0, prizes_to_take - 1)
        state.emit_event("lillies_pearl_triggered",
                         ko_player=target_player_id,
                         card_name=target.card_name)

    # Shadowy Concealment (me02.5-125 Mega Gengar ex): if D Pokémon KO'd by ex, -1 prize
    _is_attacking_active = (
        attacker_player.active is not None
        and target_player.active is not None
        and target_player.active.instance_id == target.instance_id
    )
    if _is_attacking_active:
        attacker_cdef = card_registry.get(attacker_player.active.card_def_id) if attacker_player.active else None
        target_types = cdef.types if cdef else []
        if (attacker_cdef and attacker_cdef.is_ex
                and "Darkness" in (target_types or [])):
            from app.engine.effects.abilities import _in_play
            if any(p.card_def_id in ("me02.5-125", "me02-056") for p in _in_play(target_player)):
                prizes_to_take = max(0, prizes_to_take - 1)
                state.emit_event("shadowy_concealment_triggered",
                                 ko_player=target_player_id,
                                 card_name=target.card_name)

    # Briar (sv07-132): take 1 extra prize when KO'ing opponent's Active Pokémon
    if (state.briar_active
            and attacker_id == state.active_player
            and target_player.active is not None
            and target_player.active.instance_id == target.instance_id):
        prizes_to_take += 1
        state.emit_event("briar_triggered",
                         ko_player=target_player_id,
                         card_name=target.card_name)

    # Wonder Kiss (me02.5-082 Togekiss): when opp's active is KO'd, flip coin, heads = +1 prize
    if (_is_attacking_active
            and attacker_id == state.active_player):
        from app.engine.effects.abilities import _in_play
        if any(p.card_def_id == "me02.5-082" for p in _in_play(attacker_player)):
            if _random.choice([True, False]):  # heads
                prizes_to_take += 1
                state.emit_event("wonder_kiss_triggered",
                                 ko_player=target_player_id,
                                 card_name=target.card_name)

    # Fragile Husk (me01-061 Shedinja): if KO'd by opponent's Pokémon ex, opp takes 0 prizes
    if target.card_def_id == "me01-061" and _is_attacking_active:
        attacker_cdef2 = card_registry.get(attacker_player.active.card_def_id) if attacker_player.active else None
        if attacker_cdef2 and attacker_cdef2.is_ex:
            prizes_to_take = 0
            state.emit_event("fragile_husk_triggered",
                             ko_player=target_player_id,
                             card_name=target.card_name)

    # Sandy Flapping (me02-053 Flygon): when KO'd by opponent's active, discard top 2 of opp's deck
    if target.card_def_id == "me02-053" and _is_attacking_active:
        for _ in range(2):
            if attacker_player.deck:
                top = attacker_player.deck.pop()
                top.zone = Zone.DISCARD
                attacker_player.discard.append(top)
        state.emit_event("sandy_flapping_ko_triggered", player=target_player_id,
                         card=target.card_name)

    # Exploding Needles (sv09-008 Maractus): when KO'd while active by damage, place 6 counters on attacker
    if target.card_def_id == "sv09-008" and _is_attacking_active:
        if attacker_player.active and attacker_player.active.current_hp > 0:
            attacker_player.active.current_hp -= 60
            attacker_player.active.damage_counters += 6
            state.emit_event("exploding_needles_triggered", player=target_player_id,
                             card=target.card_name,
                             attacker=attacker_player.active.card_name)
            check_ko(state, attacker_player.active, attacker_id)
            if state.phase == Phase.GAME_OVER:
                return

    # Final Chain (me02.5-143 Pecharunt): when KO'd by opponent's active, search deck for 1 card
    if target.card_def_id == "me02.5-143" and _is_attacking_active:
        if target_player.deck:
            card = _random.choice(target_player.deck)
            target_player.deck.remove(card)
            card.zone = Zone.HAND
            target_player.hand.append(card)
            state.emit_event("final_chain_triggered", player=target_player_id,
                             card=card.card_name)

    state.emit_event(
        "ko",
        ko_player=target_player_id,
        card_name=target.card_name,
        attacker=attacker_player.active.card_name if attacker_player.active else None,
        prizes_to_take=prizes_to_take,
    )

    # Move KO'd Pokémon (and attached cards) to discard
    _move_to_discard(target_player, target)

    # Remove from active / bench
    if target_player.active and target_player.active.instance_id == target.instance_id:
        target_player.active = None
    else:
        target_player.bench = [
            b for b in target_player.bench
            if b.instance_id != target.instance_id
        ]

    # Award prizes
    actual_taken = 0
    for _ in range(prizes_to_take):
        if attacker_player.prizes:
            prize_card = attacker_player.prizes.pop(0)
            prize_card.zone = Zone.HAND
            attacker_player.hand.append(prize_card)
            attacker_player.prizes_remaining = max(
                0, attacker_player.prizes_remaining - 1
            )
            actual_taken += 1

    state.emit_event(
        "prizes_taken",
        taking_player=attacker_id,
        count=actual_taken,
        remaining=attacker_player.prizes_remaining,
    )

    # Check win: all prizes taken
    if attacker_player.prizes_remaining == 0:
        state.winner = attacker_id
        state.win_condition = "prizes"
        state.phase = Phase.GAME_OVER
        state.emit_event("game_over", winner=attacker_id, condition="prizes")
        return

    # Check win: defender has no bench and was the active
    if target_player.active is None and not target_player.bench:
        state.winner = attacker_id
        state.win_condition = "no_bench"
        state.phase = Phase.GAME_OVER
        state.emit_event("game_over", winner=attacker_id, condition="no_bench")


def _move_to_discard(player: PlayerState, pokemon: CardInstance) -> None:
    """Move a KO'd Pokémon and its attached energy to the discard pile.

    Tool cards are cleared from the Pokémon's attachment list. The tool card
    instances themselves are not tracked in zone lists after attachment, so no
    separate discard step is needed for them.
    """
    # Clear tools (the card instances were removed from all zone lists on attach)
    pokemon.tools_attached.clear()

    # Detach and discard energy
    for att in pokemon.energy_attached:
        energy_card = _find_card_anywhere(player, att.source_card_id)
        if energy_card:
            energy_card.zone = Zone.DISCARD
            if energy_card not in player.discard:
                player.discard.append(energy_card)
    pokemon.energy_attached.clear()

    pokemon.zone = Zone.DISCARD
    player.discard.append(pokemon)


def _find_card_anywhere(player: PlayerState, instance_id: str) -> Optional[CardInstance]:
    all_cards = (
        player.deck
        + player.hand
        + player.discard
        + ([] if player.active is None else [player.active])
        + player.bench
    )
    for c in all_cards:
        if c.instance_id == instance_id:
            return c
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Card lookup helpers (used by action validation and effect handlers)
# ──────────────────────────────────────────────────────────────────────────────

def get_card_types(card: CardInstance) -> list[str]:
    cdef = card_registry.get(card.card_def_id)
    return cdef.types if cdef else []


def get_card_weaknesses(card: CardInstance) -> list[str]:
    cdef = card_registry.get(card.card_def_id)
    return [w.type for w in cdef.weaknesses] if cdef else []


def get_card_resistances(card: CardInstance) -> list[str]:
    cdef = card_registry.get(card.card_def_id)
    return [r.type for r in cdef.resistances] if cdef else []


def get_card_stage(card: CardInstance) -> str:
    cdef = card_registry.get(card.card_def_id)
    return cdef.stage if cdef else "Basic"


def get_prize_value(card: CardInstance) -> int:
    cdef = card_registry.get(card.card_def_id)
    return cdef.prize_value if cdef else 1


# ──────────────────────────────────────────────────────────────────────────────
# Tool helpers (called from attack/retreat/damage resolution)
# ──────────────────────────────────────────────────────────────────────────────

def has_tool(pokemon: CardInstance, tool_def_id: str) -> bool:
    """True if the given tool (by card_def_id) is attached to this Pokémon."""
    return tool_def_id in pokemon.tools_attached


def get_tool_damage_bonus(
    attacker: CardInstance,
    defender: CardInstance,
    attack_index: int,
    state: "GameState",
    attacker_player_id: str,
) -> int:
    """Return the net damage modifier from tools on attacker and defender.

    Called AFTER weakness/resistance.  Returns a signed integer to add to
    final_damage.

    Tools checked:
      Attacker's tools:
        - Maximum Belt (sv05-154): +50 vs Pokémon ex
        - Binding Mochi (sv08.5-095): +40 if attacker is Poisoned
        - Brave Bangle (sv10.5w-080): +30 vs Pokémon ex (non-rule-box attacker)
      Defender's tools:
        - Payapa Berry (sv07-141): -60 from {P} attacks
      Jamming Tower neutralizes all tools.
    """
    # Jamming Tower (sv06-153): all tools have no effect
    if state.active_stadium and state.active_stadium.card_def_id == "sv06-153":
        return 0

    from app.engine.state import StatusCondition
    bonus = 0

    # Maximum Belt (sv05-154): +50 to Pokémon ex
    if has_tool(attacker, "sv05-154"):
        defender_def = card_registry.get(defender.card_def_id)
        if defender_def and getattr(defender_def, "is_ex", False):
            bonus += 50

    # Brave Bangle (sv10.5w-080): non-rule-box attacker does +30 to Pokémon ex
    if has_tool(attacker, "sv10.5w-080"):
        attacker_def = card_registry.get(attacker.card_def_id)
        defender_def = card_registry.get(defender.card_def_id)
        if (attacker_def and not getattr(attacker_def, "has_rule_box", False)
                and defender_def and getattr(defender_def, "is_ex", False)):
            bonus += 30

    # Binding Mochi (sv08.5-095): +40 if attacker is Poisoned
    if has_tool(attacker, "sv08.5-095"):
        if StatusCondition.POISONED in attacker.status_conditions:
            bonus += 40

    # Payapa Berry (sv07-141): -60 from Psychic attacks
    if has_tool(defender, "sv07-141"):
        attacker_def = card_registry.get(attacker.card_def_id)
        if attacker_def and "Psychic" in (attacker_def.types or []):
            bonus -= 60

    return bonus


def get_retreat_cost_reduction(pokemon: CardInstance, state: "GameState", player_id: str = None) -> int:
    """Return the retreat cost reduction from tools and passive abilities.

    Tools checked:
      - Air Balloon (me02.5-181): -2 retreat cost
      - N's Castle (sv09-152): N's Pokémon free retreat (full reduction)
    Passive abilities checked:
      - Skyliner (sv08-076 Latias ex): Basic Pokémon have free retreat
    """
    # Jamming Tower neutralizes tools
    if state.active_stadium and state.active_stadium.card_def_id == "sv06-153":
        return 0

    # Melt Away (sv10-036 Ethan's Magcargo): free retreat when no Energy attached
    if pokemon.card_def_id == "sv10-036" and not pokemon.energy_attached:
        return 9999

    # Metal Bridge (sv07-107 Archaludon SCR / sv08.5-070 Archaludon ex PRE): free retreat if Metal Energy attached
    if pokemon.card_def_id in ("sv07-107", "sv08.5-070"):
        if any(att.energy_type == EnergyType.METAL for att in pokemon.energy_attached):
            return 9999

    # Skyliner (sv08-076 Latias ex): Basic Pokémon have free retreat
    if player_id is not None:
        from app.engine.effects.abilities import has_skyliner
        poke_def = card_registry.get(pokemon.card_def_id)
        if (has_skyliner(state, player_id)
                and poke_def
                and poke_def.stage.lower() == "basic"):
            return 9999

    reduction = 0

    if has_tool(pokemon, "me02.5-181"):  # Air Balloon
        reduction += 2

    # N's Castle (sv09-152): free retreat for N's Pokémon
    if (state.active_stadium and state.active_stadium.card_def_id == "sv09-152"
            and pokemon.card_name.startswith("N's")):
        return 9999  # Effectively free retreat (≥ any retreat cost)

    # Secret Forest Path (sv09-089 Toedscruel): -2 retreat cost while on bench
    if player_id is not None:
        from app.engine.effects.abilities import has_secret_forest_path
        if has_secret_forest_path(state, player_id):
            reduction += 2

    return reduction
