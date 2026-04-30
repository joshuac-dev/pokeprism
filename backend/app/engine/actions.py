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
                    # Rule 12: one Tool per Pokémon
                    for poke in _in_play(player):
                        if not poke.tools_attached:
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
            actions.append(
                Action(ActionType.USE_ABILITY, player_id,
                       card_instance_id=poke.instance_id)
            )
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
            if _can_pay_energy_cost(player.active, effective_cost, state, player_id):
                actions.append(
                    Action(ActionType.ATTACK, player_id, attack_index=i)
                )
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
