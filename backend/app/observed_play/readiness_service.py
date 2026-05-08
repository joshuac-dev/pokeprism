"""Shared service layer for corpus readiness and coach evidence filtering.

Extracted from ``app.api.observed_play`` so that:
- ``app.api.observed_play`` (Phase 5.2 / 6.0 endpoints) can import from here.
- ``app.observed_play.coach_context`` (Phase 6.1) can import from here.

All functions are read-only and never mutate the database.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from sqlalchemy import and_, desc, func, or_, select

from app.db.models import (
    ObservedCardMention,
    ObservedPlayEvent,
    ObservedPlayLog,
    ObservedPlayMemoryItem,
)
from app.observed_play.schemas import (
    CardResolutionStats,
    CorpusReadinessReport,
    CorpusStats,
    LOW_CONFIDENCE_THRESHOLD,
    MemoryQualityStats,
    ParserQualityStats,
    READINESS_AVG_EVENT_CONFIDENCE_THRESHOLD,
    READINESS_AVG_MEMORY_CONFIDENCE_THRESHOLD,
    READINESS_INGESTION_COVERAGE_THRESHOLD,
    READINESS_LOW_CONFIDENCE_EVENT_THRESHOLD,
    READINESS_TOP_N_LIMIT,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

_READINESS_CRITICAL_ROLES: frozenset[str] = frozenset({
    "actor_card", "target_card", "evolution_from", "evolution_to",
    "attached_card", "energy_card", "trainer_card", "tool_card", "stadium_card",
})


async def compute_corpus_readiness(db: AsyncSession) -> CorpusReadinessReport:
    """Compute and return the full corpus readiness report.

    Shared by ``GET /corpus-readiness``, ``GET /coach-evidence`` (readiness
    gate), and ``GET /coach-context-preview``.  Never mutates the database.
    """
    from datetime import datetime, timezone

    # ── Corpus coverage ───────────────────────────────────────────────────────
    log_count = (await db.execute(select(func.count(ObservedPlayLog.id)))).scalar() or 0

    parsed_log_count = (await db.execute(
        select(func.count(ObservedPlayLog.id)).where(ObservedPlayLog.parse_status == "parsed")
    )).scalar() or 0
    ingested_log_count = (await db.execute(
        select(func.count(ObservedPlayLog.id)).where(ObservedPlayLog.memory_status == "ingested")
    )).scalar() or 0
    failed_log_count = (await db.execute(
        select(func.count(ObservedPlayLog.id)).where(ObservedPlayLog.parse_status == "failed")
    )).scalar() or 0
    event_count = (await db.execute(select(func.count(ObservedPlayEvent.id)))).scalar() or 0
    memory_item_count = (await db.execute(select(func.count(ObservedPlayMemoryItem.id)))).scalar() or 0

    corpus = CorpusStats(
        log_count=log_count,
        parsed_log_count=parsed_log_count,
        ingested_log_count=ingested_log_count,
        not_ingested_log_count=log_count - ingested_log_count,
        failed_log_count=failed_log_count,
        event_count=event_count,
        memory_item_count=memory_item_count,
    )

    # ── Parser quality ────────────────────────────────────────────────────────
    avg_event_conf_raw = (await db.execute(
        select(func.avg(ObservedPlayEvent.confidence_score))
    )).scalar()
    min_log_conf_raw = (await db.execute(
        select(func.min(ObservedPlayLog.confidence_score)).where(ObservedPlayLog.parse_status == "parsed")
    )).scalar()
    avg_log_conf_raw = (await db.execute(
        select(func.avg(ObservedPlayLog.confidence_score)).where(ObservedPlayLog.parse_status == "parsed")
    )).scalar()
    unknown_event_count = (await db.execute(
        select(func.count(ObservedPlayEvent.id)).where(ObservedPlayEvent.event_type == "unknown")
    )).scalar() or 0
    low_confidence_event_count = (await db.execute(
        select(func.count(ObservedPlayEvent.id)).where(
            ObservedPlayEvent.confidence_score < READINESS_LOW_CONFIDENCE_EVENT_THRESHOLD
        )
    )).scalar() or 0
    logs_below_threshold = (await db.execute(
        select(func.count(ObservedPlayLog.id)).where(
            and_(
                ObservedPlayLog.parse_status == "parsed",
                ObservedPlayLog.confidence_score.isnot(None),
                ObservedPlayLog.confidence_score < READINESS_LOW_CONFIDENCE_EVENT_THRESHOLD,
            )
        )
    )).scalar() or 0

    avg_event_conf = float(avg_event_conf_raw) if avg_event_conf_raw is not None else None
    min_log_conf = float(min_log_conf_raw) if min_log_conf_raw is not None else None
    avg_log_conf = float(avg_log_conf_raw) if avg_log_conf_raw is not None else None

    parser_quality = ParserQualityStats(
        avg_event_confidence=avg_event_conf,
        min_log_confidence=min_log_conf,
        avg_log_confidence=avg_log_conf,
        unknown_event_count=unknown_event_count,
        low_confidence_event_count=low_confidence_event_count,
        low_confidence_threshold=READINESS_LOW_CONFIDENCE_EVENT_THRESHOLD,
        logs_below_ingestion_threshold=logs_below_threshold,
    )

    # ── Card resolution burden ────────────────────────────────────────────────
    card_mention_count = (await db.execute(select(func.count(ObservedCardMention.id)))).scalar() or 0
    resolved_count = (await db.execute(
        select(func.count(ObservedCardMention.id)).where(ObservedCardMention.resolution_status == "resolved")
    )).scalar() or 0
    ambiguous_count = (await db.execute(
        select(func.count(ObservedCardMention.id)).where(ObservedCardMention.resolution_status == "ambiguous")
    )).scalar() or 0
    unresolved_count = (await db.execute(
        select(func.count(ObservedCardMention.id)).where(ObservedCardMention.resolution_status == "unresolved")
    )).scalar() or 0
    critical_unresolved_count = (await db.execute(
        select(func.count(ObservedCardMention.id)).where(
            and_(
                ObservedCardMention.resolution_status == "unresolved",
                ObservedCardMention.mention_role.in_(list(_READINESS_CRITICAL_ROLES)),
            )
        )
    )).scalar() or 0

    top_ambiguous_rows = (await db.execute(
        select(ObservedCardMention.raw_name, func.count(ObservedCardMention.id).label("cnt"))
        .where(ObservedCardMention.resolution_status == "ambiguous")
        .group_by(ObservedCardMention.raw_name)
        .order_by(desc("cnt"))
        .limit(READINESS_TOP_N_LIMIT)
    )).fetchall()
    top_ambiguous = [row[0] for row in top_ambiguous_rows]

    top_unresolved_rows = (await db.execute(
        select(ObservedCardMention.raw_name, func.count(ObservedCardMention.id).label("cnt"))
        .where(ObservedCardMention.resolution_status == "unresolved")
        .group_by(ObservedCardMention.raw_name)
        .order_by(desc("cnt"))
        .limit(READINESS_TOP_N_LIMIT)
    )).fetchall()
    top_unresolved = [row[0] for row in top_unresolved_rows]

    card_resolution = CardResolutionStats(
        card_mention_count=card_mention_count,
        resolved_count=resolved_count,
        ambiguous_count=ambiguous_count,
        unresolved_count=unresolved_count,
        critical_unresolved_count=critical_unresolved_count,
        top_ambiguous=top_ambiguous,
        top_unresolved=top_unresolved,
    )

    # ── Memory quality ────────────────────────────────────────────────────────
    avg_memory_conf_raw = (await db.execute(
        select(func.avg(ObservedPlayMemoryItem.confidence_score))
    )).scalar()
    low_conf_memory_count = (await db.execute(
        select(func.count(ObservedPlayMemoryItem.id)).where(
            ObservedPlayMemoryItem.confidence_score < LOW_CONFIDENCE_THRESHOLD
        )
    )).scalar() or 0
    ambiguous_ref_count = (await db.execute(
        select(func.count(ObservedPlayMemoryItem.id)).where(
            or_(
                ObservedPlayMemoryItem.actor_resolution_status == "ambiguous",
                ObservedPlayMemoryItem.target_resolution_status == "ambiguous",
            )
        )
    )).scalar() or 0
    unresolved_ref_count = (await db.execute(
        select(func.count(ObservedPlayMemoryItem.id)).where(
            or_(
                ObservedPlayMemoryItem.actor_resolution_status == "unresolved",
                ObservedPlayMemoryItem.target_resolution_status == "unresolved",
            )
        )
    )).scalar() or 0
    memory_type_rows = (await db.execute(
        select(ObservedPlayMemoryItem.memory_type, func.count(ObservedPlayMemoryItem.id).label("cnt"))
        .group_by(ObservedPlayMemoryItem.memory_type)
        .order_by(desc("cnt"))
    )).fetchall()
    memory_type_counts = [{"memory_type": r[0], "count": r[1]} for r in memory_type_rows]

    avg_memory_conf = float(avg_memory_conf_raw) if avg_memory_conf_raw is not None else None

    memory_quality = MemoryQualityStats(
        avg_memory_confidence=avg_memory_conf,
        low_confidence_memory_item_count=low_conf_memory_count,
        ambiguous_reference_item_count=ambiguous_ref_count,
        unresolved_reference_item_count=unresolved_ref_count,
        memory_type_counts=memory_type_counts,
    )

    # ── Blockers, warnings, and recommendations ───────────────────────────────
    blockers: list[str] = []
    warnings: list[str] = []
    recommendations: list[str] = []

    if parsed_log_count == 0:
        blockers.append(
            "No logs have been parsed. Upload and parse logs before reviewing readiness."
        )
    if ingested_log_count == 0 and parsed_log_count > 0:
        blockers.append(
            "No logs have been ingested. Run memory ingestion before reviewing readiness."
        )
    if unknown_event_count > 0:
        blockers.append(
            f"{unknown_event_count} unknown event(s) detected. Parser must recognize all "
            "event types before the corpus is usable."
        )
    if low_confidence_event_count > 0:
        pct = READINESS_LOW_CONFIDENCE_EVENT_THRESHOLD
        blockers.append(
            f"{low_confidence_event_count} event(s) below {pct:.0%} confidence threshold. "
            "Investigate and re-parse affected logs."
        )
    if critical_unresolved_count > 0:
        blockers.append(
            f"{critical_unresolved_count} critical unresolved card mention(s) in "
            "actor/target/evolution roles. Add resolution rules before downstream use."
        )
    if failed_log_count > 0:
        blockers.append(
            f"{failed_log_count} log(s) failed to parse. Fix parser errors or remove failed logs."
        )

    if ambiguous_count > 0:
        warnings.append(
            f"{ambiguous_count} ambiguous card mention(s). Card-specific coaching may be "
            "inaccurate for these mentions."
        )
    if unresolved_count > 0 and critical_unresolved_count == 0:
        warnings.append(
            f"{unresolved_count} unresolved card mention(s) (non-critical). "
            "Consider adding resolution rules."
        )
    if low_conf_memory_count > 0:
        pct = LOW_CONFIDENCE_THRESHOLD
        warnings.append(
            f"{low_conf_memory_count} low-confidence memory item(s) (below {pct:.0%}). "
            "Review before downstream use."
        )
    if ambiguous_ref_count > 0:
        warnings.append(
            f"{ambiguous_ref_count} memory item(s) with ambiguous card references."
        )
    if unresolved_ref_count > 0:
        warnings.append(
            f"{unresolved_ref_count} memory item(s) with unresolved card references."
        )
    if log_count > 0 and (ingested_log_count / log_count) < READINESS_INGESTION_COVERAGE_THRESHOLD:
        coverage = ingested_log_count / log_count
        warnings.append(
            f"Ingestion coverage is {ingested_log_count}/{log_count} ({coverage:.0%}). "
            f"Below {READINESS_INGESTION_COVERAGE_THRESHOLD:.0%} threshold."
        )
    if avg_event_conf is not None and avg_event_conf < READINESS_AVG_EVENT_CONFIDENCE_THRESHOLD:
        warnings.append(
            f"Average event confidence ({avg_event_conf:.4f}) is below "
            f"{READINESS_AVG_EVENT_CONFIDENCE_THRESHOLD:.2f} threshold."
        )
    if avg_memory_conf is not None and avg_memory_conf < READINESS_AVG_MEMORY_CONFIDENCE_THRESHOLD:
        warnings.append(
            f"Average memory confidence ({avg_memory_conf:.4f}) is below "
            f"{READINESS_AVG_MEMORY_CONFIDENCE_THRESHOLD:.2f} threshold."
        )

    if ambiguous_count > 0 or (unresolved_count > 0 and critical_unresolved_count == 0):
        recommendations.append(
            "Resolve high-frequency ambiguous or unresolved card mentions before using "
            "this corpus for card-specific coaching."
        )
    if low_conf_memory_count > 0:
        recommendations.append("Review low-confidence memory items before downstream usage.")
    not_ingested = log_count - ingested_log_count
    if not_ingested > 0 and parsed_log_count > 0:
        recommendations.append(
            f"Ingest {not_ingested} eligible parsed log(s) to improve coverage."
        )
    if log_count == 0:
        recommendations.append(
            "Upload observed-play logs to begin corpus evaluation."
        )

    # ── Verdict ───────────────────────────────────────────────────────────────
    if blockers:
        verdict = "not_ready"
    elif warnings:
        verdict = "needs_review"
    else:
        verdict = "ready"

    # ── Readiness score (0–100) ───────────────────────────────────────────────
    # Parser quality: 35 pts
    parser_pts = 0.0
    parser_pts += 10.0 if unknown_event_count == 0 else 0.0
    parser_pts += 10.0 if low_confidence_event_count == 0 else 0.0
    if avg_event_conf is not None:
        parser_pts += 15.0 * max(0.0, min(1.0, avg_event_conf))

    # Ingestion coverage: 25 pts
    ingestion_pts = 0.0
    if log_count > 0:
        ingestion_pts += 20.0 * min(1.0, ingested_log_count / log_count)
    ingestion_pts += 5.0 if failed_log_count == 0 else 0.0

    # Card resolution: 20 pts
    resolution_pts = 0.0
    resolution_pts += 10.0 if critical_unresolved_count == 0 else 0.0
    if card_mention_count > 0:
        unresolved_ambiguous = ambiguous_count + unresolved_count
        resolution_ratio = max(0.0, 1.0 - unresolved_ambiguous / card_mention_count)
        resolution_pts += 10.0 * resolution_ratio
    else:
        resolution_pts += 10.0  # no mentions → no burden

    # Memory quality: 20 pts
    memory_pts = 0.0
    if avg_memory_conf is not None:
        memory_pts += 10.0 * max(0.0, min(1.0, avg_memory_conf))
    if memory_item_count > 0:
        low_conf_ratio = low_conf_memory_count / memory_item_count
        memory_pts += 10.0 * max(0.0, 1.0 - low_conf_ratio)

    readiness_score = round(parser_pts + ingestion_pts + resolution_pts + memory_pts, 2)

    return CorpusReadinessReport(
        verdict=verdict,
        readiness_score=readiness_score,
        generated_at=datetime.now(timezone.utc).isoformat(),
        review_only=True,
        corpus=corpus,
        parser_quality=parser_quality,
        card_resolution=card_resolution,
        memory_quality=memory_quality,
        blockers=blockers,
        warnings=warnings,
        recommendations=recommendations,
    )


def build_coach_evidence_filter(
    q,
    *,
    card_name: Optional[str],
    memory_type: Optional[str],
    action_name: Optional[str],
    player_alias: Optional[str],
    min_confidence: float,
):
    """Apply standard coach-evidence WHERE clauses to *q* and return the filtered query.

    Always excludes items whose actor or target card reference is unresolved,
    and items whose confidence falls below *min_confidence*.
    """
    q = q.where(ObservedPlayMemoryItem.confidence_score >= min_confidence)
    # Exclude unresolved actor references (null status is acceptable — it means
    # no card was mentioned in that slot, not that resolution failed).
    q = q.where(
        or_(
            ObservedPlayMemoryItem.actor_resolution_status.is_(None),
            ObservedPlayMemoryItem.actor_resolution_status != "unresolved",
        )
    )
    q = q.where(
        or_(
            ObservedPlayMemoryItem.target_resolution_status.is_(None),
            ObservedPlayMemoryItem.target_resolution_status != "unresolved",
        )
    )
    if memory_type:
        q = q.where(ObservedPlayMemoryItem.memory_type == memory_type)
    if action_name:
        q = q.where(ObservedPlayMemoryItem.action_name.ilike(f"%{action_name}%"))
    if player_alias:
        q = q.where(ObservedPlayMemoryItem.player_alias == player_alias)
    if card_name:
        ilike_val = f"%{card_name}%"
        q = q.where(
            ObservedPlayMemoryItem.actor_card_raw.ilike(ilike_val)
            | ObservedPlayMemoryItem.target_card_raw.ilike(ilike_val)
            | ObservedPlayMemoryItem.related_card_raw.ilike(ilike_val)
        )
    return q
