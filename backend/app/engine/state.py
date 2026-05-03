"""Game state data model for the PokéPrism engine.

Follows §6.1 of PROJECT.md exactly, with one approved addition:
  CardInstance.energy_provides: list[str]  (approved Q3)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional
import uuid


# ──────────────────────────────────────────────────────────────────────────────
# Enumerations
# ──────────────────────────────────────────────────────────────────────────────

class Zone(Enum):
    DECK = auto()
    HAND = auto()
    ACTIVE = auto()
    BENCH = auto()
    DISCARD = auto()
    PRIZES = auto()
    LOST_ZONE = auto()
    STADIUM = auto()


class Phase(Enum):
    SETUP = auto()          # Initial setup: draw 7, place basics, set prizes
    DRAW = auto()           # Mandatory draw at turn start
    MAIN = auto()           # Play trainers, attach energy, evolve, use abilities
    ATTACK = auto()         # Declare and resolve attack
    BETWEEN_TURNS = auto()  # Check status conditions (poison, burn, etc.)
    GAME_OVER = auto()      # Terminal state


class StatusCondition(Enum):
    POISONED = auto()
    BURNED = auto()
    ASLEEP = auto()
    CONFUSED = auto()
    PARALYZED = auto()
    TOXIC = auto()       # Heavy Poison: 3 damage counters between turns (Pecharunt Poison Chain)


class EnergyType(Enum):
    GRASS = "Grass"
    FIRE = "Fire"
    WATER = "Water"
    LIGHTNING = "Lightning"
    PSYCHIC = "Psychic"
    FIGHTING = "Fighting"
    DARKNESS = "Darkness"
    METAL = "Metal"
    DRAGON = "Dragon"
    FAIRY = "Fairy"
    COLORLESS = "Colorless"
    ANY = "Any"   # Wildcard — provided by Prism Energy, Legacy Energy, etc.

    @classmethod
    def from_str(cls, s: str) -> "EnergyType":
        """Case-insensitive lookup with Colorless as default."""
        s = s.strip().capitalize()
        for member in cls:
            if member.value.lower() == s.lower():
                return member
        return cls.COLORLESS


# ──────────────────────────────────────────────────────────────────────────────
# Data classes
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class EnergyAttachment:
    energy_type: EnergyType
    source_card_id: str            # The energy card's unique instance ID
    card_def_id: str = ""          # The energy card's definition ID (for effect lookups)
    provides: list[EnergyType] = field(default_factory=list)  # What it actually provides
    discard_at_end_of_turn: bool = False  # For Ignition Energy


@dataclass
class CardInstance:
    """A specific instance of a card in a game.

    card_def_id references the CardDefinition (tcgdex_id).
    instance_id is unique per game so two copies of the same card are distinct.

    ADDITION (Q3 approved): energy_provides populated at deck-build time so
    the transition layer can read it without a registry lookup on every attach.
    """

    instance_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    card_def_id: str = ""       # e.g. "sv06-130"
    card_name: str = ""
    card_type: str = ""         # "Pokemon", "Trainer", "Energy"
    card_subtype: str = ""      # "Item", "Supporter", "Stadium", "Tool",
                                # "Basic", "Special"
    zone: Zone = Zone.DECK

    # Pokémon-specific ─────────────────────────────────────────────────────────
    current_hp: int = 0
    max_hp: int = 0
    energy_attached: list[EnergyAttachment] = field(default_factory=list)
    status_conditions: set[StatusCondition] = field(default_factory=set)
    tools_attached: list[str] = field(default_factory=list)  # card_def_ids of attached tools
    evolved_from: Optional[str] = None     # instance_id of the card this evolved from
    evolution_stage: int = 0              # 0=Basic, 1=Stage 1, 2=Stage 2
    turn_played: int = -1                  # Turn number this card entered play
    retreated_this_turn: bool = False
    ability_used_this_turn: bool = False
    damage_counters: int = 0              # Each counter = 10 damage dealt

    # Multi-turn restriction flags (reset at end of turn)
    cant_attack_next_turn: bool = False   # Set by attacks like Iron Leaves ex, Bloodmoon Ursaluna ex
    cant_retreat_next_turn: bool = False  # Set by attacks like Dusknoir Shadow Bind, Yveltal
    protected_from_ex: bool = False       # Set by Acerola's Mischief; cleared at start of your turn
    attack_damage_reduction: int = 0     # Set by Growl etc.; reduces this Pokémon's attack damage
    incoming_damage_reduction: int = 0   # Set by Gaia Wave etc.; reduces damage received
    prevent_damage_one_turn: bool = False # Set by Marill Hide / Hop's Phantump Splashing Dodge
    resolute_heart_eligible: bool = False # Set in _apply_damage; read by check_ko for Pikachu ex
    last_attack_name: Optional[str] = None       # For Spiky Rolling / Mochi Rush
    moved_from_bench_this_turn: bool = False      # For Rayquaza Breakthrough Assault
    evolved_this_turn: bool = False               # Set when this Pokémon evolved; for sv10-047 Misty's Starmie
    prevent_damage_from_basic_noncolorless: bool = False  # For Crown Opal (Terapagos ex)
    locked_attack_index: Optional[int] = None             # Can't use this specific attack index next turn
    prevent_damage_from_basic: bool = False               # Prevent all damage from Basic Pokémon next turn
    heavy_poison: bool = False                            # Tainted Horn (sv10-119): 8 counters/turn instead of 1
    double_poison: bool = False                           # Crobat SFA Poison Fang: 2 counters/turn instead of 1
    prevent_damage_threshold: int = 0                    # Harden (sv09-002): prevent damage ≤ threshold next turn
    no_weakness_one_turn: bool = False                    # Metal Defender (sv08-130): no Weakness during opp's next turn
    attack_requires_flip: bool = False                    # Sand Attack: must flip coin to attack next turn (tails = fail)
    energy_attach_punish_counters: int = 0                # Electrified Incisors (me01-051): 8 damage counters per energy opponent attaches next turn
    torment_blocked_attack_name: Optional[str] = None     # Pangoro Torment: this attack name is blocked next turn
    retaliation_on_damage: bool = False                   # Zamazenta Strong Bash: reflect incoming damage back to attacker
    attack_damage_bonus: int = 0                          # Feraligatr Torrential Heart: +120 damage this turn
    repulsor_axe_active: bool = False         # Iron Boulder ex Repulsor Axe: 8 counters on attacker if hit next turn
    ready_to_ram_active: bool = False         # Bouffalant Ready to Ram: 6 counters on attacker if hit next turn
    prevent_damage_from_ancient: bool = False  # Iron Moth Anachronism Repulsor: block Ancient Pokémon damage next turn
    custom_counters: dict = field(default_factory=dict)   # Per-card counter tracking (e.g., feather counters)

    # Energy-card-specific ─────────────────────────────────────────────────────
    # Populated from CardDefinition.energy_provides at deck-build time.
    # Basic energy: ["Fire"]; special energy: ["Darkness"] or ["Any"], etc.
    energy_provides: list[str] = field(default_factory=list)

    # Trainer/tool-specific ────────────────────────────────────────────────────
    is_tool_attached: bool = False         # True when this card is attached as a Tool


@dataclass
class PlayerState:
    player_id: str                         # "p1" or "p2"
    deck: list[CardInstance] = field(default_factory=list)
    hand: list[CardInstance] = field(default_factory=list)
    active: Optional[CardInstance] = None
    bench: list[CardInstance] = field(default_factory=list)    # Max 5
    discard: list[CardInstance] = field(default_factory=list)
    prizes: list[CardInstance] = field(default_factory=list)   # 6 prizes
    lost_zone: list[CardInstance] = field(default_factory=list)

    prizes_remaining: int = 6
    supporter_played_this_turn: bool = False
    energy_attached_this_turn: bool = False
    retreat_used_this_turn: bool = False
    gx_used: bool = False
    vstar_used: bool = False
    items_locked_this_turn: bool = False  # Set by Budew's "Stun Spore" attack
    tr_supporter_played_this_turn: bool = False  # For Team Rocket's Factory stadium
    ko_taken_last_turn: bool = False      # One of my Pokémon was KO'd during opponent's last turn (Retaliate)
    ethans_pokemon_ko_last_turn: bool = False  # One of my Ethan's Pokémon was KO'd during opponent's last turn
    tarragon_played_this_turn: bool = False  # Hippowdon Twister Spewing: Tarragon was played this turn
    janines_sa_used_this_turn: bool = False  # Crobat Shadowy Envoy / Malamar Colluding Tentacles
    future_supporter_played_this_turn: bool = False  # Iron Valiant Majestic Sword
    future_effect_immunity: bool = False  # Miraidon C.O.D.E.: Protect (last one turn)
    xerosics_machinations_played_this_turn: bool = False  # Malamar Colluding Tentacles
    daydream_active: bool = False  # Hypno Daydream: end opp turn if they attach to Active
    evolution_blocked_next_turn: bool = False        # Bronzong Evolution Jammer: opp can't evolve next turn
    supporters_locked_next_turn: bool = False        # Scream Tail ex Scream: opp can't play Supporters next turn
    ancient_supporter_played_this_turn: bool = False  # Great Tusk Land Collapse: played Ancient Supporter flag
    amarys_pending: bool = False                      # Amarys: discard hand at end of turn if 5+ cards
    festival_lead_pending: bool = False               # Festival Lead: second attack if Festival Grounds active
    face_up_prize_indices: list = field(default_factory=list)  # Bother-Bot: indices of face-up prizes


@dataclass
class GameState:
    game_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    turn_number: int = 0
    active_player: str = "p1"    # Whose turn it is
    phase: Phase = Phase.SETUP
    p1: PlayerState = field(default_factory=lambda: PlayerState(player_id="p1"))
    p2: PlayerState = field(default_factory=lambda: PlayerState(player_id="p2"))
    first_player: str = ""       # Determined during setup via coin flip
    winner: Optional[str] = None
    win_condition: Optional[str] = None  # "prizes", "deck_out", "no_bench"

    # Global effects
    active_stadium: Optional[CardInstance] = None

    # One-time game flags
    legacy_prize_reduction_used: bool = False  # Legacy Energy: only once per game

    # Per-turn damage / effect flags (reset in _end_turn)
    active_player_damage_bonus: int = 0        # Kieran +30, etc. — added to base_damage
    active_player_damage_bonus_vs_ex: int = 0  # Black Belt's Training +40 vs ex only
    briar_active: bool = False                 # Briar (sv07-132): +1 prize on active KO
    sunny_day_active: bool = False             # Lilligant (sv09-007): Grass/Fire attacks +20
    force_end_turn: bool = False               # Boxed Order (sv05-143): end turn after item search

    # Event log
    events: list[dict] = field(default_factory=list)
    pending_effects: list[dict] = field(default_factory=list)  # Deferred effects (Ribombee, Permeating Chill, Corrosive Sludge)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def get_player(self, player_id: str) -> PlayerState:
        return self.p1 if player_id == "p1" else self.p2

    def get_opponent(self, player_id: str) -> PlayerState:
        return self.p2 if player_id == "p1" else self.p1

    def opponent_id(self, player_id: str) -> str:
        return "p2" if player_id == "p1" else "p1"

    def emit_event(self, event_type: str, **kwargs) -> dict:
        event = {
            "event_type": event_type,
            "turn": self.turn_number,
            "active_player": self.active_player,
            "phase": self.phase.name,
            **kwargs,
        }
        self.events.append(event)
        return event
