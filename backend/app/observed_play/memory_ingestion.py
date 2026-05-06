"""Observed Play Memory Phase 4: Gated memory ingestion.

Turns validated observed-play logs into durable, queryable observed-play
memory records.  These memory items are stored for review only — they are
NOT integrated with Coach, AI Player, pgvector, Neo4j, simulator match_events,
or card performance tables.

Public API
----------
evaluate_log_ingestion_eligibility(db, log_id, config) -> EligibilityResult
preview_observed_play_ingestion(db, log_id, config)    -> MemoryIngestionPreview
ingest_observed_play_log(db, log_id, config)           -> MemoryIngestionSummary
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ObservedCardMention,
    ObservedPlayEvent,
    ObservedPlayLog,
    ObservedPlayMemoryIngestion,
    ObservedPlayMemoryItem,
)
from app.observed_play.constants import (
    ET_ABILITY_USED,
    ET_ATTACH_CARD,
    ET_ATTACH_ENERGY,
    ET_CARD_ADDED_TO_HAND,
    ET_CARD_EFFECT_ACTIVATED,
    ET_DISCARD,
    ET_DISCARD_FROM_POKEMON,
    ET_DRAW_HIDDEN,
    ET_EVOLVE,
    ET_GAME_END,
    ET_KNOCKOUT,
    ET_OPENING_HAND_DRAW_HIDDEN,
    ET_PLAY_ITEM,
    ET_PLAY_STADIUM,
    ET_PLAY_SUPPORTER,
    ET_PLAY_TOOL,
    ET_PLAY_TRAINER,
    ET_PRIZE_TAKEN,
    ET_RETREAT,
    ET_SETUP_START,
    ET_SHUFFLE_DECK,
    ET_SWITCH_ACTIVE,
    ET_ATTACK_USED,
    ET_DAMAGE_BREAKDOWN,
    ET_TURN_START,
    ET_UNKNOWN,
    MEMORY_INGESTION_VERSION,
)
from app.observed_play.schemas import (
    EligibilityMetrics,
    EligibilityReason,
    EligibilityResult,
    IngestionConfig,
    MemoryIngestionPreview,
    MemoryIngestionSummary,
    MemoryItemPreview,
)

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Event types that produce memory items
_INGESTIBLE_EVENT_TYPES: frozenset[str] = frozenset({
    ET_PLAY_TRAINER,
    ET_PLAY_ITEM,
    ET_PLAY_SUPPORTER,
    ET_PLAY_STADIUM,
    ET_PLAY_TOOL,
    ET_ATTACH_ENERGY,
    ET_ATTACH_CARD,
    ET_EVOLVE,
    ET_ABILITY_USED,
    ET_ATTACK_USED,
    ET_DAMAGE_BREAKDOWN,
    ET_KNOCKOUT,
    ET_PRIZE_TAKEN,
    ET_RETREAT,
    ET_SWITCH_ACTIVE,
    ET_DISCARD,
    ET_DISCARD_FROM_POKEMON,
    ET_CARD_ADDED_TO_HAND,
    ET_CARD_EFFECT_ACTIVATED,
    ET_GAME_END,
})

# Event types to skip entirely (hidden/private information, setup noise)
_SKIP_EVENT_TYPES: frozenset[str] = frozenset({
    ET_UNKNOWN,
    ET_SETUP_START,
    ET_TURN_START,
    ET_SHUFFLE_DECK,
    ET_DRAW_HIDDEN,
    ET_OPENING_HAND_DRAW_HIDDEN,
})

# Mention roles that are critical — unresolved mentions in these roles block ingestion
_CRITICAL_MENTION_ROLES: frozenset[str] = frozenset({
    "actor_card",
    "target_card",
    "evolution_from",
    "evolution_to",
    "attached_card",
    "energy_card",
    "trainer_card",
    "tool_card",
    "stadium_card",
})

# Map event type -> memory_type
_ET_TO_MEMORY_TYPE: dict[str, str] = {
    ET_PLAY_TRAINER: "card_played",
    ET_PLAY_ITEM: "card_played",
    ET_PLAY_SUPPORTER: "card_played",
    ET_PLAY_STADIUM: "card_played",
    ET_PLAY_TOOL: "card_played",
    ET_ATTACH_ENERGY: "card_attached",
    ET_ATTACH_CARD: "card_attached",
    ET_EVOLVE: "card_evolved",
    ET_ABILITY_USED: "ability_used",
    ET_ATTACK_USED: "attack_used",
    ET_DAMAGE_BREAKDOWN: "damage_dealt",
    ET_KNOCKOUT: "knockout",
    ET_PRIZE_TAKEN: "prize_taken",
    ET_RETREAT: "retreat",
    ET_SWITCH_ACTIVE: "switch_active",
    ET_DISCARD: "discard",
    ET_DISCARD_FROM_POKEMON: "discard",
    ET_CARD_ADDED_TO_HAND: "card_added_to_hand",
    ET_CARD_EFFECT_ACTIVATED: "card_effect_activated",
    ET_GAME_END: "game_end",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _mention_index_by_role(
    mentions_for_event: list[ObservedCardMention],
) -> dict[str, ObservedCardMention]:
    """Build a dict mapping mention_role -> first mention row for that role."""
    result: dict[str, ObservedCardMention] = {}
    for m in mentions_for_event:
        if m.mention_role not in result:
            result[m.mention_role] = m
    return result


def _card_fields_from_mention(
    m: ObservedCardMention | None,
    *,
    allow_unresolved: bool = False,
) -> tuple[str | None, str | None, str | None]:
    """Return (raw_name, card_def_id, resolution_status) from a mention row.

    - resolved mention: include card_def_id
    - ambiguous mention: raw name only, resolution_status=ambiguous
    - unresolved mention: raw name only if allow_unresolved else (None, None, None)
    - ignored mention: skip (None, None, None)
    """
    if m is None:
        return None, None, None
    rs = m.resolution_status
    if rs == "ignored":
        return None, None, None
    if rs == "resolved":
        return m.raw_name, m.resolved_card_def_id, rs
    if rs == "ambiguous":
        return m.raw_name, None, rs
    # unresolved
    if allow_unresolved:
        return m.raw_name, None, rs
    return None, None, None


def _compute_item_confidence(
    base: float,
    mentions_by_role: dict[str, ObservedCardMention],
    critical_roles: frozenset[str],
    *,
    allow_unresolved: bool,
) -> float:
    """Compute memory item confidence with penalty for ambiguous/unresolved critical mentions."""
    score = base
    for role in critical_roles:
        m = mentions_by_role.get(role)
        if m is None:
            continue
        if m.resolution_status == "ambiguous":
            score -= 0.10
        elif m.resolution_status == "unresolved" and allow_unresolved:
            score -= 0.25
    return max(0.0, min(1.0, score))


def _make_memory_key(event_type: str, event_id: int, **parts: Any) -> str:
    """Build a deterministic memory key from event type, id, and named parts."""
    part_str = ":".join(
        str(v) if v is not None else ""
        for v in parts.values()
    )
    return f"{event_type}:{event_id}:{part_str}"


def _build_memory_item_data(
    event: ObservedPlayEvent,
    mentions_by_role: dict[str, ObservedCardMention],
    *,
    allow_unresolved: bool,
) -> dict[str, Any] | None:
    """Return a dict of field values for an ObservedPlayMemoryItem, or None to skip."""
    et = event.event_type

    if et in _SKIP_EVENT_TYPES or et not in _INGESTIBLE_EVENT_TYPES:
        return None

    memory_type = _ET_TO_MEMORY_TYPE.get(et)
    if not memory_type:
        return None

    payload: dict = event.event_payload_json or {}

    actor_raw = actor_def = actor_rs = None
    target_raw = target_def = target_rs = None
    related_raw = related_def = related_rs = None
    action_name: str | None = None

    if et == ET_ATTACK_USED:
        actor_raw, actor_def, actor_rs = _card_fields_from_mention(
            mentions_by_role.get("actor_card"), allow_unresolved=allow_unresolved)
        target_raw, target_def, target_rs = _card_fields_from_mention(
            mentions_by_role.get("target_card"), allow_unresolved=allow_unresolved)
        action_name = payload.get("attack_name") or event.card_name_raw

    elif et == ET_ABILITY_USED:
        actor_raw, actor_def, actor_rs = _card_fields_from_mention(
            mentions_by_role.get("actor_card"), allow_unresolved=allow_unresolved)
        action_name = payload.get("ability_name")

    elif et == ET_EVOLVE:
        actor_raw, actor_def, actor_rs = _card_fields_from_mention(
            mentions_by_role.get("evolution_to"), allow_unresolved=allow_unresolved)
        related_raw, related_def, related_rs = _card_fields_from_mention(
            mentions_by_role.get("evolution_from"), allow_unresolved=allow_unresolved)

    elif et in (ET_ATTACH_ENERGY, ET_ATTACH_CARD):
        actor_raw, actor_def, actor_rs = _card_fields_from_mention(
            mentions_by_role.get("energy_card")
            or mentions_by_role.get("attached_card")
            or mentions_by_role.get("tool_card"),
            allow_unresolved=allow_unresolved,
        )
        target_raw, target_def, target_rs = _card_fields_from_mention(
            mentions_by_role.get("target_card"), allow_unresolved=allow_unresolved)

    elif et in (ET_PLAY_ITEM, ET_PLAY_SUPPORTER, ET_PLAY_STADIUM,
                ET_PLAY_TOOL, ET_PLAY_TRAINER):
        actor_raw, actor_def, actor_rs = _card_fields_from_mention(
            mentions_by_role.get("trainer_card")
            or mentions_by_role.get("tool_card")
            or mentions_by_role.get("stadium_card"),
            allow_unresolved=allow_unresolved,
        )

    elif et == ET_KNOCKOUT:
        actor_raw, actor_def, actor_rs = _card_fields_from_mention(
            mentions_by_role.get("actor_card"), allow_unresolved=allow_unresolved)

    elif et == ET_DAMAGE_BREAKDOWN:
        actor_raw, actor_def, actor_rs = _card_fields_from_mention(
            mentions_by_role.get("actor_card"), allow_unresolved=allow_unresolved)
        target_raw, target_def, target_rs = _card_fields_from_mention(
            mentions_by_role.get("target_card"), allow_unresolved=allow_unresolved)

    elif et in (ET_RETREAT, ET_SWITCH_ACTIVE):
        actor_raw, actor_def, actor_rs = _card_fields_from_mention(
            mentions_by_role.get("actor_card"), allow_unresolved=allow_unresolved)

    elif et in (ET_DISCARD, ET_DISCARD_FROM_POKEMON):
        actor_raw, actor_def, actor_rs = _card_fields_from_mention(
            mentions_by_role.get("discarded_card")
            or mentions_by_role.get("actor_card"),
            allow_unresolved=allow_unresolved,
        )
        if et == ET_DISCARD_FROM_POKEMON:
            target_raw, target_def, target_rs = _card_fields_from_mention(
                mentions_by_role.get("target_card"), allow_unresolved=allow_unresolved)

    elif et == ET_CARD_ADDED_TO_HAND:
        actor_raw, actor_def, actor_rs = _card_fields_from_mention(
            mentions_by_role.get("added_to_hand_card"), allow_unresolved=allow_unresolved)

    elif et == ET_CARD_EFFECT_ACTIVATED:
        actor_raw, actor_def, actor_rs = _card_fields_from_mention(
            mentions_by_role.get("effect_card"), allow_unresolved=allow_unresolved)

    elif et == ET_PRIZE_TAKEN:
        related_raw, related_def, related_rs = _card_fields_from_mention(
            mentions_by_role.get("revealed_card"), allow_unresolved=allow_unresolved)

    elif et == ET_GAME_END:
        pass  # No card fields, just a game-end record

    # Compute memory key
    memory_key = _make_memory_key(
        _ET_TO_MEMORY_TYPE.get(et, et),
        event.id,
        actor=actor_raw,
        action=action_name,
        target=target_raw,
        damage=event.damage,
    )

    # Compute per-item confidence
    confidence = _compute_item_confidence(
        event.confidence_score,
        mentions_by_role,
        _CRITICAL_MENTION_ROLES,
        allow_unresolved=allow_unresolved,
    )

    return {
        "memory_type": memory_type,
        "memory_key": memory_key,
        "turn_number": event.turn_number,
        "phase": event.phase,
        "player_alias": event.player_alias,
        "player_raw": event.player_raw,
        "actor_card_raw": actor_raw,
        "actor_card_def_id": actor_def,
        "actor_resolution_status": actor_rs,
        "target_card_raw": target_raw,
        "target_card_def_id": target_def,
        "target_resolution_status": target_rs,
        "related_card_raw": related_raw,
        "related_card_def_id": related_def,
        "related_resolution_status": related_rs,
        "action_name": action_name,
        "amount": event.amount,
        "damage": event.damage,
        "zone": event.zone,
        "target_zone": event.target_zone,
        "confidence_score": confidence,
        "source_event_type": et,
        "source_raw_line": event.raw_line,
        "source_payload_json": payload,
    }


# ── Eligibility evaluation ────────────────────────────────────────────────────

async def evaluate_log_ingestion_eligibility(
    db: AsyncSession,
    log_id: str | uuid.UUID,
    config: IngestionConfig,
) -> EligibilityResult:
    """Check whether a log is eligible for memory ingestion.

    Returns an EligibilityResult with eligible flag, status, reasons, and metrics.
    """
    log_result = await db.execute(
        select(ObservedPlayLog).where(ObservedPlayLog.id == log_id)
    )
    log: ObservedPlayLog | None = log_result.scalars().first()

    if log is None:
        return EligibilityResult(
            eligible=False,
            status="ineligible",
            reasons=[EligibilityReason(code="log_not_found", detail=f"Log {log_id} not found")],
        )

    reasons: list[EligibilityReason] = []

    # ── Parse status gate ──────────────────────────────────────────────────────
    parse_status = log.parse_status or ""
    if parse_status not in ("parsed", "parsed_with_warnings"):
        reasons.append(EligibilityReason(
            code="not_parsed",
            detail=f"parse_status '{parse_status}' not in (parsed, parsed_with_warnings)",
        ))

    # ── Confidence gate ────────────────────────────────────────────────────────
    confidence = log.confidence_score or 0.0
    if confidence < config.min_confidence:
        reasons.append(EligibilityReason(
            code="low_confidence",
            detail=f"confidence_score {confidence:.2f} below {config.min_confidence:.2f}",
        ))

    # ── Parser diagnostics gates ───────────────────────────────────────────────
    diag = (log.metadata_json or {}).get("parser_diagnostics") or {}
    unknown_ratio = float(diag.get("unknown_ratio", 0.0))
    low_confidence_count = int(diag.get("low_confidence_count", 0))
    event_count = log.event_count or 0

    if unknown_ratio > config.max_unknown_ratio:
        reasons.append(EligibilityReason(
            code="high_unknown_ratio",
            detail=f"unknown_ratio {unknown_ratio:.3f} exceeds {config.max_unknown_ratio:.3f}",
        ))

    lcc_threshold = max(1, int(event_count * config.max_unknown_ratio)) if event_count > 0 else 5
    if low_confidence_count > lcc_threshold:
        reasons.append(EligibilityReason(
            code="high_low_confidence_count",
            detail=f"low_confidence_count {low_confidence_count} exceeds threshold {lcc_threshold}",
        ))

    if event_count == 0:
        reasons.append(EligibilityReason(
            code="no_events",
            detail="event_count is 0",
        ))

    card_mention_count = log.card_mention_count or 0
    if card_mention_count == 0:
        reasons.append(EligibilityReason(
            code="no_card_mentions",
            detail="card_mention_count is 0",
        ))

    # ── Unresolved card gates ──────────────────────────────────────────────────
    unresolved_count = log.unresolved_card_count or 0
    ambiguous_count = log.ambiguous_card_count or 0

    # Count critical unresolved mentions
    critical_unresolved_result = await db.execute(
        select(ObservedCardMention).where(
            ObservedCardMention.observed_play_log_id == log_id,
            ObservedCardMention.resolution_status == "unresolved",
            ObservedCardMention.mention_role.in_(list(_CRITICAL_MENTION_ROLES)),
        )
    )
    critical_unresolved_mentions = critical_unresolved_result.scalars().all()
    critical_unresolved_count = len(critical_unresolved_mentions)

    if not config.allow_unresolved:
        if unresolved_count > config.max_unresolved:
            reasons.append(EligibilityReason(
                code="unresolved_cards",
                detail=f"unresolved_card_count {unresolved_count} exceeds max {config.max_unresolved}",
            ))
        if critical_unresolved_count > 0:
            reasons.append(EligibilityReason(
                code="unresolved_critical_cards",
                detail=f"{critical_unresolved_count} unresolved critical (actor/target/evolution/etc.) mentions",
            ))

    # ── Build metrics ──────────────────────────────────────────────────────────
    metrics = EligibilityMetrics(
        confidence_score=confidence,
        event_count=event_count,
        unknown_ratio=unknown_ratio,
        low_confidence_count=low_confidence_count,
        card_mention_count=card_mention_count,
        unresolved_card_count=unresolved_count,
        ambiguous_card_count=ambiguous_count,
        critical_unresolved_count=critical_unresolved_count,
    )

    if not reasons:
        return EligibilityResult(eligible=True, status="eligible", reasons=[], metrics=metrics)

    if config.force and config.allow_unresolved:
        return EligibilityResult(
            eligible=True,
            status="forced",
            reasons=reasons,
            metrics=metrics,
        )

    return EligibilityResult(eligible=False, status="ineligible", reasons=reasons, metrics=metrics)


# ── Preview ───────────────────────────────────────────────────────────────────

async def preview_observed_play_ingestion(
    db: AsyncSession,
    log_id: str | uuid.UUID,
    config: IngestionConfig,
) -> MemoryIngestionPreview:
    """Preview what would be ingested without writing anything."""
    eligibility = await evaluate_log_ingestion_eligibility(db, log_id, config)

    if not eligibility.eligible:
        return MemoryIngestionPreview(
            eligible=False,
            eligibility_status=eligibility.status,
            reasons=eligibility.reasons,
            metrics=eligibility.metrics,
        )

    # Load events and their mentions
    events_result = await db.execute(
        select(ObservedPlayEvent)
        .where(ObservedPlayEvent.observed_play_log_id == log_id)
        .order_by(ObservedPlayEvent.event_index)
    )
    events = events_result.scalars().all()

    mentions_result = await db.execute(
        select(ObservedCardMention)
        .where(ObservedCardMention.observed_play_log_id == log_id)
    )
    all_mentions = mentions_result.scalars().all()

    # Build index: event_id -> list of mentions
    mentions_by_event: dict[int, list[ObservedCardMention]] = {}
    for m in all_mentions:
        mentions_by_event.setdefault(m.observed_play_event_id, []).append(m)

    items_preview: list[MemoryItemPreview] = []
    event_type_counts: dict[str, int] = {}

    for event in events:
        if event.event_type in _SKIP_EVENT_TYPES:
            continue
        mentions_by_role = _mention_index_by_role(mentions_by_event.get(event.id, []))
        data = _build_memory_item_data(
            event, mentions_by_role, allow_unresolved=config.allow_unresolved
        )
        if data is None:
            continue

        mt = data["memory_type"]
        event_type_counts[mt] = event_type_counts.get(mt, 0) + 1

        if len(items_preview) < 10:
            items_preview.append(MemoryItemPreview(
                memory_type=data["memory_type"],
                memory_key=data["memory_key"],
                turn_number=data["turn_number"],
                player_alias=data["player_alias"],
                actor_card_raw=data["actor_card_raw"],
                actor_card_def_id=data["actor_card_def_id"],
                actor_resolution_status=data["actor_resolution_status"],
                action_name=data["action_name"],
                target_card_raw=data["target_card_raw"],
                damage=data["damage"],
                confidence_score=data["confidence_score"],
                source_event_type=data["source_event_type"],
                source_raw_line=data["source_raw_line"],
            ))

    total_items = sum(event_type_counts.values())

    return MemoryIngestionPreview(
        eligible=True,
        eligibility_status=eligibility.status,
        reasons=eligibility.reasons,
        metrics=eligibility.metrics,
        estimated_memory_item_count=total_items,
        event_type_counts=event_type_counts,
        sample_items=items_preview,
    )


# ── Ingest ────────────────────────────────────────────────────────────────────

async def ingest_observed_play_log(
    db: AsyncSession,
    log_id: str | uuid.UUID,
    config: IngestionConfig,
) -> MemoryIngestionSummary:
    """Ingest a log's parsed events into observed play memory items.

    Idempotent: deletes prior memory items for the log before re-ingesting.
    Updates the log's memory_status and memory_item_count on success.
    Does NOT integrate with Coach, AI Player, pgvector, Neo4j, simulator, or
    card performance tables.
    """
    eligibility = await evaluate_log_ingestion_eligibility(db, log_id, config)

    if not eligibility.eligible:
        return MemoryIngestionSummary(
            ingestion_id="",
            log_id=str(log_id),
            status="skipped",
            eligibility_status=eligibility.status,
            reasons=eligibility.reasons,
            ingestion_version=MEMORY_INGESTION_VERSION,
            error="Ineligible for ingestion; see reasons",
        )

    # Fetch log
    log_result = await db.execute(
        select(ObservedPlayLog).where(ObservedPlayLog.id == log_id)
    )
    log: ObservedPlayLog = log_result.scalars().first()

    # ── Idempotency: delete prior memory items for this log ────────────────────
    await db.execute(
        delete(ObservedPlayMemoryItem).where(
            ObservedPlayMemoryItem.observed_play_log_id == log_id
        )
    )

    # ── Create ingestion run ───────────────────────────────────────────────────
    ingestion = ObservedPlayMemoryIngestion(
        observed_play_log_id=log.id,
        import_batch_id=log.import_batch_id,
        status="pending",
        ingestion_version=MEMORY_INGESTION_VERSION,
        eligibility_status=eligibility.status,
        eligibility_reasons_json=[r.model_dump() for r in eligibility.reasons],
        config_json=config.model_dump(),
    )
    db.add(ingestion)
    await db.flush()  # get ingestion.id

    # ── Load events and mentions ───────────────────────────────────────────────
    events_result = await db.execute(
        select(ObservedPlayEvent)
        .where(ObservedPlayEvent.observed_play_log_id == log_id)
        .order_by(ObservedPlayEvent.event_index)
    )
    events = events_result.scalars().all()

    mentions_result = await db.execute(
        select(ObservedCardMention)
        .where(ObservedCardMention.observed_play_log_id == log_id)
    )
    all_mentions = mentions_result.scalars().all()

    mentions_by_event: dict[int, list[ObservedCardMention]] = {}
    for m in all_mentions:
        mentions_by_event.setdefault(m.observed_play_event_id, []).append(m)

    # ── Generate and store memory items ───────────────────────────────────────
    memory_item_count = 0
    skipped_event_count = 0

    try:
        for event in events:
            if event.event_type in _SKIP_EVENT_TYPES:
                skipped_event_count += 1
                continue
            mentions_by_role = _mention_index_by_role(mentions_by_event.get(event.id, []))
            data = _build_memory_item_data(
                event, mentions_by_role, allow_unresolved=config.allow_unresolved
            )
            if data is None:
                skipped_event_count += 1
                continue

            item = ObservedPlayMemoryItem(
                ingestion_id=ingestion.id,
                observed_play_log_id=log.id,
                observed_play_event_id=event.id,
                import_batch_id=log.import_batch_id,
                **data,
            )
            db.add(item)
            memory_item_count += 1

        # ── Update ingestion record ────────────────────────────────────────────
        ingestion.status = "completed"
        ingestion.memory_item_count = memory_item_count
        ingestion.skipped_event_count = skipped_event_count
        ingestion.source_event_count = len(events)
        ingestion.completed_at = datetime.now(timezone.utc)
        ingestion.summary_json = {
            "memory_item_count": memory_item_count,
            "skipped_event_count": skipped_event_count,
            "source_event_count": len(events),
        }

        # ── Update log memory status ───────────────────────────────────────────
        log.memory_status = "ingested"
        log.memory_item_count = memory_item_count
        log.last_memory_ingested_at = datetime.now(timezone.utc)

    except Exception as exc:
        logger.exception("Memory ingestion failed for log %s", log_id)
        ingestion.status = "failed"
        ingestion.error_json = {"error": str(exc)}
        log.memory_status = "ingestion_failed"
        return MemoryIngestionSummary(
            ingestion_id=str(ingestion.id),
            log_id=str(log_id),
            status="failed",
            eligibility_status=eligibility.status,
            reasons=eligibility.reasons,
            ingestion_version=MEMORY_INGESTION_VERSION,
            error=str(exc),
        )

    return MemoryIngestionSummary(
        ingestion_id=str(ingestion.id),
        log_id=str(log_id),
        status="completed",
        eligibility_status=eligibility.status,
        reasons=eligibility.reasons,
        source_event_count=len(events),
        memory_item_count=memory_item_count,
        skipped_event_count=skipped_event_count,
        ingestion_version=MEMORY_INGESTION_VERSION,
    )
