"""Phase 6.1/6.2a — Feature-flagged Coach context builder for observed-play evidence.

This module:
- Reads the ``OBSERVED_PLAY_MEMORY_ENABLED`` feature flag from config.
- Checks corpus readiness (via the shared readiness_service).
- Fetches a bounded set of high-confidence, resolved observed-play evidence.
- Formats a deterministic prompt block suitable for inclusion in a Coach prompt.
- Returns a preview object so callers can inspect exactly what would be injected.

Phase 6.2a adds tiered retrieval: when deck/candidate card context is supplied,
evidence is ranked by deck overlap (Tier 1 = exact card-ID match, Tier 2 = ILIKE
name match, Tier 3 = global fallback opt-in).  Without deck context, Phase 6.1
global-top-N behaviour is preserved exactly.

**Advisory only.** Observed memory must never override card rules text, current
game state, simulator results, or card database facts.  It must never drive
AI Player, simulator runtime, deck builder, pgvector, Neo4j, match_events, or
card_performance decisions.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field as dc_field
from typing import TYPE_CHECKING, Optional

from sqlalchemy import or_, select

from app.config import settings
from app.db.models import ObservedPlayLog, ObservedPlayMemoryItem
from app.observed_play.archetype_labels import (
    CardSignal,
    ObservedCardSignal,
    infer_deck_labels_from_cards,
    infer_observed_log_labels_from_signals,
)
from app.observed_play.readiness_service import (
    build_coach_evidence_filter,
    compute_corpus_readiness,
)
from app.observed_play.schemas import (
    ArchetypeLabel,
    EvidenceExclusionSummary,
    EvidenceSelectionDetail,
    ObservedPlayCoachContextPreview,
    ObservedPlayEvidencePromptItem,
    ObservedLogArchetypeLabelPreview,
    ObservedPlayRetrievalMetadata,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Tiered retrieval constants ─────────────────────────────────────────────────

_MAX_ITEMS_PER_LOG = 2
_TIER_BONUS = {1: 0.20, 2: 0.10, 3: 0.00}
_OUTCOME_BONUS = 0.05
_SOURCE_REP_PENALTY = 0.03
_LABEL_STRATEGY = "archetype_label_boost_v1"
_LABEL_BOOST_CAP = 0.10


@dataclass
class _RawCandidate:
    """Internal structure for a candidate evidence item before final selection."""
    item: ObservedPlayMemoryItem
    log_id: str
    tier: int
    matched_card_ids: list[str] = dc_field(default_factory=list)
    matched_card_names: list[str] = dc_field(default_factory=list)
    matched_field: str | None = None
    is_deck_match: bool = False
    match_source: str | None = None
    from_winning_game: bool | None = None
    base_score: float = 0.0
    label_boost: float = 0.0
    matched_label_keys: list[str] = dc_field(default_factory=list)
    matched_label_names: list[str] = dc_field(default_factory=list)
    matched_label_types: list[str] = dc_field(default_factory=list)
    source_log_labels: list[ArchetypeLabel] = dc_field(default_factory=list)
    label_match_reason: str | None = None

    @property
    def final_score(self) -> float:
        return self.base_score + self.label_boost

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


def _determine_winning_game(
    winner_alias: str | None,
    self_player_index: int | None,
    player_1_alias: str | None,
    player_2_alias: str | None,
) -> bool | None:
    """Return True if the log was won by self, False if lost, None if undetermined."""
    if winner_alias is None or self_player_index is None:
        return None
    if self_player_index == 1:
        if player_1_alias and winner_alias == player_1_alias:
            return True
        if player_1_alias and winner_alias != player_1_alias:
            return False
    if self_player_index == 2:
        if player_2_alias and winner_alias == player_2_alias:
            return True
        if player_2_alias and winner_alias != player_2_alias:
            return False
    return None


def _labels_from_card_context(
    *,
    context_id: str,
    names: list[str],
    ids: list[str],
) -> list[ArchetypeLabel]:
    """Infer advisory labels from in-memory card context without persistence."""
    signals: list[CardSignal] = []
    for idx, name in enumerate(names):
        if not name:
            continue
        signals.append(CardSignal(
            card_id=ids[idx] if idx < len(ids) else None,
            name=name,
            count=1,
        ))
    if not signals:
        return []
    return infer_deck_labels_from_cards(context_id, None, signals).labels


def _source_log_label_cache(candidates: list[_RawCandidate]) -> dict[str, ObservedLogArchetypeLabelPreview]:
    """Infer observed-log labels from the already-fetched candidate pool only.

    Phase 7.1d intentionally does not broaden the retrieval candidate pool.
    """
    signals_by_log: dict[str, list[ObservedCardSignal]] = defaultdict(list)
    for cand in candidates:
        item = cand.item
        raw_player = getattr(item, "player_alias", None)
        player = raw_player if isinstance(raw_player, str) and raw_player else "unknown"
        for raw_name, card_id, status in (
            (item.actor_card_raw, item.actor_card_def_id, item.actor_resolution_status),
            (item.target_card_raw, item.target_card_def_id, item.target_resolution_status),
            (item.related_card_raw, item.related_card_def_id, getattr(item, "related_resolution_status", None)),
        ):
            if raw_name or card_id:
                signals_by_log[cand.log_id].append(ObservedCardSignal(
                    player_alias=player,
                    card_id=card_id,
                    name=raw_name,
                    resolution_status=status,
                    memory_item_id=str(item.id),
                    action_name=item.action_name,
                    memory_type=item.memory_type,
                    source_event_type=getattr(item, "source_event_type", None),
                ))

    return {
        log_id: infer_observed_log_labels_from_signals(log_id, signals)
        for log_id, signals in signals_by_log.items()
    }


def _labels_for_candidate(
    cand: _RawCandidate,
    label_cache: dict[str, ObservedLogArchetypeLabelPreview],
) -> list[ArchetypeLabel]:
    preview = label_cache.get(cand.log_id)
    if preview is None:
        return []
    raw_player = getattr(cand.item, "player_alias", None)
    player_alias = raw_player if isinstance(raw_player, str) and raw_player else None
    if player_alias and player_alias in preview.labels_by_player:
        labels = list(preview.labels_by_player[player_alias])
    else:
        labels = [
            label
            for group in preview.labels_by_player.values()
            for label in group
        ]
    labels.extend(preview.global_labels)
    return labels


def _boost_for_label_match(
    current_label: ArchetypeLabel,
    source_label: ArchetypeLabel,
    *,
    source_ambiguous: bool,
) -> float:
    if source_ambiguous or min(current_label.confidence, source_label.confidence) < 0.60:
        return 0.02
    if current_label.label_type == "archetype" and source_label.label_type == "archetype":
        return 0.08
    if current_label.label_type in ("package", "strategy") or source_label.label_type in ("package", "strategy"):
        return 0.04
    return 0.02


def _apply_label_boosts(
    candidates: list[_RawCandidate],
    *,
    deck_labels: list[ArchetypeLabel],
    candidate_labels: list[ArchetypeLabel],
) -> None:
    """Apply bounded label boosts to existing candidates only."""
    current_labels = deck_labels + candidate_labels
    if not candidates or not current_labels:
        return

    current_by_key = {label.canonical_key: label for label in current_labels}
    source_cache = _source_log_label_cache(candidates)

    for cand in candidates:
        source_preview = source_cache.get(cand.log_id)
        source_labels = _labels_for_candidate(cand, source_cache)
        if not source_labels:
            continue

        boost = 0.0
        matched_keys: list[str] = []
        matched_names: list[str] = []
        matched_types: list[str] = []
        matched_source_labels: list[ArchetypeLabel] = []
        reasons: list[str] = []

        for source_label in source_labels:
            current_label = current_by_key.get(source_label.canonical_key)
            if current_label is None:
                continue
            boost += _boost_for_label_match(
                current_label,
                source_label,
                source_ambiguous=bool(getattr(source_preview, "ambiguous", False)),
            )
            if source_label.canonical_key not in matched_keys:
                matched_keys.append(source_label.canonical_key)
                matched_names.append(source_label.label)
                matched_types.append(source_label.label_type)
                matched_source_labels.append(source_label)
                reasons.append(
                    f"Matched current {current_label.label_type} label {current_label.label} "
                    f"to source log/player label {source_label.label}."
                )

        cand.label_boost = round(min(_LABEL_BOOST_CAP, boost), 4)
        cand.matched_label_keys = matched_keys
        cand.matched_label_names = matched_names
        cand.matched_label_types = matched_types
        cand.source_log_labels = matched_source_labels
        cand.label_match_reason = " ".join(reasons) if reasons and cand.label_boost > 0 else None


def _format_evidence_prompt_block(
    *,
    verdict: str,
    readiness_score: float,
    filters_applied: dict,
    items: list[ObservedPlayEvidencePromptItem],
    relevance_details: dict[str, EvidenceSelectionDetail] | None = None,
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
        if relevance_details and item.memory_item_id in relevance_details:
            detail = relevance_details[item.memory_item_id]
            if detail.matched_reason:
                lines.append(f"   Relevance: {detail.matched_reason} (tier {detail.tier}).")
        lines.append("")

    return "\n".join(lines)


async def _select_tiered_evidence(
    db: AsyncSession,
    *,
    deck_card_ids: list[str],
    deck_card_names: list[str],
    candidate_card_ids: list[str],
    candidate_card_names: list[str],
    min_confidence: float,
    effective_limit: int,
    allow_fallback: bool,
    card_id_to_name: dict[str, str] | None = None,
    deck_labels: list[ArchetypeLabel] | None = None,
    candidate_labels: list[ArchetypeLabel] | None = None,
) -> tuple[list[_RawCandidate], EvidenceExclusionSummary]:
    """Tiered evidence retrieval.

    Tier 1: exact resolved card-ID match (actor/target/related_card_def_id)
    Tier 2: ILIKE name match (actor/target/related_card_raw)
    Tier 3: global fallback — only when allow_fallback=True

    Source diversity cap: max _MAX_ITEMS_PER_LOG per observed_play_log_id.
    Win/loss: +0.05 tiebreaker bonus, never a hard gate.
    Deck-card matches sorted before candidate-card matches at equal tier/score.

    Does not write to any observed-play tables.
    """
    id_to_name = card_id_to_name or {}
    deck_id_set = set(deck_card_ids)
    candidate_id_set = set(candidate_card_ids)
    deck_name_set = {n.lower() for n in deck_card_names if n}
    candidate_name_set = {n.lower() for n in candidate_card_names if n}
    all_card_ids = list(dict.fromkeys(deck_card_ids + candidate_card_ids))
    all_names_raw = list(dict.fromkeys(deck_card_names + candidate_card_names))
    valid_names = [n for n in all_names_raw if n and len(n.strip()) > 2]

    exclusion = EvidenceExclusionSummary()
    tier1_item_ids: list = []

    def _base_q():
        return (
            select(
                ObservedPlayMemoryItem,
                ObservedPlayLog.winner_alias,
                ObservedPlayLog.self_player_index,
                ObservedPlayLog.player_1_alias,
                ObservedPlayLog.player_2_alias,
            )
            .join(ObservedPlayLog, ObservedPlayMemoryItem.observed_play_log_id == ObservedPlayLog.id)
            .where(ObservedPlayMemoryItem.confidence_score >= min_confidence)
            .where(
                or_(
                    ObservedPlayMemoryItem.actor_resolution_status.is_(None),
                    ObservedPlayMemoryItem.actor_resolution_status != "unresolved",
                )
            )
            .where(
                or_(
                    ObservedPlayMemoryItem.target_resolution_status.is_(None),
                    ObservedPlayMemoryItem.target_resolution_status != "unresolved",
                )
            )
        )

    raw_candidates: list[_RawCandidate] = []

    # ── Tier 1: exact resolved card-ID match ──────────────────────────────────
    if all_card_ids:
        tier1_q = _base_q().where(
            or_(
                ObservedPlayMemoryItem.actor_card_def_id.in_(all_card_ids),
                ObservedPlayMemoryItem.target_card_def_id.in_(all_card_ids),
                ObservedPlayMemoryItem.related_card_def_id.in_(all_card_ids),
            )
        ).order_by(ObservedPlayMemoryItem.confidence_score.desc())

        for row in (await db.execute(tier1_q)).all():
            item, winner_alias, self_idx, p1, p2 = row[0], row[1], row[2], row[3], row[4]
            tier1_item_ids.append(item.id)

            matched_ids: list[str] = []
            matched_names: list[str] = []
            matched_field: str | None = None
            for fld, val in [
                ("actor_card_def_id", item.actor_card_def_id),
                ("target_card_def_id", item.target_card_def_id),
                ("related_card_def_id", item.related_card_def_id),
            ]:
                if val and val in deck_id_set or (val and val in candidate_id_set):
                    if val not in matched_ids:
                        matched_ids.append(val)
                    name = id_to_name.get(val)
                    if name and name not in matched_names:
                        matched_names.append(name)
                    if matched_field is None:
                        matched_field = fld

            is_deck_match = any(cid in deck_id_set for cid in matched_ids)
            match_source = "deck_card" if is_deck_match else "candidate_card"

            from_win = _determine_winning_game(winner_alias, self_idx, p1, p2)
            outcome_bonus = _OUTCOME_BONUS if from_win else 0.0
            base_score = min(1.0, item.confidence_score + _TIER_BONUS[1] + outcome_bonus)

            raw_candidates.append(_RawCandidate(
                item=item,
                log_id=str(item.observed_play_log_id),
                tier=1,
                matched_card_ids=matched_ids,
                matched_card_names=matched_names,
                matched_field=matched_field,
                is_deck_match=is_deck_match,
                match_source=match_source,
                from_winning_game=from_win,
                base_score=base_score,
            ))

    # ── Tier 2: ILIKE name-based match ────────────────────────────────────────
    if valid_names:
        name_conds = or_(*[
            or_(
                ObservedPlayMemoryItem.actor_card_raw.ilike(f"%{n}%"),
                ObservedPlayMemoryItem.target_card_raw.ilike(f"%{n}%"),
                ObservedPlayMemoryItem.related_card_raw.ilike(f"%{n}%"),
            )
            for n in valid_names
        ])
        tier2_q = _base_q().where(name_conds)
        if tier1_item_ids:
            tier2_q = tier2_q.where(ObservedPlayMemoryItem.id.not_in(tier1_item_ids))
        tier2_q = tier2_q.order_by(ObservedPlayMemoryItem.confidence_score.desc())

        for row in (await db.execute(tier2_q)).all():
            item, winner_alias, self_idx, p1, p2 = row[0], row[1], row[2], row[3], row[4]

            matched_names: list[str] = []
            matched_field: str | None = None
            is_deck_name_match = False
            for n in valid_names:
                n_lower = n.lower()
                for fld, raw in [
                    ("actor_card_raw", item.actor_card_raw),
                    ("target_card_raw", item.target_card_raw),
                    ("related_card_raw", item.related_card_raw),
                ]:
                    if raw and n_lower in raw.lower():
                        if n not in matched_names:
                            matched_names.append(n)
                        if matched_field is None:
                            matched_field = fld
                        if n_lower in deck_name_set:
                            is_deck_name_match = True

            match_source = "name_fallback_deck" if is_deck_name_match else "name_fallback_candidate"

            from_win = _determine_winning_game(winner_alias, self_idx, p1, p2)
            outcome_bonus = _OUTCOME_BONUS if from_win else 0.0
            base_score = min(1.0, item.confidence_score + _TIER_BONUS[2] + outcome_bonus)

            raw_candidates.append(_RawCandidate(
                item=item,
                log_id=str(item.observed_play_log_id),
                tier=2,
                matched_card_names=matched_names[:3],
                matched_field=matched_field,
                is_deck_match=is_deck_name_match,
                match_source=match_source,
                from_winning_game=from_win,
                base_score=base_score,
            ))

    # ── Tier 3: global fallback (opt-in only) ─────────────────────────────────
    if allow_fallback and len(raw_candidates) < effective_limit:
        all_tier12_ids = tier1_item_ids + [c.item.id for c in raw_candidates if c.tier == 2]
        tier3_q = _base_q().order_by(
            ObservedPlayMemoryItem.confidence_score.desc(),
            ObservedPlayMemoryItem.created_at.desc(),
        )
        if all_tier12_ids:
            tier3_q = tier3_q.where(ObservedPlayMemoryItem.id.not_in(all_tier12_ids))

        for row in (await db.execute(tier3_q)).all():
            item, winner_alias, self_idx, p1, p2 = row[0], row[1], row[2], row[3], row[4]
            from_win = _determine_winning_game(winner_alias, self_idx, p1, p2)
            outcome_bonus = _OUTCOME_BONUS if from_win else 0.0
            base_score = min(1.0, item.confidence_score + _TIER_BONUS[3] + outcome_bonus)

            raw_candidates.append(_RawCandidate(
                item=item,
                log_id=str(item.observed_play_log_id),
                tier=3,
                match_source="global_fallback",
                from_winning_game=from_win,
                base_score=base_score,
            ))

    # ── Label boost: bounded re-ranking signal within existing candidates only
    effective_deck_labels = deck_labels
    if effective_deck_labels is None:
        effective_deck_labels = _labels_from_card_context(
            context_id="current-deck",
            names=deck_card_names,
            ids=deck_card_ids,
        )
    effective_candidate_labels = candidate_labels
    if effective_candidate_labels is None:
        effective_candidate_labels = _labels_from_card_context(
            context_id="candidate-cards",
            names=candidate_card_names,
            ids=candidate_card_ids,
        )

    _apply_label_boosts(
        raw_candidates,
        deck_labels=effective_deck_labels,
        candidate_labels=effective_candidate_labels,
    )

    # ── Sort: tier first, then deck matches, then final score descending ──────
    raw_candidates.sort(key=lambda c: (c.tier, not c.is_deck_match, -c.final_score))

    # ── Source diversity cap ───────────────────────────────────────────────────
    log_counts: dict[str, int] = defaultdict(int)
    selected: list[_RawCandidate] = []
    source_cap_excluded = 0

    for cand in raw_candidates:
        if log_counts[cand.log_id] < _MAX_ITEMS_PER_LOG:
            if log_counts[cand.log_id] == 1:
                # Apply source repetition penalty for 2nd item from same log
                cand.base_score = max(0.0, cand.base_score - _SOURCE_REP_PENALTY)
            log_counts[cand.log_id] += 1
            selected.append(cand)
        else:
            source_cap_excluded += 1

        if len(selected) >= effective_limit:
            break

    exclusion.source_cap_excluded = source_cap_excluded
    return selected, exclusion


async def build_coach_context_preview(
    db: AsyncSession,
    *,
    card_name: Optional[str] = None,
    action_name: Optional[str] = None,
    memory_type: Optional[str] = None,
    player_alias: Optional[str] = None,
    min_confidence: Optional[float] = None,
    limit: Optional[int] = None,
    # Phase 6.2a — deck context for tiered retrieval
    deck_card_ids: list[str] | None = None,
    deck_card_names: list[str] | None = None,
    candidate_card_ids: list[str] | None = None,
    candidate_card_names: list[str] | None = None,
    allow_fallback: bool = False,
    include_relevance_hints: bool = True,
    card_id_to_name: dict[str, str] | None = None,
) -> ObservedPlayCoachContextPreview:
    """Build and return the Coach context preview for observed-play evidence.

    When deck_card_ids / deck_card_names / candidate_card_ids / candidate_card_names
    are supplied, tiered retrieval (Phase 6.2a) is used instead of the global
    top-N path (Phase 6.1).  Calling with no deck context preserves Phase 6.1
    behavior exactly.

    This is the main entry point, called by:
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

    # ── Evidence retrieval: tiered path or legacy (Phase 6.1) path ───────────
    use_tiered = any(v is not None for v in [
        deck_card_ids, deck_card_names, candidate_card_ids, candidate_card_names
    ])

    if use_tiered:
        return await _build_tiered_preview(
            db,
            readiness=readiness,
            warnings=warnings,
            filters_applied=filters_applied,
            deck_card_ids=deck_card_ids or [],
            deck_card_names=deck_card_names or [],
            candidate_card_ids=candidate_card_ids or [],
            candidate_card_names=candidate_card_names or [],
            effective_min_conf=effective_min_conf,
            effective_limit=effective_limit,
            allow_fallback=allow_fallback,
            include_relevance_hints=include_relevance_hints,
            card_id_to_name=card_id_to_name or {},
        )

    # ── Legacy Phase 6.1 path ────────────────────────────────────────────────
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


async def _build_tiered_preview(
    db: AsyncSession,
    *,
    readiness,
    warnings: list[str],
    filters_applied: dict,
    deck_card_ids: list[str],
    deck_card_names: list[str],
    candidate_card_ids: list[str],
    candidate_card_names: list[str],
    effective_min_conf: float,
    effective_limit: int,
    allow_fallback: bool,
    include_relevance_hints: bool,
    card_id_to_name: dict[str, str] | None = None,
) -> ObservedPlayCoachContextPreview:
    """Tiered retrieval path for Phase 6.2a."""
    id_to_name = card_id_to_name or {}

    # Deduplicate before storage and retrieval
    unique_deck_ids = list(dict.fromkeys(deck_card_ids))
    unique_deck_names = list(dict.fromkeys(deck_card_names))
    unique_candidate_ids = list(dict.fromkeys(candidate_card_ids))
    unique_candidate_names = list(dict.fromkeys(candidate_card_names))
    deck_labels = _labels_from_card_context(
        context_id="current-deck",
        names=unique_deck_names,
        ids=unique_deck_ids,
    )
    candidate_labels = _labels_from_card_context(
        context_id="candidate-cards",
        names=unique_candidate_names,
        ids=unique_candidate_ids,
    )

    selected_candidates, exclusion = await _select_tiered_evidence(
        db,
        deck_card_ids=unique_deck_ids,
        deck_card_names=unique_deck_names,
        candidate_card_ids=unique_candidate_ids,
        candidate_card_names=unique_candidate_names,
        min_confidence=effective_min_conf,
        effective_limit=effective_limit,
        allow_fallback=allow_fallback,
        card_id_to_name=id_to_name,
        deck_labels=deck_labels,
        candidate_labels=candidate_labels,
    )

    no_evidence = not selected_candidates and not allow_fallback

    prompt_items: list[ObservedPlayEvidencePromptItem] = []
    evidence_ids: list[str] = []
    evidence_details: list[EvidenceSelectionDetail] = []
    relevance_details: dict[str, EvidenceSelectionDetail] = {}

    for cand in selected_candidates:
        item = cand.item
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

        # Build matched_reason: "<match_source> <card_name> matched <field>"
        if cand.matched_card_ids:
            cid = cand.matched_card_ids[0]
            card_label = id_to_name.get(cid, cid)
            matched_reason = (
                f"{cand.match_source or 'card'} {card_label} matched {cand.matched_field}"
            )
        elif cand.matched_card_names:
            card_label = cand.matched_card_names[0]
            matched_reason = (
                f"{cand.match_source or 'card'} {card_label} matched {cand.matched_field}"
            )
        elif cand.tier == 3:
            matched_reason = "global fallback (no deck overlap)"
        else:
            matched_reason = None

        detail = EvidenceSelectionDetail(
            memory_item_id=mid,
            relevance_score=round(cand.final_score, 4),
            base_relevance_score=round(cand.base_score, 4),
            label_boost=round(cand.label_boost, 4),
            final_relevance_score=round(cand.final_score, 4),
            tier=cand.tier,
            match_source=cand.match_source,
            matched_card_ids=cand.matched_card_ids,
            matched_card_names=cand.matched_card_names,
            matched_field=cand.matched_field,
            matched_reason=matched_reason,
            matched_label_keys=cand.matched_label_keys,
            matched_label_names=cand.matched_label_names,
            matched_label_types=cand.matched_label_types,
            source_log_labels=cand.source_log_labels,
            label_match_reason=cand.label_match_reason,
            source_log_id=cand.log_id,
            from_winning_game=cand.from_winning_game,
        )
        evidence_details.append(detail)
        relevance_details[mid] = detail

    retrieval_metadata = ObservedPlayRetrievalMetadata(
        strategy="deck_overlap_v1",
        label_strategy=_LABEL_STRATEGY,
        label_ranking_enabled=True,
        deck_card_ids=unique_deck_ids,
        deck_card_names=unique_deck_names,
        candidate_card_ids=unique_candidate_ids,
        candidate_card_names=unique_candidate_names,
        deck_labels=deck_labels,
        candidate_labels=candidate_labels,
        label_boost_cap=_LABEL_BOOST_CAP,
        label_boost_applied_count=sum(1 for cand in selected_candidates if cand.label_boost > 0),
        allow_fallback=allow_fallback,
        max_items_per_log=_MAX_ITEMS_PER_LOG,
        no_relevant_evidence=no_evidence,
        evidence_selected=evidence_details,
        excluded_summary=exclusion,
    )

    if no_evidence:
        return ObservedPlayCoachContextPreview(
            enabled=True,
            readiness_verdict=readiness.verdict,
            readiness_score=readiness.readiness_score,
            would_inject=False,
            no_relevant_evidence=True,
            reason="no relevant observed-play evidence found for current deck",
            prompt_block="",
            evidence_count=0,
            evidence_ids=[],
            warnings=warnings,
            filters_applied=filters_applied,
            retrieval_metadata=retrieval_metadata,
        )

    prompt_block = _format_evidence_prompt_block(
        verdict=readiness.verdict,
        readiness_score=readiness.readiness_score,
        filters_applied={k: v for k, v in filters_applied.items() if v is not None},
        items=prompt_items,
        relevance_details=relevance_details if include_relevance_hints else None,
    )

    return ObservedPlayCoachContextPreview(
        enabled=True,
        readiness_verdict=readiness.verdict,
        readiness_score=readiness.readiness_score,
        would_inject=True,
        no_relevant_evidence=False,
        reason=f"OBSERVED_PLAY_MEMORY_ENABLED is true; corpus is {readiness.verdict}",
        prompt_block=prompt_block,
        evidence_count=len(prompt_items),
        evidence_ids=evidence_ids,
        warnings=warnings,
        filters_applied=filters_applied,
        retrieval_metadata=retrieval_metadata,
    )
