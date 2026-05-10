"""Tests for Phase 6.2a tiered evidence retrieval in coach_context.py.

Covers:
1. Tier 1 exact card-ID match selected before unrelated higher-confidence item.
2. Candidate card ID match included even if not in deck_ids.
3. Tier 2 ILIKE name fallback when card_def_id absent.
4. Source diversity cap: at most 2 items per observed_play_log_id.
5. No relevant evidence + allow_fallback=False → would_inject=False, no_relevant_evidence=True.
6. allow_fallback=True enables global fallback.
7. Win/loss is a tiebreaker only, not a hard filter.
8. Retrieval metadata populated with strategy, query context, tier details.
9. _select_tiered_evidence: no writes to observed-play tables.
10-12. Covered via test_analyst.py (deck context passing, flag-off 3-tuple, existing tests).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ────────────────────────────────────────────────────────────────────

def _uuid(hex_prefix: str) -> uuid.UUID:
    """Build a UUID from a short prefix for readability."""
    padded = hex_prefix.replace("-", "")[:8].ljust(32, "0")
    return uuid.UUID(padded)


def _make_item(
    *,
    item_id: uuid.UUID | None = None,
    log_id: uuid.UUID | None = None,
    actor_card_def_id: str | None = None,
    target_card_def_id: str | None = None,
    related_card_def_id: str | None = None,
    actor_card_raw: str | None = None,
    target_card_raw: str | None = None,
    related_card_raw: str | None = None,
    confidence_score: float = 0.90,
    memory_type: str = "attack",
    action_name: str | None = "test-action",
    turn_number: int | None = 3,
    damage: int | None = None,
    source_raw_line: str = "Player attacked.",
    actor_resolution_status: str | None = None,
    target_resolution_status: str | None = None,
    related_resolution_status: str | None = None,
    player_alias: str | None = None,
) -> MagicMock:
    item = MagicMock()
    item.id = item_id or uuid.uuid4()
    item.observed_play_log_id = log_id or uuid.uuid4()
    item.actor_card_def_id = actor_card_def_id
    item.target_card_def_id = target_card_def_id
    item.related_card_def_id = related_card_def_id
    item.actor_card_raw = actor_card_raw
    item.target_card_raw = target_card_raw
    item.related_card_raw = related_card_raw
    item.confidence_score = confidence_score
    item.memory_type = memory_type
    item.action_name = action_name
    item.turn_number = turn_number
    item.damage = damage
    item.source_raw_line = source_raw_line
    item.actor_resolution_status = actor_resolution_status
    item.target_resolution_status = target_resolution_status
    item.related_resolution_status = related_resolution_status
    item.player_alias = player_alias
    item.source_event_type = None
    return item


def _make_row(item, winner_alias=None, self_player_index=None, p1=None, p2=None):
    """Simulate a SQLAlchemy Row for _select_tiered_evidence indexing."""
    values = [item, winner_alias, self_player_index, p1, p2]

    class _Row:
        def __getitem__(self, idx):
            return values[idx]

    return _Row()


def _make_db(*per_call_rows):
    """Mock async DB session returning given row lists on successive execute() calls.

    Extra calls beyond the provided row lists return an empty result, allowing
    Phase 7.2c coverage queries to succeed without StopIteration errors.
    """
    db = AsyncMock()
    results = []
    for rows in per_call_rows:
        r = MagicMock()
        r.all.return_value = rows
        results.append(r)

    _empty = MagicMock()
    _empty.all.return_value = []
    _call_idx = [0]

    async def _execute(stmt):
        idx = _call_idx[0]
        _call_idx[0] += 1
        return results[idx] if idx < len(results) else _empty

    db.execute = _execute
    return db


def _ready_readiness():
    from app.observed_play.schemas import (
        CardResolutionStats, CorpusReadinessReport, CorpusStats,
        MemoryQualityStats, ParserQualityStats,
    )
    return CorpusReadinessReport(
        verdict="ready",
        readiness_score=97.0,
        generated_at="2024-01-01T00:00:00+00:00",
        review_only=True,
        corpus=CorpusStats(
            log_count=2, parsed_log_count=2, ingested_log_count=2,
            failed_log_count=0, parse_coverage_pct=100.0,
            ingestion_coverage_pct=100.0, total_events=20, total_memory_items=10,
        ),
        parser_quality=ParserQualityStats(
            avg_event_confidence=0.92, events_below_threshold=0,
            low_confidence_pct=0.0, unknown_event_count=0,
            confidence_threshold_used=0.80,
        ),
        card_resolution=CardResolutionStats(
            total_card_mentions=10, resolved_mentions=10, ambiguous_mentions=0,
            unresolved_mentions=0, critical_unresolved_mentions=0,
            resolution_rate_pct=100.0,
        ),
        memory_quality=MemoryQualityStats(
            avg_memory_confidence=0.91, memory_items_below_threshold=0,
            low_confidence_memory_pct=0.0, memory_confidence_threshold_used=0.80,
            top_memory_types=[],
        ),
        blockers=[], warnings=[], recommendations=[],
    )


# ── Tests for _determine_winning_game ─────────────────────────────────────────

class TestDetermineWinningGame:
    def _fn(self, *args, **kwargs):
        from app.observed_play.coach_context import _determine_winning_game
        return _determine_winning_game(*args, **kwargs)

    def test_self_player1_won(self):
        assert self._fn("Alice", 1, "Alice", "Bob") is True

    def test_self_player1_lost(self):
        assert self._fn("Bob", 1, "Alice", "Bob") is False

    def test_self_player2_won(self):
        assert self._fn("Bob", 2, "Alice", "Bob") is True

    def test_self_player2_lost(self):
        assert self._fn("Alice", 2, "Alice", "Bob") is False

    def test_unknown_when_winner_none(self):
        assert self._fn(None, 1, "Alice", "Bob") is None

    def test_unknown_when_index_none(self):
        assert self._fn("Alice", None, "Alice", "Bob") is None

    def test_unknown_when_alias_mismatch(self):
        assert self._fn("Alice", 1, None, "Bob") is None


# ── Tests for _select_tiered_evidence ─────────────────────────────────────────

class TestSelectTieredEvidence:

    @pytest.mark.asyncio
    async def test_tier1_exact_id_match_selected_over_unrelated(self):
        """Tier 1 card-ID match beats a higher-confidence unrelated item."""
        from app.observed_play.coach_context import _select_tiered_evidence

        log_a = uuid.uuid4()
        log_b = uuid.uuid4()
        # Tier 1 candidate: lower raw confidence but has exact card-ID match
        tier1_item = _make_item(
            item_id=_uuid("aa000001"),
            log_id=log_a,
            actor_card_def_id="sv06-dragapult",
            confidence_score=0.88,
        )
        # An item that would only appear in global fallback (no ID/name match)
        global_item = _make_item(
            item_id=_uuid("bb000001"),
            log_id=log_b,
            actor_card_def_id="sv99-salazzle",
            confidence_score=0.97,  # higher confidence but wrong archetype
        )

        # Tier 1 returns the deck-matched item; Tier 2 returns nothing
        db = _make_db(
            [_make_row(tier1_item)],  # Tier 1 results
            [],                       # Tier 2 results (no name matches)
        )
        selected, exclusion = await _select_tiered_evidence(
            db,
            deck_card_ids=["sv06-dragapult"],
            deck_card_names=["Dragapult ex"],
            candidate_card_ids=[],
            candidate_card_names=[],
            min_confidence=0.85,
            effective_limit=8,
            allow_fallback=False,
        )
        assert len(selected) == 1
        assert str(selected[0].item.id) == str(_uuid("aa000001"))
        assert selected[0].tier == 1

    @pytest.mark.asyncio
    async def test_candidate_card_id_match_included(self):
        """Candidate card ID match is selected even if not in deck_ids."""
        from app.observed_play.coach_context import _select_tiered_evidence

        log_a = uuid.uuid4()
        candidate_item = _make_item(
            item_id=_uuid("cc000001"),
            log_id=log_a,
            actor_card_def_id="sv05-pidgeot",  # candidate only, not in deck
            confidence_score=0.90,
        )
        db = _make_db(
            [_make_row(candidate_item)],  # Tier 1 result (via candidate_card_ids)
            [],                           # Tier 2
        )
        selected, exclusion = await _select_tiered_evidence(
            db,
            deck_card_ids=[],                    # NOT in deck
            deck_card_names=[],
            candidate_card_ids=["sv05-pidgeot"],  # in candidates
            candidate_card_names=["Pidgeot ex"],
            min_confidence=0.85,
            effective_limit=8,
            allow_fallback=False,
        )
        assert len(selected) == 1
        assert selected[0].tier == 1
        assert "sv05-pidgeot" in selected[0].matched_card_ids

    @pytest.mark.asyncio
    async def test_tier2_ilike_fallback_when_no_card_def_id(self):
        """Tier 2 selects items where raw card name matches but card_def_id is absent."""
        from app.observed_play.coach_context import _select_tiered_evidence

        log_a = uuid.uuid4()
        tier2_item = _make_item(
            item_id=_uuid("dd000001"),
            log_id=log_a,
            actor_card_def_id=None,          # no resolved ID
            actor_card_raw="Dragapult ex",   # but name matches
            confidence_score=0.87,
        )
        db = _make_db(
            [],                               # Tier 1: no card-ID matches
            [_make_row(tier2_item)],          # Tier 2: ILIKE name match
        )
        selected, exclusion = await _select_tiered_evidence(
            db,
            deck_card_ids=["sv06-dragapult"],
            deck_card_names=["Dragapult ex"],
            candidate_card_ids=[],
            candidate_card_names=[],
            min_confidence=0.85,
            effective_limit=8,
            allow_fallback=False,
        )
        assert len(selected) == 1
        assert str(selected[0].item.id) == str(_uuid("dd000001"))
        assert selected[0].tier == 2
        assert "Dragapult ex" in selected[0].matched_card_names

    @pytest.mark.asyncio
    async def test_source_diversity_cap_at_most_2_per_log(self):
        """At most 2 selected items share the same observed_play_log_id."""
        from app.observed_play.coach_context import _select_tiered_evidence

        shared_log = uuid.uuid4()
        items = [
            _make_item(item_id=_uuid(f"ee00000{i}"), log_id=shared_log,
                       actor_card_def_id="sv06-drag", confidence_score=0.97 - i * 0.02)
            for i in range(1, 5)
        ]
        rows = [_make_row(it) for it in items]
        db = _make_db(rows, [])  # All 4 from Tier 1
        selected, exclusion = await _select_tiered_evidence(
            db,
            deck_card_ids=["sv06-drag"],
            deck_card_names=["Dragapult"],
            candidate_card_ids=[],
            candidate_card_names=[],
            min_confidence=0.85,
            effective_limit=8,
            allow_fallback=False,
        )
        log_ids_in_selected = [c.log_id for c in selected]
        assert log_ids_in_selected.count(str(shared_log)) <= 2
        assert exclusion.source_cap_excluded >= 2

    @pytest.mark.asyncio
    async def test_no_relevant_evidence_without_fallback(self):
        """When Tier 1+2 return nothing and allow_fallback=False, exclusion has 0 items."""
        from app.observed_play.coach_context import _select_tiered_evidence

        db = _make_db([], [])  # Tier 1 empty, Tier 2 empty
        selected, exclusion = await _select_tiered_evidence(
            db,
            deck_card_ids=["sv06-drag"],
            deck_card_names=["Dragapult ex"],
            candidate_card_ids=[],
            candidate_card_names=[],
            min_confidence=0.85,
            effective_limit=8,
            allow_fallback=False,
        )
        assert selected == []
        assert exclusion.source_cap_excluded == 0

    @pytest.mark.asyncio
    async def test_allow_fallback_true_returns_global_items(self):
        """allow_fallback=True fetches Tier 3 (global) items when Tier 1+2 empty."""
        from app.observed_play.coach_context import _select_tiered_evidence

        log_x = uuid.uuid4()
        global_item = _make_item(
            item_id=_uuid("ff000001"), log_id=log_x,
            actor_card_def_id="sv99-salazzle", confidence_score=0.95,
        )
        # Tier 1 empty, Tier 2 empty, Tier 3 returns global item
        db = _make_db([], [], [_make_row(global_item)])
        selected, exclusion = await _select_tiered_evidence(
            db,
            deck_card_ids=["sv06-drag"],
            deck_card_names=["Dragapult ex"],
            candidate_card_ids=[],
            candidate_card_names=[],
            min_confidence=0.85,
            effective_limit=8,
            allow_fallback=True,
        )
        assert len(selected) == 1
        assert selected[0].tier == 3

    @pytest.mark.asyncio
    async def test_win_loss_is_tiebreaker_not_gate(self):
        """Win/loss adds +0.05 bonus but does NOT exclude losing-game items.

        Use allow_fallback=True with Tier 3 items (0 tier bonus) so the +0.05
        outcome bonus is visible without clamping.
        """
        from app.observed_play.coach_context import _select_tiered_evidence

        log_w, log_l = uuid.uuid4(), uuid.uuid4()
        # Use a different archetype so these don't match deck IDs
        win_item = _make_item(
            item_id=_uuid("a1000001"), log_id=log_w,
            actor_card_def_id="sv99-unrelated", confidence_score=0.87,
        )
        loss_item = _make_item(
            item_id=_uuid("b2000001"), log_id=log_l,
            actor_card_def_id="sv99-unrelated", confidence_score=0.87,
        )
        win_row = _make_row(win_item, winner_alias="Alice", self_player_index=1, p1="Alice", p2="Bob")
        loss_row = _make_row(loss_item, winner_alias="Bob", self_player_index=1, p1="Alice", p2="Bob")

        # Tier 1 empty (no card-ID match), Tier 2 empty (no name match),
        # Tier 3 (global fallback) returns both win/loss items
        db = _make_db([], [], [win_row, loss_row])
        selected, _ = await _select_tiered_evidence(
            db,
            deck_card_ids=["sv06-drag"],   # no match in items above
            deck_card_names=["Dragapult ex"],
            candidate_card_ids=[],
            candidate_card_names=[],
            min_confidence=0.85,
            effective_limit=8,
            allow_fallback=True,
        )
        # Both items should be selected (losing item not excluded)
        assert len(selected) == 2
        # Winning game item ranks first (0.87 + 0.00 + 0.05 = 0.92 vs 0.87 + 0.00 = 0.87)
        assert selected[0].from_winning_game is True
        assert selected[1].from_winning_game is False
        # Winning item has higher relevance score
        assert selected[0].base_score > selected[1].base_score

    @pytest.mark.asyncio
    async def test_retrieval_metadata_populated(self):
        """Retrieval metadata has correct strategy, query context, and tier details."""
        from app.observed_play.coach_context import _select_tiered_evidence

        log_a = uuid.uuid4()
        item = _make_item(
            item_id=_uuid("cc111001"), log_id=log_a,
            actor_card_def_id="sv06-drag", confidence_score=0.91,
        )
        db = _make_db([_make_row(item)], [])
        selected, exclusion = await _select_tiered_evidence(
            db,
            deck_card_ids=["sv06-drag"],
            deck_card_names=["Dragapult ex"],
            candidate_card_ids=["sv05-pid"],
            candidate_card_names=["Pidgeot ex"],
            min_confidence=0.85,
            effective_limit=8,
            allow_fallback=False,
        )
        assert len(selected) == 1
        cand = selected[0]
        assert cand.tier == 1
        assert "sv06-drag" in cand.matched_card_ids
        assert cand.matched_field == "actor_card_def_id"
        assert cand.base_score > 0.88  # confidence + tier bonus

    @pytest.mark.asyncio
    async def test_label_boost_applied_for_matching_source_label(self):
        """A matching current/source archetype label applies a bounded boost."""
        from app.observed_play.coach_context import _select_tiered_evidence

        log_a = uuid.uuid4()
        item = _make_item(
            item_id=_uuid("ab000001"),
            log_id=log_a,
            actor_card_def_id="sv-dragapult",
            target_card_def_id="sv-drakloak",
            related_card_def_id="sv-dreepy",
            actor_card_raw="Dragapult ex",
            target_card_raw="Drakloak",
            related_card_raw="Dreepy",
            confidence_score=0.70,
            player_alias="player_1",
        )
        db = _make_db([_make_row(item)], [])
        selected, _ = await _select_tiered_evidence(
            db,
            deck_card_ids=["sv-dragapult", "sv-drakloak", "sv-dreepy"],
            deck_card_names=["Dragapult ex", "Drakloak", "Dreepy"],
            candidate_card_ids=[],
            candidate_card_names=[],
            min_confidence=0.65,
            effective_limit=8,
            allow_fallback=False,
        )
        assert selected[0].label_boost == 0.10
        assert selected[0].final_score == pytest.approx(selected[0].base_score + 0.10)
        assert "dragapult-ex" in selected[0].matched_label_keys
        assert "Matched current archetype label Dragapult ex" in selected[0].label_match_reason

    @pytest.mark.asyncio
    async def test_label_boost_cap(self):
        """Multiple matched labels cannot exceed the configured boost cap."""
        from app.observed_play.coach_context import _select_tiered_evidence

        item = _make_item(
            item_id=_uuid("ab000002"),
            log_id=uuid.uuid4(),
            actor_card_def_id="sv-dragapult",
            target_card_def_id="sv-drakloak",
            related_card_def_id="sv-dreepy",
            actor_card_raw="Dragapult ex",
            target_card_raw="Drakloak",
            related_card_raw="Dreepy",
            confidence_score=0.70,
            player_alias="player_1",
            action_name="Phantom Dive",
            memory_type="attack_used",
        )
        db = _make_db([_make_row(item)], [])
        selected, _ = await _select_tiered_evidence(
            db,
            deck_card_ids=["sv-dragapult", "sv-drakloak", "sv-dreepy"],
            deck_card_names=["Dragapult ex", "Drakloak", "Dreepy"],
            candidate_card_ids=[],
            candidate_card_names=[],
            min_confidence=0.65,
            effective_limit=8,
            allow_fallback=False,
        )
        assert selected[0].label_boost <= 0.10

    @pytest.mark.asyncio
    async def test_label_boost_reorders_within_same_tier_only(self):
        """Label boost may reorder same-tier evidence."""
        from app.observed_play.coach_context import _select_tiered_evidence

        no_label_item = _make_item(
            item_id=_uuid("ab000003"),
            log_id=uuid.uuid4(),
            actor_card_def_id="sv-tech",
            actor_card_raw="Tech Card",
            confidence_score=0.80,
            player_alias="player_1",
        )
        label_item = _make_item(
            item_id=_uuid("ab000004"),
            log_id=uuid.uuid4(),
            actor_card_def_id="sv-dragapult",
            target_card_def_id="sv-drakloak",
            related_card_def_id="sv-dreepy",
            actor_card_raw="Dragapult ex",
            target_card_raw="Drakloak",
            related_card_raw="Dreepy",
            confidence_score=0.75,
            player_alias="player_1",
        )
        db = _make_db([_make_row(no_label_item), _make_row(label_item)], [])
        selected, _ = await _select_tiered_evidence(
            db,
            deck_card_ids=["sv-tech", "sv-dragapult", "sv-drakloak", "sv-dreepy"],
            deck_card_names=["Tech Card", "Dragapult ex", "Drakloak", "Dreepy"],
            candidate_card_ids=[],
            candidate_card_names=[],
            min_confidence=0.65,
            effective_limit=8,
            allow_fallback=False,
        )
        assert [str(c.item.id) for c in selected[:2]] == [str(_uuid("ab000004")), str(_uuid("ab000003"))]
        assert selected[0].tier == selected[1].tier == 1

    @pytest.mark.asyncio
    async def test_label_boost_cannot_outrank_higher_tier(self):
        """Tier ordering is preserved before label-adjusted score."""
        from app.observed_play.coach_context import _select_tiered_evidence

        tier1_item = _make_item(
            item_id=_uuid("ab000005"),
            log_id=uuid.uuid4(),
            actor_card_def_id="sv-tech",
            actor_card_raw="Tech Card",
            confidence_score=0.65,
        )
        tier2_item = _make_item(
            item_id=_uuid("ab000006"),
            log_id=uuid.uuid4(),
            actor_card_def_id=None,
            actor_card_raw="Dragapult ex",
            target_card_raw="Drakloak",
            related_card_raw="Dreepy",
            confidence_score=0.95,
            player_alias="player_1",
        )
        db = _make_db([_make_row(tier1_item)], [_make_row(tier2_item)])
        selected, _ = await _select_tiered_evidence(
            db,
            deck_card_ids=["sv-tech", "sv-dragapult", "sv-drakloak", "sv-dreepy"],
            deck_card_names=["Tech Card", "Dragapult ex", "Drakloak", "Dreepy"],
            candidate_card_ids=[],
            candidate_card_names=[],
            min_confidence=0.65,
            effective_limit=8,
            allow_fallback=False,
        )
        assert selected[0].tier == 1
        assert str(selected[0].item.id) == str(_uuid("ab000005"))
        assert selected[1].tier == 2
        assert selected[1].final_score > selected[0].final_score

    @pytest.mark.asyncio
    async def test_no_label_signals_do_not_crash_retrieval(self):
        """Retrieval with no deck-name signals (empty label context) completes safely."""
        from app.observed_play.coach_context import _select_tiered_evidence

        item = _make_item(
            item_id=_uuid("ab000008"),
            log_id=uuid.uuid4(),
            actor_card_def_id="sv-basic",
            actor_card_raw=None,
            confidence_score=0.80,
            player_alias=None,
        )
        db = _make_db([_make_row(item)], [])
        selected, _ = await _select_tiered_evidence(
            db,
            deck_card_ids=["sv-basic"],
            deck_card_names=[],  # no names → no label inference → no boost
            candidate_card_ids=[],
            candidate_card_names=[],
            min_confidence=0.65,
            effective_limit=8,
            allow_fallback=False,
        )
        assert len(selected) == 1
        assert selected[0].label_boost == 0.0
        assert selected[0].matched_label_keys == []
        assert selected[0].label_match_reason is None


# ── Tests for build_coach_context_preview (tiered path) ───────────────────────

class TestBuildCoachContextPreviewTiered:

    @pytest.mark.asyncio
    async def test_no_relevant_evidence_flag_on_when_tiered_empty(self):
        """no_relevant_evidence=True and would_inject=False when tiered returns nothing."""
        from app.observed_play.coach_context import build_coach_context_preview

        db = _make_db([], [])  # Tier 1 and Tier 2 empty
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv06-drag"],
                deck_card_names=["Dragapult ex"],
                allow_fallback=False,
            )
        assert preview.would_inject is False
        assert preview.no_relevant_evidence is True
        assert preview.prompt_block == ""
        assert preview.retrieval_metadata is not None
        assert preview.retrieval_metadata.strategy == "deck_overlap_v1"

    @pytest.mark.asyncio
    async def test_allow_fallback_in_preview_enables_global(self):
        """allow_fallback=True in preview returns global item with would_inject=True."""
        from app.observed_play.coach_context import build_coach_context_preview

        log_x = uuid.uuid4()
        global_item = _make_item(
            item_id=_uuid("77000001"), log_id=log_x,
            actor_card_def_id="sv99-salazzle", confidence_score=0.95,
        )
        db = _make_db([], [], [_make_row(global_item)])
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv06-drag"],
                deck_card_names=["Dragapult ex"],
                allow_fallback=True,
            )
        assert preview.would_inject is True
        assert preview.no_relevant_evidence is False
        assert preview.evidence_count == 1
        assert preview.retrieval_metadata is not None
        assert preview.retrieval_metadata.allow_fallback is True

    @pytest.mark.asyncio
    async def test_flag_off_returns_disabled_even_with_deck_context(self):
        """OBSERVED_PLAY_MEMORY_ENABLED=False returns disabled preview regardless of deck context."""
        from app.observed_play.coach_context import build_coach_context_preview

        db = AsyncMock()
        with patch("app.observed_play.coach_context.settings") as mock_settings:
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = False
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv06-drag"],
                deck_card_names=["Dragapult ex"],
            )
        assert preview.enabled is False
        assert preview.would_inject is False
        assert preview.prompt_block == ""
        assert preview.retrieval_metadata is None
        # DB should not have been queried
        db.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_label_metadata_in_tiered_preview(self):
        """Retrieval metadata exposes label strategy and per-evidence boost detail."""
        from app.observed_play.coach_context import build_coach_context_preview

        item = _make_item(
            item_id=_uuid("88000002"),
            log_id=uuid.uuid4(),
            actor_card_def_id="sv-dragapult",
            target_card_def_id="sv-drakloak",
            related_card_def_id="sv-dreepy",
            actor_card_raw="Dragapult ex",
            target_card_raw="Drakloak",
            related_card_raw="Dreepy",
            confidence_score=0.70,
            player_alias="player_1",
        )
        db = _make_db([_make_row(item)], [])
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.65
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult", "sv-drakloak", "sv-dreepy"],
                deck_card_names=["Dragapult ex", "Drakloak", "Dreepy"],
                allow_fallback=False,
            )

        meta = preview.retrieval_metadata
        assert meta is not None
        assert meta.strategy == "deck_overlap_v1"
        assert meta.label_strategy == "archetype_label_boost_v1"
        assert meta.label_ranking_enabled is True
        assert meta.label_boost_cap == 0.10
        assert meta.label_boost_applied_count == 1
        assert [label.canonical_key for label in meta.deck_labels] == [
            "dragapult-ex", "stage-2-setup", "spread-damage"
        ]
        detail = meta.evidence_selected[0]
        assert detail.base_relevance_score is not None
        assert detail.final_relevance_score == detail.relevance_score
        assert detail.label_boost == 0.10
        assert "dragapult-ex" in detail.matched_label_keys
        assert detail.source_log_labels[0].canonical_key == "dragapult-ex"
        assert "Matched current archetype label Dragapult ex" in detail.label_match_reason

    @pytest.mark.asyncio
    async def test_relevance_hints_in_prompt_block(self):
        """Tier 1 items include a relevance hint line in the prompt block."""
        from app.observed_play.coach_context import build_coach_context_preview

        log_a = uuid.uuid4()
        item = _make_item(
            item_id=_uuid("88000001"), log_id=log_a,
            actor_card_def_id="sv06-drag", confidence_score=0.91,
            actor_card_raw="Dragapult ex",
        )
        db = _make_db([_make_row(item)], [])
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv06-drag"],
                deck_card_names=["Dragapult ex"],
                include_relevance_hints=True,
            )
        assert preview.would_inject is True
        assert "Relevance:" in preview.prompt_block
        assert "tier 1" in preview.prompt_block

    @pytest.mark.asyncio
    async def test_legacy_path_preserved_when_no_deck_context(self):
        """Calling with no deck context uses Phase 6.1 path (no retrieval_metadata)."""
        from app.observed_play.coach_context import build_coach_context_preview

        log_a = uuid.uuid4()
        item = _make_item(
            item_id=_uuid("99000001"), log_id=log_a, confidence_score=0.90,
        )
        # Legacy path queries once (no Tier 1/2 split)
        legacy_result = MagicMock()
        legacy_result.all.return_value = [
            MagicMock(**{"__getitem__": lambda s, i: [item, str(log_a)][i]})
        ]
        # Simpler: use a tuple-like row
        class _LegacyRow:
            def __getitem__(self, i):
                return [item, log_a][i]
        legacy_result.all.return_value = [_LegacyRow()]

        db = AsyncMock()
        db.execute = AsyncMock(return_value=legacy_result)

        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(db)  # No deck context
        assert preview.enabled is True
        assert preview.retrieval_metadata is None  # legacy path doesn't set this
        assert preview.no_relevant_evidence is False

    @pytest.mark.asyncio
    async def test_no_observed_play_tables_written_during_retrieval(self):
        """Retrieval never calls db.add(), db.flush(), or db.delete()."""
        from app.observed_play.coach_context import build_coach_context_preview

        db = _make_db([], [])
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            await build_coach_context_preview(
                db,
                deck_card_ids=["sv06-drag"],
                deck_card_names=["Dragapult ex"],
            )
        db.add.assert_not_called()
        db.flush.assert_not_called()
        db.delete.assert_not_called()


# ── Tests for Phase 7.2b matchup context preview helpers ─────────────────────

class TestPrimaryArchetypeLabel:
    def _fn(self, labels):
        from app.observed_play.coach_context import _primary_archetype_label
        return _primary_archetype_label(labels)

    def _make_label(self, canonical_key, label_type="archetype", confidence=0.90):
        from app.observed_play.schemas import ArchetypeLabel
        return ArchetypeLabel(
            label=canonical_key,
            canonical_key=canonical_key,
            label_type=label_type,
            source="deck_cards",
            confidence=confidence,
            review_status="suggested",
            evidence_card_ids=[],
            evidence_card_names=[],
            evidence_counts={},
            evidence_event_ids=[],
            evidence_memory_item_ids=[],
            schema_version="archetype_label_v1",
        )

    def test_returns_highest_confidence_archetype_label(self):
        low = self._make_label("crustle", confidence=0.70)
        high = self._make_label("dragapult-ex", confidence=0.92)
        result = self._fn([low, high])
        assert result is not None
        assert result.canonical_key == "dragapult-ex"

    def test_ignores_non_archetype_labels(self):
        pkg = self._make_label("stage-2-setup", label_type="package", confidence=0.95)
        arch = self._make_label("dragapult-ex", label_type="archetype", confidence=0.80)
        result = self._fn([pkg, arch])
        assert result is not None
        assert result.canonical_key == "dragapult-ex"

    def test_returns_none_for_empty_list(self):
        assert self._fn([]) is None

    def test_returns_none_when_no_archetype_labels(self):
        pkg = self._make_label("spread-damage", label_type="strategy", confidence=0.85)
        assert self._fn([pkg]) is None


class TestComputeMatchupContext:
    def _fn(self, deck_labels, candidate_labels):
        from app.observed_play.coach_context import _compute_matchup_context
        return _compute_matchup_context(deck_labels, candidate_labels)

    def _make_label(self, canonical_key, label_type="archetype", confidence=0.90):
        from app.observed_play.schemas import ArchetypeLabel
        return ArchetypeLabel(
            label=canonical_key,
            canonical_key=canonical_key,
            label_type=label_type,
            source="deck_cards",
            confidence=confidence,
            review_status="suggested",
            evidence_card_ids=[],
            evidence_card_names=[],
            evidence_counts={},
            evidence_event_ids=[],
            evidence_memory_item_ids=[],
            schema_version="archetype_label_v1",
        )

    def test_directed_key_formed_when_both_archetypes_present(self):
        deck = [self._make_label("dragapult-ex", confidence=0.92)]
        cand = [self._make_label("gardevoir-ex", confidence=0.85)]
        ctx = self._fn(deck, cand)
        assert ctx["directed_matchup_key"] == "dragapult-ex|vs|gardevoir-ex"
        assert ctx["current_primary_archetype_key"] == "dragapult-ex"
        assert ctx["opponent_primary_archetype_key"] == "gardevoir-ex"
        assert ctx["no_matchup_signal_reason"] is None

    def test_direction_matters(self):
        deck = [self._make_label("gardevoir-ex", confidence=0.88)]
        cand = [self._make_label("dragapult-ex", confidence=0.90)]
        ctx = self._fn(deck, cand)
        assert ctx["directed_matchup_key"] == "gardevoir-ex|vs|dragapult-ex"

    def test_no_directed_key_when_current_archetype_absent(self):
        deck = [self._make_label("spread-damage", label_type="strategy", confidence=0.90)]
        cand = [self._make_label("gardevoir-ex", confidence=0.88)]
        ctx = self._fn(deck, cand)
        assert ctx["directed_matchup_key"] is None
        assert ctx["no_matchup_signal_reason"] == "no_current_archetype_label"

    def test_no_directed_key_when_opponent_archetype_absent(self):
        deck = [self._make_label("dragapult-ex", confidence=0.92)]
        cand = []
        ctx = self._fn(deck, cand)
        assert ctx["directed_matchup_key"] is None
        assert ctx["current_primary_archetype_key"] == "dragapult-ex"
        assert ctx["no_matchup_signal_reason"] == "no_opponent_archetype_label"

    def test_confidence_is_minimum_of_both(self):
        deck = [self._make_label("dragapult-ex", confidence=0.92)]
        cand = [self._make_label("crustle", confidence=0.70)]
        ctx = self._fn(deck, cand)
        assert ctx["matchup_confidence"] == pytest.approx(0.70, abs=0.001)

    def test_empty_inputs_return_no_directed_key(self):
        ctx = self._fn([], [])
        assert ctx["directed_matchup_key"] is None
        assert ctx["no_matchup_signal_reason"] == "no_current_archetype_label"


class TestSourceLogMatchupMetadata:
    """Tests for _source_log_matchup_metadata — per-evidence source-log player assignment."""

    def _make_label(self, canonical_key, label_type="archetype", confidence=0.90):
        from app.observed_play.schemas import ArchetypeLabel
        return ArchetypeLabel(
            label=canonical_key,
            canonical_key=canonical_key,
            label_type=label_type,
            source="observed_log",
            confidence=confidence,
            review_status="suggested",
            evidence_card_ids=[],
            evidence_card_names=[],
            evidence_counts={},
            evidence_event_ids=[],
            evidence_memory_item_ids=[],
            schema_version="archetype_label_v1",
        )

    def _make_cand(self, log_id: str):
        from app.observed_play.coach_context import _RawCandidate
        item = MagicMock()
        return _RawCandidate(item=item, log_id=log_id, tier=1, base_score=0.90)

    def _make_preview(self, log_id: str, labels_by_player: dict):
        from app.observed_play.schemas import ObservedLogArchetypeLabelPreview
        return ObservedLogArchetypeLabelPreview(
            observed_play_log_id=log_id,
            labels_by_player=labels_by_player,
        )

    def _fn(self, cand, label_cache, current_primary_key):
        from app.observed_play.coach_context import _source_log_matchup_metadata
        return _source_log_matchup_metadata(cand, label_cache, current_primary_key)

    def test_full_assignment_produces_directed_key(self):
        """Both players identified → source_log_matchup_key is formed."""
        log_id = str(uuid.uuid4())
        cand = self._make_cand(log_id)
        preview = self._make_preview(log_id, {
            "player_1": [self._make_label("dragapult-ex")],
            "player_2": [self._make_label("gardevoir-ex")],
        })
        result = self._fn(cand, {log_id: preview}, "dragapult-ex")
        assert result["source_log_matchup_key"] == "dragapult-ex|vs|gardevoir-ex"
        assert result["matchup_match_reason"] is not None
        assert "dragapult-ex" in result["matchup_match_reason"]
        assert "gardevoir-ex" in result["matchup_match_reason"]

    def test_partial_assignment_returns_null_key_not_unknown_suffix(self):
        """Current player identified but opponent has no archetype label → source_log_matchup_key=None.

        Regression test for |vs|unknown overclaiming fix.
        """
        log_id = str(uuid.uuid4())
        cand = self._make_cand(log_id)
        # player_2 has only strategy labels, not archetype
        preview = self._make_preview(log_id, {
            "player_1": [self._make_label("dragapult-ex")],
            "player_2": [self._make_label("spread-damage", label_type="strategy")],
        })
        result = self._fn(cand, {log_id: preview}, "dragapult-ex")
        # Must NOT produce |vs|unknown — that overclaims
        assert result["source_log_matchup_key"] is None
        assert result["matchup_match_reason"] is None
        # Player labels should still be populated
        assert len(result["source_log_current_player_labels"]) >= 1

    def test_no_current_primary_key_returns_null(self):
        """current_primary_key=None → all fields are None/empty."""
        log_id = str(uuid.uuid4())
        cand = self._make_cand(log_id)
        preview = self._make_preview(log_id, {"player_1": [self._make_label("dragapult-ex")]})
        result = self._fn(cand, {log_id: preview}, None)
        assert result["source_log_matchup_key"] is None
        assert result["matchup_match_reason"] is None
        assert result["source_log_current_player_labels"] == []

    def test_no_cache_entry_returns_null(self):
        """Missing label cache entry → all fields null."""
        log_id = str(uuid.uuid4())
        cand = self._make_cand(log_id)
        result = self._fn(cand, {}, "dragapult-ex")
        assert result["source_log_matchup_key"] is None
        assert result["matchup_match_reason"] is None

    def test_no_player_matches_current_primary_key(self):
        """Neither player alias matches current_primary_key → null key, no overclaiming."""
        log_id = str(uuid.uuid4())
        cand = self._make_cand(log_id)
        preview = self._make_preview(log_id, {
            "player_1": [self._make_label("crustle")],
            "player_2": [self._make_label("gardevoir-ex")],
        })
        result = self._fn(cand, {log_id: preview}, "dragapult-ex")
        assert result["source_log_matchup_key"] is None
        assert result["matchup_match_reason"] is None

class TestMatchupMetadataInTieredPreview:

    @pytest.mark.asyncio
    async def test_matchup_strategy_present_in_tiered_metadata(self):
        """Tiered retrieval metadata includes matchup_strategy=matchup_context_boost_v1."""
        from app.observed_play.coach_context import build_coach_context_preview

        item = _make_item(
            item_id=_uuid("7b000001"),
            log_id=uuid.uuid4(),
            actor_card_def_id="sv-dragapult",
            actor_card_raw="Dragapult ex",
            confidence_score=0.88,
        )
        db = _make_db([_make_row(item)], [])
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult"],
                deck_card_names=["Dragapult ex"],
                allow_fallback=False,
            )
        meta = preview.retrieval_metadata
        assert meta is not None
        assert meta.matchup_strategy == "matchup_context_boost_v1"
        assert meta.matchup_context_enabled is True
        assert meta.matchup_ranking_enabled is False
        assert meta.matchup_candidate_pool_expanded is False
        assert meta.matchup_filter_applied is False

    @pytest.mark.asyncio
    async def test_matchup_boost_is_zero_without_opponent_context(self):
        """Without opponent context, coverage gate is never triggered; matchup_boost=0.0 on all evidence."""
        from app.observed_play.coach_context import build_coach_context_preview

        item = _make_item(
            item_id=_uuid("7b000002"),
            log_id=uuid.uuid4(),
            actor_card_def_id="sv-dragapult",
            target_card_def_id="sv-drakloak",
            related_card_def_id="sv-dreepy",
            actor_card_raw="Dragapult ex",
            target_card_raw="Drakloak",
            related_card_raw="Dreepy",
            confidence_score=0.70,
            player_alias="player_1",
        )
        db = _make_db([_make_row(item)], [])
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.65
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult", "sv-drakloak", "sv-dreepy"],
                deck_card_names=["Dragapult ex", "Drakloak", "Dreepy"],
                allow_fallback=False,
            )
        meta = preview.retrieval_metadata
        assert meta is not None
        for detail in meta.evidence_selected:
            assert detail.matchup_boost == 0.0

    @pytest.mark.asyncio
    async def test_scores_and_order_unchanged_when_matchup_boost_is_zero(self):
        """Without opponent context, matchup_boost=0.0, so relevance_score order is unchanged."""
        from app.observed_play.coach_context import build_coach_context_preview

        log_a, log_b = uuid.uuid4(), uuid.uuid4()
        item_a = _make_item(
            item_id=_uuid("7b000003"), log_id=log_a,
            actor_card_def_id="sv-dragapult", actor_card_raw="Dragapult ex",
            confidence_score=0.91, player_alias="player_1",
        )
        item_b = _make_item(
            item_id=_uuid("7b000004"), log_id=log_b,
            actor_card_def_id="sv-dragapult", actor_card_raw="Dragapult ex",
            confidence_score=0.88, player_alias="player_1",
        )

        async def _run():
            db = _make_db([_make_row(item_a), _make_row(item_b)], [])
            with patch("app.observed_play.coach_context.settings") as mock_settings, \
                 patch(
                     "app.observed_play.coach_context.compute_corpus_readiness",
                     new=AsyncMock(return_value=_ready_readiness()),
                 ):
                mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
                mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
                mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
                return await build_coach_context_preview(
                    db,
                    deck_card_ids=["sv-dragapult"],
                    deck_card_names=["Dragapult ex"],
                    allow_fallback=False,
                )

        preview = await _run()
        meta = preview.retrieval_metadata
        assert meta is not None
        ids = [d.memory_item_id for d in meta.evidence_selected]
        scores = [d.relevance_score for d in meta.evidence_selected]
        # Order: item_a before item_b (higher confidence)
        assert ids[0] == str(_uuid("7b000003"))
        assert ids[1] == str(_uuid("7b000004"))
        # Score formula: base + label_boost + matchup_boost (0.0 here — no opponent context)
        for detail in meta.evidence_selected:
            assert detail.final_relevance_score == pytest.approx(
                detail.base_relevance_score + detail.label_boost + detail.matchup_boost, abs=0.0001
            )

    @pytest.mark.asyncio
    async def test_directed_matchup_key_in_metadata_when_opponent_present(self):
        """directed_matchup_key is populated when both deck and candidate have archetype labels."""
        from app.observed_play.coach_context import build_coach_context_preview

        item = _make_item(
            item_id=_uuid("7b000005"),
            log_id=uuid.uuid4(),
            actor_card_def_id="sv-dragapult",
            actor_card_raw="Dragapult ex",
            confidence_score=0.88,
        )
        db = _make_db([_make_row(item)], [])
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult"],
                deck_card_names=["Dragapult ex"],
                candidate_card_ids=["sv-gardevoir"],
                candidate_card_names=["Gardevoir ex"],
                allow_fallback=False,
            )
        meta = preview.retrieval_metadata
        assert meta is not None
        assert meta.directed_matchup_key is not None
        assert "|vs|" in meta.directed_matchup_key
        assert meta.no_matchup_signal_reason is None
        assert meta.matchup_confidence is not None

    @pytest.mark.asyncio
    async def test_no_matchup_signal_when_no_opponent_cards(self):
        """no_matchup_signal_reason populated when candidate cards produce no archetype label."""
        from app.observed_play.coach_context import build_coach_context_preview

        item = _make_item(
            item_id=_uuid("7b000006"),
            log_id=uuid.uuid4(),
            actor_card_def_id="sv-dragapult",
            actor_card_raw="Dragapult ex",
            confidence_score=0.88,
        )
        db = _make_db([_make_row(item)], [])
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult"],
                deck_card_names=["Dragapult ex"],
                # No candidate cards → no opponent archetype label
                allow_fallback=False,
            )
        meta = preview.retrieval_metadata
        assert meta is not None
        assert meta.directed_matchup_key is None
        assert meta.no_matchup_signal_reason == "no_opponent_archetype_label"

    @pytest.mark.asyncio
    async def test_no_evidence_path_still_has_matchup_context(self):
        """no_relevant_evidence path still returns matchup context in retrieval_metadata."""
        from app.observed_play.coach_context import build_coach_context_preview

        db = _make_db([], [])
        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult"],
                deck_card_names=["Dragapult ex"],
                allow_fallback=False,
            )
        assert preview.would_inject is False
        assert preview.no_relevant_evidence is True
        meta = preview.retrieval_metadata
        assert meta is not None
        assert meta.matchup_strategy == "matchup_context_boost_v1"
        assert meta.matchup_ranking_enabled is False

    @pytest.mark.asyncio
    async def test_flag_off_matchup_context_absent(self):
        """When flag is off, retrieval_metadata is None and no matchup context is computed."""
        from app.observed_play.coach_context import build_coach_context_preview

        db = AsyncMock()
        with patch("app.observed_play.coach_context.settings") as mock_settings:
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = False
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult"],
                deck_card_names=["Dragapult ex"],
            )
        assert preview.enabled is False
        assert preview.retrieval_metadata is None


# ── Tests for Phase 7.2c guarded matchup boost ───────────────────────────────

class TestMatchupCoverageAndBoost:
    """Phase 7.2c: guarded matchup boost — coverage gate and boost application."""

    def _make_label(self, canonical_key, label_type="archetype", confidence=0.90):
        from app.observed_play.schemas import ArchetypeLabel
        return ArchetypeLabel(
            label=canonical_key,
            canonical_key=canonical_key,
            label_type=label_type,
            source="observed_log",
            confidence=confidence,
            review_status="suggested",
            evidence_card_ids=[],
            evidence_card_names=[],
            evidence_counts={},
            evidence_event_ids=[],
            evidence_memory_item_ids=[],
            schema_version="archetype_label_v1",
        )

    def _make_preview(self, log_id, player1_key, player2_key=None, ambiguous=False):
        """Build a controlled ObservedLogArchetypeLabelPreview."""
        from app.observed_play.schemas import ObservedLogArchetypeLabelPreview
        labels_by_player = {}
        if player1_key:
            labels_by_player["player_1"] = [self._make_label(player1_key)]
        if player2_key:
            labels_by_player["player_2"] = [self._make_label(player2_key)]
        return ObservedLogArchetypeLabelPreview(
            observed_play_log_id=str(log_id),
            ambiguous=ambiguous,
            labels_by_player=labels_by_player,
        )

    class _CovRow:
        """Row wrapper for coverage query (select(ObservedPlayMemoryItem))."""
        def __init__(self, item):
            self._item = item
        def __getitem__(self, idx):
            return self._item

    # ── 1. Coverage helper counts only clean directed matchup logs ──────────

    @pytest.mark.asyncio
    async def test_coverage_counts_clean_directed_logs(self):
        """Coverage helper counts logs where both sides have primary archetype labels."""
        from app.observed_play.coach_context import _count_directed_matchup_logs

        log_ids = [uuid.uuid4() for _ in range(3)]
        items = [
            _make_item(
                log_id=lid,
                player_alias="player_1",
                actor_card_raw="Dragapult ex",
                actor_card_def_id="sv-drag",
            )
            for lid in log_ids
        ]
        cov_rows = [self._CovRow(it) for it in items]
        db = _make_db(cov_rows)

        def _mock_infer(log_id, signals):
            return self._make_preview(log_id, "dragapult-ex", "gardevoir-ex")

        with patch(
            "app.observed_play.coach_context.infer_observed_log_labels_from_signals",
            side_effect=_mock_infer,
        ):
            count, reason = await _count_directed_matchup_logs(
                db, "dragapult-ex|vs|gardevoir-ex", "dragapult-ex"
            )

        assert count == 3
        assert "boost eligible" in reason

    # ── 2. Coverage helper ignores ambiguous logs ──────────────────────────

    @pytest.mark.asyncio
    async def test_coverage_ignores_ambiguous_logs(self):
        """Coverage helper skips logs whose preview is marked ambiguous."""
        from app.observed_play.coach_context import _count_directed_matchup_logs

        log_id = uuid.uuid4()
        item = _make_item(log_id=log_id, player_alias="player_1", actor_card_raw="Dragapult ex")
        db = _make_db([self._CovRow(item)])

        def _mock_infer(lid, signals):
            return self._make_preview(lid, "dragapult-ex", "gardevoir-ex", ambiguous=True)

        with patch(
            "app.observed_play.coach_context.infer_observed_log_labels_from_signals",
            side_effect=_mock_infer,
        ):
            count, _ = await _count_directed_matchup_logs(
                db, "dragapult-ex|vs|gardevoir-ex", "dragapult-ex"
            )

        assert count == 0

    # ── 3. Coverage helper ignores one-sided logs ──────────────────────────

    @pytest.mark.asyncio
    async def test_coverage_ignores_one_sided_logs(self):
        """Logs with only one player labeled do not count towards coverage."""
        from app.observed_play.coach_context import _count_directed_matchup_logs

        log_id = uuid.uuid4()
        item = _make_item(log_id=log_id, player_alias="player_1", actor_card_raw="Dragapult ex")
        db = _make_db([self._CovRow(item)])

        def _mock_infer(lid, signals):
            # Only player_1 has a label — opponent side unknown
            return self._make_preview(lid, "dragapult-ex", player2_key=None)

        with patch(
            "app.observed_play.coach_context.infer_observed_log_labels_from_signals",
            side_effect=_mock_infer,
        ):
            count, _ = await _count_directed_matchup_logs(
                db, "dragapult-ex|vs|gardevoir-ex", "dragapult-ex"
            )

        assert count == 0

    # ── 4. Mirror match doesn't count for a different directed pair ─────────

    @pytest.mark.asyncio
    async def test_coverage_ignores_mirror_match_for_different_pair(self):
        """A dragapult-ex vs dragapult-ex mirror match doesn't count for dragapult-ex|vs|gardevoir-ex."""
        from app.observed_play.coach_context import _count_directed_matchup_logs

        log_id = uuid.uuid4()
        item = _make_item(log_id=log_id, player_alias="player_1", actor_card_raw="Dragapult ex")
        db = _make_db([self._CovRow(item)])

        def _mock_infer(lid, signals):
            return self._make_preview(lid, "dragapult-ex", "dragapult-ex")

        with patch(
            "app.observed_play.coach_context.infer_observed_log_labels_from_signals",
            side_effect=_mock_infer,
        ):
            count, _ = await _count_directed_matchup_logs(
                db, "dragapult-ex|vs|gardevoir-ex", "dragapult-ex"
            )

        assert count == 0

    # ── 5. Directed pair with ≥3 logs is eligible ──────────────────────────

    @pytest.mark.asyncio
    async def test_directed_pair_with_three_logs_is_eligible(self):
        """matchup_pair_eligible=True and matchup_ranking_enabled=True when coverage >= 3."""
        from app.observed_play.coach_context import build_coach_context_preview

        log_ids = [uuid.uuid4() for _ in range(3)]
        items = [
            _make_item(
                log_id=lid, actor_card_def_id="sv-dragapult",
                actor_card_raw="Dragapult ex", confidence_score=0.88, player_alias="player_1",
            )
            for lid in log_ids
        ]
        # Tier 1 rows for evidence selection, then coverage rows
        tier1_rows = [_make_row(items[0])]
        cov_rows = [self._CovRow(it) for it in items]

        db = _make_db(tier1_rows, [], cov_rows)

        def _mock_infer(lid, signals):
            return self._make_preview(lid, "dragapult-ex", "gardevoir-ex")

        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ), \
             patch(
                 "app.observed_play.coach_context.infer_observed_log_labels_from_signals",
                 side_effect=_mock_infer,
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult"],
                deck_card_names=["Dragapult ex"],
                candidate_card_ids=["sv-gardevoir"],
                candidate_card_names=["Gardevoir ex"],
                allow_fallback=False,
            )

        meta = preview.retrieval_metadata
        assert meta is not None
        assert meta.matchup_pair_eligible is True
        assert meta.matchup_ranking_enabled is True
        assert meta.matchup_pair_log_count == 3
        assert meta.matchup_strategy == "matchup_context_boost_v1"

    # ── 6. Directed pair with <3 logs is not eligible ──────────────────────

    @pytest.mark.asyncio
    async def test_directed_pair_with_two_logs_is_not_eligible(self):
        """matchup_pair_eligible=False when coverage < 3."""
        from app.observed_play.coach_context import build_coach_context_preview

        log_ids = [uuid.uuid4() for _ in range(2)]
        items = [
            _make_item(
                log_id=lid, actor_card_def_id="sv-dragapult",
                actor_card_raw="Dragapult ex", confidence_score=0.88, player_alias="player_1",
            )
            for lid in log_ids
        ]
        tier1_rows = [_make_row(items[0])]
        cov_rows = [self._CovRow(it) for it in items]

        db = _make_db(tier1_rows, [], cov_rows)

        def _mock_infer(lid, signals):
            return self._make_preview(lid, "dragapult-ex", "gardevoir-ex")

        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ), \
             patch(
                 "app.observed_play.coach_context.infer_observed_log_labels_from_signals",
                 side_effect=_mock_infer,
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult"],
                deck_card_names=["Dragapult ex"],
                candidate_card_ids=["sv-gardevoir"],
                candidate_card_names=["Gardevoir ex"],
                allow_fallback=False,
            )

        meta = preview.retrieval_metadata
        assert meta is not None
        assert meta.matchup_pair_eligible is False
        assert meta.matchup_ranking_enabled is False
        assert meta.matchup_pair_log_count == 2

    # ── 7. Unseen matchup is not eligible and does not error ───────────────

    @pytest.mark.asyncio
    async def test_unseen_matchup_is_not_eligible_and_no_error(self):
        """Unseen matchup with 0 coverage logs → not eligible, no exception."""
        from app.observed_play.coach_context import build_coach_context_preview

        item = _make_item(
            log_id=uuid.uuid4(), actor_card_def_id="sv-dragapult",
            actor_card_raw="Dragapult ex", confidence_score=0.88,
        )
        db = _make_db([_make_row(item)], [], [])  # empty coverage

        def _mock_infer(lid, signals):
            # All corpus logs are of a completely different matchup
            return self._make_preview(lid, "charizard-ex", "pikachu-ex")

        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ), \
             patch(
                 "app.observed_play.coach_context.infer_observed_log_labels_from_signals",
                 side_effect=_mock_infer,
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult"],
                deck_card_names=["Dragapult ex"],
                candidate_card_ids=["sv-gardevoir"],
                candidate_card_names=["Gardevoir ex"],
                allow_fallback=False,
            )

        meta = preview.retrieval_metadata
        assert meta is not None
        assert meta.matchup_pair_eligible is False
        assert meta.matchup_ranking_enabled is False
        assert meta.matchup_pair_log_count == 0
        assert meta.matchup_boost_applied_count == 0

    # ── 8. Eligible pair applies boost to matching evidence ────────────────

    @pytest.mark.asyncio
    async def test_eligible_pair_applies_boost_to_matching_evidence(self):
        """When eligible, evidence from a log with matching directed matchup key gets matchup_boost > 0."""
        from app.observed_play.coach_context import build_coach_context_preview

        log_a = uuid.uuid4()
        item_a = _make_item(
            log_id=log_a, actor_card_def_id="sv-dragapult",
            actor_card_raw="Dragapult ex", confidence_score=0.88, player_alias="player_1",
        )
        # Coverage items: 3 matching logs (log_a + 2 more)
        cov_log_ids = [log_a, uuid.uuid4(), uuid.uuid4()]
        cov_items = [
            _make_item(log_id=lid, player_alias="player_1", actor_card_raw="Dragapult ex")
            for lid in cov_log_ids
        ]
        cov_rows = [self._CovRow(it) for it in cov_items]

        db = _make_db([_make_row(item_a)], [], cov_rows)

        def _mock_infer(lid, signals):
            return self._make_preview(str(lid), "dragapult-ex", "gardevoir-ex")

        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ), \
             patch(
                 "app.observed_play.coach_context.infer_observed_log_labels_from_signals",
                 side_effect=_mock_infer,
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult"],
                deck_card_names=["Dragapult ex"],
                candidate_card_ids=["sv-gardevoir"],
                candidate_card_names=["Gardevoir ex"],
                allow_fallback=False,
            )

        meta = preview.retrieval_metadata
        assert meta is not None
        assert meta.matchup_boost_applied_count >= 1
        assert meta.evidence_selected[0].matchup_boost > 0.0

    # ── 9. Non-matching source_log_matchup_key gets boost=0.0 ─────────────

    @pytest.mark.asyncio
    async def test_non_matching_source_log_gets_zero_boost(self):
        """Evidence from a log that doesn't match the directed matchup key gets matchup_boost=0.0."""
        from app.observed_play.coach_context import build_coach_context_preview

        log_a = uuid.uuid4()
        item_a = _make_item(
            log_id=log_a, actor_card_def_id="sv-dragapult",
            actor_card_raw="Dragapult ex", confidence_score=0.88, player_alias="player_1",
        )
        # Coverage: 3 logs matching dragapult vs gardevoir
        cov_items = [
            _make_item(log_id=uuid.uuid4(), player_alias="player_1", actor_card_raw="Dragapult ex")
            for _ in range(3)
        ]

        db = _make_db([_make_row(item_a)], [], [self._CovRow(it) for it in cov_items])

        call_count = [0]

        def _mock_infer(lid, signals):
            call_count[0] += 1
            # Coverage logs return dragapult vs gardevoir (eligible)
            # But the selected evidence log_a is from a charizard vs pikachu game
            lid_str = str(lid)
            if lid_str == str(log_a):
                return self._make_preview(lid_str, "charizard-ex", "pikachu-ex")
            return self._make_preview(lid_str, "dragapult-ex", "gardevoir-ex")

        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ), \
             patch(
                 "app.observed_play.coach_context.infer_observed_log_labels_from_signals",
                 side_effect=_mock_infer,
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult"],
                deck_card_names=["Dragapult ex"],
                candidate_card_ids=["sv-gardevoir"],
                candidate_card_names=["Gardevoir ex"],
                allow_fallback=False,
            )

        meta = preview.retrieval_metadata
        assert meta is not None
        assert meta.matchup_ranking_enabled is True  # coverage gate met
        assert meta.evidence_selected[0].matchup_boost == 0.0  # this log doesn't match

    # ── 10. Boost cap enforced at 0.12 ─────────────────────────────────────

    def test_matchup_boost_cap_is_0_12(self):
        """_MATCHUP_BOOST_CAP constant is exactly 0.12."""
        from app.observed_play.coach_context import _MATCHUP_BOOST_CAP
        assert _MATCHUP_BOOST_CAP == 0.12

    # ── 11. final_relevance_score = base + label_boost + matchup_boost ─────

    @pytest.mark.asyncio
    async def test_final_score_composition_with_matchup_boost(self):
        """final_relevance_score = base_relevance_score + label_boost + matchup_boost."""
        from app.observed_play.coach_context import build_coach_context_preview

        log_a = uuid.uuid4()
        item_a = _make_item(
            log_id=log_a, actor_card_def_id="sv-dragapult",
            actor_card_raw="Dragapult ex", confidence_score=0.88, player_alias="player_1",
        )
        cov_items = [
            _make_item(log_id=uuid.uuid4(), player_alias="player_1", actor_card_raw="Dragapult ex")
            for _ in range(3)
        ]

        db = _make_db([_make_row(item_a)], [], [self._CovRow(it) for it in cov_items])

        def _mock_infer(lid, signals):
            return self._make_preview(str(lid), "dragapult-ex", "gardevoir-ex")

        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ), \
             patch(
                 "app.observed_play.coach_context.infer_observed_log_labels_from_signals",
                 side_effect=_mock_infer,
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult"],
                deck_card_names=["Dragapult ex"],
                candidate_card_ids=["sv-gardevoir"],
                candidate_card_names=["Gardevoir ex"],
                allow_fallback=False,
            )

        meta = preview.retrieval_metadata
        assert meta is not None
        for detail in meta.evidence_selected:
            expected = (detail.base_relevance_score or 0.0) + detail.label_boost + detail.matchup_boost
            assert detail.final_relevance_score == pytest.approx(expected, abs=0.0002)

    # ── 12. Same-tier evidence may reorder by matchup boost ────────────────

    @pytest.mark.asyncio
    async def test_same_tier_reorder_by_matchup_boost(self):
        """Same-tier evidence with matchup boost outranks same-tier evidence without it."""
        from app.observed_play.coach_context import build_coach_context_preview

        # log_a: matches the directed matchup key — gets boost
        # log_b: does not match — lower final score
        # Initially log_b has higher base confidence, but boost should put log_a first
        log_a = uuid.uuid4()
        log_b = uuid.uuid4()
        item_a = _make_item(
            item_id=_uuid("c0000001"), log_id=log_a,
            actor_card_def_id="sv-dragapult", actor_card_raw="Dragapult ex",
            confidence_score=0.88, player_alias="player_1",
        )
        item_b = _make_item(
            item_id=_uuid("c0000002"), log_id=log_b,
            actor_card_def_id="sv-dragapult", actor_card_raw="Dragapult ex",
            confidence_score=0.92,  # higher base confidence
            player_alias="player_1",
        )
        # Coverage: 3 logs confirming dragapult-ex|vs|gardevoir-ex
        cov_items = [
            _make_item(log_id=uuid.uuid4(), player_alias="player_1", actor_card_raw="Dragapult ex")
            for _ in range(3)
        ]

        db = _make_db(
            [_make_row(item_a), _make_row(item_b)], [],
            [self._CovRow(it) for it in cov_items],
        )

        def _mock_infer(lid, signals):
            lid_str = str(lid)
            if lid_str == str(log_a):
                return self._make_preview(lid_str, "dragapult-ex", "gardevoir-ex")
            elif lid_str == str(log_b):
                # log_b is from a different matchup — no boost
                return self._make_preview(lid_str, "charizard-ex", "gardevoir-ex")
            # Coverage logs
            return self._make_preview(lid_str, "dragapult-ex", "gardevoir-ex")

        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ), \
             patch(
                 "app.observed_play.coach_context.infer_observed_log_labels_from_signals",
                 side_effect=_mock_infer,
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult"],
                deck_card_names=["Dragapult ex"],
                candidate_card_ids=["sv-gardevoir"],
                candidate_card_names=["Gardevoir ex"],
                allow_fallback=False,
            )

        meta = preview.retrieval_metadata
        assert meta is not None
        # log_a should be ranked first due to matchup boost despite lower base confidence
        ids = [d.memory_item_id for d in meta.evidence_selected]
        assert ids[0] == str(_uuid("c0000001"))  # log_a first
        assert meta.evidence_selected[0].matchup_boost == pytest.approx(0.12, abs=0.001)
        assert meta.evidence_selected[1].matchup_boost == 0.0

    # ── 13. Lower-tier evidence with boost cannot outrank higher-tier ───────

    @pytest.mark.asyncio
    async def test_tier_invariant_lower_tier_with_boost_cannot_outrank_higher_tier(self):
        """Tier 1 evidence without boost stays above Tier 2 evidence with matchup boost."""
        from app.observed_play.coach_context import build_coach_context_preview

        log_a = uuid.uuid4()  # Tier 1, no matchup boost
        log_b = uuid.uuid4()  # Tier 2, gets matchup boost

        item_tier1 = _make_item(
            item_id=_uuid("d0000001"), log_id=log_a,
            actor_card_def_id="sv-dragapult", actor_card_raw="Dragapult ex",
            confidence_score=0.88, player_alias="player_1",
        )
        item_tier2 = _make_item(
            item_id=_uuid("d0000002"), log_id=log_b,
            actor_card_raw="Dragapult ex",  # name match only → tier 2
            actor_card_def_id=None,
            confidence_score=0.90, player_alias="player_1",
        )
        cov_items = [
            _make_item(log_id=uuid.uuid4(), player_alias="player_1", actor_card_raw="Dragapult ex")
            for _ in range(3)
        ]

        db = _make_db(
            [_make_row(item_tier1)],   # Tier 1 results
            [_make_row(item_tier2)],   # Tier 2 results
            [self._CovRow(it) for it in cov_items],
        )

        def _mock_infer(lid, signals):
            # Both logs match the directed matchup key
            return self._make_preview(str(lid), "dragapult-ex", "gardevoir-ex")

        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ), \
             patch(
                 "app.observed_play.coach_context.infer_observed_log_labels_from_signals",
                 side_effect=_mock_infer,
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult"],
                deck_card_names=["Dragapult ex"],
                candidate_card_ids=["sv-gardevoir"],
                candidate_card_names=["Gardevoir ex"],
                allow_fallback=False,
            )

        meta = preview.retrieval_metadata
        assert meta is not None
        assert len(meta.evidence_selected) == 2
        # Tier 1 must be first regardless of matchup boost on tier 2
        assert meta.evidence_selected[0].tier == 1
        assert meta.evidence_selected[1].tier == 2

    # ── 14. no_relevant_evidence remains no evidence ────────────────────────

    @pytest.mark.asyncio
    async def test_no_relevant_evidence_remains_no_evidence_with_coverage(self):
        """no_relevant_evidence=True even when matchup coverage >= 3; no evidence injected."""
        from app.observed_play.coach_context import build_coach_context_preview

        # No evidence (tier1+2 empty, allow_fallback=False)
        cov_items = [
            _make_item(log_id=uuid.uuid4(), player_alias="player_1", actor_card_raw="Dragapult ex")
            for _ in range(3)
        ]
        db = _make_db([], [], [self._CovRow(it) for it in cov_items])

        def _mock_infer(lid, signals):
            return self._make_preview(str(lid), "dragapult-ex", "gardevoir-ex")

        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ), \
             patch(
                 "app.observed_play.coach_context.infer_observed_log_labels_from_signals",
                 side_effect=_mock_infer,
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult"],
                deck_card_names=["Dragapult ex"],
                candidate_card_ids=["sv-gardevoir"],
                candidate_card_names=["Gardevoir ex"],
                allow_fallback=False,
            )

        assert preview.would_inject is False
        assert preview.no_relevant_evidence is True
        assert preview.evidence_count == 0
        meta = preview.retrieval_metadata
        assert meta is not None
        assert len(meta.evidence_selected) == 0

    # ── 15. allow_fallback=False behavior unchanged ─────────────────────────

    @pytest.mark.asyncio
    async def test_allow_fallback_false_behavior_unchanged(self):
        """allow_fallback=False still returns no evidence when no deck overlap."""
        from app.observed_play.coach_context import build_coach_context_preview

        db = _make_db([], [])

        with patch("app.observed_play.coach_context.settings") as mock_settings, \
             patch(
                 "app.observed_play.coach_context.compute_corpus_readiness",
                 new=AsyncMock(return_value=_ready_readiness()),
             ):
            mock_settings.OBSERVED_PLAY_MEMORY_ENABLED = True
            mock_settings.OBSERVED_PLAY_MEMORY_MAX_EVIDENCE = 8
            mock_settings.OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE = 0.85
            preview = await build_coach_context_preview(
                db,
                deck_card_ids=["sv-dragapult"],
                deck_card_names=["Dragapult ex"],
                allow_fallback=False,
            )

        assert preview.would_inject is False
        assert preview.no_relevant_evidence is True

    # ── 16. Strategy name updated to boost_v1 ──────────────────────────────

    def test_matchup_strategy_name_is_boost_v1(self):
        """_MATCHUP_STRATEGY constant is matchup_context_boost_v1."""
        from app.observed_play.coach_context import _MATCHUP_STRATEGY
        assert _MATCHUP_STRATEGY == "matchup_context_boost_v1"
