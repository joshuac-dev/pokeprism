"""Card mention extraction for Observed Play Memory Phase 3.

Extracts raw card names from parsed ObservedPlayEvent rows into structured
ObservedCardMention candidates for downstream resolution.

Does NOT resolve cards — that is card_resolution.py's job.
Does NOT extract attack_name or ability_name as card mentions.
"""

from __future__ import annotations

import re
from typing import Any

from app.observed_play.constants import (
    ET_ABILITY_USED,
    ET_ATTACH_CARD,
    ET_ATTACH_ENERGY,
    ET_CARD_ADDED_TO_HAND,
    ET_CARD_EFFECT_ACTIVATED,
    ET_DISCARD,
    ET_DISCARD_FROM_POKEMON,
    ET_EVOLVE,
    ET_KNOCKOUT,
    ET_PLAY_BASIC_TO_BENCH,
    ET_PLAY_ITEM,
    ET_PLAY_STADIUM,
    ET_PLAY_SUPPORTER,
    ET_PLAY_TO_BENCH,
    ET_PLAY_TO_BENCH_HIDDEN,
    ET_PLAY_TOOL,
    ET_PLAY_TRAINER,
    ET_PRIZE_CARD_ADDED,
    ET_PRIZE_TAKEN,
    ET_RETREAT,
    ET_ATTACK_USED,
)

_RE_WHITESPACE = re.compile(r"\s+")

# Raw names that are not meaningful card names (hidden placeholders, etc.)
_IGNORED_NORMALIZED = frozenset({
    "a card",
    "card",
    "",
    "unknown",
})


def normalize_card_name(raw: str) -> str:
    """Conservative normalization for card name matching.

    - Trim and collapse internal whitespace.
    - Normalize Unicode apostrophes (\u2018, \u2019) to straight apostrophe.
    - Lowercase.
    - Strip trailing sentence punctuation.
    """
    if not raw:
        return ""
    s = raw.replace("\u2019", "'").replace("\u2018", "'")
    s = _RE_WHITESPACE.sub(" ", s).strip()
    s = s.lower()
    s = s.rstrip(".,;:")
    return s


def _is_meaningful(raw: str) -> bool:
    if not raw:
        return False
    norm = normalize_card_name(raw)
    return norm not in _IGNORED_NORMALIZED and len(norm) >= 2


def _guess_attached_role(card_name: str | None) -> str:
    """Best-effort role for attach_card events based on name heuristics."""
    if not card_name:
        return "attached_card"
    lower = card_name.lower()
    tool_words = ("belt", "band", "vest", "collar", "rope", "cape", "goggles",
                  "scope", "charm", "brace", "helmet", "mirror", "lens", "pad")
    if any(w in lower for w in tool_words):
        return "tool_card"
    return "attached_card"


def extract_mentions_from_event(event: Any) -> list[dict[str, Any]]:
    """Return list of raw mention dicts for a single ObservedPlayEvent.

    Each dict has keys:
      mention_role, raw_name, source_field, source_payload_path

    Does NOT assign mention_index — the caller assigns sequential indices.
    Does NOT resolve cards.
    """
    mentions: list[dict[str, Any]] = []
    et = event.event_type
    payload: dict = event.event_payload_json or {}

    def _add(role: str, raw_name: str | None,
             source_field: str, source_payload_path: str | None = None) -> None:
        if raw_name and _is_meaningful(raw_name):
            mentions.append({
                "mention_role": role,
                "raw_name": raw_name,
                "source_field": source_field,
                "source_payload_path": source_payload_path,
            })

    card = event.card_name_raw
    target = event.target_card_name_raw

    if et == ET_ATTACK_USED:
        _add("actor_card", card, "card_name_raw")
        _add("target_card", target, "target_card_name_raw")
        # attack_name is NOT a card mention

    elif et == ET_ABILITY_USED:
        _add("actor_card", card, "card_name_raw")
        # ability_name is NOT a card mention

    elif et == ET_EVOLVE:
        _add("evolution_from", target, "target_card_name_raw")
        _add("evolution_to", card, "card_name_raw")

    elif et == ET_ATTACH_ENERGY:
        _add("energy_card", card, "card_name_raw")
        _add("target_card", target, "target_card_name_raw")

    elif et == ET_ATTACH_CARD:
        role = _guess_attached_role(card)
        _add(role, card, "card_name_raw")
        _add("target_card", target, "target_card_name_raw")

    elif et in (ET_PLAY_ITEM, ET_PLAY_SUPPORTER, ET_PLAY_STADIUM,
                ET_PLAY_TOOL, ET_PLAY_TRAINER):
        _add("trainer_card", card, "card_name_raw")

    elif et in (ET_DISCARD, ET_DISCARD_FROM_POKEMON):
        _add("discarded_card", card, "card_name_raw")
        if et == ET_DISCARD_FROM_POKEMON:
            _add("target_card", target, "target_card_name_raw")

    elif et in (ET_PRIZE_TAKEN,):
        _add("revealed_card", card, "card_name_raw")

    elif et == ET_PRIZE_CARD_ADDED:
        _add("added_to_hand_card", card, "card_name_raw")

    elif et == ET_CARD_ADDED_TO_HAND:
        _add("added_to_hand_card", card, "card_name_raw")

    elif et == ET_CARD_EFFECT_ACTIVATED:
        _add("effect_card", card, "card_name_raw")

    elif et == ET_RETREAT:
        _add("actor_card", card, "card_name_raw")

    elif et in (ET_PLAY_BASIC_TO_BENCH, ET_PLAY_TO_BENCH, ET_PLAY_TO_BENCH_HIDDEN):
        _add("actor_card", card, "card_name_raw")

    elif et == ET_KNOCKOUT:
        _add("actor_card", card, "card_name_raw")

    elif et in ("opening_hand_draw_known", ET_PLAY_TO_BENCH):
        _add("revealed_card", card, "card_name_raw")

    else:
        # Generic fallback: extract card fields if present
        _add("unknown_card", card, "card_name_raw")
        _add("unknown_card", target, "target_card_name_raw")

    # Opening hand / mulligan payload card lists
    if et in ("opening_hand_draw_known", "mulligan_cards_revealed"):
        for i, c in enumerate(payload.get("cards", [])):
            if isinstance(c, str) and _is_meaningful(c):
                mentions.append({
                    "mention_role": "revealed_card",
                    "raw_name": c,
                    "source_field": "event_payload_json",
                    "source_payload_path": f"cards[{i}]",
                })

    # Deduplicate by (role, normalized_name, source_field) while preserving order
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for m in mentions:
        key = (m["mention_role"], normalize_card_name(m["raw_name"]), m["source_field"])
        if key not in seen:
            seen.add(key)
            deduped.append(m)

    return deduped
