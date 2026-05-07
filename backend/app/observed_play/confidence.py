"""Deterministic confidence scoring for parsed events."""

from __future__ import annotations


def event_confidence(event_type: str, fields_captured: list[str]) -> tuple[float, list[str]]:
    """Return (score, reasons) for a parsed event."""
    if event_type == "unknown":
        return 0.30, ["unrecognized line pattern"]

    if event_type in ("setup_start", "turn_start"):
        return 0.98, ["structural marker"]

    if event_type in ("coin_flip_choice", "coin_flip_result", "turn_order_choice"):
        return 0.97, ["exact pattern with player captured"]

    if event_type in ("mulligan", "mulligan_extra_draw", "end_turn"):
        return 0.95, ["exact pattern matched"]

    if event_type == "damage_breakdown":
        if "base_damage" in fields_captured and "damage" in fields_captured:
            return 0.92, ["numeric damage values captured"]
        return 0.85, ["damage block structure matched"]

    if event_type == "attack_used":
        if "damage" in fields_captured and "card_name_raw" in fields_captured:
            return 0.95, ["attack with player/card/damage captured"]
        if "card_name_raw" in fields_captured:
            return 0.88, ["no-damage attack with player/card captured"]
        return 0.80, ["attack pattern partial match"]

    if event_type in ("knockout", "game_end"):
        return 0.97, ["exact structural pattern"]

    if event_type == "pokemon_checkup":
        return 0.95, ["exact checkup phase marker"]

    if event_type in ("special_condition_applied", "special_condition_removed"):
        if "card_name_raw" in fields_captured:
            return 0.90, ["special condition with player/card captured"]
        return 0.85, ["special condition pattern matched"]

    if event_type == "special_condition_damage":
        if "card_name_raw" in fields_captured and "amount" in fields_captured:
            return 0.92, ["condition damage with card/amount captured"]
        return 0.85, ["condition damage pattern matched"]

    if event_type in ("damage_counters_placed", "damage_counters_moved"):
        if "target_card_name_raw" in fields_captured and "amount" in fields_captured:
            return 0.88, ["damage counter event with target/amount captured"]
        return 0.80, ["damage counter pattern matched"]

    if event_type == "pokemon_switched":
        if "card_name_raw" in fields_captured and "target_card_name_raw" in fields_captured:
            return 0.90, ["pokemon switched with both cards captured"]
        return 0.83, ["pokemon switched pattern matched"]

    if event_type == "cards_discarded":
        if "amount" in fields_captured:
            return 0.85, ["cards discarded with player/amount captured"]
        return 0.80, ["cards discarded pattern matched"]

    if event_type == "cards_discarded_from_pokemon":
        if "target_card_name_raw" in fields_captured and "amount" in fields_captured:
            return 0.88, ["discarded from pokemon with target/amount captured"]
        return 0.80, ["discarded from pokemon pattern matched"]

    if event_type == "cards_moved_to_hand":
        if "amount" in fields_captured:
            return 0.85, ["cards moved to hand with player/amount captured"]
        return 0.80, ["cards moved to hand pattern matched"]

    if event_type == "cards_shuffled_into_deck":
        if "amount" in fields_captured:
            return 0.85, ["cards shuffled with player/amount captured"]
        return 0.80, ["cards shuffled pattern matched"]

    if event_type in ("prize_taken",):
        return 0.97, ["exact prize count captured"]

    if event_type in ("opening_hand_draw_hidden", "draw_hidden"):
        return 0.82, ["hidden card identity"]

    if event_type in ("opening_hand_draw_known", "mulligan_cards_revealed"):
        if "card_list" in fields_captured:
            return 0.90, ["card list captured from bullet lines"]
        return 0.85, ["structured reveal block"]

    if event_type in ("draw",):
        return 0.95, ["known draw with card name"]

    if event_type == "ability_used":
        if "card_name_raw" in fields_captured:
            return 0.88, ["ability with player/card captured"]
        return 0.80, ["ability pattern partial match"]

    if event_type == "play_trainer":
        return 0.85, ["generic trainer play with card name"]

    if event_type == "attach_card":
        return 0.87, ["non-energy attachment with player/card/target captured"]

    if event_type == "play_to_bench_hidden":
        return 0.82, ["hidden aggregate bench play"]

    if event_type == "card_effect_activated":
        return 0.78, ["card activation with name captured"]

    if event_type == "discard_from_pokemon":
        if "card_name_raw" in fields_captured and "target_card_name_raw" in fields_captured:
            return 0.88, ["discard from pokemon with card/player/target captured"]
        return 0.80, ["discard from pokemon pattern matched"]

    if event_type == "card_added_to_hand":
        if "card_name_raw" in fields_captured:
            return 0.88, ["known card added to hand with player captured"]
        return 0.80, ["hidden card added to hand with player captured"]

    if len(fields_captured) >= 2:
        return 0.88, ["pattern matched with multiple fields"]
    if len(fields_captured) == 1:
        return 0.80, ["pattern matched with single field"]
    return 0.75, ["pattern matched"]


def log_confidence(event_confidences: list[float]) -> float:
    """Compute log-level confidence from event confidences."""
    if not event_confidences:
        return 0.0
    avg = sum(event_confidences) / len(event_confidences)
    unknown_count = sum(1 for c in event_confidences if c <= 0.31)
    unknown_ratio = unknown_count / len(event_confidences)
    penalty = min(0.25, unknown_ratio * 0.5)
    return max(0.0, min(1.0, avg - penalty))
