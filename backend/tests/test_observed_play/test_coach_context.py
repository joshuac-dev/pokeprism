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
    return item


def _make_row(item, winner_alias=None, self_player_index=None, p1=None, p2=None):
    """Simulate a SQLAlchemy Row for _select_tiered_evidence indexing."""
    values = [item, winner_alias, self_player_index, p1, p2]

    class _Row:
        def __getitem__(self, idx):
            return values[idx]

    return _Row()


def _make_db(*per_call_rows):
    """Mock async DB session returning given row lists on successive execute() calls."""
    db = AsyncMock()
    results = []
    for rows in per_call_rows:
        r = MagicMock()
        r.all.return_value = rows
        results.append(r)
    db.execute = AsyncMock(side_effect=results)
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
