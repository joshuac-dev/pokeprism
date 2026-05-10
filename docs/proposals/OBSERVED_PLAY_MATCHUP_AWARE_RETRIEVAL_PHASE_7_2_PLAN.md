# Phase 7.2 — Matchup-Aware Retrieval: Design and Implementation Plan

> Design/specification only. No application code, retrieval behavior, migrations,
> Coach strategy, simulator gameplay, AI Player behavior, pgvector writes,
> Neo4j writes, `match_events` writes, `card_performance` writes, or
> observed-play ingestion changes are added by this document.
>
> Phase 7.2a update: design completed 2026-05-09 on branch
> `phase-7-2a-matchup-aware-retrieval-design`. Corpus findings and recommended
> implementation slices (7.2b–7.2e) are recorded here.
>
> Phase 7.2b update: metadata-only implementation completed 2026-05-09 on branch
> `phase-7-2b-matchup-context-preview`. Added `matchup_strategy=matchup_context_preview_v1`,
> directed matchup key, `current/opponent_archetype_labels`,
> `matchup_context_enabled=True`, `matchup_ranking_enabled=False`,
> `matchup_boost=0.0`. Scores, ordering, and evidence IDs unchanged from Phase 7.1d.
> Hardening: `|vs|unknown` overclaiming removed; source_log_matchup_key returns
> `None` when opponent side is indeterminate.
> Backend: 1272 passed, 1 skipped. Frontend: 372 passed.
>
> Phase 7.2c UX/debug validation completed 2026-05-10 on branch
> `phase-7-2c-post-merge-ux-debug-validation` (from f4399a0).
> Verdict: `ready_for_parallel_corpus_expansion`. Four retrieval contexts checked.
> All confirmed correct fallback behavior. Coach-debug readability: 7/7 YES.
> Minor UI fix: `matchup_boost_applied_count` always shown in 7.2c context.
> Full report: `docs/proposals/OBSERVED_PLAY_PHASE_7_2C_UX_DEBUG_VALIDATION_REPORT.md`.
>
> Phase 7.2 corpus readiness audit completed 2026-05-09 on branch
> `phase-7-2-corpus-expansion-readiness`. Verdict: `not_ready_needs_more_logs`.
> 49 logs total; salazzle-ex (1 log), charizard-ex (1 log) are critical gaps.
> All cross-matchup pairs have exactly 1 log each — below ≥3 gate for 7.2c.
> Phase 7.2c is gated. Full report:
> `docs/proposals/OBSERVED_PLAY_CORPUS_EXPANSION_PHASE_7_2_READINESS_REPORT.md`.

## Phase 7.2c Status: Implemented

Phase 7.2c implements a generic guarded matchup boost. The mechanism is fallback-safe:

- Mechanism: implemented and generic (not tied to specific matchups)
- Real-corpus activation: blocked for pairs with <3 clean logs (most pairs in current corpus)
- Broad rollout: pending corpus expansion for meaningful validation

The previous corpus readiness gate blocks BOOST ACTIVATION for under-covered pairs and BROAD ROLLOUT,
not the generic fallback-safe implementation.

---

## 1. Executive Summary

Phase 7.1 established deterministic archetype labels, bounded label-boost ranking,
and validated label behavior across six retrieval contexts. The result is a stable
foundation and a clear next gap: the current retrieval system knows what deck the
user is playing, but does not model who they are playing _against_.

Phase 7.2 adds matchup-aware retrieval: the ability to bias evidence selection
toward observed-play logs where the user's archetype faced the opponent's
archetype. This allows the Coach to cite evidence from strategically similar
matchup contexts rather than just deck-card overlap.

**Conservative design principle:** Phase 7.2 must not regress the Phase 7.1
ranking invariants. Every new signal is additive and bounded. Tier-first sorting
and no-evidence gating must hold throughout. Candidate-pool expansion (fetching
logs not in the initial deck_overlap set) is deferred until corpus coverage
crosses an explicit minimum threshold.

**Recommended first implementation slice:**

```
Phase 7.2b — backend matchup context preview and metadata only,
no retrieval behavior change.
```

---

## 2. Current Baseline After Phases 7.1b–7.1e

### Retrieval invariants

```
strategy=deck_overlap_v1
label_strategy=archetype_label_boost_v1
label_boost_cap=0.10
Tier 1 exact card-ID match > Tier 2 name match > Tier 3 global fallback
Same-tier label reorder only
Labels do not expand the candidate pool
Labels do not hard-filter evidence
Labels do not persist
no_relevant_evidence gating intact
allow_fallback=false default
```

### Labeling infrastructure

- `archetype_labels.py`: deterministic seed-rule inference for Dragapult ex,
  Salazzle ex, Crustle, Charizard ex, Gardevoir ex; plus fire-toolbox and
  poison/burn/spread strategy labels.
- `infer_deck_labels_from_cards`: produces `DeckArchetypeLabelPreview` from deck
  card signals.
- `infer_observed_log_labels_from_signals`: produces
  `ObservedLogArchetypeLabelPreview` with `labels_by_player` and `global_labels`
  from resolved card mentions.
- `ArchetypeLabel` schema: `label`, `canonical_key`, `label_type`, `source`,
  `confidence`, `review_status`, `player_alias`, evidence fields, `notes`.

### Evidence metadata

`EvidenceSelectionDetail` already includes:
- `base_relevance_score`, `label_boost`, `final_relevance_score`
- `matched_label_keys`, `matched_label_names`, `matched_label_types`
- `source_log_labels`, `label_match_reason`
- `tier`, `match_source`, `from_winning_game`

`ObservedPlayRetrievalMetadata` already includes:
- `strategy`, `label_strategy`, `label_ranking_enabled`
- `deck_labels`, `candidate_labels`
- `label_boost_cap`, `label_boost_applied_count`
- `no_relevant_evidence`, `evidence_selected`

### Corpus state (Phase 7.1e baseline, 2026-05-09)

```
observed_play_logs:            49 (all ingested)
observed_play_events:      10 047
observed_card_mentions:     8 670
observed_play_memory_items: 4 786
observed_play_memory_ingestions: 198
```

Archetype signal distribution from action_name analysis:

| Archetype | Key actions | Approx action hits |
|---|---|---|
| Dragapult ex | Phantom Dive (52), Recon Directive (136) | ~188 |
| Gardevoir ex | Adrena-Brain (59), Mega Symphonia (19), Do the Wave (22) | ~100 |
| Crustle | Superb Scissors (48) | ~48 |
| Ogerpon (Teal Mask) | Teal Dance (35) | ~35 |
| Other / passive events | null action_name | ~3866 |

All 49 logs use generic `player_1` / `player_2` aliases. No real player identity
is tracked.

---

## 3. Goals and Non-Goals

### Goals

- Define matchup as a first-class retrieval concept with explicit directionality.
- Design a metadata schema that surfaces matchup context in coach-debug and
  Dashboard without changing ranking behavior in Phase 7.2b.
- Design a matchup-aware ranking boost (Phase 7.2c) that rewards evidence from
  logs where both user-side and opponent-side labels match the source log.
- Specify the corpus coverage threshold below which candidate-pool expansion must
  not be enabled.
- Create a corpus expansion plan targeting the archetypes and matchup pairs where
  the current corpus is insufficient for matchup retrieval.

### Non-Goals (Phase 7.2)

- Semantic/vector retrieval.
- LLM-generated labels as retrieval source of truth.
- Persistent label storage or user accept/reject UI changes.
- Hard matchup filtering (excluding evidence that doesn't match the matchup).
- Unbounded candidate-pool expansion.
- Matchup-aware Coach strategy changes or prompt injection policy changes.
- Simulator, AI Player, deck-builder, ingestion, or card-database changes.
- `match_events` writes, `card_performance` writes, Neo4j writes, pgvector writes.
- Migrations.

---

## 4. Definition of Matchup and Directionality

### Matchup definition

A matchup is a directed pair:

```
matchup = (current_primary_archetype_key, opponent_primary_archetype_key)
```

- `current_primary_archetype_key`: canonical key of the user's deck primary
  archetype label (e.g. `dragapult-ex`).
- `opponent_primary_archetype_key`: canonical key of the opponent/candidate
  deck's primary archetype label (e.g. `gardevoir-ex`).

### Directionality

**Direction matters.** Playing Dragapult against Gardevoir is not the same
strategic situation as playing Gardevoir against Dragapult. The evidence most
relevant to "how should I play my Dragapult deck against Gardevoir?" comes from
logs where the Dragapult player made decisions, not the Gardevoir player.

Matchup key format:

```
{current_primary_key}|vs|{opponent_primary_key}
```

Examples:

```
dragapult-ex|vs|gardevoir-ex
gardevoir-ex|vs|dragapult-ex
crustle|vs|dragapult-ex
```

These are three distinct matchup keys with different retrieval implications.

### One-sided matchup

When only one side has a label:

- Use `current_primary_archetype_key|vs|unknown` (current side known, opponent
  unknown) or `unknown|vs|{opponent_primary_key}` (opponent side known, current
  unknown).
- Rank evidence using single-side label boost only (existing Phase 7.1d behavior).
- Mark `matchup_direction=partial` in metadata.
- Do not activate matchup-pair retrieval logic for one-sided matchups.

### No-label matchup

When neither side has a confident label:

- `matchup_key=null`, `no_matchup_signal_reason` populated.
- Retrieval falls back to Phase 7.1d label-only behavior (or further to
  deck_overlap_v1 if no labels either).

---

## 5. Matchup Context Model

### Inputs to matchup context

```
current_deck_card_ids:      list[str]    # user deck card IDs
current_deck_card_names:    list[str]    # user deck card names
candidate_card_ids:         list[str]    # opponent deck card IDs
candidate_card_names:       list[str]    # opponent deck card names
```

These inputs already exist in `build_coach_context_preview` as parameters. No
new data is needed from the caller for Phase 7.2b.

### Derived matchup context

```python
@dataclass
class MatchupContext:
    # Current (user) side
    current_labels: list[ArchetypeLabel]          # inferred from current deck cards
    current_primary_archetype: ArchetypeLabel | None
    current_supporting_labels: list[ArchetypeLabel]  # strategy + package labels

    # Opponent side
    opponent_labels: list[ArchetypeLabel]         # inferred from candidate deck cards
    opponent_primary_archetype: ArchetypeLabel | None
    opponent_supporting_labels: list[ArchetypeLabel]

    # Matchup pair
    matchup_key: str | None                       # "X|vs|Y" or None
    matchup_direction: str                        # "forward" | "partial" | "unknown"
    matchup_confidence: float                     # min(current_conf, opponent_conf), capped 0–1
    no_matchup_signal_reason: str | None
```

### Confidence handling

- `matchup_confidence = min(current_primary.confidence, opponent_primary.confidence)`
  if both sides have a primary archetype label.
- For one-sided matchup: `matchup_confidence = current_primary.confidence` or
  `opponent_primary.confidence`, whichever side is known.
- Ambiguous labels (multiple archetypes near the confidence threshold) should
  produce a lower `matchup_confidence`. Recommended: multiply by `0.7` when
  `ambiguous=True`.
- `matchup_confidence < 0.50` should suppress matchup-pair boost and set
  `matchup_direction=partial` or `unknown`.

### Opponent context inference sources

In order of preference:

1. **Candidate deck card IDs/names** (already available in Phase 7.1d) — use
   `infer_deck_labels_from_cards` on candidate cards. This is the primary Phase
   7.2 inference path.
2. **Simulation opponent metadata** (`SimulationOpponent.deck_id`,
   `SimulationOpponent.deck_name`) — available at simulation creation time; can
   pre-compute opponent labels. Do not block retrieval waiting for opponent label
   persistence.
3. **Source log opponent player labels** — inferred from source log memory items
   at retrieval time (existing `_source_log_label_cache`). These labels already
   exist in Phase 7.1d for the `candidate_labels` field.
4. **Manual future labels** — when label persistence exists. Out of scope for
   Phase 7.2.

Do not assume future persistence exists. All inference is ephemeral.

---

## 6. Proposed Metadata Schema

### New `ObservedPlayRetrievalMetadata` fields

These fields should be added in Phase 7.2b (preview only, no behavior change) and
populated in Phase 7.2c (with matchup ranking enabled):

```python
class ObservedPlayRetrievalMetadata(BaseModel):
    # ... existing Phase 7.1d fields unchanged ...

    # Phase 7.2 matchup fields
    matchup_strategy: str | None = None
    # e.g. "matchup_context_boost_v1" when enabled; None until 7.2c

    matchup_ranking_enabled: bool = False
    # True only when matchup boost is active (Phase 7.2c+)

    current_primary_archetype: str | None = None
    # canonical_key of user deck's primary archetype label

    opponent_primary_archetype: str | None = None
    # canonical_key of opponent deck's primary archetype label

    matchup_key: str | None = None
    # "{current_primary}|vs|{opponent_primary}" or None

    matchup_direction: str = "unknown"
    # "forward" | "partial" | "unknown"

    matchup_confidence: float | None = None
    # min(current_conf, opponent_conf); None if matchup_key is None

    matchup_boost_cap: float = 0.0
    # 0.0 until Phase 7.2c; recommended 0.12

    matchup_boost_applied_count: int = 0
    # number of evidence items that received a matchup_boost > 0

    no_matchup_signal_reason: str | None = None
    # e.g. "Opponent deck has no confident archetype label"

    matchup_candidate_pool_expanded: bool = False
    # Always False until Phase 7.2d; explicit corpus-expansion gate

    matchup_filter_applied: bool = False
    # Always False; hard filtering is not planned for Phase 7.2
```

### New `EvidenceSelectionDetail` fields

```python
class EvidenceSelectionDetail(BaseModel):
    # ... existing Phase 7.1d fields unchanged ...

    # Phase 7.2 matchup fields
    matchup_boost: float = 0.0
    # Additive to label_boost; 0.0 if matchup did not match

    matched_matchup_keys: list[str] = Field(default_factory=list)
    # matchup keys that contributed to matchup_boost

    source_log_current_player_labels: list[str] = Field(default_factory=list)
    # canonical_keys of source log labels for the player whose side ≈ current deck

    source_log_opponent_player_labels: list[str] = Field(default_factory=list)
    # canonical_keys of source log labels for the other player

    matchup_match_reason: str | None = None
    # Human-readable explanation: "Source log player_1 labels [dragapult-ex] matched
    #   current archetype dragapult-ex. Source log player_2 labels [gardevoir-ex]
    #   matched opponent archetype gardevoir-ex."
```

### Score composition

```
base_score      = tier score + outcome_bonus − source_rep_penalty
label_boost     ≤ label_boost_cap (0.10, Phase 7.1d)
matchup_boost   ≤ matchup_boost_cap (0.12, Phase 7.2c)
final_score     = base_score + label_boost + matchup_boost
```

These are additive. A single evidence item can receive both. Combined maximum
effective boost: `0.22` before any source diversity penalties are applied.

The `relevance_score` field (used for legacy compatibility) should equal
`final_score` when matchup is enabled.

---

## 7. Retrieval Ranking Design

### Phase 7.2b — metadata only, no ranking change

In Phase 7.2b:
- Compute `MatchupContext` from existing card inputs.
- Attach `current_primary_archetype`, `opponent_primary_archetype`, `matchup_key`,
  `matchup_direction`, `matchup_confidence` to `ObservedPlayRetrievalMetadata`.
- Attach `source_log_current_player_labels`, `source_log_opponent_player_labels`
  to each `EvidenceSelectionDetail` (using the existing `_source_log_label_cache`
  data, no additional DB queries).
- Set `matchup_ranking_enabled=False`, `matchup_boost=0.0`.
- All existing Phase 7.1d ranking scores and ordering are preserved exactly.

This makes matchup context visible in coach-debug and Dashboard without touching
any retrieval behavior. It can be validated independently.

### Phase 7.2c — matchup-aware ranking boost

Activate after Phase 7.2b validates metadata is correct.

Ranking change:

1. For each selected evidence candidate, determine whether the source log's
   per-player labels represent the matched matchup:
   - Look up `source_log_current_player_labels` and
     `source_log_opponent_player_labels` using the existing label cache.
   - Check: does `current_primary_archetype_key` appear in the source log's
     current-player labels AND does `opponent_primary_archetype_key` appear in
     the source log's opponent-player labels?
   - Both must match to award `matchup_boost`. Single-side match is already
     covered by Phase 7.1d `label_boost`.

2. Apply `matchup_boost ≤ matchup_boost_cap (0.12)` additively to base_score.

3. Recompute `final_score = base_score + label_boost + matchup_boost`.

4. Re-sort within tier by `final_score` descending (same-tier only, exactly as
   Phase 7.1d does for `label_boost`).

### Ranking invariants (unchanged from Phase 7.1d)

| Invariant | Phase 7.2 behavior |
|---|---|
| Tier-first sort (Tier 1 before Tier 2 before Tier 3) | **Preserved.** Matchup boost reorders within tier only. |
| Exact card-ID evidence (Tier 1) always outranks label/matchup-only matches | **Preserved.** Matchup boost ≤ 0.12; cannot promote a Tier 2 item above a Tier 1 item. |
| Label boost cap (0.10) maintained | **Preserved.** Matchup boost is a separate cap (0.12). |
| No evidence injection when `allow_fallback=False` and no deck/name overlap | **Preserved.** Matchup boost applies only to candidates already in the pool. |
| No evidence injection when `no_relevant_evidence=True` | **Preserved.** |
| Source diversity cap (`_MAX_ITEMS_PER_LOG=2`) maintained | **Preserved.** |

### Player-side assignment in source log

The key question for matchup boost: which player in the source log is the
"current deck" player and which is the "opponent"?

Approach:
- Look at the memory item's `player_alias` (`player_1` or `player_2`).
- Look at the source log's `player_1_alias` / `player_2_alias` (always
  `player_1` / `player_2` in current corpus).
- Check which player's labels match the current deck's primary archetype.
- If `player_1` labels match current deck → current side = `player_1`, opponent
  side = `player_2`.
- If `player_2` labels match current deck → current side = `player_2`, opponent
  side = `player_1`.
- If neither or both match (ambiguous) → no matchup boost for this item;
  populate `matchup_match_reason="Ambiguous player assignment in source log."`.

This is directional. If the user is playing Dragapult and we retrieve a memory
item from log X where `player_1` is Dragapult and `player_2` is Gardevoir, the
matchup check is: "Does `dragapult-ex` appear in `player_1` labels AND does
`gardevoir-ex` appear in `player_2` labels?" The memory item's own player_alias
(which side the event came from) then determines which player's strategic context
is being retrieved.

---

## 8. Candidate-Pool Expansion Policy

**Candidate-pool expansion is deferred.** It must not be implemented until the
corpus meets explicit minimum thresholds.

### What candidate-pool expansion would do (Phase 7.2d)

In Phase 7.2c, only candidates already in the deck_overlap_v1 pool receive
matchup boost. Phase 7.2d would optionally expand the initial SQL queries to
include logs from matching matchup pairs even when no exact card-ID or name
overlap exists.

This is a qualitative change: Phase 7.1d/7.2c only re-rank; Phase 7.2d
would introduce new candidates.

### Minimum corpus thresholds before enabling expansion

| Condition | Minimum | Rationale |
|---|---|---|
| Logs per archetype (both current and opponent side) | ≥ 5 clean ingested logs | Prevents single-log monopoly |
| Logs per matchup pair | ≥ 3 logs where both player-side labels are confident | Below 3, expansion adds noise |
| Label confidence threshold for expansion-eligible logs | ≥ 0.70 on both sides | Prevents ambiguous logs from polluting the pool |

**Current corpus assessment (2026-05-09):**

| Archetype | Estimated log count | Expansion-eligible? |
|---|---|---|
| Dragapult ex | ~30+ | ✅ Single-side expansion eligible |
| Gardevoir ex | ~3–5 | ❌ Borderline; needs more logs |
| Crustle | ~3–5 | ❌ Borderline; needs more logs |
| Salazzle ex | ~0 | ❌ Not eligible |
| Charizard ex | ~1–2 | ❌ Not eligible |
| Ogerpon (Teal Mask) | ~5–8 est. | 🟡 Possible; needs count |

| Matchup pair | Estimated pair logs | Expansion-eligible? |
|---|---|---|
| dragapult-ex vs gardevoir-ex | ~2–3 | ❌ Just below threshold |
| gardevoir-ex vs dragapult-ex | ~2–3 | ❌ Just below threshold |
| dragapult-ex vs crustle | ~1–2 | ❌ Not eligible |
| crustle vs dragapult-ex | ~1–2 | ❌ Not eligible |
| dragapult-ex vs ogerpon | ~1–3 | ❌ Not eligible |

**Conclusion:** Candidate-pool expansion must not be enabled before corpus
expansion (Section 9). It should be gated behind an explicit feature flag
(`MATCHUP_POOL_EXPANSION_ENABLED=false` default) and validated manually before
enabling.

### Hard constraints on expansion (Phase 7.2d+)

- Expansion must be feature-flagged, off by default.
- Expansion must not activate `allow_fallback=true` implicitly.
- Expanded candidates must be clearly marked in metadata (`matchup_candidate_pool_expanded=true`,
  per-item `match_source="matchup_expansion"`).
- No matchup-only evidence may be injected when `allow_fallback=false`.
- Hard filtering (excluding evidence that doesn't match the matchup) must never
  be applied. Evidence is ranked, not filtered.

---

## 9. Corpus Expansion Plan

The current corpus is too Dragapult-heavy for matchup-pair retrieval to be
broadly useful. The following expansion plan should be completed before Phase
7.2c is considered production-ready and before Phase 7.2d is enabled.

### Priority targets

| Priority | Archetype | Target log count | Primary matchup pairs to cover |
|---|---|---|---|
| 1 | Gardevoir ex | 5 more logs (total ≥ 8) | Gardevoir vs Dragapult, Gardevoir vs Crustle |
| 2 | Crustle | 5 more logs (total ≥ 8) | Crustle vs Dragapult, Crustle vs Gardevoir |
| 3 | Salazzle ex | 5+ logs | Salazzle vs any |
| 4 | Charizard ex | 5+ logs | Charizard vs any |
| 5 | Ogerpon (Teal Mask) | Count current; add if < 5 | Ogerpon vs any |
| 6 | Unknown/no-label control | 5–8 logs | Validates fallback gating |
| 7 | Mixed/ambiguous | 3–5 logs | Validates ambiguous label handling |

### Priority matchup pairs

These specific matchup pairs should have ≥ 3 logs covering both player sides
before matchup-pair retrieval can be trusted:

```
dragapult-ex|vs|gardevoir-ex     (current: ~2–3 → target: ≥5)
gardevoir-ex|vs|dragapult-ex     (current: ~2–3 → target: ≥5)
dragapult-ex|vs|crustle          (current: ~1–2 → target: ≥3)
crustle|vs|dragapult-ex          (current: ~1–2 → target: ≥3)
gardevoir-ex|vs|crustle          (current: ~0 → target: ≥3)
dragapult-ex|vs|salazzle-ex      (current: ~0 → target: ≥3)
```

### Import sequencing

Recommended import order:

1. **Gardevoir vs Dragapult logs** — highest-priority matchup pair for meta
   relevance; also covers the primary Dragapult corpus gap from the opponent side.
2. **Crustle vs Dragapult logs** — second-priority; Crustle already has some
   corpus representation.
3. **Gardevoir vs Crustle or other** — expands Gardevoir beyond Dragapult context.
4. **Salazzle ex logs** — fills the critical seed rule that currently has zero
   log representation.
5. **Charizard ex logs** — fills another critical seed rule.
6. **Mixed/ambiguous and unknown control** — validates gating behavior at scale.

### Quality verification after expansion

After each import batch:

1. Re-run label preview endpoints for all newly added logs:
   ```bash
   curl -s "http://localhost:8000/api/observed-play/logs/{id}/archetype-label-preview" | jq
   ```
2. Confirm label confidence ≥ 0.70 for at least the primary archetype label per
   player side.
3. Run backend observed-play tests (`pytest tests/test_observed_play -q`).
4. Run corpus count checks to confirm no unexpected writes.
5. If matchup-pair threshold (≥3 clean logs per pair) is crossed, document which
   pairs are now expansion-eligible.

### Re-validation after expansion

After reaching minimum thresholds:

1. Repeat Phase 7.1e-style DB-backed retrieval validation for newly covered
   archetypes and matchup pairs.
2. Verify that Dragapult evidence does not crowd out newly added archetype evidence
   for decks where it should not appear.
3. Record findings in a Phase 7.2e manual validation report.

---

## 10. UI / Debug Requirements

### Dashboard — RetrievalMetadataPanel

Phase 7.2b metadata additions (display only, no behavior change):

- Show `matchup_key` if present (e.g. `dragapult-ex vs gardevoir-ex`).
- Show `matchup_direction` (`forward` | `partial` | `unknown`).
- Show `matchup_confidence` as a percentage.
- Show `no_matchup_signal_reason` if `matchup_key` is null.
- Show `matchup_ranking_enabled` status.

Phase 7.2c additions:

- Show `matchup_boost_cap` and `matchup_boost_applied_count`.
- Per-evidence: show `matchup_boost` (e.g. `+0.08 matchup`), `matchup_match_reason`.
- Show `source_log_current_player_labels` and `source_log_opponent_player_labels`
  in the per-evidence detail.
- Show `matched_matchup_keys`.

Phase 7.2d additions (if enabled):

- Show `matchup_candidate_pool_expanded=true` prominently.
- Per-evidence `match_source="matchup_expansion"` items should be visually
  distinguished from `deck_card` / `candidate_card` items.

### Advisory language requirements

The UI must continue to make clear:

- Labels are advisory and not persisted.
- Matchup context is inferred, not verified.
- Matchup boost is a ranking signal, not a hard filter.
- Observed-play evidence is never a source of card rule information.

Suggested UI copy for matchup metadata section:
> "Matchup context inferred from deck card lists. Labels are advisory."

---

## 11. Test Plan

### Unit tests (Phase 7.2b)

```
test_matchup_context_no_current_labels()         → matchup_key=None, no_matchup_signal_reason populated
test_matchup_context_no_opponent_labels()        → matchup_direction=partial, matchup_confidence=current_conf
test_matchup_context_both_sides()                → matchup_key correct, matchup_confidence=min(...)
test_matchup_context_ambiguous_current()         → matchup_confidence reduced by 0.7 factor
test_matchup_key_format()                        → "dragapult-ex|vs|gardevoir-ex"
test_matchup_direction_cases()                   → forward/partial/unknown
test_source_log_player_assignment_current_p1()   → current side correctly assigned to player_1
test_source_log_player_assignment_current_p2()   → current side correctly assigned to player_2
test_source_log_player_assignment_ambiguous()    → matchup_boost=0, reason populated
```

### Unit tests (Phase 7.2c)

```
test_matchup_boost_both_sides_match()            → matchup_boost > 0, ≤ matchup_boost_cap
test_matchup_boost_one_side_only()               → matchup_boost=0 (single-side handled by label_boost)
test_matchup_boost_cap_enforced()                → boost never exceeds matchup_boost_cap
test_label_plus_matchup_boost_additive()         → final_score = base + label_boost + matchup_boost
test_tier_first_sort_preserved_with_matchup()    → Tier 1 always before Tier 2
test_no_evidence_gating_unchanged()              → no_relevant_evidence=True → no matchup injection
test_allow_fallback_false_unchanged()            → matchup does not expand candidate pool
test_matchup_boost_applied_count()               → count matches items with matchup_boost > 0
```

### Integration tests

```
test_build_coach_context_preview_dragapult_vs_gardevoir()
test_build_coach_context_preview_gardevoir_vs_dragapult()
test_build_coach_context_preview_no_opponent_context()
test_build_coach_context_preview_unknown_deck()
test_retrieval_metadata_matchup_fields_present()
test_retrieval_metadata_matchup_ranking_disabled_by_default()  # Phase 7.2b
```

### Regression tests (preserve Phase 7.1d invariants)

```
test_phase_7_1d_invariants_unchanged_with_matchup_context()
# Runs all existing Phase 7.1d test cases with matchup metadata fields present
# and verifies scores/ordering are identical when matchup_ranking_enabled=False
```

---

## 12. Manual Validation Plan

Phase 7.2e is the dedicated validation phase. The approach mirrors Phase 7.1e:

### Validation contexts (minimum)

| Context | Deck | Opponent | Expected matchup_key |
|---|---|---|---|
| Dragapult vs Gardevoir | Dragapult ex | Mega Gardevoir ex | `dragapult-ex\|vs\|gardevoir-ex` |
| Gardevoir vs Dragapult | Mega Gardevoir ex | Dragapult ex | `gardevoir-ex\|vs\|dragapult-ex` |
| Crustle vs Dragapult | Crustle | Dragapult ex | `crustle\|vs\|dragapult-ex` |
| Unknown vs Dragapult | N's Zoroark | Dragapult ex | `unknown\|vs\|dragapult-ex` (partial) |
| Dragapult vs Unknown | Dragapult ex | N's Zoroark | `dragapult-ex\|vs\|unknown` (partial) |
| No-match | Unknown | Unknown | `null` |

### Validation assertions per context

For each context, confirm:

1. `matchup_key` is correctly formed.
2. `matchup_confidence` is consistent with constituent label confidences.
3. Evidence items from matching matchup-pair logs receive `matchup_boost > 0`.
4. Evidence items from non-matching logs receive `matchup_boost = 0`.
5. Tier-first sort is preserved.
6. `matchup_match_reason` is readable and accurate.
7. No evidence injected for no-match context.
8. Corpus counts unchanged after validation (read-only confirmed).

### Post-expansion re-validation

After the corpus expansion targets in Section 9 are met, repeat the above with
newly added archetypes (Salazzle, Charizard, additional Gardevoir/Crustle contexts).

---

## 13. Risk Analysis

### Mislabeled player sides in source logs

**Risk:** Player assignment logic assigns the wrong player as "current side,"
leading to incorrectly boosted or suppressed evidence.

**Mitigation:** Explicit `matchup_match_reason` text citing which player alias
was assigned to which side. Ambiguous assignment → no matchup boost, reason
populated. Manual validation in Phase 7.2e.

### Corpus skew propagates into matchup retrieval

**Risk:** Dragapult-heavy corpus means matchup-aware retrieval still returns
mostly Dragapult evidence even for non-Dragapult decks.

**Mitigation:** Corpus expansion (Section 9) before Phase 7.2c promotion.
Source diversity cap (`_MAX_ITEMS_PER_LOG=2`) limits per-log monopoly. Dashboard
UI shows `source_log_id` so skew is visible.

### Matchup boost obscures label_match_reason

**Risk:** Two additive boosts (`label_boost` + `matchup_boost`) make it harder
to understand why a specific item ranked highly.

**Mitigation:** Both boosts are separately reported in `EvidenceSelectionDetail`.
`label_match_reason` and `matchup_match_reason` are separate fields. Dashboard
tile shows them independently. No rollup into a single unexplained "relevance"
number.

### Duplicate-key accumulation (documented Phase 7.1d limitation)

**Risk:** Expanded corpus with more logs may surface the documented
`current_by_key` last-write-wins edge case.

**Mitigation:** Continue monitoring during corpus expansion and Phase 7.2e
manual validation. If triggered, a targeted fix (deduplicate at the label-cache
level before boost accumulation) should happen before Phase 7.2d.

### Ambiguous opponent label → matchup boost suppressed for known user archetype

**Risk:** Opponent deck has two near-equal archetypes (e.g., Gardevoir +
Charizard toolbox) → matchup_confidence is low → no matchup boost even when
user archetype is strongly known.

**Mitigation:** This is the correct conservative behavior. Single-side label
boost from Phase 7.1d still applies. Matchup boost requires both sides to be
confident. Document in Phase 7.2e report.

### UI implying matchup is authoritative

**Risk:** Dashboard display of `matchup_key` leads users to treat it as a
confirmed or persisted matchup record.

**Mitigation:** Advisory language in all UI surfaces (Section 10). No accept/reject
UI for matchup labels in Phase 7.2. No persistence.

---

## 14. Implementation Phases 7.2b–7.2e

### Phase 7.2b — Matchup context metadata (no behavior change)

**Scope:**

- Add `MatchupContext` dataclass to `coach_context.py`.
- Compute `MatchupContext` in `build_coach_context_preview` using existing card
  inputs.
- Extend `ObservedPlayRetrievalMetadata` with Phase 7.2 metadata fields
  (`matchup_key`, `matchup_direction`, `matchup_confidence`, etc.).
- Extend `EvidenceSelectionDetail` with `source_log_current_player_labels`,
  `source_log_opponent_player_labels`, `matchup_boost=0.0`,
  `matchup_match_reason=None`.
- Set `matchup_ranking_enabled=False`, `matchup_strategy=None` in all paths.
- Populate matchup metadata without changing any scores or ordering.
- Add unit tests for `MatchupContext` computation.
- Add frontend type additions to `observedPlay.ts` for new metadata fields.
- Add Dashboard `RetrievalMetadataPanel` display of matchup context (Phase 7.2b
  display section).
- Docs: STATUS.md, CHANGELOG.md, spec update.

**Acceptance criteria:**
- All existing Phase 7.1d tests pass unchanged.
- New matchup metadata fields populated and visible in coach-debug.
- Scores and ordering are byte-for-byte identical to Phase 7.1d.
- `matchup_ranking_enabled=False` in all responses.

### Phase 7.2c — Matchup-aware ranking boost

**Pre-condition:** Phase 7.2b validated in real corpus. Corpus expansion has
reached ≥ 5 logs for Gardevoir and ≥ 3 logs for the `gardevoir-ex|vs|dragapult-ex`
and `dragapult-ex|vs|gardevoir-ex` matchup pairs.

**Scope:**

- Add `_apply_matchup_boost()` function alongside `_apply_label_boosts()`.
- Compute per-item `matchup_boost` using player-side assignment logic.
- Apply `matchup_boost_cap=0.12` independently of `label_boost_cap`.
- Recompute `final_score` and re-sort within tier.
- Set `matchup_strategy="matchup_context_boost_v1"`, `matchup_ranking_enabled=True`.
- Add Phase 7.2c unit and integration tests.
- Manual validation in Phase 7.2e.

### Phase 7.2d — Guarded candidate-pool expansion

**Pre-condition:** Phase 7.2c validated. Corpus expansion has reached ≥ 3 logs
for target matchup pairs. Explicit user decision to enable expansion.

**Scope:**

- Add `MATCHUP_POOL_EXPANSION_ENABLED=false` feature flag.
- When enabled, extend the Tier 1 and Tier 2 SQL queries to include logs where
  both player-side labels match the matchup pair, even without card overlap.
- Mark expanded candidates with `match_source="matchup_expansion"`.
- Enforce `matchup_candidate_pool_expanded=True` in metadata.
- Do not activate when `allow_fallback=False` and no deck/name evidence exists.
- Hard threshold gate: disable if `matchup_confidence < 0.60`.

### Phase 7.2e — UI/debug validation and manual review

**Scope:**

- Repeat Phase 7.1e-style validation across all matchup contexts.
- Validate Phase 7.2b or 7.2c (whichever is current) against real corpus.
- Produce Phase 7.2e validation report.
- Confirm read-only corpus behavior.
- Assess whether duplicate-key accumulation appeared.
- Update STATUS.md, CHANGELOG.md, spec.

---

## 15. Recommendation for the Next Implementation Slice

**Start with Phase 7.2b.**

Rationale:

1. It delivers visible matchup context in coach-debug with zero retrieval behavior
   change — identical scores, identical evidence selection.
2. It validates that `MatchupContext` inference from existing card inputs is
   correct before committing to a boost formula.
3. It provides the UI surface needed to do Phase 7.2e-style manual validation
   of matchup _metadata_ before enabling matchup _ranking_.
4. It surfaces the corpus gap: once the Dashboard shows `matchup_key` and
   `matchup_confidence=0.0` for Gardevoir vs Crustle, it is immediately clear
   which logs need to be imported.
5. It is entirely docs-visible, reversible, and can be independently hardened
   before Phase 7.2c is attempted.

**Phase 7.2c (matchup boost) should not begin until:**

- Phase 7.2b metadata is validated in real corpus.
- Gardevoir ex corpus reaches ≥ 5 clean logs.
- At least one priority matchup pair (`dragapult-ex|vs|gardevoir-ex` or
  `gardevoir-ex|vs|dragapult-ex`) has ≥ 3 log representatives.

**Phase 7.2d (candidate-pool expansion) should not begin until:**

- Phase 7.2c is validated.
- All priority matchup pairs in Section 9 meet their minimum thresholds.
- An explicit user decision to enable expansion is made.

---

## Appendix: Corpus Counts (Phase 7.1e baseline, 2026-05-09)

| Table | Count |
|---|---|
| `observed_play_logs` | 49 |
| `observed_play_events` | 10 047 |
| `observed_card_mentions` | 8 670 |
| `observed_play_memory_items` | 4 786 |
| `observed_play_memory_ingestions` | 198 |

## Appendix: Known Deck / Log IDs

| Resource | ID | Labels |
|---|---|---|
| Dragapult ex deck | `0e9ed003-6761-4423-8d77-6b3925d951fe` | dragapult-ex, stage-2-setup, spread-damage |
| Mega Gardevoir ex deck | `dce51bf7-c405-41ae-a27e-0bccf12d9d79` | gardevoir-ex, psychic-engine |
| Crustle deck | `f8f9c9fb-c148-4397-aa4b-94d89c44d5ac` | crustle |
| N's Zoroark deck (unknown) | `0c5b74b1-cdc8-4782-b764-3f3858a0fd84` | (none) |
| Dragapult ex log | `0c405fb6-195f-41e9-b7f1-3a8daa948523` | p1: dragapult-ex, spread-damage |
| Crustle log | `d6c629b8-becf-41c0-a28d-a961aa167f79` | p1+p2: crustle |
| Mixed/Ambiguous log | `7e8b7d51-59a8-4bfe-a8b9-d8a5a97c07db` | p1: dragapult-ex + salazzle-ex |
| Gardevoir/Charizard log | `1fb9d428-d337-47ee-9aa6-918541dfab6f` | p1: gardevoir-ex (0.78), charizard-ex (0.52) |
