# Phase 7.2c UX / Coach-Debug Validation Report

**Verdict:** ready_for_parallel_corpus_expansion
**Date:** 2026-05-10
**Branch:** phase-7-2c-post-merge-ux-debug-validation
**Baseline commit:** f4399a059f0280ae2869fabe84c5cf51561e0b4a
**Environment:** Local dev (Docker Compose)

## Summary

Phase 7.2c (guarded matchup boost, `matchup_context_boost_v1`) was validated
against four retrieval contexts using the backend Python layer directly
(`build_coach_context_preview` with `OBSERVED_PLAY_MEMORY_ENABLED=true` via env
override). All metadata fields were inspected. All contexts returned the expected
fallback behavior: `matchup_pair_eligible=False`, `matchup_boost_applied_count=0`,
`matchup_ranking_enabled=False`, consistent with a corpus where no directed pair
has ≥3 clean logs.

One minor UI gap was found and fixed: `matchup_boost_applied_count` was previously
hidden when its value was 0, making it impossible for a coach-debugger to
explicitly confirm "boost was considered but applied to 0 items." The fix always
shows the count when the 7.2c boost section is active. One matching test was
added. All 380 frontend tests pass; build is clean.

The implementation is correct, fallback-safe, and coach-debuggable. No retrieval
behavior was changed. Corpus expansion continues in parallel.

## Corpus Counts

| Table | Count (pre-validation) | Count (post-validation) |
|---|---|---|
| observed_play_logs | 49 | 49 |
| observed_play_events | 10,047 | 10,047 |
| observed_card_mentions | 8,670 | 8,670 |
| observed_play_memory_items | 4,786 | 4,786 |
| observed_play_memory_ingestions | 198 | 198 |

Validation is read-only; no corpus changes.

## API Contexts Checked

> Note: The public REST API does not expose a POST endpoint that accepts
> `deck_card_ids` and `current_opponent_archetype`. Tiered retrieval is
> exercised through the internal `build_coach_context_preview` Python function
> (also used by `CoachAnalyst`). Smoke checks were run via `docker compose exec
> backend python3` with `OBSERVED_PLAY_MEMORY_ENABLED=true` set in the process
> environment. The public `GET /api/observed-play/coach-context-preview` endpoint
> was separately confirmed reachable (no deck context parameters, uses legacy
> Phase 6.1 path).

### Context 1: Dragapult vs Gardevoir

```
deck_card_ids: [dragapult-ex, pidgey, pidgeot-ex, rare-candy, ultra-ball]
candidate_card_ids: [gardevoir-ex, kirlia, ralts]
allow_fallback: true
```

| Field | Value |
|---|---|
| would_inject | True |
| no_relevant_evidence | False |
| matchup_strategy | matchup_context_boost_v1 |
| matchup_ranking_enabled | False |
| matchup_pair_log_count | 1 |
| matchup_pair_eligible | False |
| matchup_boost_applied_count | 0 |
| directed_matchup_key | dragapult-ex\|vs\|gardevoir-ex |
| matchup_coverage_reason | 1 clean log(s) match dragapult-ex\|vs\|gardevoir-ex; minimum is 3 |
| matchup_boost_cap | 0.12 |
| matchup_min_pair_logs | 3 |
| matchup_candidate_pool_expanded | False |
| matchup_filter_applied | False |
| evidence_count | 8 |
| first evidence matchup_boost | 0.0 |
| first evidence source_log_matchup_key | None |

### Context 2: Crustle vs Dragapult

```
deck_card_ids: [crustle, arcanine-ex, rare-candy]
candidate_card_ids: [dragapult-ex, pidgey, pidgeot-ex]
allow_fallback: true
```

| Field | Value |
|---|---|
| would_inject | True |
| matchup_strategy | matchup_context_boost_v1 |
| matchup_ranking_enabled | False |
| matchup_pair_eligible | False |
| matchup_boost_applied_count | 0 |
| directed_matchup_key | crustle\|vs\|dragapult-ex |
| matchup_coverage_reason | 1 clean log(s) match crustle\|vs\|dragapult-ex; minimum is 3 |

### Context 3: No-match (fake cards, allow_fallback=false)

```
deck_card_ids: [zzz-fake-card-111, zzz-fake-card-222]
allow_fallback: false
```

| Field | Value |
|---|---|
| would_inject | False |
| no_relevant_evidence | True |
| matchup_strategy | matchup_context_boost_v1 |
| matchup_ranking_enabled | False |
| evidence_count | 0 |
| matchup_pair_eligible | False |

### Context 4: No-label / no opponent

```
deck_card_ids: [ultra-ball, nest-ball, professor-research]
allow_fallback: true
```

| Field | Value |
|---|---|
| would_inject | True |
| matchup_strategy | matchup_context_boost_v1 |
| directed_matchup_key | None |
| matchup_ranking_enabled | False |
| matchup_coverage_reason | no_current_archetype_label |
| no_matchup_signal_reason | no_current_archetype_label |

## Coach-Debug Readability Checklist

| # | Question | Answer | Notes |
|---|---|---|---|
| 1 | Can I tell whether matchup boost was available? | **Yes** | "Eligible: no" shown in amber; pair log count shown with amber color when below minimum. |
| 2 | Can I tell why boost did or did not apply? | **Yes** | "Coverage: 1 clean log(s) match dragapult-ex\|vs\|gardevoir-ex; minimum is 3" explains the gate exactly. |
| 3 | Can I tell how many clean logs the matchup pair has? | **Yes** | "Pair log count: 1" is shown with amber color when below threshold, green when above. |
| 4 | Can I tell that candidate-pool expansion is off? | **Yes** | "Candidate pool expansion: disabled" is always shown in the matchup section header. |
| 5 | Can I tell that filtering is off? | **Yes** | "Filter applied: no" is always shown in the matchup section header. |
| 6 | Can I tell which evidence items received matchup_boost? | **Yes** | "Matchup boost" column in evidence table shows "—" or "+N.NN" per item. After fix: "Boost applied: 0 items" also shown in the boost section when count is 0, making it unambiguous. |
| 7 | Can I tell that normal retrieval still worked even without matchup boost? | **Yes** | Evidence table shows retrieved items. Fallback advisory copy states "PokéPrism falls back to card overlap and archetype/package/strategy labels." |

## UI Fixes Made

### Fix 1 — Always show `matchup_boost_applied_count` in 7.2c context

**File:** `frontend/src/components/observedPlay/RetrievalMetadataPanel.tsx`

**Problem:** `matchup_boost_applied_count` was rendered only when its value was
`> 0`. For under-covered matchups (the common case today), the field was absent,
making it impossible for a developer to explicitly confirm "boost was evaluated
but applied to 0 items."

**Fix:** Removed the `> 0` guard. The count is now always visible inside the
`matchup_boost_cap != null` section (i.e., whenever the 7.2c boost section
renders). Output reads "Boost applied: 0 items" / "Boost applied: 1 item" /
"Boost applied: N items" consistently.

**Test added:** `ObservedPlayRetrievalDebugTile.test.tsx` — new test case
"shows boost applied count as 0 when boost did not apply in under-covered
context" verifies "Boost applied" text is present even with
`matchup_boost_applied_count: 0`.

**Test result:** 380 passed (up from 379). Build: clean.

**Scope:** UI copy only. No retrieval behavior, no backend changes, no
migrations, no schema changes.

## Known Limitations

- Current corpus has 0 eligible directed matchup pairs (all checked pairs have
  exactly 1 clean log; minimum is 3). This is expected and documented. Corpus
  expansion will unlock real boost activation without any code changes.
- `OBSERVED_PLAY_MEMORY_ENABLED` is `false` by default in local Docker Compose.
  Smoke checks required temporarily enabling the flag via Python env override
  (`os.environ['OBSERVED_PLAY_MEMORY_ENABLED'] = 'true'`). The public
  `GET /api/observed-play/coach-context-preview` endpoint uses the legacy Phase
  6.1 path (no deck context / no matchup metadata). Production simulation
  coaching exercises the tiered path through `CoachAnalyst.analyze_and_mutate`.
- The directed matchup key uses the highest-confidence archetype label from each
  side. For generic trainer-only decks (ultra-ball, nest-ball, etc.), no archetype
  label is inferred, so `no_matchup_signal_reason=no_current_archetype_label`
  fires. This is correct.

## Recommendation

- Continue corpus expansion in parallel (no code changes required for boost to
  activate once ≥3 clean directed-pair logs exist).
- Phase 7.2d (candidate-pool expansion) remains deferred; the current corpus does
  not yet justify it.
- No technical blockers for ongoing corpus import or simulation runs.
- Next re-validation (Phase 7.2e) should be triggered after at least one directed
  matchup pair crosses the ≥3 clean log threshold, to verify boost activation
  end-to-end.
