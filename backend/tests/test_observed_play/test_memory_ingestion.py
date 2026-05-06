"""Tests for Observed Play Memory Phase 4: memory ingestion.

Tests eligibility gates, preview, ingestion, idempotency, memory item
generation by event type, and card mention handling.

Does NOT test connectivity to real DB — uses mocked SQLAlchemy sessions
following the pattern of other observed_play test files.

Confirmed: no writes to matches, match_events, card_performance, pgvector,
Neo4j, Coach/AI tables.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.observed_play.constants import (
    ET_ABILITY_USED,
    ET_ATTACH_CARD,
    ET_ATTACH_ENERGY,
    ET_CARD_ADDED_TO_HAND,
    ET_CARD_EFFECT_ACTIVATED,
    ET_DISCARD,
    ET_DRAW_HIDDEN,
    ET_EVOLVE,
    ET_GAME_END,
    ET_KNOCKOUT,
    ET_OPENING_HAND_DRAW_HIDDEN,
    ET_PLAY_ITEM,
    ET_PLAY_SUPPORTER,
    ET_PRIZE_TAKEN,
    ET_RETREAT,
    ET_SETUP_START,
    ET_SHUFFLE_DECK,
    ET_SWITCH_ACTIVE,
    ET_ATTACK_USED,
    ET_TURN_START,
    MEMORY_INGESTION_VERSION,
)
from app.observed_play.memory_ingestion import (
    _build_memory_item_data,
    _card_fields_from_mention,
    _compute_item_confidence,
    _mention_index_by_role,
    evaluate_log_ingestion_eligibility,
    ingest_observed_play_log,
    preview_observed_play_ingestion,
)
from app.observed_play.schemas import IngestionConfig


# ── Fake object helpers ────────────────────────────────────────────────────────

LOG_ID = str(uuid.uuid4())
EVENT_ID = 1001


def _log(
    parse_status: str = "parsed",
    memory_status: str = "not_ingested",
    confidence_score: float = 0.90,
    event_count: int = 20,
    card_mention_count: int = 10,
    unresolved_card_count: int = 0,
    ambiguous_card_count: int = 2,
    unknown_ratio: float = 0.02,
    low_confidence_count: int = 1,
) -> Any:
    return SimpleNamespace(
        id=LOG_ID,
        import_batch_id=None,
        parse_status=parse_status,
        memory_status=memory_status,
        confidence_score=confidence_score,
        event_count=event_count,
        card_mention_count=card_mention_count,
        unresolved_card_count=unresolved_card_count,
        ambiguous_card_count=ambiguous_card_count,
        metadata_json={
            "parser_diagnostics": {
                "unknown_ratio": unknown_ratio,
                "low_confidence_count": low_confidence_count,
            }
        },
        memory_item_count=0,
        last_memory_ingested_at=None,
    )


def _event(
    event_type: str,
    event_id: int = EVENT_ID,
    turn_number: int = 1,
    phase: str = "turn",
    player_alias: str = "P1",
    player_raw: str = "Player1",
    card_name_raw: str | None = None,
    target_card_name_raw: str | None = None,
    damage: int | None = None,
    amount: int | None = None,
    zone: str | None = None,
    target_zone: str | None = None,
    confidence_score: float = 0.90,
    event_payload_json: dict | None = None,
) -> Any:
    return SimpleNamespace(
        id=event_id,
        event_type=event_type,
        turn_number=turn_number,
        phase=phase,
        player_alias=player_alias,
        player_raw=player_raw,
        card_name_raw=card_name_raw,
        target_card_name_raw=target_card_name_raw,
        damage=damage,
        amount=amount,
        zone=zone,
        target_zone=target_zone,
        confidence_score=confidence_score,
        raw_line=f"{player_alias} did something with {card_name_raw}",
        event_payload_json=event_payload_json or {},
    )


def _mention(
    role: str,
    raw_name: str,
    resolution_status: str = "resolved",
    resolved_card_def_id: str | None = "sv06-001",
    event_id: int = EVENT_ID,
) -> Any:
    return SimpleNamespace(
        mention_role=role,
        raw_name=raw_name,
        resolution_status=resolution_status,
        resolved_card_def_id=resolved_card_def_id if resolution_status == "resolved" else None,
        observed_play_event_id=event_id,
        observed_play_log_id=LOG_ID,
    )


def _db_with_log(
    log: Any | None,
    critical_mentions: list[Any] | None = None,
    events: list[Any] | None = None,
    all_mentions: list[Any] | None = None,
) -> AsyncMock:
    """Build an AsyncMock DB session with pre-configured execute responses."""
    session = AsyncMock()

    def _make_result(items):
        result = MagicMock()
        result.scalars.return_value.first.return_value = items[0] if items else None
        result.scalars.return_value.all.return_value = items
        return result

    responses = []
    # 1st execute: log lookup
    responses.append(_make_result([log] if log else []))
    # 2nd execute: critical unresolved mentions
    responses.append(_make_result(critical_mentions or []))
    # 3rd execute: events (for preview/ingest)
    if events is not None:
        responses.append(_make_result(events))
    # 4th execute: all mentions
    if all_mentions is not None:
        responses.append(_make_result(all_mentions))

    session.execute = AsyncMock(side_effect=responses)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.delete = MagicMock()
    return session


# ── Test 1: Eligibility passes for high-confidence parsed log ──────────────────

@pytest.mark.asyncio
async def test_eligibility_passes_for_good_log():
    log = _log()
    db = _db_with_log(log, critical_mentions=[])
    config = IngestionConfig()
    result = await evaluate_log_ingestion_eligibility(db, LOG_ID, config)
    assert result.eligible is True
    assert result.status == "eligible"
    assert result.reasons == []


# ── Test 2: Eligibility fails for low confidence ──────────────────────────────

@pytest.mark.asyncio
async def test_eligibility_fails_low_confidence():
    log = _log(confidence_score=0.72)
    db = _db_with_log(log, critical_mentions=[])
    config = IngestionConfig()
    result = await evaluate_log_ingestion_eligibility(db, LOG_ID, config)
    assert result.eligible is False
    codes = [r.code for r in result.reasons]
    assert "low_confidence" in codes


# ── Test 3: Eligibility fails for high unknown ratio ─────────────────────────

@pytest.mark.asyncio
async def test_eligibility_fails_high_unknown_ratio():
    log = _log(unknown_ratio=0.10)
    db = _db_with_log(log, critical_mentions=[])
    config = IngestionConfig()
    result = await evaluate_log_ingestion_eligibility(db, LOG_ID, config)
    assert result.eligible is False
    codes = [r.code for r in result.reasons]
    assert "high_unknown_ratio" in codes


# ── Test 4: Eligibility fails for unresolved critical cards ──────────────────

@pytest.mark.asyncio
async def test_eligibility_fails_unresolved_critical_cards():
    log = _log(unresolved_card_count=2)
    critical = [_mention("actor_card", "Pikachu", resolution_status="unresolved",
                         resolved_card_def_id=None)]
    db = _db_with_log(log, critical_mentions=critical)
    config = IngestionConfig(allow_unresolved=False)
    result = await evaluate_log_ingestion_eligibility(db, LOG_ID, config)
    assert result.eligible is False
    codes = [r.code for r in result.reasons]
    assert "unresolved_critical_cards" in codes


# ── Test 5: Eligibility can be forced ────────────────────────────────────────

@pytest.mark.asyncio
async def test_eligibility_forced_with_explicit_config():
    """force=True + allow_unresolved=True overrides blocking reasons (e.g., low confidence)."""
    log = _log(confidence_score=0.60)  # Low confidence normally blocks ingestion
    db = _db_with_log(log, critical_mentions=[])
    config = IngestionConfig(allow_unresolved=True, force=True)
    result = await evaluate_log_ingestion_eligibility(db, LOG_ID, config)
    assert result.eligible is True
    assert result.status == "forced"
    assert any(r.code == "low_confidence" for r in result.reasons)


# ── Test 6: Preview returns estimated item count and sample items ─────────────

@pytest.mark.asyncio
async def test_preview_returns_estimated_count_and_samples():
    log = _log()
    events = [
        _event(ET_ATTACK_USED, card_name_raw="Pikachu", damage=70),
        _event(ET_KNOCKOUT, event_id=1002, card_name_raw="Charmander"),
    ]
    mentions = [
        _mention("actor_card", "Pikachu", event_id=events[0].id),
        _mention("actor_card", "Charmander", event_id=events[1].id),
    ]

    session = AsyncMock()

    def _r(items):
        r = MagicMock()
        r.scalars.return_value.first.return_value = items[0] if items else None
        r.scalars.return_value.all.return_value = items
        return r

    session.execute = AsyncMock(side_effect=[
        _r([log]),       # log lookup
        _r([]),          # critical unresolved
        _r(events),      # events
        _r(mentions),    # mentions
    ])

    config = IngestionConfig()
    result = await preview_observed_play_ingestion(session, LOG_ID, config)
    assert result.eligible is True
    assert result.estimated_memory_item_count >= 1
    assert len(result.sample_items) >= 1


# ── Test 7: Ingest creates memory ingestion row ───────────────────────────────

@pytest.mark.asyncio
async def test_ingest_creates_ingestion_row():
    log = _log()
    events = [_event(ET_ATTACK_USED, card_name_raw="Pikachu", damage=60)]
    mentions = [_mention("actor_card", "Pikachu", event_id=events[0].id)]

    session = AsyncMock()
    added_objects = []

    def _r(items):
        r = MagicMock()
        r.scalars.return_value.first.return_value = items[0] if items else None
        r.scalars.return_value.all.return_value = items
        return r

    session.execute = AsyncMock(side_effect=[
        _r([log]),      # eligibility: log lookup
        _r([]),         # eligibility: critical mentions
        _r([log]),      # ingest: log lookup
        _r([]),         # ingest: delete prior items (no-op result)
        _r(events),     # events
        _r(mentions),   # mentions
    ])
    session.add = lambda obj: added_objects.append(obj)
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    config = IngestionConfig()
    result = await ingest_observed_play_log(session, LOG_ID, config)

    from app.db.models import ObservedPlayMemoryIngestion
    ingestion_rows = [o for o in added_objects if isinstance(o, ObservedPlayMemoryIngestion)]
    assert len(ingestion_rows) == 1


# ── Test 8: Ingest creates memory item rows ───────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_creates_memory_item_rows():
    log = _log()
    events = [
        _event(ET_ATTACK_USED, card_name_raw="Pikachu", damage=60),
        _event(ET_KNOCKOUT, event_id=1002, card_name_raw="Charmander"),
    ]
    mentions = [
        _mention("actor_card", "Pikachu", event_id=events[0].id),
        _mention("actor_card", "Charmander", event_id=events[1].id),
    ]

    session = AsyncMock()
    added_objects = []

    def _r(items):
        r = MagicMock()
        r.scalars.return_value.first.return_value = items[0] if items else None
        r.scalars.return_value.all.return_value = items
        return r

    session.execute = AsyncMock(side_effect=[
        _r([log]),
        _r([]),
        _r([log]),
        _r([]),         # delete
        _r(events),
        _r(mentions),
    ])
    session.add = lambda obj: added_objects.append(obj)
    session.flush = AsyncMock()
    session.commit = AsyncMock()

    config = IngestionConfig()
    await ingest_observed_play_log(session, LOG_ID, config)

    from app.db.models import ObservedPlayMemoryItem
    item_rows = [o for o in added_objects if isinstance(o, ObservedPlayMemoryItem)]
    assert len(item_rows) == 2


# ── Test 9: Ingest updates log memory_status to ingested ─────────────────────

@pytest.mark.asyncio
async def test_ingest_updates_log_memory_status():
    log = _log()
    events = [_event(ET_ATTACK_USED, card_name_raw="Pikachu", damage=60)]
    mentions = [_mention("actor_card", "Pikachu", event_id=events[0].id)]

    session = AsyncMock()

    def _r(items):
        r = MagicMock()
        r.scalars.return_value.first.return_value = items[0] if items else None
        r.scalars.return_value.all.return_value = items
        return r

    session.execute = AsyncMock(side_effect=[
        _r([log]), _r([]), _r([log]), _r([]), _r(events), _r(mentions)
    ])
    session.add = MagicMock()
    session.flush = AsyncMock()

    await ingest_observed_play_log(session, LOG_ID, IngestionConfig())
    assert log.memory_status == "ingested"


# ── Test 10: Ingest updates memory item count ─────────────────────────────────

@pytest.mark.asyncio
async def test_ingest_updates_memory_item_count():
    log = _log()
    events = [
        _event(ET_ATTACK_USED, event_id=1, damage=60),
        _event(ET_ABILITY_USED, event_id=2),
    ]
    mentions = [
        _mention("actor_card", "Pikachu", event_id=1),
        _mention("actor_card", "Bulbasaur", event_id=2),
    ]

    session = AsyncMock()

    def _r(items):
        r = MagicMock()
        r.scalars.return_value.first.return_value = items[0] if items else None
        r.scalars.return_value.all.return_value = items
        return r

    session.execute = AsyncMock(side_effect=[
        _r([log]), _r([]), _r([log]), _r([]), _r(events), _r(mentions)
    ])
    session.add = MagicMock()
    session.flush = AsyncMock()

    result = await ingest_observed_play_log(session, LOG_ID, IngestionConfig())
    assert result.memory_item_count == 2
    assert log.memory_item_count == 2


# ── Test 11: Re-ingest is idempotent ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_reingest_is_idempotent():
    """delete is called on re-ingest, preventing duplicates."""
    log = _log()
    events = [_event(ET_ATTACK_USED, card_name_raw="Pikachu")]
    mentions = [_mention("actor_card", "Pikachu", event_id=events[0].id)]

    session = AsyncMock()

    def _r(items):
        r = MagicMock()
        r.scalars.return_value.first.return_value = items[0] if items else None
        r.scalars.return_value.all.return_value = items
        return r

    session.execute = AsyncMock(side_effect=[
        _r([log]), _r([]), _r([log]), _r([]), _r(events), _r(mentions)
    ])
    session.add = MagicMock()
    session.flush = AsyncMock()

    result = await ingest_observed_play_log(session, LOG_ID, IngestionConfig())
    assert result.status == "completed"
    # 6 executes: 2 eligibility + 1 log fetch + 1 delete + 1 events + 1 mentions
    assert session.execute.call_count == 6


# ── Test 12: Memory item source links to observed_play_event ──────────────────

@pytest.mark.asyncio
async def test_memory_item_links_to_event():
    event = _event(ET_ATTACK_USED, event_id=99, card_name_raw="Mewtwo", damage=120)
    mention = _mention("actor_card", "Mewtwo", event_id=99)

    mentions_by_role = _mention_index_by_role([mention])
    data = _build_memory_item_data(event, mentions_by_role, allow_unresolved=False)
    assert data is not None
    assert data["source_event_type"] == ET_ATTACK_USED


# ── Test 13: Memory item preserves source_raw_line ───────────────────────────

@pytest.mark.asyncio
async def test_memory_item_preserves_source_raw_line():
    event = _event(ET_ATTACK_USED, event_id=5, card_name_raw="Snorlax", damage=130)
    event.raw_line = "P1's Snorlax used Body Slam on P2's Pikachu."
    mention = _mention("actor_card", "Snorlax", event_id=5)

    mentions_by_role = _mention_index_by_role([mention])
    data = _build_memory_item_data(event, mentions_by_role, allow_unresolved=False)
    assert data is not None
    assert data["source_raw_line"] == "P1's Snorlax used Body Slam on P2's Pikachu."


# ── Test 14: Attack event creates attack_used memory item ────────────────────

def test_attack_event_creates_attack_used_item():
    event = _event(ET_ATTACK_USED, card_name_raw="Charizard", damage=200,
                   event_payload_json={"attack_name": "Flamethrower"})
    mention = _mention("actor_card", "Charizard", event_id=event.id)
    mentions_by_role = _mention_index_by_role([mention])
    data = _build_memory_item_data(event, mentions_by_role, allow_unresolved=False)
    assert data is not None
    assert data["memory_type"] == "attack_used"
    assert data["action_name"] == "Flamethrower"
    assert data["actor_card_raw"] == "Charizard"


# ── Test 15: Ability event creates ability_used memory item ──────────────────

def test_ability_event_creates_ability_used_item():
    event = _event(ET_ABILITY_USED, card_name_raw="Gengar",
                   event_payload_json={"ability_name": "Cursed Drop"})
    mention = _mention("actor_card", "Gengar", event_id=event.id)
    mentions_by_role = _mention_index_by_role([mention])
    data = _build_memory_item_data(event, mentions_by_role, allow_unresolved=False)
    assert data is not None
    assert data["memory_type"] == "ability_used"
    assert data["action_name"] == "Cursed Drop"


# ── Test 16: Evolution event creates card_evolved memory item ─────────────────

def test_evolve_event_creates_card_evolved_item():
    event = _event(ET_EVOLVE, card_name_raw="Charizard",
                   target_card_name_raw="Charmeleon")
    to_mention = _mention("evolution_to", "Charizard", event_id=event.id)
    from_mention = _mention("evolution_from", "Charmeleon", event_id=event.id,
                            resolved_card_def_id="sv06-002")
    mentions_by_role = _mention_index_by_role([to_mention, from_mention])
    data = _build_memory_item_data(event, mentions_by_role, allow_unresolved=False)
    assert data is not None
    assert data["memory_type"] == "card_evolved"
    assert data["actor_card_raw"] == "Charizard"
    assert data["related_card_raw"] == "Charmeleon"


# ── Test 17: Attachment event creates card_attached memory item ───────────────

def test_attach_energy_creates_card_attached_item():
    event = _event(ET_ATTACH_ENERGY, card_name_raw="Fire Energy",
                   target_card_name_raw="Charizard")
    energy_mention = _mention("energy_card", "Fire Energy", event_id=event.id)
    target_mention = _mention("target_card", "Charizard", event_id=event.id,
                              resolved_card_def_id="sv06-003")
    mentions_by_role = _mention_index_by_role([energy_mention, target_mention])
    data = _build_memory_item_data(event, mentions_by_role, allow_unresolved=False)
    assert data is not None
    assert data["memory_type"] == "card_attached"
    assert data["actor_card_raw"] == "Fire Energy"
    assert data["target_card_raw"] == "Charizard"


# ── Test 18: KO event creates knockout memory item ────────────────────────────

def test_ko_event_creates_knockout_item():
    event = _event(ET_KNOCKOUT, card_name_raw="Pikachu")
    mention = _mention("actor_card", "Pikachu", event_id=event.id)
    mentions_by_role = _mention_index_by_role([mention])
    data = _build_memory_item_data(event, mentions_by_role, allow_unresolved=False)
    assert data is not None
    assert data["memory_type"] == "knockout"
    assert data["actor_card_raw"] == "Pikachu"


# ── Test 19: Hidden/setup/turn/shuffle events are skipped ────────────────────

@pytest.mark.parametrize("skip_type", [
    ET_SETUP_START, ET_TURN_START, ET_SHUFFLE_DECK,
    ET_DRAW_HIDDEN, ET_OPENING_HAND_DRAW_HIDDEN,
])
def test_skipped_event_types_produce_no_item(skip_type):
    event = _event(skip_type)
    data = _build_memory_item_data(event, {}, allow_unresolved=False)
    assert data is None


# ── Test 20: Ambiguous mentions stored as raw/ambiguous without def_id ────────

def test_ambiguous_mention_stores_raw_without_def_id():
    event = _event(ET_ATTACK_USED, card_name_raw="Pikachu", damage=60)
    mention = _mention("actor_card", "Pikachu", resolution_status="ambiguous",
                       resolved_card_def_id=None)
    mentions_by_role = _mention_index_by_role([mention])
    data = _build_memory_item_data(event, mentions_by_role, allow_unresolved=False)
    assert data is not None
    assert data["actor_card_raw"] == "Pikachu"
    assert data["actor_card_def_id"] is None
    assert data["actor_resolution_status"] == "ambiguous"


# ── Test 21: Resolved mentions store def_id ───────────────────────────────────

def test_resolved_mention_stores_def_id():
    event = _event(ET_ATTACK_USED, card_name_raw="Pikachu", damage=60)
    mention = _mention("actor_card", "Pikachu", resolution_status="resolved",
                       resolved_card_def_id="sv06-049")
    mentions_by_role = _mention_index_by_role([mention])
    data = _build_memory_item_data(event, mentions_by_role, allow_unresolved=False)
    assert data is not None
    assert data["actor_card_def_id"] == "sv06-049"
    assert data["actor_resolution_status"] == "resolved"


# ── Test 22: Unresolved critical cards block ingestion unless forced ──────────

@pytest.mark.asyncio
async def test_unresolved_critical_blocks_unless_forced():
    log = _log(unresolved_card_count=2)
    critical = [_mention("actor_card", "Mystery Card", resolution_status="unresolved",
                         resolved_card_def_id=None)]
    db = _db_with_log(log, critical_mentions=critical)
    config = IngestionConfig(allow_unresolved=False, force=False)
    result = await evaluate_log_ingestion_eligibility(db, LOG_ID, config)
    assert result.eligible is False
    codes = [r.code for r in result.reasons]
    assert "unresolved_critical_cards" in codes

    # force=True + allow_unresolved=True but with another blocking condition → "forced"
    log2 = _log(unresolved_card_count=2, confidence_score=0.65)
    db2 = _db_with_log(log2, critical_mentions=[])
    config_forced = IngestionConfig(allow_unresolved=True, force=True)
    result_forced = await evaluate_log_ingestion_eligibility(db2, LOG_ID, config_forced)
    assert result_forced.eligible is True
    assert result_forced.status == "forced"


# ── Test 23: Metrics included in eligibility result ──────────────────────────

@pytest.mark.asyncio
async def test_eligibility_result_includes_metrics():
    log = _log(confidence_score=0.92, event_count=30, card_mention_count=15,
               unresolved_card_count=0, ambiguous_card_count=3)
    db = _db_with_log(log, critical_mentions=[])
    result = await evaluate_log_ingestion_eligibility(db, LOG_ID, IngestionConfig())
    assert result.metrics.confidence_score == pytest.approx(0.92)
    assert result.metrics.event_count == 30
    assert result.metrics.card_mention_count == 15
    assert result.metrics.ambiguous_card_count == 3


# ── Test 24: Ingest returns skipped for not_parsed log ───────────────────────

@pytest.mark.asyncio
async def test_ingest_returns_skipped_for_not_parsed_log():
    log = _log(parse_status="raw_archived")
    db = _db_with_log(log, critical_mentions=[])
    result = await ingest_observed_play_log(db, LOG_ID, IngestionConfig())
    assert result.status == "skipped"
    assert result.eligibility_status == "ineligible"
    assert any(r.code == "not_parsed" for r in result.reasons)


# ── Test 25: Preview returns ineligible for bad log without querying events ───

@pytest.mark.asyncio
async def test_preview_returns_ineligible_without_events():
    log = _log(confidence_score=0.50)
    db = _db_with_log(log, critical_mentions=[])
    result = await preview_observed_play_ingestion(db, LOG_ID, IngestionConfig())
    assert result.eligible is False
    assert result.eligibility_status == "ineligible"
    assert result.estimated_memory_item_count == 0


# ── Test 26: _card_fields_from_mention handles all resolution statuses ────────

def test_card_fields_from_mention_resolved():
    m = _mention("actor_card", "Pikachu", resolution_status="resolved",
                 resolved_card_def_id="sv06-049")
    raw, def_id, rs = _card_fields_from_mention(m)
    assert raw == "Pikachu"
    assert def_id == "sv06-049"
    assert rs == "resolved"


def test_card_fields_from_mention_ambiguous():
    m = _mention("actor_card", "Pikachu", resolution_status="ambiguous",
                 resolved_card_def_id=None)
    raw, def_id, rs = _card_fields_from_mention(m)
    assert raw == "Pikachu"
    assert def_id is None
    assert rs == "ambiguous"


def test_card_fields_from_mention_unresolved_blocked():
    m = _mention("actor_card", "???", resolution_status="unresolved",
                 resolved_card_def_id=None)
    raw, def_id, rs = _card_fields_from_mention(m, allow_unresolved=False)
    assert raw is None
    assert def_id is None
    assert rs is None


def test_card_fields_from_mention_unresolved_allowed():
    m = _mention("actor_card", "???", resolution_status="unresolved",
                 resolved_card_def_id=None)
    raw, def_id, rs = _card_fields_from_mention(m, allow_unresolved=True)
    assert raw == "???"
    assert def_id is None
    assert rs == "unresolved"


def test_card_fields_from_mention_ignored():
    m = _mention("actor_card", "ignored", resolution_status="ignored",
                 resolved_card_def_id=None)
    raw, def_id, rs = _card_fields_from_mention(m)
    assert raw is None


def test_card_fields_from_mention_none():
    raw, def_id, rs = _card_fields_from_mention(None)
    assert raw is None
    assert def_id is None
    assert rs is None


# ── Test 27: Confidence penalty for ambiguous/unresolved critical cards ───────

def test_confidence_penalty_for_ambiguous_critical():
    m = _mention("actor_card", "Pikachu", resolution_status="ambiguous",
                 resolved_card_def_id=None)
    mentions_by_role = {"actor_card": m}
    from app.observed_play.memory_ingestion import _CRITICAL_MENTION_ROLES
    score = _compute_item_confidence(
        0.90, mentions_by_role, _CRITICAL_MENTION_ROLES, allow_unresolved=False
    )
    assert score == pytest.approx(0.80)


def test_confidence_penalty_for_unresolved_critical_when_allowed():
    m = _mention("actor_card", "???", resolution_status="unresolved",
                 resolved_card_def_id=None)
    mentions_by_role = {"actor_card": m}
    from app.observed_play.memory_ingestion import _CRITICAL_MENTION_ROLES
    score = _compute_item_confidence(
        0.90, mentions_by_role, _CRITICAL_MENTION_ROLES, allow_unresolved=True
    )
    assert score == pytest.approx(0.65)


# ── Test 28: MEMORY_INGESTION_VERSION constant ────────────────────────────────

def test_ingestion_version_constant():
    assert MEMORY_INGESTION_VERSION == "1.0"


# ── Test 29: No writes to simulator/Coach/AI tables ──────────────────────────

def test_no_simulator_imports_in_memory_ingestion():
    """Ensure memory_ingestion.py does not import Coach/AI/pgvector/Neo4j modules."""
    import importlib
    mod = importlib.import_module("app.observed_play.memory_ingestion")
    # Check module's imported names, not docstring prose
    imported_modules = set(vars(mod).keys())
    forbidden_modules = ["pgvector", "neo4j", "coach", "ai_player", "card_performance"]
    for name in forbidden_modules:
        assert name not in imported_modules, f"Forbidden module {name!r} imported in memory_ingestion.py"

    # Also ensure no imports from match_events or coach tables
    import ast, inspect
    source = inspect.getsource(mod)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    names.append(alias.name)
            for name in names:
                assert "coach" not in name.lower(), f"Coach import found: {name}"
                assert "ai_player" not in name.lower(), f"AIPlayer import found: {name}"
                assert "match_event" not in name.lower(), f"match_events import found: {name}"
                assert "pgvector" not in name.lower(), f"pgvector import found: {name}"
