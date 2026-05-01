"""Energy effect handlers — Phase 2 implementation.

Special energy on-attach handlers.  Basic energies (mee-001 through mee-007)
need no handlers — their type is handled by the default attachment logic.

Handler contract:
  - Regular functions: ``handler(state, action) -> None``  (mutate state)
  - Generator functions: ``handler(state, action) -> Generator``  (yield ChoiceRequest)
  - The action's ``card_instance_id`` is the energy card being attached.
  - The action's ``target_instance_id`` is the Pokémon receiving the energy.
  - The EnergyAttachment is already present in target.energy_attached when the
    handler is called; handlers update ``att.provides`` and ``att.discard_at_end_of_turn``
    as needed.
"""

from __future__ import annotations

import logging
import random

from app.engine.state import EnergyType, GameState, Zone
from app.engine.effects.base import ChoiceRequest, draw_cards
from app.engine.effects.registry import EffectRegistry
from app.cards import registry as card_registry

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────

def _noop_energy(state: GameState, action) -> None:
    """No-op energy handler for flagged/passive-only special energies."""


def _get_attachment(target, source_card_id: str):
    """Return the EnergyAttachment whose source_card_id matches."""
    for att in target.energy_attached:
        if att.source_card_id == source_card_id:
            return att
    return None


def _set_provides(target, source_card_id: str, provides: list[EnergyType]) -> None:
    att = _get_attachment(target, source_card_id)
    if att:
        att.provides = provides
        att.energy_type = provides[0] if provides else EnergyType.COLORLESS


# ──────────────────────────────────────────────────────────────────────────────
# Prism Energy (me02.5-216)
# Provides Any for Basic Pokémon, Colorless for evolved.
# ──────────────────────────────────────────────────────────────────────────────

def _prism_energy(state: GameState, action) -> None:
    player = state.get_player(action.player_id)
    target = next(
        (c for c in ([player.active] if player.active else []) + player.bench
         if c.instance_id == action.target_instance_id), None
    )
    if target is None:
        return
    if target.evolution_stage == 0:
        _set_provides(target, action.card_instance_id, [EnergyType.ANY])
    else:
        _set_provides(target, action.card_instance_id, [EnergyType.COLORLESS])


# ──────────────────────────────────────────────────────────────────────────────
# Growing Grass Energy (me03-086)
# Provides Grass. The Grass Pokémon this card is attached to gets +20 HP.
# ──────────────────────────────────────────────────────────────────────────────

def _growing_grass_energy(state: GameState, action) -> None:
    player = state.get_player(action.player_id)
    target = next(
        (c for c in ([player.active] if player.active else []) + player.bench
         if c.instance_id == action.target_instance_id), None
    )
    if target is None:
        return
    _set_provides(target, action.card_instance_id, [EnergyType.GRASS])
    target_def = card_registry.get(target.card_def_id)
    if target_def and "Grass" in (target_def.types or []):
        target.max_hp += 20
        target.current_hp += 20
        state.emit_event("hp_boost", player=action.player_id, card=target.card_name,
                         amount=20, reason="growing_grass_energy")


# ──────────────────────────────────────────────────────────────────────────────
# Telepathic Psychic Energy (me03-088)
# Provides Psychic. On-attach to a Psychic Pokémon: search deck for up to 2
# Basic Psychic Pokémon → bench.  Requires player choice (generator).
# ──────────────────────────────────────────────────────────────────────────────

def _telepathic_psychic_energy(state: GameState, action):
    player = state.get_player(action.player_id)
    target = next(
        (c for c in ([player.active] if player.active else []) + player.bench
         if c.instance_id == action.target_instance_id), None
    )
    if target is None:
        return
    _set_provides(target, action.card_instance_id, [EnergyType.PSYCHIC])

    # Check if attached to a Psychic Pokémon
    target_def = card_registry.get(target.card_def_id)
    if not target_def or "Psychic" not in (target_def.types or []):
        return  # No bench effect outside Psychic targets

    bench_slots = 5 - len(player.bench) - (1 if player.active else 0)
    # Bench is relative to bench count; active slot always occupied if set
    bench_slots = 5 - len(player.bench)
    if bench_slots <= 0:
        return

    basics_in_deck = [
        c for c in player.deck
        if c.card_type.lower() == "pokemon" and c.evolution_stage == 0
        and "Psychic" in (card_registry.get(c.card_def_id).types or []
                          if card_registry.get(c.card_def_id) else [])
    ]
    if not basics_in_deck:
        return

    max_bench = min(2, bench_slots, len(basics_in_deck))
    request = ChoiceRequest(
        choice_type="choose_cards",
        player_id=action.player_id,
        prompt="Telepathic Psychic Energy: search your deck for up to 2 Basic Psychic Pokémon to put on your Bench.",
        cards=basics_in_deck,
        min_count=0,
        max_count=max_bench,
    )
    chosen_action = yield request
    selected_ids = (chosen_action.selected_cards or []) if chosen_action else []

    for iid in selected_ids:
        if len(player.bench) >= 5:
            break
        poke = next((c for c in player.deck if c.instance_id == iid), None)
        if poke:
            player.deck.remove(poke)
            poke.zone = Zone.IN_PLAY
            poke.turn_played = state.turn_number
            player.bench.append(poke)
            state.emit_event("bench", player=action.player_id, card=poke.card_name,
                             reason="telepathic_psychic_energy")

    # Shuffle deck
    random.shuffle(player.deck)
    state.emit_event("deck_shuffled", player=action.player_id,
                     reason="telepathic_psychic_energy")


# ──────────────────────────────────────────────────────────────────────────────
# Mist Energy (sv05-161)
# Provides Colorless. Passive: prevents opponent attack EFFECTS on this Pokémon.
# (Damage is not blocked — only additional effects like status, discard, etc.)
# The passive is checked in individual attack handlers via has_mist_energy().
# No special on-attach logic needed.
# ──────────────────────────────────────────────────────────────────────────────

def _mist_energy(state: GameState, action) -> None:
    # provides already set to COLORLESS by _attach_energy default
    logger.debug("Mist Energy attached — opponent attack effects blocked on this Pokémon.")


# ──────────────────────────────────────────────────────────────────────────────
# Legacy Energy (sv06-167)
# Provides Any type (1). On-KO: attacker takes 1 fewer prize (once per game).
# The KO prize reduction is handled in base.check_ko() via att.card_def_id check.
# ──────────────────────────────────────────────────────────────────────────────

def _legacy_energy(state: GameState, action) -> None:
    player = state.get_player(action.player_id)
    target = next(
        (c for c in ([player.active] if player.active else []) + player.bench
         if c.instance_id == action.target_instance_id), None
    )
    if target is None:
        return
    _set_provides(target, action.card_instance_id, [EnergyType.ANY])


# ──────────────────────────────────────────────────────────────────────────────
# Enriching Energy (sv08-191)
# Provides Colorless. On-attach: draw 4 cards.
# ──────────────────────────────────────────────────────────────────────────────

def _enriching_energy(state: GameState, action) -> None:
    drawn = draw_cards(state, action.player_id, 4)
    logger.debug("Enriching Energy: drew %d cards for %s", drawn, action.player_id)


# ──────────────────────────────────────────────────────────────────────────────
# Team Rocket's Energy (sv10-182)
# Provides 2 Any (P/D combo). Can only attach to Team Rocket's Pokémon.
# If attached to non-TR Pokémon, discard this energy immediately.
# ──────────────────────────────────────────────────────────────────────────────

def _team_rockets_energy(state: GameState, action) -> None:
    player = state.get_player(action.player_id)
    target = next(
        (c for c in ([player.active] if player.active else []) + player.bench
         if c.instance_id == action.target_instance_id), None
    )
    if target is None:
        return

    is_tr_pokemon = target.card_name.startswith("Team Rocket's")
    att = _get_attachment(target, action.card_instance_id)
    if not att:
        return

    if not is_tr_pokemon:
        # Discard immediately
        target.energy_attached.remove(att)
        state.emit_event(
            "energy_discarded",
            card_def_id="sv10-182",
            pokemon=target.card_name,
            reason="team_rockets_energy_invalid_target",
        )
        return

    # Valid: provides 2 Any (limited to Psychic/Darkness in practice)
    att.provides = [EnergyType.ANY, EnergyType.ANY]
    att.energy_type = EnergyType.ANY


# ──────────────────────────────────────────────────────────────────────────────
# Ignition Energy (sv10.5w-086)
# Provides Colorless (or 3 Colorless for Evolution Pokémon).
# Discarded at end of the turn it is attached.
# ──────────────────────────────────────────────────────────────────────────────

def _ignition_energy(state: GameState, action) -> None:
    player = state.get_player(action.player_id)
    target = next(
        (c for c in ([player.active] if player.active else []) + player.bench
         if c.instance_id == action.target_instance_id), None
    )
    if target is None:
        return

    att = _get_attachment(target, action.card_instance_id)
    if not att:
        return

    is_evolution = target.evolution_stage > 0
    if is_evolution:
        att.provides = [EnergyType.COLORLESS, EnergyType.COLORLESS, EnergyType.COLORLESS]
        att.energy_type = EnergyType.COLORLESS
    else:
        att.provides = [EnergyType.COLORLESS]

    att.discard_at_end_of_turn = True


# ──────────────────────────────────────────────────────────────────────────────
# Passive helpers (called from attack handlers)
# ──────────────────────────────────────────────────────────────────────────────

def has_mist_energy(pokemon) -> bool:
    """True if the Pokémon has a Mist Energy attached."""
    _MIST_ID = "sv05-161"
    return any(att.card_def_id == _MIST_ID for att in pokemon.energy_attached)


def has_rocky_fighting_energy(pokemon) -> bool:
    """True if the Pokémon has a Rocky Fighting Energy attached."""
    _ROCKY_ID = "me03-087"
    return any(att.card_def_id == _ROCKY_ID for att in pokemon.energy_attached)


# ──────────────────────────────────────────────────────────────────────────────
# Rocky Fighting Energy (me03-087)
# Provides Fighting. Pokémon is not affected by any effects of opponent's
# attacks (damage is not an effect — this is a passive, checked via
# has_rocky_fighting_energy() in attack handlers that apply effects).
# ──────────────────────────────────────────────────────────────────────────────

def _rocky_fighting_energy(state: GameState, action) -> None:
    player = state.get_player(action.player_id)
    target = next(
        (c for c in ([player.active] if player.active else []) + player.bench
         if c.instance_id == action.target_instance_id), None
    )
    if target is None:
        return
    _set_provides(target, action.card_instance_id, [EnergyType.FIGHTING])


# ──────────────────────────────────────────────────────────────────────────────
# Registration
# ──────────────────────────────────────────────────────────────────────────────

def register_all(registry: EffectRegistry) -> None:
    """Register all special energy effect handlers."""
    registry.register_energy("me02.5-216", _prism_energy)
    registry.register_energy("me03-086",   _growing_grass_energy)
    registry.register_energy("me03-088",   _telepathic_psychic_energy)
    registry.register_energy("sv05-161",   _mist_energy)
    registry.register_energy("sv06-167",   _legacy_energy)
    registry.register_energy("sv08-191",   _enriching_energy)
    registry.register_energy("sv10-182",   _team_rockets_energy)
    registry.register_energy("sv10.5w-086", _ignition_energy)
    registry.register_energy("me03-087",   _rocky_fighting_energy)
    registry.register_energy("me02.5-217", _team_rockets_energy)   # Team Rocket's Energy (alt art)
    registry.register_energy("sv10.5b-086", _prism_energy)         # Prism Energy (alt art)
    # Flagged special energies — complex effects not yet modelled
    registry.register_energy("sv06-166", _noop_energy)  # Boomerang Energy (complex reuse — flagged)
    registry.register_energy("sv09-159", _noop_energy)  # Spiky Energy (damage on attach — flagged)
