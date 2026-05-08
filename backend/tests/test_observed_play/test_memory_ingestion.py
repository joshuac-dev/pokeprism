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
    _MAX_BLOCKERS,
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
    normalized_name: str | None = None,
    source_event_type: str = ET_ATTACK_USED,
    source_field: str = "card_name_raw",
    mention_id: str | None = None,
) -> Any:
    return SimpleNamespace(
        id=mention_id or str(uuid.uuid4()),
        mention_role=role,
        raw_name=raw_name,
        normalized_name=normalized_name or raw_name.lower(),
        resolution_status=resolution_status,
        resolved_card_def_id=resolved_card_def_id if resolution_status == "resolved" else None,
        observed_play_event_id=event_id,
        observed_play_log_id=LOG_ID,
        source_event_type=source_event_type,
        source_field=source_field,
    )


def _db_with_log(
    log: Any | None,
    critical_mentions: list[Any] | None = None,
    events: list[Any] | None = None,
    all_mentions: list[Any] | None = None,
    blocker_events: list[Any] | None = None,
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
    # 3rd execute: blocker events query (only when there are critical mentions)
    if critical_mentions:
        responses.append(_make_result(blocker_events or []))
    # 4th execute: events (for preview/ingest)
    if events is not None:
        responses.append(_make_result(events))
    # 5th execute: all mentions
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


# ── Phase 4.1: Blocker detail tests ──────────────────────────────────────────

def _blocker_event(
    event_id: int = EVENT_ID,
    turn_number: int = 3,
    player_alias: str = "P1",
    raw_line: str = "P1's Mystery Card used Attack.",
) -> Any:
    return SimpleNamespace(
        id=event_id,
        turn_number=turn_number,
        player_alias=player_alias,
        raw_line=raw_line,
    )


@pytest.mark.asyncio
async def test_eligibility_result_includes_blocker_details():
    """Eligibility result contains structured blockers for unresolved critical mentions."""
    log = _log(unresolved_card_count=1)
    mention_id = str(uuid.uuid4())
    critical = [_mention(
        "actor_card", "Mystery Card",
        resolution_status="unresolved",
        resolved_card_def_id=None,
        mention_id=mention_id,
        source_event_type=ET_ATTACK_USED,
        source_field="card_name_raw",
    )]
    event = _blocker_event(event_id=EVENT_ID, turn_number=3, player_alias="P1",
                           raw_line="P1's Mystery Card used Attack.")
    db = _db_with_log(log, critical_mentions=critical, blocker_events=[event])
    result = await evaluate_log_ingestion_eligibility(db, LOG_ID, IngestionConfig())

    assert result.blocker_count == 1
    assert len(result.blockers) == 1
    b = result.blockers[0]
    assert b.code == "unresolved_critical_card"
    assert b.raw_name == "Mystery Card"
    assert b.normalized_name == "mystery card"
    assert b.mention_role == "actor_card"
    assert b.resolution_status == "unresolved"
    assert b.source_event_type == ET_ATTACK_USED
    assert b.source_field == "card_name_raw"
    assert b.turn_number == 3
    assert b.player_alias == "P1"
    assert b.raw_line == "P1's Mystery Card used Attack."
    assert b.observed_play_event_id == EVENT_ID
    assert b.observed_card_mention_id == mention_id


@pytest.mark.asyncio
async def test_blockers_truncated_when_over_limit():
    """blocker_count reflects full count; blockers list is limited to _MAX_BLOCKERS."""
    log = _log(unresolved_card_count=_MAX_BLOCKERS + 5)
    critical = [
        _mention("actor_card", f"Card {i}", resolution_status="unresolved",
                 resolved_card_def_id=None, event_id=EVENT_ID + i)
        for i in range(_MAX_BLOCKERS + 5)
    ]
    db = _db_with_log(log, critical_mentions=critical, blocker_events=[])
    result = await evaluate_log_ingestion_eligibility(db, LOG_ID, IngestionConfig())

    assert result.blocker_count == _MAX_BLOCKERS + 5
    assert len(result.blockers) == _MAX_BLOCKERS
    assert result.blockers_truncated is True


@pytest.mark.asyncio
async def test_blockers_not_truncated_below_limit():
    """blockers_truncated is False when count is at or below limit."""
    log = _log(unresolved_card_count=3)
    critical = [
        _mention("actor_card", f"Card {i}", resolution_status="unresolved",
                 resolved_card_def_id=None, event_id=EVENT_ID + i)
        for i in range(3)
    ]
    db = _db_with_log(log, critical_mentions=critical, blocker_events=[])
    result = await evaluate_log_ingestion_eligibility(db, LOG_ID, IngestionConfig())

    assert result.blocker_count == 3
    assert len(result.blockers) == 3
    assert result.blockers_truncated is False


@pytest.mark.asyncio
async def test_eligible_log_has_empty_blockers():
    """A fully eligible log returns empty blockers list."""
    log = _log()
    db = _db_with_log(log, critical_mentions=[])
    result = await evaluate_log_ingestion_eligibility(db, LOG_ID, IngestionConfig())

    assert result.eligible is True
    assert result.blockers == []
    assert result.blocker_count == 0
    assert result.blockers_truncated is False


@pytest.mark.asyncio
async def test_blocker_raw_line_truncated_to_max_length():
    """Raw lines longer than _MAX_RAW_LINE_LENGTH are truncated."""
    from app.observed_play.memory_ingestion import _MAX_RAW_LINE_LENGTH
    long_line = "x" * (_MAX_RAW_LINE_LENGTH + 50)
    log = _log(unresolved_card_count=1)
    critical = [_mention("actor_card", "SomeCard", resolution_status="unresolved",
                         resolved_card_def_id=None)]
    event = _blocker_event(raw_line=long_line)
    db = _db_with_log(log, critical_mentions=critical, blocker_events=[event])
    result = await evaluate_log_ingestion_eligibility(db, LOG_ID, IngestionConfig())

    assert len(result.blockers[0].raw_line) == _MAX_RAW_LINE_LENGTH


@pytest.mark.asyncio
async def test_preview_includes_blockers_for_ineligible_log():
    """Preview response carries blockers when log is ineligible due to critical unresolved."""
    log = _log(unresolved_card_count=1)
    critical = [_mention("actor_card", "BlockerCard", resolution_status="unresolved",
                         resolved_card_def_id=None)]
    event = _blocker_event(raw_line="P1's BlockerCard used Move.")
    db = _db_with_log(log, critical_mentions=critical, blocker_events=[event])
    result = await preview_observed_play_ingestion(db, LOG_ID, IngestionConfig())

    assert result.eligible is False
    assert result.blocker_count == 1
    assert len(result.blockers) == 1
    assert result.blockers[0].raw_name == "BlockerCard"


@pytest.mark.asyncio
async def test_ingest_skipped_summary_includes_blockers():
    """Ineligible ingest returns skipped summary with blocker details."""
    log = _log(unresolved_card_count=1)
    critical = [_mention("actor_card", "BlockerCard", resolution_status="unresolved",
                         resolved_card_def_id=None)]
    event = _blocker_event()
    db = _db_with_log(log, critical_mentions=critical, blocker_events=[event])
    result = await ingest_observed_play_log(db, LOG_ID, IngestionConfig())

    assert result.status == "skipped"
    assert result.blocker_count == 1
    assert len(result.blockers) == 1
    assert result.blockers[0].mention_role == "actor_card"


@pytest.mark.asyncio
async def test_non_critical_unresolved_not_in_blockers():
    """Non-critical unresolved roles (e.g. revealed_card) do not appear in blockers."""
    log = _log(unresolved_card_count=1)
    # revealed_card is not a critical role — it shouldn't appear in critical_mentions at all
    # The gate query filters by _CRITICAL_MENTION_ROLES, so a non-critical mention
    # would never be in critical_unresolved_mentions.
    db = _db_with_log(log, critical_mentions=[])  # no critical blockers
    result = await evaluate_log_ingestion_eligibility(db, LOG_ID, IngestionConfig())

    # There may be an unresolved_cards reason but no blockers
    assert result.blockers == []
    assert result.blocker_count == 0


@pytest.mark.asyncio
async def test_blocker_event_lookup_handles_missing_event():
    """Blocker is built even if the event row is not found (raw_line/turn/player are None)."""
    log = _log(unresolved_card_count=1)
    critical = [_mention("actor_card", "OrphanCard", resolution_status="unresolved",
                         resolved_card_def_id=None, event_id=9999)]
    # blocker_events is empty — no matching event row
    db = _db_with_log(log, critical_mentions=critical, blocker_events=[])
    result = await evaluate_log_ingestion_eligibility(db, LOG_ID, IngestionConfig())

    assert len(result.blockers) == 1
    b = result.blockers[0]
    assert b.raw_name == "OrphanCard"
    assert b.turn_number is None
    assert b.player_alias is None
    assert b.raw_line is None


@pytest.mark.asyncio
async def test_preview_eligible_log_has_empty_blockers_in_preview():
    """Eligible preview returns blockers=[] (no blocking issues)."""
    log = _log()
    events = [_event(ET_ATTACK_USED, card_name_raw="Pikachu", damage=70)]
    mentions = [_mention("actor_card", "Pikachu", event_id=events[0].id)]

    session = AsyncMock()

    def _r(items):
        r = MagicMock()
        r.scalars.return_value.first.return_value = items[0] if items else None
        r.scalars.return_value.all.return_value = items
        return r

    session.execute = AsyncMock(side_effect=[
        _r([log]),       # log lookup
        _r([]),          # critical unresolved (empty → no blocker events query)
        _r(events),      # events
        _r(mentions),    # mentions
    ])

    result = await preview_observed_play_ingestion(session, LOG_ID, IngestionConfig())
    assert result.eligible is True
    assert result.blockers == []
    assert result.blocker_count == 0
    assert result.blockers_truncated is False


# ── Phase 2.4: New event types do not produce junk memory items ───────────────

from app.observed_play.constants import (
    ET_POKEMON_CHECKUP,
    ET_SPECIAL_CONDITION_APPLIED,
    ET_SPECIAL_CONDITION_REMOVED,
    ET_SPECIAL_CONDITION_DAMAGE,
    ET_DAMAGE_COUNTERS_PLACED,
    ET_DAMAGE_COUNTERS_MOVED,
    ET_POKEMON_SWITCHED,
    ET_CARDS_DISCARDED,
    ET_CARDS_DISCARDED_FROM_POKEMON,
    ET_CARDS_MOVED_TO_HAND,
    ET_CARDS_SHUFFLED_INTO_DECK,
)


@pytest.mark.parametrize("skip_type", [
    ET_POKEMON_CHECKUP,
    ET_SPECIAL_CONDITION_APPLIED,
    ET_SPECIAL_CONDITION_REMOVED,
    ET_SPECIAL_CONDITION_DAMAGE,
    ET_DAMAGE_COUNTERS_PLACED,
    ET_DAMAGE_COUNTERS_MOVED,
    ET_CARDS_DISCARDED,
    ET_CARDS_DISCARDED_FROM_POKEMON,
    ET_CARDS_MOVED_TO_HAND,
    ET_CARDS_SHUFFLED_INTO_DECK,
])
def test_phase24_new_event_types_produce_no_memory_item(skip_type):
    """Phase 2.4 parser events not yet memory-mapped must not create any item."""
    event = _event(skip_type, card_name_raw="Dragapult ex")
    data = _build_memory_item_data(event, {}, allow_unresolved=False)
    assert data is None, (
        f"Expected {skip_type!r} to produce no memory item, but got: {data}"
    )


def test_pokemon_switched_produces_no_memory_item():
    event = _event(ET_POKEMON_SWITCHED, card_name_raw="Pecharunt",
                   target_card_name_raw="Salazzle ex")
    data = _build_memory_item_data(event, {}, allow_unresolved=False)
    assert data is None
