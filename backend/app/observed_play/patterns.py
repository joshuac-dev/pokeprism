import re

# Setup
RE_SETUP_HEADER = re.compile(r'^Setup\s*$', re.IGNORECASE)
RE_COIN_FLIP_CHOICE = re.compile(r'^(?P<player>.+?) chose (?P<choice>heads|tails) for the opening coin flip', re.IGNORECASE)
RE_COIN_FLIP_RESULT = re.compile(r'^(?P<player>.+?) won the coin toss', re.IGNORECASE)
RE_TURN_ORDER_CHOICE = re.compile(r'^(?P<player>.+?) decided to go (?P<order>first|second)', re.IGNORECASE)
RE_OPENING_HAND_HIDDEN = re.compile(r'^(?P<player>.+?) drew (?P<n>\d+) cards? for the opening hand', re.IGNORECASE)
RE_MULLIGAN = re.compile(r'^(?P<player>.+?) took a mulligan', re.IGNORECASE)
# Plural: "PLAYER took N mulligans." (two or more mulligans)
RE_MULLIGAN_PLURAL = re.compile(r'^(?P<player>.+?) took (?P<n>\d+) mulligans?\.', re.IGNORECASE)
RE_MULLIGAN_EXTRA_DRAW = re.compile(r'^(?P<player>.+?) drew (?P<n>\d+) more card.*because (?P<other>.+?) took at least', re.IGNORECASE)
RE_MULLIGAN_CARDS_LABEL = re.compile(r'^Cards revealed from Mulligan', re.IGNORECASE)
RE_PLAY_TO_ACTIVE = re.compile(r'^(?P<player>.+?) played (?P<card>.+?) to the Active Spot', re.IGNORECASE)
RE_PLAY_TO_BENCH = re.compile(r"^(?P<player>.+?) played (?P<card>.+?) to the Bench", re.IGNORECASE)

# Turn headers
RE_TURN_START = re.compile(r"^(?P<player>.+?)['\u2019]s Turn(?:\s+\d+)?\s*$")

# Draws — checked in this order: N hidden, single hidden, then known card
RE_DRAW_HIDDEN = re.compile(r"^(?P<player>.+?) drew a card\.$", re.IGNORECASE)
RE_DRAW_N_HIDDEN = re.compile(r"^(?P<player>.+?) drew (?P<n>\d+) cards?\.$", re.IGNORECASE)
RE_DRAW_KNOWN = re.compile(r"^(?P<player>.+?) drew (?P<card>.+?)\.$")

# Play trainer — specific types checked first; generic fallback last
RE_PLAY_ITEM = re.compile(r"^(?P<player>.+?) played (?P<card>.+?) \(Item\)", re.IGNORECASE)
RE_PLAY_SUPPORTER = re.compile(r"^(?P<player>.+?) played (?P<card>.+?) \(Supporter\)", re.IGNORECASE)
RE_PLAY_STADIUM = re.compile(r"^(?P<player>.+?) played (?P<card>.+?) to the Stadium spot", re.IGNORECASE)
RE_PLAY_TOOL = re.compile(r"^(?P<player>.+?) attached (?P<card>.+?) as a Tool to (?P<target>.+?)\.", re.IGNORECASE)
# Generic trainer play (no subtype tag, no zone): "PLAYER played CARD." — must be last "played" handler
RE_PLAY_TRAINER_GENERIC = re.compile(r"^(?P<player>.+?) played (?P<card>.+?)\.$", re.IGNORECASE)

# Evolution — two PTCGL log formats:
# 1. Possessive:  "PLAYER's FROM evolved into TO."
# 2. Direct:      "PLAYER evolved FROM to TO [in the Active Spot|on the Bench]."
RE_EVOLVE = re.compile(r"^(?P<player>.+?)['\u2019]s (?P<from_card>.+?) evolved into (?P<to_card>.+?)\.", re.IGNORECASE)
RE_EVOLVE_DIRECT = re.compile(r"^(?P<player>.+?) evolved (?P<from_card>.+?) to (?P<rest>.+?)\.$", re.IGNORECASE)

# Energy / card attachment
RE_ATTACH_ENERGY = re.compile(r"^(?P<player>.+?) attached (?P<energy>.+?) Energy to (?P<target>.+?)\.", re.IGNORECASE)
# General attachment — classifies as attach_energy if card contains "Energy", else attach_card
RE_ATTACH_GENERAL = re.compile(r"^(?P<player>.+?) attached (?P<card>.+?) to (?P<target_with_zone>.+?)\.$", re.IGNORECASE)

# Ability patterns — checked before no-damage attack
# Primary: "PLAYER's CARD used ABILITY." — no target (ability activation)
RE_ABILITY_USED_NEW = re.compile(r"^(?P<player>.+?)['\u2019]s (?P<card>.+?) used (?P<ability>.+?)\.$", re.IGNORECASE)
# Legacy: "PLAYER used CARD's ABILITY ability"
RE_ABILITY_USED = re.compile(r"^(?P<player>.+?) used (?P<card>.+?)['\u2019]s (?P<ability>.+?) ability", re.IGNORECASE)

# Attacks
RE_ATTACK = re.compile(
    r"^(?P<player>.+?)['\u2019]s (?P<card>.+?) used (?P<attack>.+?) on (?P<target_player>.+?)['\u2019]s (?P<target_card>.+?) for (?P<damage>\d+) damage\.",
    re.IGNORECASE,
)
# No-damage attack: has target but no "for N damage" suffix
RE_ATTACK_NO_DAMAGE = re.compile(
    r"^(?P<player>.+?)['\u2019]s (?P<card>.+?) used (?P<attack>.+?) on (?P<target_player>.+?)['\u2019]s (?P<target_card>.+?)\.$",
    re.IGNORECASE,
)
RE_DAMAGE_BREAKDOWN_LABEL = re.compile(r"^Damage breakdown:\s*$", re.IGNORECASE)
RE_DAMAGE_LINE = re.compile(r"•\s*(?:Base damage|Total damage|.*?):\s*(?P<n>\d+) damage", re.IGNORECASE)
RE_BASE_DAMAGE = re.compile(r"•\s*Base damage:\s*(?P<n>\d+) damage", re.IGNORECASE)
RE_TOTAL_DAMAGE = re.compile(r"•\s*Total damage:\s*(?P<n>\d+) damage", re.IGNORECASE)

# Knockout
RE_KNOCKOUT = re.compile(r"^(?P<player>.+?)['\u2019]s (?P<card>.+?) was Knocked Out!", re.IGNORECASE)

# Prize — singular must be checked before numeric pattern
RE_PRIZE_TAKEN_SINGULAR = re.compile(r"^(?P<player>.+?) took a Prize card\b", re.IGNORECASE)
RE_PRIZE_TAKEN = re.compile(r"^(?P<player>.+?) took (?P<n>\d+) Prize cards?", re.IGNORECASE)
RE_PRIZE_CARD_ADDED = re.compile(r"^A card was added to (?P<player>.+?)['\u2019]s hand", re.IGNORECASE)

# Game end
RE_GAME_END_PRIZES = re.compile(r"All Prize cards taken\.\s*(?P<winner>.+?) wins", re.IGNORECASE)
RE_GAME_END_DECK = re.compile(r"(?P<winner>.+?) wins because (?P<loser>.+?) has no cards", re.IGNORECASE)
RE_GAME_END_KO = re.compile(r"(?P<winner>.+?) wins!", re.IGNORECASE)
# Alternative game-end phrasings seen in the PTCGL corpus
RE_GAME_END_PRIZES_OPPONENT = re.compile(
    r"^Opponent took all of their Prize cards\.\s*(?P<winner>.+?) wins\.",
    re.IGNORECASE,
)
RE_GAME_END_DECK_YOURS = re.compile(
    r"^Your deck ran out of cards\.\s*(?P<winner>.+?) wins\.",
    re.IGNORECASE,
)
RE_GAME_END_KO_NO_BENCH = re.compile(
    r"^Knocked Out with no Benched Pok[e\u00e9]mon\.\s*(?P<winner>.+?) wins\.",
    re.IGNORECASE,
)
RE_GAME_END_NO_BENCH_BACKUP = re.compile(
    r"^No Benched Pok[e\u00e9]mon for backup\.\s*(?P<winner>.+?) wins\.",
    re.IGNORECASE,
)

# Retreat / switch
RE_RETREAT = re.compile(r"^(?P<player>.+?)['\u2019]s (?P<card>.+?) retreated", re.IGNORECASE)
# Direct retreat: "PLAYER retreated CARD to the Bench."
RE_RETREAT_DIRECT = re.compile(
    r"^(?P<player>.+?) retreated (?P<card>.+?) to the Bench\.$",
    re.IGNORECASE,
)
RE_SWITCH_ACTIVE = re.compile(r"^(?P<player>.+?) switched in (?P<card>.+?) to the Active Spot", re.IGNORECASE)
# Promotion / "now in Active Spot": "PLAYER's CARD is now in the Active Spot."
RE_NOW_ACTIVE = re.compile(r"^(?P<player>.+?)['\u2019]s (?P<card>.+?) is now in the Active Spot", re.IGNORECASE)

# End turn
RE_END_TURN = re.compile(r"^(?P<player>.+?) ended their turn", re.IGNORECASE)

# Shuffle
RE_SHUFFLE = re.compile(r"^(?P<player>.+?) shuffled their deck", re.IGNORECASE)

# Discard
RE_DISCARD = re.compile(r"^(?P<player>.+?) discarded (?P<card>.+?) from their", re.IGNORECASE)
# Passive discard from a Pokémon: "CARD was discarded from PLAYER's TARGET."
RE_DISCARD_FROM_POKEMON = re.compile(
    r"^(?P<card>.+?) was discarded from (?P<player>.+?)['\u2019]s (?P<target>.+?)\.$",
    re.IGNORECASE,
)

# Bullet / sub-line
RE_BULLET_LINE = re.compile(r"^\s+•\s*(?P<content>.+)$")
RE_DASH_LINE = re.compile(r"^-\s*(?P<content>.+)$")

# Bench from deck (hidden aggregate dash-line):
# "- PLAYER drew N cards and played them to the Bench."
RE_BENCH_FROM_DECK_HIDDEN = re.compile(
    r"^(?P<player>.+?) drew (?P<n>\d+) cards? and played them to the Bench",
    re.IGNORECASE,
)

# Search / fetch
RE_SEARCH = re.compile(r"^(?P<player>.+?) searched their (?P<zone>deck|discard|hand) for (?P<card>.+?)\.", re.IGNORECASE)
RE_RECOVER = re.compile(r"^(?P<player>.+?) recovered (?P<card>.+?) from the discard", re.IGNORECASE)

# Play basic to bench (generic; RE_PLAY_TO_BENCH will also match)
RE_PLAY_BASIC = re.compile(r"^(?P<player>.+?) played (?P<card>.+?) to the Bench", re.IGNORECASE)

# Phase 2.4 — Special conditions, damage counters, checkup, concession

# Pokémon Checkup phase marker
RE_POKEMON_CHECKUP = re.compile(r"^Pok[e\u00e9]mon Checkup\s*$", re.IGNORECASE)

# Coin flip during Pokémon Checkup (Burned): "PLAYER flipped a coin and it landed on heads/tails."
RE_CHECKUP_COIN_FLIP = re.compile(
    r"^(?P<player>.+?) flipped a coin and it landed on (?P<result>heads|tails)\.",
    re.IGNORECASE,
)

# Special condition damage from checkup:
# "N damage counter(s) were/was placed on PLAYER's CARD for the Special Condition COND."
RE_SPECIAL_CONDITION_DAMAGE = re.compile(
    r"^(?P<n>\d+) damage counters? (?:was|were) placed on (?P<player>.+?)[\u2019']s (?P<card>.+?) for the Special Condition (?P<condition>Burned|Poisoned|Paralyzed|Confused|Asleep)\.",
    re.IGNORECASE,
)

# Special condition applied: "PLAYER's CARD is now COND."
RE_SPECIAL_CONDITION_APPLIED = re.compile(
    r"^(?P<player>.+?)[\u2019']s (?P<card>.+?) is now (?P<condition>Burned|Poisoned|Paralyzed|Confused|Asleep)\.",
    re.IGNORECASE,
)

# Special condition removed: "PLAYER's CARD is no longer COND."
RE_SPECIAL_CONDITION_REMOVED = re.compile(
    r"^(?P<player>.+?)[\u2019']s (?P<card>.+?) is no longer (?P<condition>Burned|Poisoned|Paralyzed|Confused|Asleep)\.",
    re.IGNORECASE,
)

# Damage counters placed by effect: "ACTOR put N damage counter(s) on PLAYER's CARD."
RE_DAMAGE_COUNTERS_PLACED = re.compile(
    r"^(?P<actor>.+?) put (?P<n>\d+) damage counters? on (?P<target_player>.+?)[\u2019']s (?P<target_card>.+?)\.",
    re.IGNORECASE,
)

# Damage counters moved by ability: "ACTOR moved N damage counter(s) from PLAYER's CARD to PLAYER2's CARD2."
RE_DAMAGE_COUNTERS_MOVED = re.compile(
    r"^(?P<actor>.+?) moved (?P<n>\d+) damage counters? from (?P<source_player>.+?)[\u2019']s (?P<source_card>.+?) to (?P<target_player>.+?)[\u2019']s (?P<target_card>.+?)\.",
    re.IGNORECASE,
)

# Pokémon switched: "PLAYER's CARD was switched with PLAYER2's CARD2 to become the Active Pokémon."
RE_POKEMON_SWITCHED = re.compile(
    r"^(?P<player>.+?)[\u2019']s (?P<card>.+?) was switched with (?P<target_player>.+?)[\u2019']s (?P<target_card>.+?) to become the Active Pok[e\u00e9]mon\.",
    re.IGNORECASE,
)

# Cards discarded (cost/effect): "PLAYER discarded N cards."
RE_CARDS_DISCARDED = re.compile(
    r"^(?P<player>.+?) discarded (?P<n>\d+) cards?\.",
    re.IGNORECASE,
)

# Cards discarded from Pokémon: "N card(s) were/was discarded from PLAYER's TARGET."
RE_CARDS_DISCARDED_FROM_POKEMON = re.compile(
    r"^(?P<n>\d+) cards? (?:was|were) discarded from (?P<player>.+?)[\u2019']s (?P<target>.+?)\.",
    re.IGNORECASE,
)

# Cards moved to hand: "PLAYER moved OWNER's N cards to their hand."
RE_CARDS_MOVED_TO_HAND = re.compile(
    r"^(?P<player>.+?) moved (?P<owner>.+?)[\u2019']s (?P<n>\d+) cards? to their hand\.",
    re.IGNORECASE,
)

# Cards shuffled into deck: "PLAYER shuffled N cards into their deck."
RE_CARDS_SHUFFLED_INTO_DECK = re.compile(
    r"^(?P<player>.+?) shuffled (?P<n>\d+) cards? into their deck\.",
    re.IGNORECASE,
)

# Opponent conceded: "Opponent conceded. WINNER wins."
RE_GAME_END_CONCEDED = re.compile(
    r"^Opponent conceded\.\s*(?P<winner>.+?) wins\.",
    re.IGNORECASE,
)

# Phase 2.3 patterns
# Card/effect activation: "CARD was activated."
RE_CARD_EFFECT_ACTIVATED = re.compile(
    r"^(?P<card>.+?) was activated\.$",
    re.IGNORECASE,
)
# Named card added to hand: "CARD was added to PLAYER's hand."
# (keep after RE_PRIZE_CARD_ADDED which handles "A card was added to PLAYER's hand.")
RE_CARD_ADDED_TO_HAND_KNOWN = re.compile(
    r"^(?P<card>.+?) was added to (?P<player>.+?)['\u2019]s hand\.$",
    re.IGNORECASE,
)

# Game system events (informational, not ingested into memory)
# "PLAYER didn't take an action in time."
RE_PLAYER_TIMEOUT = re.compile(
    r"^(?P<player>.+?) didn['\u2019]t take an action in time\.",
    re.IGNORECASE,
)
# "PLAYER lost connection and reconnected to the server."
RE_PLAYER_RECONNECTED = re.compile(
    r"^(?P<player>.+?) lost connection and reconnected to the server\.",
    re.IGNORECASE,
)
