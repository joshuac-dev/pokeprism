"""Phase 2 PTCGL battle log parser v1.

Parses raw text into ParsedObservedEvent dataclasses.
No card DB resolution, no memory ingestion.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .constants import (
    PARSER_VERSION,
    PHASE_SETUP, PHASE_TURN, PHASE_COMBAT, PHASE_GAME_END,
    ET_SETUP_START, ET_COIN_FLIP_CHOICE, ET_COIN_FLIP_RESULT,
    ET_TURN_ORDER_CHOICE, ET_OPENING_HAND_DRAW_HIDDEN, ET_OPENING_HAND_DRAW_KNOWN,
    ET_MULLIGAN, ET_MULLIGAN_CARDS_REVEALED, ET_MULLIGAN_EXTRA_DRAW,
    ET_PLAY_TO_ACTIVE, ET_PLAY_TO_BENCH,
    ET_TURN_START, ET_DRAW, ET_DRAW_HIDDEN,
    ET_ATTACH_ENERGY, ET_PLAY_ITEM, ET_PLAY_SUPPORTER, ET_PLAY_STADIUM,
    ET_REPLACE_STADIUM, ET_PLAY_TOOL, ET_PLAY_BASIC_TO_BENCH,
    ET_EVOLVE, ET_ABILITY_USED, ET_RETREAT, ET_SWITCH_ACTIVE,
    ET_DISCARD, ET_SHUFFLE_DECK, ET_SEARCH_OR_FETCH, ET_RECOVER_FROM_DISCARD,
    ET_END_TURN,
    ET_ATTACK_USED, ET_DAMAGE_BREAKDOWN, ET_KNOCKOUT, ET_PRIZE_TAKEN,
    ET_PRIZE_CARD_ADDED, ET_GAME_END,
    ET_UNKNOWN,
)
from .patterns import (
    RE_SETUP_HEADER, RE_COIN_FLIP_CHOICE, RE_COIN_FLIP_RESULT,
    RE_TURN_ORDER_CHOICE, RE_OPENING_HAND_HIDDEN,
    RE_MULLIGAN, RE_MULLIGAN_EXTRA_DRAW, RE_MULLIGAN_CARDS_LABEL,
    RE_PLAY_TO_ACTIVE, RE_PLAY_TO_BENCH,
    RE_TURN_START,
    RE_DRAW_KNOWN, RE_DRAW_HIDDEN, RE_DRAW_N_HIDDEN,
    RE_PLAY_ITEM, RE_PLAY_SUPPORTER, RE_PLAY_STADIUM, RE_PLAY_TOOL,
    RE_EVOLVE,
    RE_ATTACH_ENERGY, RE_ATTACH_ENERGY2,
    RE_ABILITY_USED,
    RE_RETREAT, RE_SWITCH_ACTIVE,
    RE_END_TURN, RE_SHUFFLE, RE_DISCARD,
    RE_ATTACK, RE_DAMAGE_BREAKDOWN_LABEL,
    RE_BASE_DAMAGE, RE_TOTAL_DAMAGE,
    RE_KNOCKOUT, RE_PRIZE_TAKEN, RE_PRIZE_CARD_ADDED,
    RE_GAME_END_PRIZES, RE_GAME_END_DECK, RE_GAME_END_KO,
    RE_BULLET_LINE, RE_DASH_LINE,
    RE_SEARCH, RE_RECOVER,
)
from .confidence import event_confidence, log_confidence


@dataclass
class ParsedObservedEvent:
    event_index: int
    turn_number: Optional[int]
    phase: str
    player_raw: Optional[str]
    player_alias: Optional[str]
    actor_type: Optional[str]
    event_type: str
    raw_line: str
    raw_block: Optional[str]
    card_name_raw: Optional[str]
    target_card_name_raw: Optional[str]
    zone: Optional[str]
    target_zone: Optional[str]
    amount: Optional[int]
    damage: Optional[int]
    base_damage: Optional[int]
    weakness_damage: Optional[int]
    resistance_delta: Optional[int]
    healing_amount: Optional[int]
    energy_type: Optional[str]
    prize_count_delta: Optional[int]
    deck_count_delta: Optional[int]
    hand_count_delta: Optional[int]
    discard_count_delta: Optional[int]
    event_payload: dict = field(default_factory=dict)
    confidence_score: float = 0.0
    confidence_reasons: list[str] = field(default_factory=list)


@dataclass
class ParsedObservedLog:
    parser_version: str
    events: list[ParsedObservedEvent]
    player_1_name_raw: Optional[str]
    player_2_name_raw: Optional[str]
    player_1_alias: Optional[str]
    player_2_alias: Optional[str]
    winner_raw: Optional[str]
    winner_alias: Optional[str]
    win_condition: Optional[str]
    turn_count: int
    event_count: int
    confidence_score: float
    warnings: list[dict]
    errors: list[dict]
    metadata: dict


def _make_event(
    event_index: int,
    turn_number: Optional[int],
    phase: str,
    event_type: str,
    raw_line: str,
    *,
    player_raw: Optional[str] = None,
    player_alias: Optional[str] = None,
    actor_type: Optional[str] = None,
    raw_block: Optional[str] = None,
    card_name_raw: Optional[str] = None,
    target_card_name_raw: Optional[str] = None,
    zone: Optional[str] = None,
    target_zone: Optional[str] = None,
    amount: Optional[int] = None,
    damage: Optional[int] = None,
    base_damage: Optional[int] = None,
    weakness_damage: Optional[int] = None,
    resistance_delta: Optional[int] = None,
    healing_amount: Optional[int] = None,
    energy_type: Optional[str] = None,
    prize_count_delta: Optional[int] = None,
    deck_count_delta: Optional[int] = None,
    hand_count_delta: Optional[int] = None,
    discard_count_delta: Optional[int] = None,
    event_payload: Optional[dict] = None,
    confidence_score: float = 0.0,
    confidence_reasons: Optional[list[str]] = None,
) -> ParsedObservedEvent:
    return ParsedObservedEvent(
        event_index=event_index,
        turn_number=turn_number,
        phase=phase,
        player_raw=player_raw,
        player_alias=player_alias,
        actor_type=actor_type,
        event_type=event_type,
        raw_line=raw_line,
        raw_block=raw_block,
        card_name_raw=card_name_raw,
        target_card_name_raw=target_card_name_raw,
        zone=zone,
        target_zone=target_zone,
        amount=amount,
        damage=damage,
        base_damage=base_damage,
        weakness_damage=weakness_damage,
        resistance_delta=resistance_delta,
        healing_amount=healing_amount,
        energy_type=energy_type,
        prize_count_delta=prize_count_delta,
        deck_count_delta=deck_count_delta,
        hand_count_delta=hand_count_delta,
        discard_count_delta=discard_count_delta,
        event_payload=event_payload or {},
        confidence_score=confidence_score,
        confidence_reasons=confidence_reasons or [],
    )


def parse_log(raw_content: str) -> ParsedObservedLog:
    """Parse a raw PTCGL log string into a ParsedObservedLog.

    Never throws — always returns a ParsedObservedLog even on malformed input.
    """
    try:
        return _parse_log_inner(raw_content)
    except Exception as exc:
        return ParsedObservedLog(
            parser_version=PARSER_VERSION,
            events=[],
            player_1_name_raw=None,
            player_2_name_raw=None,
            player_1_alias=None,
            player_2_alias=None,
            winner_raw=None,
            winner_alias=None,
            win_condition=None,
            turn_count=0,
            event_count=0,
            confidence_score=0.0,
            warnings=[],
            errors=[{"error": str(exc), "type": "parse_exception"}],
            metadata={"parser_version": PARSER_VERSION, "raw_line_count": 0},
        )


def _parse_log_inner(raw_content: str) -> ParsedObservedLog:
    """Internal parser implementation."""
    lines = raw_content.splitlines()
    events: list[ParsedObservedEvent] = []
    warnings: list[dict] = []
    errors: list[dict] = []

    player_names: list[str] = []

    def get_alias(name: str) -> tuple[str, str]:
        if not name:
            return "unknown", "unknown"
        if name not in player_names:
            player_names.append(name)
        idx = player_names.index(name)
        alias = f"player_{idx + 1}" if idx < 2 else "unknown"
        return alias, alias

    current_phase = PHASE_SETUP
    current_turn: Optional[int] = None
    event_idx = 0
    winner_raw: Optional[str] = None
    winner_alias: Optional[str] = None
    win_condition: Optional[str] = None
    turn_count = 0

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # ── Game end (check before others) ────────────────────────────────────
        m = RE_GAME_END_PRIZES.search(stripped)
        if m:
            winner_raw = m.group("winner").strip()
            win_condition = "prizes"
            alias, actor = get_alias(winner_raw)
            winner_alias = alias
            score, reasons = event_confidence(ET_GAME_END, ["winner_raw"])
            current_phase = PHASE_GAME_END
            events.append(_make_event(
                event_idx, current_turn, PHASE_GAME_END, ET_GAME_END, stripped,
                player_raw=winner_raw, player_alias=alias, actor_type=actor,
                event_payload={"winner": winner_raw, "win_condition": "prizes"},
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        m = RE_GAME_END_DECK.search(stripped)
        if m:
            winner_raw = m.group("winner").strip()
            win_condition = "deck_out"
            alias, actor = get_alias(winner_raw)
            winner_alias = alias
            score, reasons = event_confidence(ET_GAME_END, ["winner_raw"])
            current_phase = PHASE_GAME_END
            events.append(_make_event(
                event_idx, current_turn, PHASE_GAME_END, ET_GAME_END, stripped,
                player_raw=winner_raw, player_alias=alias, actor_type=actor,
                event_payload={"winner": winner_raw, "win_condition": "deck_out"},
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Setup header ──────────────────────────────────────────────────────
        if RE_SETUP_HEADER.match(stripped):
            score, reasons = event_confidence(ET_SETUP_START, [])
            events.append(_make_event(
                event_idx, None, PHASE_SETUP, ET_SETUP_START, stripped,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Coin flip choice ──────────────────────────────────────────────────
        m = RE_COIN_FLIP_CHOICE.match(stripped)
        if m:
            player = m.group("player").strip()
            choice = m.group("choice")
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_COIN_FLIP_CHOICE, ["player_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_COIN_FLIP_CHOICE, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                event_payload={"choice": choice},
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Coin flip result ──────────────────────────────────────────────────
        m = RE_COIN_FLIP_RESULT.match(stripped)
        if m:
            player = m.group("player").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_COIN_FLIP_RESULT, ["player_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_COIN_FLIP_RESULT, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Turn order choice ─────────────────────────────────────────────────
        m = RE_TURN_ORDER_CHOICE.match(stripped)
        if m:
            player = m.group("player").strip()
            order = m.group("order")
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_TURN_ORDER_CHOICE, ["player_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_TURN_ORDER_CHOICE, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                event_payload={"order": order},
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Mulligan extra draw ───────────────────────────────────────────────
        m = RE_MULLIGAN_EXTRA_DRAW.match(stripped)
        if m:
            player = m.group("player").strip()
            n = int(m.group("n"))
            other = m.group("other").strip()
            alias, actor = get_alias(player)
            block_lines = [stripped]
            j = i + 1
            while j < len(lines):
                sub = lines[j].strip()
                if not sub:
                    break
                if RE_DASH_LINE.match(sub) or RE_BULLET_LINE.match(lines[j]):
                    block_lines.append(sub)
                    j += 1
                else:
                    break
            raw_block = "\n".join(block_lines) if len(block_lines) > 1 else None
            i = j
            score, reasons = event_confidence(ET_MULLIGAN_EXTRA_DRAW, ["player_raw", "amount"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_MULLIGAN_EXTRA_DRAW, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                amount=n, raw_block=raw_block,
                event_payload={"other_player": other, "n": n},
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            continue

        # ── Mulligan cards label ──────────────────────────────────────────────
        if RE_MULLIGAN_CARDS_LABEL.match(stripped):
            block_lines = [stripped]
            cards: list[str] = []
            j = i + 1
            while j < len(lines):
                bm = RE_BULLET_LINE.match(lines[j])
                if bm:
                    content = bm.group("content").strip()
                    block_lines.append(lines[j].strip())
                    for c in content.split(","):
                        c = c.strip()
                        if c:
                            cards.append(c)
                    j += 1
                else:
                    break
            raw_block = "\n".join(block_lines)
            i = j
            fields = ["card_list"] if cards else []
            score, reasons = event_confidence(ET_MULLIGAN_CARDS_REVEALED, fields)
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_MULLIGAN_CARDS_REVEALED, stripped,
                raw_block=raw_block,
                event_payload={"cards": cards},
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            continue

        # ── Mulligan ──────────────────────────────────────────────────────────
        m = RE_MULLIGAN.match(stripped)
        if m:
            player = m.group("player").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_MULLIGAN, ["player_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_MULLIGAN, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Opening hand draw ─────────────────────────────────────────────────
        m = RE_OPENING_HAND_HIDDEN.match(stripped)
        if m:
            player = m.group("player").strip()
            n = int(m.group("n"))
            alias, actor = get_alias(player)
            block_lines = [stripped]
            cards_list: list[str] = []
            j = i + 1
            known = False
            while j < len(lines):
                sub_stripped = lines[j].strip()
                if not sub_stripped:
                    break
                if RE_DASH_LINE.match(sub_stripped):
                    block_lines.append(sub_stripped)
                    j += 1
                elif RE_BULLET_LINE.match(lines[j]):
                    bm = RE_BULLET_LINE.match(lines[j])
                    content = bm.group("content").strip()
                    block_lines.append(lines[j].strip())
                    for c in content.split(","):
                        c = c.strip()
                        if c:
                            cards_list.append(c)
                    known = True
                    j += 1
                else:
                    break
            raw_block = "\n".join(block_lines) if len(block_lines) > 1 else None
            i = j
            if known:
                et = ET_OPENING_HAND_DRAW_KNOWN
                fields = ["card_list", "player_raw", "amount"]
            else:
                et = ET_OPENING_HAND_DRAW_HIDDEN
                fields = ["player_raw", "amount"]
            score, reasons = event_confidence(et, fields)
            events.append(_make_event(
                event_idx, current_turn, current_phase, et, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                amount=n, raw_block=raw_block,
                event_payload={"cards": cards_list} if cards_list else {},
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            continue

        # ── Play to active (setup) ────────────────────────────────────────────
        m = RE_PLAY_TO_ACTIVE.match(stripped)
        if m:
            player = m.group("player").strip()
            card = m.group("card").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_PLAY_TO_ACTIVE, ["player_raw", "card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_PLAY_TO_ACTIVE, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=card,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Turn start ────────────────────────────────────────────────────────
        m = RE_TURN_START.match(stripped)
        if m:
            current_phase = PHASE_TURN
            current_turn = (current_turn or 0) + 1
            turn_count += 1
            player = m.group("player").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_TURN_START, ["player_raw"])
            events.append(_make_event(
                event_idx, current_turn, PHASE_TURN, ET_TURN_START, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Play to bench ─────────────────────────────────────────────────────
        m = RE_PLAY_TO_BENCH.match(stripped)
        if m:
            player = m.group("player").strip()
            card = m.group("card").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_PLAY_TO_BENCH, ["player_raw", "card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_PLAY_TO_BENCH, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=card,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Damage breakdown label ────────────────────────────────────────────
        if RE_DAMAGE_BREAKDOWN_LABEL.match(stripped):
            block_lines = [stripped]
            base_dmg: Optional[int] = None
            total_dmg: Optional[int] = None
            j = i + 1
            while j < len(lines):
                bm = RE_BULLET_LINE.match(lines[j])
                if bm:
                    content = lines[j].strip()
                    block_lines.append(content)
                    bbase = RE_BASE_DAMAGE.search(content)
                    if bbase:
                        base_dmg = int(bbase.group("n"))
                    btotal = RE_TOTAL_DAMAGE.search(content)
                    if btotal:
                        total_dmg = int(btotal.group("n"))
                    j += 1
                else:
                    break
            raw_block = "\n".join(block_lines)
            i = j
            captured = []
            if base_dmg is not None:
                captured.append("base_damage")
            if total_dmg is not None:
                captured.append("damage")
            score, reasons = event_confidence(ET_DAMAGE_BREAKDOWN, captured)
            events.append(_make_event(
                event_idx, current_turn, PHASE_COMBAT if current_turn else PHASE_SETUP,
                ET_DAMAGE_BREAKDOWN, stripped,
                raw_block=raw_block,
                base_damage=base_dmg,
                damage=total_dmg,
                event_payload={"base_damage": base_dmg, "total_damage": total_dmg},
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            continue

        # ── Attack used ───────────────────────────────────────────────────────
        m = RE_ATTACK.match(stripped)
        if m:
            player = m.group("player").strip()
            card = m.group("card").strip()
            attack = m.group("attack").strip()
            target_player = m.group("target_player").strip()
            target_card = m.group("target_card").strip()
            dmg = int(m.group("damage"))
            alias, actor = get_alias(player)
            target_alias, _ = get_alias(target_player)
            current_phase = PHASE_COMBAT
            score, reasons = event_confidence(ET_ATTACK_USED, ["player_raw", "card_name_raw", "damage"])
            events.append(_make_event(
                event_idx, current_turn, PHASE_COMBAT, ET_ATTACK_USED, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=card, target_card_name_raw=target_card,
                damage=dmg,
                event_payload={
                    "attack_name": attack,
                    "target_player_raw": target_player,
                    "target_player_alias": target_alias,
                },
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Knockout ──────────────────────────────────────────────────────────
        m = RE_KNOCKOUT.match(stripped)
        if m:
            player = m.group("player").strip()
            card = m.group("card").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_KNOCKOUT, ["player_raw", "card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_KNOCKOUT, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=card,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Prize taken ───────────────────────────────────────────────────────
        m = RE_PRIZE_TAKEN.match(stripped)
        if m:
            player = m.group("player").strip()
            n = int(m.group("n"))
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_PRIZE_TAKEN, ["player_raw", "prize_count_delta"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_PRIZE_TAKEN, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                prize_count_delta=n,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Prize card added to hand ──────────────────────────────────────────
        m = RE_PRIZE_CARD_ADDED.match(stripped)
        if m:
            player = m.group("player").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_PRIZE_CARD_ADDED, ["player_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_PRIZE_CARD_ADDED, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Draw (known) ──────────────────────────────────────────────────────
        m = RE_DRAW_KNOWN.match(stripped)
        if m:
            player = m.group("player").strip()
            card = m.group("card").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_DRAW, ["player_raw", "card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_DRAW, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=card,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Draw hidden (N cards) ─────────────────────────────────────────────
        m = RE_DRAW_N_HIDDEN.match(stripped)
        if m:
            player = m.group("player").strip()
            n = int(m.group("n"))
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_DRAW_HIDDEN, ["player_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_DRAW_HIDDEN, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                amount=n,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Draw hidden (a card) ──────────────────────────────────────────────
        m = RE_DRAW_HIDDEN.match(stripped)
        if m:
            player = m.group("player").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_DRAW_HIDDEN, ["player_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_DRAW_HIDDEN, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Play tool ─────────────────────────────────────────────────────────
        m = RE_PLAY_TOOL.match(stripped)
        if m:
            player = m.group("player").strip()
            card = m.group("card").strip()
            target = m.group("target").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_PLAY_TOOL, ["player_raw", "card_name_raw", "target_card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_PLAY_TOOL, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=card, target_card_name_raw=target,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Evolve ────────────────────────────────────────────────────────────
        m = RE_EVOLVE.match(stripped)
        if m:
            player = m.group("player").strip()
            from_card = m.group("from_card").strip()
            to_card = m.group("to_card").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_EVOLVE, ["player_raw", "card_name_raw", "target_card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_EVOLVE, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=from_card, target_card_name_raw=to_card,
                event_payload={"from_card": from_card, "to_card": to_card},
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Attach energy ─────────────────────────────────────────────────────
        m = RE_ATTACH_ENERGY.match(stripped)
        if m:
            player = m.group("player").strip()
            energy = m.group("energy").strip()
            target = m.group("target").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_ATTACH_ENERGY, ["player_raw", "energy_type", "target_card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_ATTACH_ENERGY, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                energy_type=energy, target_card_name_raw=target,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        m = RE_ATTACH_ENERGY2.match(stripped)
        if m:
            player = m.group("player").strip()
            energy = m.group("energy").strip()
            target = m.group("target").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_ATTACH_ENERGY, ["player_raw", "energy_type"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_ATTACH_ENERGY, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                energy_type=energy, target_card_name_raw=target,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Play stadium ──────────────────────────────────────────────────────
        m = RE_PLAY_STADIUM.match(stripped)
        if m:
            player = m.group("player").strip()
            card = m.group("card").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_PLAY_STADIUM, ["player_raw", "card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_PLAY_STADIUM, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=card,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Play item ─────────────────────────────────────────────────────────
        m = RE_PLAY_ITEM.match(stripped)
        if m:
            player = m.group("player").strip()
            card = m.group("card").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_PLAY_ITEM, ["player_raw", "card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_PLAY_ITEM, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=card,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Play supporter ────────────────────────────────────────────────────
        m = RE_PLAY_SUPPORTER.match(stripped)
        if m:
            player = m.group("player").strip()
            card = m.group("card").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_PLAY_SUPPORTER, ["player_raw", "card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_PLAY_SUPPORTER, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=card,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Ability used ──────────────────────────────────────────────────────
        m = RE_ABILITY_USED.match(stripped)
        if m:
            player = m.group("player").strip()
            card = m.group("card").strip()
            ability = m.group("ability").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_ABILITY_USED, ["player_raw", "card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_ABILITY_USED, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=card,
                event_payload={"ability_name": ability},
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Retreat ───────────────────────────────────────────────────────────
        m = RE_RETREAT.match(stripped)
        if m:
            player = m.group("player").strip()
            card = m.group("card").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_RETREAT, ["player_raw", "card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_RETREAT, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=card,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Switch active ─────────────────────────────────────────────────────
        m = RE_SWITCH_ACTIVE.match(stripped)
        if m:
            player = m.group("player").strip()
            card = m.group("card").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_SWITCH_ACTIVE, ["player_raw", "card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_SWITCH_ACTIVE, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=card,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Shuffle deck ──────────────────────────────────────────────────────
        m = RE_SHUFFLE.match(stripped)
        if m:
            player = m.group("player").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_SHUFFLE_DECK, ["player_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_SHUFFLE_DECK, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Discard ───────────────────────────────────────────────────────────
        m = RE_DISCARD.match(stripped)
        if m:
            player = m.group("player").strip()
            card = m.group("card").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_DISCARD, ["player_raw", "card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_DISCARD, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=card,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Search or fetch ───────────────────────────────────────────────────
        m = RE_SEARCH.match(stripped)
        if m:
            player = m.group("player").strip()
            zone = m.group("zone").strip()
            card = m.group("card").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_SEARCH_OR_FETCH, ["player_raw", "card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_SEARCH_OR_FETCH, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=card, zone=zone,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Recover from discard ──────────────────────────────────────────────
        m = RE_RECOVER.match(stripped)
        if m:
            player = m.group("player").strip()
            card = m.group("card").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_RECOVER_FROM_DISCARD, ["player_raw", "card_name_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_RECOVER_FROM_DISCARD, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                card_name_raw=card,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── End turn ──────────────────────────────────────────────────────────
        m = RE_END_TURN.match(stripped)
        if m:
            player = m.group("player").strip()
            alias, actor = get_alias(player)
            score, reasons = event_confidence(ET_END_TURN, ["player_raw"])
            events.append(_make_event(
                event_idx, current_turn, current_phase, ET_END_TURN, stripped,
                player_raw=player, player_alias=alias, actor_type=actor,
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Bullet/dash sub-lines (not consumed by parent) ────────────────────
        if RE_BULLET_LINE.match(line):
            i += 1
            continue
        if RE_DASH_LINE.match(stripped):
            i += 1
            continue

        # ── Game end fallback (X wins!) ────────────────────────────────────────
        m = RE_GAME_END_KO.search(stripped)
        if m:
            w = m.group("winner").strip()
            winner_raw = w
            win_condition = "ko"
            alias, actor = get_alias(w)
            winner_alias = alias
            score, reasons = event_confidence(ET_GAME_END, ["winner_raw"])
            current_phase = PHASE_GAME_END
            events.append(_make_event(
                event_idx, current_turn, PHASE_GAME_END, ET_GAME_END, stripped,
                player_raw=w, player_alias=alias, actor_type=actor,
                event_payload={"winner": w, "win_condition": "ko"},
                confidence_score=score, confidence_reasons=reasons,
            ))
            event_idx += 1
            i += 1
            continue

        # ── Unknown fallback ──────────────────────────────────────────────────
        score, reasons = event_confidence(ET_UNKNOWN, [])
        events.append(_make_event(
            event_idx, current_turn, current_phase, ET_UNKNOWN, stripped,
            event_payload={"raw": stripped},
            confidence_score=score, confidence_reasons=reasons,
        ))
        event_idx += 1
        i += 1

    p1 = player_names[0] if len(player_names) > 0 else None
    p2 = player_names[1] if len(player_names) > 1 else None

    confidences = [e.confidence_score for e in events]
    log_conf = log_confidence(confidences)

    return ParsedObservedLog(
        parser_version=PARSER_VERSION,
        events=events,
        player_1_name_raw=p1,
        player_2_name_raw=p2,
        player_1_alias="player_1" if p1 else None,
        player_2_alias="player_2" if p2 else None,
        winner_raw=winner_raw,
        winner_alias=winner_alias,
        win_condition=win_condition,
        turn_count=turn_count,
        event_count=len(events),
        confidence_score=log_conf,
        warnings=warnings,
        errors=errors,
        metadata={"parser_version": PARSER_VERSION, "raw_line_count": len(lines)},
    )
