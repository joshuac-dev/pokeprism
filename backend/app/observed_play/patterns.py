import re

# Setup
RE_SETUP_HEADER = re.compile(r'^Setup\s*$', re.IGNORECASE)
RE_COIN_FLIP_CHOICE = re.compile(r'^(?P<player>.+?) chose (?P<choice>heads|tails) for the opening coin flip', re.IGNORECASE)
RE_COIN_FLIP_RESULT = re.compile(r'^(?P<player>.+?) won the coin toss', re.IGNORECASE)
RE_TURN_ORDER_CHOICE = re.compile(r'^(?P<player>.+?) decided to go (?P<order>first|second)', re.IGNORECASE)
RE_OPENING_HAND_HIDDEN = re.compile(r'^(?P<player>.+?) drew (?P<n>\d+) cards? for the opening hand', re.IGNORECASE)
RE_MULLIGAN = re.compile(r'^(?P<player>.+?) took a mulligan', re.IGNORECASE)
RE_MULLIGAN_EXTRA_DRAW = re.compile(r'^(?P<player>.+?) drew (?P<n>\d+) more card.*because (?P<other>.+?) took at least', re.IGNORECASE)
RE_MULLIGAN_CARDS_LABEL = re.compile(r'^-\s*Cards revealed from Mulligan', re.IGNORECASE)
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
RE_DAMAGE_BREAKDOWN_LABEL = re.compile(r"^-\s*Damage breakdown:\s*$", re.IGNORECASE)
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

# Retreat / switch
RE_RETREAT = re.compile(r"^(?P<player>.+?)['\u2019]s (?P<card>.+?) retreated", re.IGNORECASE)
RE_SWITCH_ACTIVE = re.compile(r"^(?P<player>.+?) switched in (?P<card>.+?) to the Active Spot", re.IGNORECASE)
# Promotion / "now in Active Spot": "PLAYER's CARD is now in the Active Spot."
RE_NOW_ACTIVE = re.compile(r"^(?P<player>.+?)['\u2019]s (?P<card>.+?) is now in the Active Spot", re.IGNORECASE)

# End turn
RE_END_TURN = re.compile(r"^(?P<player>.+?) ended their turn", re.IGNORECASE)

# Shuffle
RE_SHUFFLE = re.compile(r"^(?P<player>.+?) shuffled their deck", re.IGNORECASE)

# Discard
RE_DISCARD = re.compile(r"^(?P<player>.+?) discarded (?P<card>.+?) from their", re.IGNORECASE)

# Bullet / sub-line
RE_BULLET_LINE = re.compile(r"^\s+•\s*(?P<content>.+)$")
RE_DASH_LINE = re.compile(r"^-\s*(?P<content>.+)$")

# Bench from deck (hidden aggregate dash-line):
# "- PLAYER drew N cards and played them to the Bench."
RE_BENCH_FROM_DECK_HIDDEN = re.compile(
    r"^-\s*(?P<player>.+?) drew (?P<n>\d+) cards? and played them to the Bench",
    re.IGNORECASE,
)

# Search / fetch
RE_SEARCH = re.compile(r"^(?P<player>.+?) searched their (?P<zone>deck|discard|hand) for (?P<card>.+?)\.", re.IGNORECASE)
RE_RECOVER = re.compile(r"^(?P<player>.+?) recovered (?P<card>.+?) from the discard", re.IGNORECASE)

# Play basic to bench (generic; RE_PLAY_TO_BENCH will also match)
RE_PLAY_BASIC = re.compile(r"^(?P<player>.+?) played (?P<card>.+?) to the Bench", re.IGNORECASE)
