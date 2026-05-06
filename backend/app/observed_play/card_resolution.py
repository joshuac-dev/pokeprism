"""Card resolution for Observed Play Memory Phase 3.

Resolves raw card mentions against the PokéPrism card database.
Resolution is advisory metadata only — it does not affect simulation,
Coach/AI Player, pgvector, Neo4j, or memory ingestion.

Resolution strategy (in order):
1. Manual ignore/resolve rules (ObservedCardResolutionRule rows).
2. Exact normalized name match in card DB.
   - Unique: resolved (0.98).
   - Multiple candidates: ambiguous (0.60).
3. Basic energy alias (e.g. "fighting energy" ↔ "basic fighting energy").
   - Unique alias match: resolved (0.95).
4. Unresolved (0.0).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.observed_play.card_mentions import (
    extract_mentions_from_event,
    normalize_card_name,
)
from app.observed_play.constants import PARSER_VERSION

logger = logging.getLogger(__name__)

RESOLVER_VERSION = "1.0"

# Resolution statuses
RS_RESOLVED  = "resolved"
RS_AMBIGUOUS = "ambiguous"
RS_UNRESOLVED = "unresolved"
RS_IGNORED   = "ignored"

# Log-level card_resolution_status values
CRS_NOT_RESOLVED          = "not_resolved"
CRS_RESOLVED              = "resolved"
CRS_RESOLVED_WITH_WARNINGS = "resolved_with_warnings"
CRS_HAS_UNRESOLVED        = "has_unresolved"
CRS_HAS_AMBIGUOUS         = "has_ambiguous"

# Basic energy alias table: normalized mention → normalized DB lookup alternative
_BASIC_ENERGY_ALIASES: dict[str, str] = {}
_ENERGY_TYPES = (
    "grass", "fire", "water", "lightning", "psychic", "fighting",
    "darkness", "metal", "fairy", "dragon", "colorless",
)
for _t in _ENERGY_TYPES:
    _BASIC_ENERGY_ALIASES[f"{_t} energy"] = f"basic {_t} energy"
    _BASIC_ENERGY_ALIASES[f"basic {_t} energy"] = f"{_t} energy"


@dataclass
class CardResolutionSummary:
    log_id: str
    card_mention_count: int = 0
    resolved_card_count: int = 0
    ambiguous_card_count: int = 0
    unresolved_card_count: int = 0
    ignored_card_count: int = 0
    card_resolution_status: str = CRS_NOT_RESOLVED
    resolver_version: str = RESOLVER_VERSION
    errors: list[str] = field(default_factory=list)


def _resolve_one(
    normalized_name: str,
    cards_by_norm: dict[str, list[dict[str, Any]]],
    rules_by_norm: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Resolve a single normalized card name. Returns a resolution dict."""

    # 1. Manual rules
    rule = rules_by_norm.get(normalized_name)
    if rule:
        if rule["action"] == "ignore":
            return {
                "resolution_status": RS_IGNORED,
                "resolution_confidence": None,
                "resolution_method": "manual_rule_ignore",
                "resolution_reason": "Manually ignored",
                "resolved_card_def_id": None,
                "resolved_card_name": None,
                "candidate_count": 0,
                "candidates_json": [],
            }
        if rule["action"] == "resolve" and rule.get("target_card_def_id"):
            return {
                "resolution_status": RS_RESOLVED,
                "resolution_confidence": 1.0,
                "resolution_method": "manual_rule_resolve",
                "resolution_reason": "Manual resolution rule",
                "resolved_card_def_id": rule["target_card_def_id"],
                "resolved_card_name": rule.get("target_card_name"),
                "candidate_count": 1,
                "candidates_json": [],
            }

    def _candidates_for(norm: str) -> list[dict[str, Any]]:
        return cards_by_norm.get(norm, [])

    # 2. Exact match
    candidates = _candidates_for(normalized_name)
    if candidates:
        if len(candidates) == 1:
            c = candidates[0]
            return {
                "resolution_status": RS_RESOLVED,
                "resolution_confidence": 0.98,
                "resolution_method": "exact_name_unique",
                "resolution_reason": "Exact normalized name, unique card",
                "resolved_card_def_id": c["tcgdex_id"],
                "resolved_card_name": c["name"],
                "candidate_count": 1,
                "candidates_json": [_compact_candidate(c, 0.98, "exact normalized name")],
            }
        else:
            return {
                "resolution_status": RS_AMBIGUOUS,
                "resolution_confidence": 0.60,
                "resolution_method": "exact_name_ambiguous",
                "resolution_reason": f"Exact name matches {len(candidates)} cards",
                "resolved_card_def_id": None,
                "resolved_card_name": None,
                "candidate_count": len(candidates),
                "candidates_json": [
                    _compact_candidate(c, 0.60, "exact normalized name") for c in candidates[:10]
                ],
            }

    # 3. Basic energy alias
    alias = _BASIC_ENERGY_ALIASES.get(normalized_name)
    if alias:
        alias_candidates = _candidates_for(alias)
        if len(alias_candidates) == 1:
            c = alias_candidates[0]
            return {
                "resolution_status": RS_RESOLVED,
                "resolution_confidence": 0.95,
                "resolution_method": "basic_energy_alias",
                "resolution_reason": f"Basic energy alias: '{normalized_name}' → '{alias}'",
                "resolved_card_def_id": c["tcgdex_id"],
                "resolved_card_name": c["name"],
                "candidate_count": 1,
                "candidates_json": [_compact_candidate(c, 0.95, "basic energy alias")],
            }
        elif len(alias_candidates) > 1:
            return {
                "resolution_status": RS_AMBIGUOUS,
                "resolution_confidence": 0.60,
                "resolution_method": "basic_energy_alias_ambiguous",
                "resolution_reason": f"Energy alias matches {len(alias_candidates)} cards",
                "resolved_card_def_id": None,
                "resolved_card_name": None,
                "candidate_count": len(alias_candidates),
                "candidates_json": [
                    _compact_candidate(c, 0.60, "basic energy alias") for c in alias_candidates[:10]
                ],
            }

    # 4. Unresolved
    return {
        "resolution_status": RS_UNRESOLVED,
        "resolution_confidence": 0.0,
        "resolution_method": None,
        "resolution_reason": "No card match found",
        "resolved_card_def_id": None,
        "resolved_card_name": None,
        "candidate_count": 0,
        "candidates_json": [],
    }


def _compact_candidate(card: dict[str, Any], confidence: float, reason: str) -> dict[str, Any]:
    return {
        "card_def_id": card["tcgdex_id"],
        "name": card["name"],
        "set_abbrev": card.get("set_abbrev", ""),
        "set_number": card.get("set_number", ""),
        "image_url": card.get("image_url"),
        "confidence": confidence,
        "reason": reason,
    }


def _derive_log_resolution_status(summary: CardResolutionSummary) -> str:
    if summary.card_mention_count == 0:
        return CRS_NOT_RESOLVED
    if summary.unresolved_card_count > 0:
        return CRS_HAS_UNRESOLVED
    if summary.ambiguous_card_count > 0:
        return CRS_HAS_AMBIGUOUS
    if summary.resolved_card_count + summary.ignored_card_count == summary.card_mention_count:
        return CRS_RESOLVED
    return CRS_RESOLVED_WITH_WARNINGS


async def extract_and_resolve_mentions_for_log(
    db: AsyncSession,
    log_id: UUID | str,
) -> CardResolutionSummary:
    """Extract card mentions from all events for a log, resolve them, and persist.

    Idempotent: deletes existing mentions before inserting new ones.
    Does NOT commit — the caller must commit.
    """
    from app.db.models import (
        Card,
        ObservedCardMention,
        ObservedCardResolutionRule,
        ObservedPlayEvent,
        ObservedPlayLog,
    )
    from sqlalchemy import delete

    log_uuid = UUID(str(log_id))
    summary = CardResolutionSummary(log_id=str(log_id))

    # Load log row
    log_result = await db.execute(
        select(ObservedPlayLog).where(ObservedPlayLog.id == log_uuid)
    )
    log = log_result.scalars().first()
    if log is None:
        summary.errors.append(f"Log {log_id} not found")
        return summary

    # Delete existing mentions
    await db.execute(
        delete(ObservedCardMention).where(
            ObservedCardMention.observed_play_log_id == log_uuid
        )
    )

    # Load events ordered by event_index
    events_result = await db.execute(
        select(ObservedPlayEvent)
        .where(ObservedPlayEvent.observed_play_log_id == log_uuid)
        .order_by(ObservedPlayEvent.event_index)
    )
    events = list(events_result.scalars().all())

    if not events:
        log.card_mention_count = 0
        log.recognized_card_count = 0
        log.unresolved_card_count = 0
        log.ambiguous_card_count = 0
        log.card_resolution_status = CRS_NOT_RESOLVED
        log.resolver_version = RESOLVER_VERSION
        return summary

    # Bulk-load all cards into memory (indexed by normalized name)
    all_cards_result = await db.execute(
        select(Card.tcgdex_id, Card.name, Card.set_abbrev, Card.set_number, Card.image_url)
    )
    cards_by_norm: dict[str, list[dict[str, Any]]] = {}
    for row in all_cards_result:
        norm = normalize_card_name(row.name)
        entry = {
            "tcgdex_id": row.tcgdex_id,
            "name": row.name,
            "set_abbrev": row.set_abbrev,
            "set_number": row.set_number,
            "image_url": row.image_url,
        }
        cards_by_norm.setdefault(norm, []).append(entry)

    # Load resolution rules indexed by normalized_name
    rules_result = await db.execute(
        select(ObservedCardResolutionRule).where(
            ObservedCardResolutionRule.scope == "global"
        )
    )
    rules_by_norm: dict[str, dict[str, Any]] = {}
    for rule in rules_result.scalars().all():
        rules_by_norm[rule.normalized_name] = {
            "action": rule.action,
            "target_card_def_id": rule.target_card_def_id,
            "target_card_name": rule.target_card_name,
        }

    # Extract, resolve, and insert mentions
    parser_version = getattr(log, "parser_version", PARSER_VERSION) or PARSER_VERSION
    all_mentions: list[ObservedCardMention] = []

    for event in events:
        raw_mentions = extract_mentions_from_event(event)
        for idx, m in enumerate(raw_mentions):
            norm = normalize_card_name(m["raw_name"])
            resolution = _resolve_one(norm, cards_by_norm, rules_by_norm)
            mention = ObservedCardMention(
                observed_play_log_id=log_uuid,
                observed_play_event_id=event.id,
                import_batch_id=event.import_batch_id,
                mention_index=idx,
                mention_role=m["mention_role"],
                raw_name=m["raw_name"],
                normalized_name=norm,
                source_event_type=event.event_type,
                source_field=m["source_field"],
                source_payload_path=m.get("source_payload_path"),
                parser_version=parser_version,
                resolver_version=RESOLVER_VERSION,
                **resolution,
            )
            all_mentions.append(mention)

    for mention in all_mentions:
        db.add(mention)

    # Compute summary counters
    summary.card_mention_count = len(all_mentions)
    summary.resolved_card_count = sum(
        1 for m in all_mentions if m.resolution_status == RS_RESOLVED
    )
    summary.ambiguous_card_count = sum(
        1 for m in all_mentions if m.resolution_status == RS_AMBIGUOUS
    )
    summary.unresolved_card_count = sum(
        1 for m in all_mentions if m.resolution_status == RS_UNRESOLVED
    )
    summary.ignored_card_count = sum(
        1 for m in all_mentions if m.resolution_status == RS_IGNORED
    )
    summary.card_resolution_status = _derive_log_resolution_status(summary)

    # Update log counters
    log.card_mention_count = summary.card_mention_count
    log.recognized_card_count = summary.resolved_card_count
    log.unresolved_card_count = summary.unresolved_card_count
    log.ambiguous_card_count = summary.ambiguous_card_count
    log.card_resolution_status = summary.card_resolution_status
    log.resolver_version = RESOLVER_VERSION

    return summary
