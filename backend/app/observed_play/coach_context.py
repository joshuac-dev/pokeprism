"""Phase 6.1 — Feature-flagged Coach context builder for observed-play evidence.

This module:
- Reads the ``OBSERVED_PLAY_MEMORY_ENABLED`` feature flag from config.
- Checks corpus readiness (via the shared readiness_service).
- Fetches a bounded set of high-confidence, resolved observed-play evidence.
- Formats a deterministic prompt block suitable for inclusion in a Coach prompt.
- Returns a preview object so callers can inspect exactly what would be injected.

**Advisory only.** Observed memory must never override card rules text, current
game state, simulator results, or card database facts.  It must never drive
AI Player, simulator runtime, deck builder, pgvector, Neo4j, match_events, or
card_performance decisions.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

from sqlalchemy import desc, select

from app.config import settings
from app.db.models import ObservedPlayLog, ObservedPlayMemoryItem
from app.observed_play.readiness_service import (
    build_coach_evidence_filter,
    compute_corpus_readiness,
)
from app.observed_play.schemas import (
    ObservedPlayCoachContextPreview,
    ObservedPlayEvidencePromptItem,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_REVIEW_ONLY_HEADER = """\
OBSERVED PLAY EVIDENCE — REVIEW ONLY
These examples are from imported PTCGL battle logs. They are advisory context \
only and must not override rules text, current game state, simulator results, \
or card database facts.

Use observed-play evidence only as supporting examples.
Do not infer card rules from observed logs if card database/rules text disagrees.
Cite observed evidence IDs when referencing this evidence.
If evidence is sparse or not relevant, say so.
"""


def _format_evidence_prompt_block(
    *,
    verdict: str,
    readiness_score: float,
    filters_applied: dict,
    items: list[ObservedPlayEvidencePromptItem],
) -> str:
    """Render the evidence block that will be injected into the Coach prompt."""
    lines: list[str] = [_REVIEW_ONLY_HEADER]

    score_str = f"{readiness_score:.2f}/100" if readiness_score is not None else "n/a"
    lines.append(f"Corpus readiness: {verdict} (score {score_str})")

    if filters_applied:
        filter_parts = [f"{k}={v}" for k, v in filters_applied.items() if v is not None]
        lines.append(f"Filters used: {', '.join(filter_parts)}" if filter_parts else "Filters used: (none)")
    lines.append("")

    if not items:
        lines.append("No matching observed-play evidence found for the supplied filters.")
        return "\n".join(lines)

    lines.append("Evidence:")
    for i, item in enumerate(items, start=1):
        lines.append(
            f"{i}. [log={item.log_id}, event_id={item.memory_item_id}, "
            f"turn={item.turn_number}, confidence={item.confidence_score:.2f}]"
        )
        lines.append(f"   Type: {item.memory_type}")
        if item.actor_card_raw:
            lines.append(f"   Actor: {item.actor_card_raw}")
        if item.target_card_raw:
            lines.append(f"   Target: {item.target_card_raw}")
        if item.action_name:
            lines.append(f"   Action: {item.action_name}")
        if item.damage is not None:
            lines.append(f"   Damage: {item.damage}")
        lines.append(f'   Source: "{item.source_raw_line}"')
        lines.append("")

    return "\n".join(lines)


async def build_coach_context_preview(
    db: AsyncSession,
    *,
    card_name: Optional[str] = None,
    action_name: Optional[str] = None,
    memory_type: Optional[str] = None,
    player_alias: Optional[str] = None,
    min_confidence: Optional[float] = None,
    limit: Optional[int] = None,
) -> ObservedPlayCoachContextPreview:
    """Build and return the Coach context preview for observed-play evidence.

    This is the main Phase 6.1 entry point, called by:
    - ``GET /api/observed-play/coach-context-preview`` (debug endpoint)
    - ``CoachAnalyst.analyze_and_mutate`` (when flag is enabled)

    Never mutates the database.
    """
    # ── Resolve effective limits from config ──────────────────────────────────
    effective_limit = min(
        limit if limit is not None else settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE,
        settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE,
    )
    effective_min_conf = (
        min_confidence if min_confidence is not None
        else settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE
    )

    filters_applied: dict = {
        "card_name": card_name,
        "action_name": action_name,
        "memory_type": memory_type,
        "player_alias": player_alias,
        "min_confidence": effective_min_conf,
        "limit": effective_limit,
    }

    # ── Feature flag check ────────────────────────────────────────────────────
    if not settings.OBSERVED_PLAY_MEMORY_ENABLED:
        return ObservedPlayCoachContextPreview(
            enabled=False,
            readiness_verdict=None,
            readiness_score=None,
            would_inject=False,
            reason="OBSERVED_PLAY_MEMORY_ENABLED is false",
            prompt_block="",
            evidence_count=0,
            evidence_ids=[],
            warnings=[],
            filters_applied=filters_applied,
        )

    # ── Corpus readiness gate ─────────────────────────────────────────────────
    readiness = await compute_corpus_readiness(db)
    warnings: list[str] = []

    if readiness.verdict == "not_ready":
        blocker_summary = "; ".join(readiness.blockers[:3]) if readiness.blockers else "Corpus is not ready."
        return ObservedPlayCoachContextPreview(
            enabled=True,
            readiness_verdict=readiness.verdict,
            readiness_score=readiness.readiness_score,
            would_inject=False,
            reason=f"Corpus is not_ready — injection blocked. Blockers: {blocker_summary}",
            prompt_block="",
            evidence_count=0,
            evidence_ids=[],
            warnings=list(readiness.blockers),
            filters_applied=filters_applied,
        )

    if readiness.verdict == "needs_review":
        warnings = list(readiness.warnings)

    # ── Fetch evidence ────────────────────────────────────────────────────────
    evidence_q = build_coach_evidence_filter(
        select(ObservedPlayMemoryItem, ObservedPlayLog.id.label("log_uuid")).join(
            ObservedPlayLog,
            ObservedPlayMemoryItem.observed_play_log_id == ObservedPlayLog.id,
        ),
        card_name=card_name,
        memory_type=memory_type,
        action_name=action_name,
        player_alias=player_alias,
        min_confidence=effective_min_conf,
    ).order_by(
        ObservedPlayMemoryItem.confidence_score.desc(),
        ObservedPlayMemoryItem.created_at.desc(),
    ).limit(effective_limit)

    rows = (await db.execute(evidence_q)).all()

    prompt_items: list[ObservedPlayEvidencePromptItem] = []
    evidence_ids: list[str] = []
    for row in rows:
        item: ObservedPlayMemoryItem = row[0]
        mid = str(item.id)
        evidence_ids.append(mid)
        prompt_items.append(ObservedPlayEvidencePromptItem(
            memory_item_id=mid,
            log_id=str(item.observed_play_log_id),
            turn_number=item.turn_number,
            confidence_score=item.confidence_score,
            memory_type=item.memory_type,
            actor_card_raw=item.actor_card_raw,
            target_card_raw=item.target_card_raw,
            action_name=item.action_name,
            damage=item.damage,
            source_raw_line=item.source_raw_line,
        ))

    prompt_block = _format_evidence_prompt_block(
        verdict=readiness.verdict,
        readiness_score=readiness.readiness_score,
        filters_applied={k: v for k, v in filters_applied.items() if v is not None},
        items=prompt_items,
    )

    return ObservedPlayCoachContextPreview(
        enabled=True,
        readiness_verdict=readiness.verdict,
        readiness_score=readiness.readiness_score,
        would_inject=True,
        reason=(
            f"OBSERVED_PLAY_MEMORY_ENABLED is true; corpus is {readiness.verdict}"
        ),
        prompt_block=prompt_block,
        evidence_count=len(prompt_items),
        evidence_ids=evidence_ids,
        warnings=warnings,
        filters_applied=filters_applied,
    )
