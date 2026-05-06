"""Observed Play parser constants and event type registry."""

PARSER_VERSION = "1.0"

# Event phases
PHASE_SETUP = "setup"
PHASE_TURN = "turn"
PHASE_COMBAT = "combat"
PHASE_GAME_END = "game_end"

# Event types (setup)
ET_SETUP_START = "setup_start"
ET_COIN_FLIP_CHOICE = "coin_flip_choice"
ET_COIN_FLIP_RESULT = "coin_flip_result"
ET_TURN_ORDER_CHOICE = "turn_order_choice"
ET_OPENING_HAND_DRAW_HIDDEN = "opening_hand_draw_hidden"
ET_OPENING_HAND_DRAW_KNOWN = "opening_hand_draw_known"
ET_MULLIGAN = "mulligan"
ET_MULLIGAN_CARDS_REVEALED = "mulligan_cards_revealed"
ET_MULLIGAN_EXTRA_DRAW = "mulligan_extra_draw"
ET_PLAY_TO_ACTIVE = "play_to_active"
ET_PLAY_TO_BENCH = "play_to_bench"

# Event types (turn)
ET_TURN_START = "turn_start"
ET_DRAW = "draw"
ET_DRAW_HIDDEN = "draw_hidden"
ET_ATTACH_ENERGY = "attach_energy"
ET_ATTACH_CARD = "attach_card"
ET_PLAY_ITEM = "play_item"
ET_PLAY_SUPPORTER = "play_supporter"
ET_PLAY_STADIUM = "play_stadium"
ET_REPLACE_STADIUM = "replace_stadium"
ET_PLAY_TOOL = "play_tool"
ET_PLAY_TRAINER = "play_trainer"
ET_PLAY_BASIC_TO_BENCH = "play_basic_to_bench"
ET_PLAY_TO_BENCH_HIDDEN = "play_to_bench_hidden"
ET_EVOLVE = "evolve"
ET_ABILITY_USED = "ability_used"
ET_RETREAT = "retreat"
ET_SWITCH_ACTIVE = "switch_active"
ET_DISCARD = "discard"
ET_SHUFFLE_DECK = "shuffle_deck"
ET_SEARCH_OR_FETCH = "search_or_fetch"
ET_RECOVER_FROM_DISCARD = "recover_from_discard"
ET_END_TURN = "end_turn"

# Event types (combat/game end)
ET_ATTACK_USED = "attack_used"
ET_DAMAGE_BREAKDOWN = "damage_breakdown"
ET_KNOCKOUT = "knockout"
ET_PRIZE_TAKEN = "prize_taken"
ET_PRIZE_CARD_ADDED = "prize_card_added_to_hand"
ET_GAME_END = "game_end"

# Fallback
ET_UNKNOWN = "unknown"
