"""Action types, Action dataclass, and ActionValidator.

Implements all 14 validation rules from §6.3 of PROJECT.md.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    pass

from app.engine.state import (
    CardInstance,
    EnergyType,
    GameState,
    Phase,
    PlayerState,
    Zone,
)
from app.cards import registry as card_registry

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Action types (§6.2)
# ──────────────────────────────────────────────────────────────────────────────

class ActionType(Enum):
    # Setup
    PLACE_ACTIVE = auto()
    PLACE_BENCH = auto()
    MULLIGAN_REDRAW = auto()

    # Main phase
    PLAY_SUPPORTER = auto()
    PLAY_ITEM = auto()
    PLAY_STADIUM = auto()
    PLAY_TOOL = auto()
    ATTACH_ENERGY = auto()
    EVOLVE = auto()
    RETREAT = auto()
    USE_ABILITY = auto()
    PLAY_BASIC = auto()    # Play a Basic Pokémon to bench during main phase

    # Attack phase
    ATTACK = auto()

    # Forced / interrupts
    CHOOSE_TARGET = auto()
    CHOOSE_CARDS = auto()
    CHOOSE_OPTION = auto()
    DISCARD_ENERGY = auto()
    SWITCH_ACTIVE = auto()

    # Turn management
    PASS = auto()      # End main phase → move to attack declaration
    END_TURN = auto()  # End turn without attacking


@dataclass
class Action:
    action_type: ActionType
    player_id: str
    card_instance_id: Optional[str] = None      # Card being played/used
    target_instance_id: Optional[str] = None    # Target of the action
    attack_index: Optional[int] = None          # Which attack (0 or 1)
    selected_cards: Optional[list[str]] = None  # For multi-select effects
    selected_option: Optional[int] = None       # For choice effects

    # AI reasoning (only populated for AI players)
    reasoning: Optional[str] = None

    # Choice metadata (populated for CHOOSE_* action types so players can read constraints)
    choice_context: Optional[object] = None  # ChoiceRequest — avoids circular import

    @property
    def chosen_card_ids(self) -> Optional[list[str]]:
        """Alias for selected_cards, used by many attack handlers."""
        return self.selected_cards

    @property
    def chosen_ids(self) -> Optional[list[str]]:
        """Alias for selected_cards, used by batch-style attack handlers."""
        return self.selected_cards


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _find(cards: list[CardInstance], instance_id: str) -> Optional[CardInstance]:
    for c in cards:
        if c.instance_id == instance_id:
            return c
    return None


def _in_play(player: PlayerState) -> list[CardInstance]:
    """All Pokémon a player has in play (active + bench)."""
    result = []
    if player.active:
        result.append(player.active)
    result.extend(player.bench)
    return result


def _can_pay_energy_cost(pokemon: CardInstance, cost: list[str],
                         state=None, player_id: str = None) -> bool:
    """Return True if the attached energy satisfies the attack's energy cost.

    "Any" energy (provided by Prism Energy, Legacy Energy) satisfies one typed
    requirement as a wildcard — it acts like any single energy type.
    Wild Growth (me01-010 Meganium): each Basic Grass Energy provides 2G.
    """
    if not cost:
        return True

    available: list[str] = []
    for att in pokemon.energy_attached:
        available.extend([e.value for e in att.provides])

    # Separate "Any" wildcards from typed energy
    any_count = available.count("Any")
    typed_available: dict[str, int] = {}
    for e in available:
        if e != "Any":
            typed_available[e] = typed_available.get(e, 0) + 1

    # Wild Growth (me01-010 Meganium): each Basic Grass Energy provides 2G instead of 1G
    if state is not None and player_id is not None:
        from app.engine.effects.abilities import has_wild_growth
        if has_wild_growth(state, player_id):
            for att in pokemon.energy_attached:
                if att.energy_type.value == "Grass":
                    cdef_e = card_registry.get(att.card_def_id)
                    if (cdef_e
                            and cdef_e.category.lower() == "energy"
                            and cdef_e.subcategory.lower() == "basic"):
                        typed_available["Grass"] = typed_available.get("Grass", 0) + 1

    colorless_needed = 0
    wildcards_used = 0
    for req in cost:
        if req.capitalize() == "Colorless":
            colorless_needed += 1
        else:
            # Try matching exact typed energy first
            if typed_available.get(req, 0) > 0:
                typed_available[req] -= 1
            elif wildcards_used < any_count:
                # "Any" energy satisfies one typed requirement
                wildcards_used += 1
            else:
                return False

    # Remaining typed energy + unused "Any" covers Colorless requirements
    total_remaining = sum(typed_available.values()) + (any_count - wildcards_used)
    return total_remaining >= colorless_needed


def _can_pay_retreat(pokemon: CardInstance, retreat_cost: int, state: GameState = None, player_id: str = None) -> bool:
    """Return True if the Pokémon has enough total energy for its retreat cost.

    Accounts for tool-based and ability-based retreat cost reductions.
    """
    from app.engine.effects.base import get_retreat_cost_reduction
    if state:
        reduction = get_retreat_cost_reduction(pokemon, state, player_id)
        effective_cost = max(0, retreat_cost - reduction)
    else:
        effective_cost = retreat_cost
    total = sum(len(att.provides) for att in pokemon.energy_attached)
    return total >= effective_cost


def _evolves_from(candidate: CardInstance, target: CardInstance, state: GameState) -> bool:
    """Return True if candidate is a valid evolution of target.

    Uses the CardDefinition registry to check evolve_from field.
    """
    cdef = card_registry.get(candidate.card_def_id)
    if cdef is None:
        return False
    if cdef.evolve_from is None:
        return False
    # Rainbow DNA (sv08.5-075 Eevee ex): any Pokémon ex that evolves from Eevee
    # can be placed onto Eevee ex (bypasses the evolve_from="Eevee" vs card_name="Eevee ex" mismatch)
    if target.card_def_id == "sv08.5-075":
        return (cdef.evolve_from.lower() == "eevee"
                and "ex" in candidate.card_name.lower())
    # evolve_from holds the *name* of the pre-evolution
    return cdef.evolve_from.lower() == target.card_name.lower()


# ──────────────────────────────────────────────────────────────────────────────
# ActionValidator (§6.3)
# ──────────────────────────────────────────────────────────────────────────────

class ActionValidator:
    """Gatekeeper for all state transitions.

    No state mutation occurs without passing through validate().
    get_legal_actions() is used by players to enumerate choices.
    """

    MAX_BENCH_SIZE = 5

    # ── Public API ─────────────────────────────────────────────────────────────

    @staticmethod
    def get_legal_actions(state: GameState, player_id: str) -> list[Action]:
        """Return ALL legal actions for the given player in the current state."""
        player = state.get_player(player_id)
        actions: list[Action] = []

        if state.phase == Phase.SETUP:
            actions.extend(ActionValidator._setup_actions(state, player, player_id))

        elif state.phase == Phase.MAIN:
            if state.active_player != player_id:
                return []
            actions.extend(ActionValidator._get_play_basic_actions(state, player, player_id))
            actions.extend(ActionValidator._get_play_actions(state, player, player_id))
            actions.extend(ActionValidator._get_energy_actions(state, player, player_id))
            actions.extend(ActionValidator._get_evolve_actions(state, player, player_id))
            actions.extend(ActionValidator._get_retreat_actions(state, player, player_id))
            actions.extend(ActionValidator._get_ability_actions(state, player, player_id))
            actions.append(Action(ActionType.PASS, player_id))
            actions.append(Action(ActionType.END_TURN, player_id))

        elif state.phase == Phase.ATTACK:
            if state.active_player != player_id:
                return []
            actions.extend(ActionValidator._get_attack_actions(state, player, player_id))
            actions.append(Action(ActionType.END_TURN, player_id))

        return actions

    @staticmethod
    def validate(state: GameState, action: Action) -> tuple[bool, str]:
        """Returns (is_valid, error_message).

        Quick path: rebuild legal actions and check if this action is in the set.
        For FORCED actions (SWITCH_ACTIVE, CHOOSE_*, DISCARD_ENERGY) bypass normal
        phase checks.
        """
        forced = {
            ActionType.SWITCH_ACTIVE,
            ActionType.CHOOSE_TARGET,
            ActionType.CHOOSE_CARDS,
            ActionType.CHOOSE_OPTION,
            ActionType.DISCARD_ENERGY,
        }
        if action.action_type in forced:
            return True, ""

        legal = ActionValidator.get_legal_actions(state, action.player_id)
        for la in legal:
            if ActionValidator._actions_match(la, action):
                return True, ""
        return False, f"{action.action_type.name} is not legal in current state"

    # ── Setup ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _setup_actions(
        state: GameState, player: PlayerState, player_id: str
    ) -> list[Action]:
        actions: list[Action] = []
        basics = [c for c in player.hand
                  if c.card_type.lower() == "pokemon" and c.evolution_stage == 0]

        # If player has no basics → must mulligan
        if not basics:
            actions.append(Action(ActionType.MULLIGAN_REDRAW, player_id))
            return actions

        # Must place active if not yet placed
        if player.active is None:
            for b in basics:
                actions.append(
                    Action(ActionType.PLACE_ACTIVE, player_id,
                           card_instance_id=b.instance_id)
                )
            return actions

        # Active is set; may place up to MAX_BENCH_SIZE bench Pokémon
        if len(player.bench) < ActionValidator.MAX_BENCH_SIZE:
            for b in basics:
                actions.append(
                    Action(ActionType.PLACE_BENCH, player_id,
                           card_instance_id=b.instance_id)
                )

        return actions

    # ── Main phase ────────────────────────────────────────────────────────────

    @staticmethod
    def _get_play_basic_actions(
        state: GameState, player: PlayerState, player_id: str
    ) -> list[Action]:
        """Play a Basic Pokémon to the bench (rule 9: max 5)."""
        if len(player.bench) >= ActionValidator.MAX_BENCH_SIZE:
            return []
        opp = state.get_opponent(player_id)
        # Potent Glare (sv10-113 TR Arbok): opp cannot play Pokémon with abilities from hand
        # (except Team Rocket's Pokémon)
        potent_glare = (opp.active and opp.active.card_def_id == "sv10-113")
        basics = [c for c in player.hand
                  if c.card_type.lower() == "pokemon" and c.evolution_stage == 0]
        result = []
        for b in basics:
            if potent_glare:
                bcdef = card_registry.get(b.card_def_id)
                if bcdef and bcdef.abilities and "Team Rocket's" not in b.card_name:
                    continue
            result.append(Action(ActionType.PLAY_BASIC, player_id, card_instance_id=b.instance_id))
        return result

    @staticmethod
    def _get_play_actions(
        state: GameState, player: PlayerState, player_id: str
    ) -> list[Action]:
        actions: list[Action] = []
        for card in player.hand:
            ctype = card.card_type.lower()
            csub = card.card_subtype.lower()

            if ctype == "trainer":
                if csub == "supporter":
                    # Rule 1: only one Supporter per turn
                    if not player.supporter_played_this_turn:
                        if player.supporters_locked_next_turn:
                            continue  # Scream Tail ex locked Supporter plays this turn
                        actions.append(
                            Action(ActionType.PLAY_SUPPORTER, player_id,
                                   card_instance_id=card.instance_id)
                        )
                elif csub == "item":
                    if not player.items_locked_this_turn:
                        # Daunting Gaze (sv09-095 Tyranitar): opp cannot play Item cards while Active
                        opp_for_dg = state.get_opponent(player_id)
                        if (opp_for_dg.active
                                and opp_for_dg.active.card_def_id == "sv09-095"):
                            continue
                        # Oceanic Curse (sv10.5w-045 Jellicent ex): opp cannot play Item or Tool cards
                        if (opp_for_dg.active
                                and opp_for_dg.active.card_def_id == "sv10.5w-045"):
                            continue
                        actions.append(
                            Action(ActionType.PLAY_ITEM, player_id,
                                   card_instance_id=card.instance_id)
                        )
                elif csub == "stadium":
                    # Rule 10: cannot play same Stadium already in play
                    if (state.active_stadium is None
                            or state.active_stadium.card_def_id != card.card_def_id):
                        actions.append(
                            Action(ActionType.PLAY_STADIUM, player_id,
                                   card_instance_id=card.instance_id)
                        )
                elif csub == "tool":
                    # Oceanic Curse (sv10.5w-045 Jellicent ex): opp cannot play Item or Tool cards
                    opp_for_oc = state.get_opponent(player_id)
                    if (opp_for_oc.active
                            and opp_for_oc.active.card_def_id == "sv10.5w-045"):
                        continue
                    # Multi Adapter (me02-029 Rotom ex): Rotom-named Pokémon may have 2 Tools
                    _has_multi_adapter = any(
                        p.card_def_id == "me02-029" for p in _in_play(player)
                    )
                    # Rule 12: one Tool per Pokémon (two for Rotom with Multi Adapter)
                    for poke in _in_play(player):
                        max_tools = (2 if _has_multi_adapter
                                     and "Rotom" in poke.card_name else 1)
                        if len(poke.tools_attached) < max_tools:
                            actions.append(
                                Action(ActionType.PLAY_TOOL, player_id,
                                       card_instance_id=card.instance_id,
                                       target_instance_id=poke.instance_id)
                            )
        return actions

    @staticmethod
    def _get_energy_actions(
        state: GameState, player: PlayerState, player_id: str
    ) -> list[Action]:
        # Rule 2: only one manual energy attachment per turn
        if player.energy_attached_this_turn:
            # Inferno Fandango (sv10.5w-013 Emboar): unlimited Basic Fire Energy attachments
            if any(p.card_def_id == "sv10.5w-013" for p in _in_play(player)):
                fire_energy = [
                    c for c in player.hand
                    if c.card_type.lower() == "energy"
                    and c.card_subtype.lower() == "basic"
                    and "Fire" in (c.energy_provides or [])
                ]
                if not fire_energy:
                    return []
                targets = _in_play(player)
                return [
                    Action(ActionType.ATTACH_ENERGY, player_id,
                           card_instance_id=e.instance_id,
                           target_instance_id=t.instance_id)
                    for e in fire_energy
                    for t in targets
                ]
            return []
        energy_in_hand = [
            c for c in player.hand if c.card_type.lower() == "energy"
        ]
        targets = _in_play(player)
        return [
            Action(ActionType.ATTACH_ENERGY, player_id,
                   card_instance_id=e.instance_id,
                   target_instance_id=t.instance_id)
            for e in energy_in_hand
            for t in targets
        ]

    @staticmethod
    def _get_evolve_actions(
        state: GameState, player: PlayerState, player_id: str
    ) -> list[Action]:
        """Return all legal evolution actions.

        Rules 3 & 4: cannot evolve a Pokémon the same turn it was played or evolved.
        Rule 11: evolution must follow the correct chain.
        """
        actions: list[Action] = []
        if player.evolution_blocked_next_turn:
            return []
        in_play = _in_play(player)
        evolutions_in_hand = [
            c for c in player.hand
            if c.card_type.lower() == "pokemon" and c.evolution_stage > 0
        ]
        opp_for_pg = state.get_opponent(player_id)
        # Potent Glare (sv10-113 TR Arbok): opp cannot play Pokémon with abilities from hand
        potent_glare_evo = (opp_for_pg.active and opp_for_pg.active.card_def_id == "sv10-113")
        for evo in evolutions_in_hand:
            # Potent Glare check: if evo card has abilities, skip it (unless Team Rocket's)
            if potent_glare_evo:
                evo_cdef_pg = card_registry.get(evo.card_def_id)
                if evo_cdef_pg and evo_cdef_pg.abilities and "Team Rocket's" not in evo.card_name:
                    continue
            for target in in_play:
                # Cannot evolve a card played or evolved this turn
                if target.turn_played == state.turn_number:
                    # Forest of Vitality (me01-117): Grass Pokémon may evolve same turn
                    # they were played (except on the very first turn of the game)
                    if (state.active_stadium
                            and state.active_stadium.card_def_id == "me01-117"
                            and not (state.turn_number == 1
                                     and state.active_player == state.first_player)):
                        tdef = card_registry.get(target.card_def_id)
                        if not (tdef and "Grass" in (tdef.types or [])):
                            continue
                    # Stimulated Evolution (sv10.5b-009 Karrablast): evo allowed if Shelmet in play
                    elif (target.card_def_id == "sv10.5b-009"
                          and any(p.card_def_id == "sv10.5w-008" for p in in_play)):
                        pass  # allow evolution
                    # Stimulated Evolution (sv10.5w-008 Shelmet): evo allowed if Karrablast in play
                    elif (target.card_def_id == "sv10.5w-008"
                          and any(p.card_def_id == "sv10.5b-009" for p in in_play)):
                        pass  # allow evolution
                    # Boosted Evolution (sv08.5-074 Eevee PRE): evo allowed if in Active Spot
                    elif (target.card_def_id == "sv08.5-074"
                          and player.active is not None
                          and player.active.instance_id == target.instance_id):
                        pass  # allow evolution while Active
                    else:
                        continue
                # Must follow correct chain
                if not _evolves_from(evo, target, state):
                    continue
                # Stage must be exactly one step up
                cdef = card_registry.get(evo.card_def_id)
                if cdef and cdef.stage:
                    stage_map = {"stage1": 1, "stage 1": 1,
                                 "stage2": 2, "stage 2": 2, "mega": 2}
                    req_stage = stage_map.get(cdef.stage.lower(), evo.evolution_stage)
                    if req_stage != target.evolution_stage + 1:
                        continue
                actions.append(
                    Action(ActionType.EVOLVE, player_id,
                           card_instance_id=evo.instance_id,
                           target_instance_id=target.instance_id)
                )
        return actions

    @staticmethod
    def _get_retreat_actions(
        state: GameState, player: PlayerState, player_id: str
    ) -> list[Action]:
        """Rule 6: cannot retreat if no bench.  Rule 7: must pay cost."""
        if player.retreat_used_this_turn:
            return []
        if not player.active:
            return []
        if not player.bench:  # Rule 6
            return []
        # Multi-turn lock (e.g. Dusknoir Shadow Bind, Yveltal)
        if player.active.cant_retreat_next_turn:
            return []

        cdef = card_registry.get(player.active.card_def_id)
        retreat_cost = cdef.retreat_cost if cdef else 0
        # Paradise Resort (svp-150 / svp-224): Psyduck retreat cost reduced by 1
        if (state.active_stadium
                and state.active_stadium.card_def_id in ("svp-150", "svp-224")
                and player.active.card_def_id == "mep-007"):
            retreat_cost = max(0, retreat_cost - 1)
        if not _can_pay_retreat(player.active, retreat_cost, state, player_id):  # Rule 7
            return []

        return [
            Action(ActionType.RETREAT, player_id,
                   target_instance_id=b.instance_id)
            for b in player.bench
        ]

    @staticmethod
    def _get_ability_actions(
        state: GameState, player: PlayerState, player_id: str
    ) -> list[Action]:
        from app.engine.effects.registry import EffectRegistry
        registry = EffectRegistry.instance()
        actions: list[Action] = []
        for poke in _in_play(player):
            if poke.ability_used_this_turn:
                continue
            cdef = card_registry.get(poke.card_def_id)
            if not (cdef and cdef.abilities):
                continue
            ability_name = cdef.abilities[0].name
            # Only offer USE_ABILITY for abilities with a registered handler.
            # Passive abilities (e.g. Damp, Power Saver) have no handler and
            # must never appear as player actions.
            if not registry.has_effect(cdef.tcgdex_id, "ability"):
                continue
            # If a precondition is registered, check it before offering.
            if not registry.ability_can_activate(cdef.tcgdex_id, ability_name,
                                                 state, player_id, poke):
                continue
            # Watchtower (sv10-180): Colorless Pokémon cannot use abilities
            if (state.active_stadium
                    and state.active_stadium.card_def_id == "sv10-180"
                    and "Colorless" in (cdef.types or [])):
                continue
            # Initialization (sv08.5-032 Iron Thorns ex): rule-box Pokémon can't use abilities
            # when Iron Thorns is active on either side.
            opp_init = state.get_opponent(player_id)
            if cdef.has_rule_box and (
                (opp_init.active and opp_init.active.card_def_id == "sv08.5-032")
                or (player.active and player.active.card_def_id == "sv08.5-032")
            ):
                continue
            # Midnight Fluttering (sv08.5-043 Flutter Mane): opp's active Pokémon can't use abilities
            if (opp_init.active and opp_init.active.card_def_id == "sv08.5-043"
                    and poke is player.active):
                continue
            # Midnight Fluttering (sv05-078 / svp-097 Flutter Mane alt prints): same effect
            if (opp_init.active and opp_init.active.card_def_id in ("sv05-078", "svp-097")
                    and poke is player.active):
                continue
            # Sticky Bind (sv08-107 Gastrodon): opp's Benched Stage-2 Pokémon can't use abilities
            if (opp_init.active and opp_init.active.card_def_id == "sv08-107"
                    and poke is not player.active):
                poke_cdef = card_registry.get(poke.card_def_id)
                if poke_cdef and (poke_cdef.stage or "").lower() in ("stage2", "stage 2"):
                    continue
            # Ancient Wing (sv10.5w-051 Archeops): Active only; opp must have evolved Pokémon
            if poke.card_def_id == "sv10.5w-051":
                if poke is not player.active:
                    continue
                _opp_archeops = state.get_opponent(player_id)
                _opp_evolved = [p for p in (([_opp_archeops.active] if _opp_archeops.active else []) + _opp_archeops.bench)
                                if p.evolved_from is not None]
                if not _opp_evolved:
                    continue
            actions.append(
                Action(ActionType.USE_ABILITY, player_id,
                       card_instance_id=poke.instance_id)
            )
        # Emergency Rotation (sv07-101 Klinklang): from hand → bench if opp has Stage 2
        _opp_er = state.get_opponent(player_id)
        _has_opp_stage2 = any(p.evolution_stage == 2 for p in (
            ([_opp_er.active] if _opp_er.active else []) + _opp_er.bench))
        if _has_opp_stage2 and len(player.bench) < ActionValidator.MAX_BENCH_SIZE:
            for c in player.hand:
                if c.card_def_id == "sv07-101" and not c.ability_used_this_turn:
                    actions.append(Action(ActionType.USE_ABILITY, player_id,
                                          card_instance_id=c.instance_id))
        return actions

    # ── Attack phase ──────────────────────────────────────────────────────────

    @staticmethod
    def _get_attack_actions(
        state: GameState, player: PlayerState, player_id: str
    ) -> list[Action]:
        """Rule 5: first player cannot attack on turn 1.  Rule 8: must have energy."""
        if not player.active:
            return []
        # Rule 5: no attack on the very first turn for the first player
        if state.turn_number == 1 and state.active_player == state.first_player:
            # Debut Performance (sv10.5b-044 Meloetta ex): can attack on first turn if going first
            # Precocious Evolution (sv08-001 Exeggcute): can use atk0 on first turn if going first
            if not (player.active
                    and player.active.card_def_id in ("sv10.5b-044", "sv08-001")):
                return []
        # Multi-turn lock (e.g. Iron Leaves ex Mach Claw, Bloodmoon Ursaluna ex)
        if player.active.cant_attack_next_turn:
            return []
        # Power Saver (sv10-081 TR Mewtwo ex): cannot attack unless 4+ TR Pokémon in play
        from app.engine.effects.abilities import power_saver_blocks_attack
        if power_saver_blocks_attack(state, player.active, player_id):
            return []

        cdef = card_registry.get(player.active.card_def_id)
        if not cdef or not cdef.attacks:
            return []

        actions: list[Action] = []
        opp = state.get_opponent(player_id)
        for i, attack in enumerate(cdef.attacks):
            if player.active.locked_attack_index is not None and i == player.active.locked_attack_index:
                continue
            effective_cost = list(attack.cost) if attack.cost else []
            # Seasoned Skill (sv06-141 Bloodmoon Ursaluna ex): costs 1 less {C}
            # per prize card the opponent has taken.
            if cdef.tcgdex_id == "sv06-141":
                prizes_taken = 6 - opp.prizes_remaining
                for _ in range(prizes_taken):
                    if "Colorless" in effective_cost:
                        effective_cost.remove("Colorless")
            # Cutting Riposte (me01-085 Crawdaunt): cost drops to {D} if has damage counters
            if cdef.tcgdex_id == "me01-085" and i == 1:
                if player.active.damage_counters > 0:
                    effective_cost = ["Darkness"]
            # Tuning Echo (sv09-128 Noivern): Frightening Howl costs nothing if hand sizes match
            if cdef.tcgdex_id == "sv09-128" and i == 0:
                if len(player.hand) == len(opp.hand):
                    effective_cost = []
            # Raging Tentacles (sv08-113 Grapploct): cost drops to {F} if has damage counters
            if cdef.tcgdex_id == "sv08-113" and i == 1:
                if player.active.damage_counters > 0:
                    effective_cost = ["Fighting"]
            # Hustle Play (sv05-034 Incineroar ex): costs {C} less per opp Benched Pokémon
            if cdef.tcgdex_id == "sv05-034":
                opp_bench_count = len(opp.bench)
                for _ in range(opp_bench_count):
                    if "Colorless" in effective_cost:
                        effective_cost.remove("Colorless")
                    else:
                        break
            # Glistening Bubbles (sv08-074 Azumarill): Double-Edge costs {P} if any Tera in play
            if cdef.tcgdex_id == "sv08-074" and i == 0:  # Double-Edge is atk0
                if any(getattr(card_registry.get(p.card_def_id), "is_tera", False)
                       for p in _in_play(player)):
                    effective_cost = ["Psychic"]
            # Gutsy Swing (sv06-105 Conkeldurr TWM): free if has any Special Condition
            if cdef.tcgdex_id == "sv06-105" and i == 1:  # Gutsy Swing is atk1
                if player.active.status_conditions:
                    effective_cost = []
            if _can_pay_energy_cost(player.active, effective_cost, state, player_id):
                actions.append(
                    Action(ActionType.ATTACK, player_id, attack_index=i)
                )

        # TM attack support: check Pokémon tools for cards with their own attacks
        for _tool_slot, _tm_def_id in enumerate(player.active.tools_attached):
            _tm_cdef = card_registry.get(_tm_def_id)
            if not _tm_cdef or not getattr(_tm_cdef, "attacks", None):
                continue
            for _tm_atk_idx, _tm_attack in enumerate(_tm_cdef.attacks):
                _tm_cost = list(_tm_attack.cost) if _tm_attack.cost else []
                if _can_pay_energy_cost(player.active, _tm_cost, state, player_id):
                    actions.append(
                        Action(ActionType.ATTACK, player_id,
                               attack_index=100 + _tool_slot * 10 + _tm_atk_idx)
                    )

        # Memory Dive (sv05-084 Relicanth): evolved active Pokémon can use prior-form attacks
        _relicanth_ids = {"sv05-084"}
        _all_in_play_md = ([player.active] if player.active else []) + list(player.bench)
        if (player.active
                and player.active.evolved_from
                and any(p.card_def_id in _relicanth_ids for p in _all_in_play_md)):
            _pre_evo_inst = player.active.evolved_from
            _pre_evo = next(
                (c for c in player.discard if c.instance_id == _pre_evo_inst), None
            )
            if _pre_evo:
                _pre_cdef = card_registry.get(_pre_evo.card_def_id)
                if _pre_cdef and _pre_cdef.attacks:
                    for _md_atk_idx, _md_atk in enumerate(_pre_cdef.attacks):
                        _md_cost = list(_md_atk.cost) if _md_atk.cost else []
                        if _can_pay_energy_cost(player.active, _md_cost, state, player_id):
                            actions.append(Action(
                                action_type=ActionType.ATTACK,
                                player_id=player_id,
                                attack_index=200 + _md_atk_idx,
                            ))

        return actions

    # ── Matching helper ────────────────────────────────────────────────────────

    @staticmethod
    def _actions_match(a: Action, b: Action) -> bool:
        """Compare two actions for equality (ignores reasoning)."""
        return (
            a.action_type == b.action_type
            and a.player_id == b.player_id
            and a.card_instance_id == b.card_instance_id
            and a.target_instance_id == b.target_instance_id
            and a.attack_index == b.attack_index
        )
