# Phase 6.2 — Observed-Play Evidence Relevance / Retrieval Quality

> **Phase 6.2a: COMPLETE.** Backend tiered retrieval implemented and tested.
> Phase 6.2b (UI/debug polish) is the next step.
> Phase 6.1 is complete and verified.

---

## 1. Purpose

Phase 6.1 proved that observed-play evidence can be injected into Coach prompts,
is correctly gated, is advisory-only, and is read-only with respect to observed-play
memory tables.

However, manual verification revealed a consistent rejection pattern:

> The Coach often rejected injected observed-play evidence as irrelevant because it
> came from a different deck archetype.

The root cause is retrieval quality: the current system fetches the **globally
top-8 highest-confidence memory items** with no filtering by the current deck,
archetype, or candidate cards. If the corpus is dominated by Salazzle ex logs
but the Coach is optimizing a Dragapult ex deck, it receives Salazzle evidence
and correctly rejects it.

Phase 6.2's goal is to make retrieved evidence **relevant** to the current deck,
core evolution line, and candidate cards — without changing Coach strategy,
simulation logic, or any other system.

---

## 2. Phase 6.1 Verified Baseline

- `OBSERVED_PLAY_MEMORY_ENABLED=false` by default.
- When enabled: `build_coach_context_preview(db)` is called with **no deck context**;
  returns global top-8 by confidence.
- Evidence block is injected into the Coach prompt; LLM must cite IDs or provide
  `not_used_reason`.
- `coach-debug` exposes `any_block_injected`, `analysis_rounds`, `simulation_observed_play_summary`.
- All five observed-play memory tables are read-only during Coach injection (User Check 4, 2026-05-08).

---

## 3. Current Evidence Retrieval Flow

### Entry point

`CoachAnalyst.analyze_and_mutate()` at line ~135:

```python
observed_play_block, observed_play_ids = await self._fetch_observed_play_block()
```

`_fetch_observed_play_block()` receives **no arguments** — it does not know:
- what deck is being optimized;
- what cards are in the deck;
- what candidate add/remove cards are being considered;
- what matchup is being played.

### Query inside `build_coach_context_preview()`

```python
.where(ObservedPlayMemoryItem.confidence_score >= effective_min_conf)
.where(actor_resolution_status != "unresolved")
.where(target_resolution_status != "unresolved")
.order_by(confidence_score DESC, created_at DESC)
.limit(8)
```

No card filter. No deck filter. No archetype filter. No source diversity cap.
No win/loss weighting.

### Result

Top 8 items by confidence across the entire corpus, regardless of which deck
they came from or what cards they mention.

---

## 4. Problems Observed in Manual Testing

1. **Wrong archetype evidence** — Dragapult ex deck received Salazzle/Charizard-related
   memories; Coach rejected with `not_used_reason: "different deck archetype"`.
2. **Source monopoly** — All 8 slots could theoretically come from one log if that
   log produced many high-confidence items.
3. **No win/loss weighting** — Items from conceded/losing games rank equally to items
   from decisive wins.
4. **No debug visibility for retrieval reason** — `coach-debug` shows which items were
   selected but not why (tier/score/matched field).
5. **No "no relevant evidence" state** — Even when evidence is entirely off-archetype,
   the block is still injected with 8 irrelevant items.
6. **Deck context not passed** — `_fetch_observed_play_block()` has access to nothing
   about the current simulation state.

---

## 5. Available Data Today (No Schema Changes Required)

### ObservedPlayMemoryItem — key fields for relevance

| Field | Type | Available | Use |
|---|---|---|---|
| `actor_card_def_id` | Text (tcgdex_id) | ✅ Indexed | Exact deck-card match |
| `target_card_def_id` | Text (tcgdex_id) | ✅ Indexed | Exact deck-card match |
| `related_card_def_id` | Text (tcgdex_id) | ✅ | Exact deck-card match |
| `actor_card_raw` | Text | ✅ | Name-based ILIKE fallback |
| `target_card_raw` | Text | ✅ | Name-based ILIKE fallback |
| `related_card_raw` | Text | ✅ | Name-based ILIKE fallback |
| `actor_resolution_status` | Text | ✅ | Already used for quality gate |
| `target_resolution_status` | Text | ✅ | Already used for quality gate |
| `confidence_score` | Float | ✅ Indexed | Tier ranking |
| `memory_type` | Text | ✅ Indexed | Action-type filtering |
| `action_name` | Text | ✅ | Semantic relevance |
| `observed_play_log_id` | UUID FK | ✅ Indexed | Source diversity cap |

### ObservedPlayLog — fields joinable for outcome weighting

| Field | Type | Available | Use |
|---|---|---|---|
| `winner_alias` | Text | ✅ | Win/loss outcome |
| `self_player_index` | Integer | ✅ | Which player is "self" |
| `win_condition` | Text | ✅ | prizes / deck_out / no_bench |
| `confidence_score` | Float | ✅ | Log-level quality filter |
| `player_1_alias`, `player_2_alias` | Text | ✅ | Player identity |

### CoachAnalyst — context available at call time

| Data | Available | Path |
|---|---|---|
| `current_deck: list[CardDefinition]` | ✅ | `analyze_and_mutate` param |
| `deck_ids: list[str]` (tcgdex_ids) | ✅ | Computed from `current_deck` |
| `candidate_card_ids: list[str]` | ✅ | `analyze_and_mutate` param |
| Primary evolution line IDs (`primary_ids`) | ✅ | Computed by `_identify_primary_line()` |
| Tier classification (`tiers`) | ✅ | Computed by `_classify_deck_tiers()` |
| `CardDefinition.name` | ✅ | Each card in deck |
| `CardDefinition.evolve_from` | ✅ | Evolution chain |

---

## 6. Missing Data / Future Data

| Gap | Phase 6.2 solve? | Defer to? |
|---|---|---|
| Deck archetype label on logs | ❌ Defer | Phase 6.3 / log import UX |
| Opponent deck identity | ❌ Defer | Phase 6.3 |
| Board state snapshot around memory item | ❌ Defer | Phase 7 |
| pgvector embedding similarity | ❌ Defer | Phase 7 |
| Match outcome joined to memory items as a denormalized field | ❌ Defer | Future migration |
| Retrieval-relevance score stored on memory items | ❌ Out of scope | Future phase |
| Multiple card names per query (compound OR) | ✅ Implement | Phase 6.2 |
| Source diversity (max N per log) | ✅ Implement | Phase 6.2 |
| Win/loss weighting (join ObservedPlayLog) | ✅ Implement | Phase 6.2 |
| Deck-card ID match (actor/target_card_def_id IN deck) | ✅ Implement | Phase 6.2 |

---

## 7. Proposed Phase 6.2 Design

### 7.1 Pass deck context to `_fetch_observed_play_block()`

Update the call site in `analyze_and_mutate`:

```python
observed_play_block, observed_play_ids, retrieval_metadata = \
    await self._fetch_observed_play_block(
        deck_card_ids=deck_ids,
        deck_card_names=[c.name for c in current_deck],
        candidate_card_ids=list(candidate_card_ids or []),
        candidate_card_names=[...],  # from top_cards
        primary_line_ids=list(primary_ids),
    )
```

All parameters remain optional with safe defaults — flag-off path unchanged.

### 7.2 Tiered evidence selection in `build_coach_context_preview()`

Replace the single global query with a three-tier selection function
`_select_tiered_evidence()`. Each tier is an independent filtered query.
Items are collected tier-by-tier until `effective_limit` (default 8) is reached.

**Tier 1 — Exact DB-resolved deck-card match:**

Items where `actor_card_def_id`, `target_card_def_id`, or `related_card_def_id`
is in the provided `deck_card_ids` set (or `candidate_card_ids` set).
These are resolved items whose card identity is unambiguous.

```sql
WHERE (
    actor_card_def_id = ANY(:deck_ids)
    OR target_card_def_id = ANY(:deck_ids)
    OR related_card_def_id = ANY(:deck_ids)
    OR actor_card_def_id = ANY(:candidate_ids)
    OR target_card_def_id = ANY(:candidate_ids)
)
AND confidence_score >= :min_conf
AND actor_resolution_status != 'unresolved'
AND target_resolution_status != 'unresolved'
ORDER BY confidence_score DESC
```

**Tier 2 — Name-based ILIKE deck-card match (fallback for unresolved/partial):**

Items not already selected in Tier 1, where `actor_card_raw`, `target_card_raw`,
or `related_card_raw` ILIKE-matches any deck card name.
Includes all deck card names and candidate names.

This handles items where resolution partially failed but the raw name is correct.

```sql
WHERE id NOT IN (:tier1_ids)
AND (
    actor_card_raw ILIKE ANY(:name_patterns)   -- e.g. '%Dragapult ex%'
    OR target_card_raw ILIKE ANY(:name_patterns)
    OR related_card_raw ILIKE ANY(:name_patterns)
)
AND confidence_score >= :min_conf
ORDER BY confidence_score DESC
```

**Tier 3 — Global high-confidence fallback:**

Items not already selected, ordered by confidence. Only used if tiers 1+2
yield fewer than `effective_limit` items.

If the number of Tier 1+2 items is zero, the system should **not** inject
an evidence block with 8 unrelated items. Instead it should return a
`no_relevant_evidence=true` state (see §7.4).

### 7.3 Source diversity cap

Within each tier, apply a per-log cap of `MAX_ITEMS_PER_LOG` (suggested: 2).
This prevents a single high-confidence log from filling all 8 slots.

Implementation: in Python after query, group by `observed_play_log_id` and
keep at most 2 per group, prioritized by confidence within each group.

### 7.4 Win/loss weighting

Join `ObservedPlayLog` to get `winner_alias` and `self_player_index`. If
`self_player_index == 1` and `winner_alias == player_1_alias`, the memory
came from a game the "self" player won.

Apply a small relevance score boost (`+0.05`) to items from winning games.
This is a tiebreaker, not a hard filter — losing-game memories are still
eligible but ranked lower.

The join is already required for Tier 1 (to check log quality); adding the
outcome fields is zero additional queries.

### 7.5 No-relevant-evidence state

If Tier 1 + Tier 2 produce zero items:
- Set `would_inject=False` with `reason="no relevant observed-play evidence found for current deck"`.
- Do not fall through to Tier 3 unless a `allow_fallback=True` flag is explicitly set.
- The prompt block is empty; Coach prompt is unmodified.

This avoids injecting 8 off-archetype items that the LLM will correctly reject
(wasting token budget and triggering repair retries).

The `allow_fallback` flag should default to `False` for the simulation path
and configurable for the preview path.

---

## 8. Relevance Scoring Model

Each selected evidence item receives a `relevance_score` (float, 0–1) for
debug output. Score is not stored in the DB; computed at retrieval time.

```
relevance_score = base_confidence
    + tier_bonus
    + outcome_bonus
    - source_repetition_penalty
```

| Component | Value |
|---|---|
| `base_confidence` | `item.confidence_score` (0–1) |
| Tier 1 bonus | +0.20 |
| Tier 2 bonus | +0.10 |
| Tier 3 bonus | 0.00 |
| Win outcome bonus | +0.05 |
| Source repetition (2nd item from same log) | −0.03 |

Score is exposed in `retrieval_metadata` for debug. Not used for DB storage
or any gameplay decision.

---

## 9. Query / Filter API Changes

### `build_coach_context_preview()` signature

Add optional parameters:

```python
async def build_coach_context_preview(
    db: AsyncSession,
    *,
    card_name: Optional[str] = None,          # existing (manual preview)
    action_name: Optional[str] = None,         # existing
    memory_type: Optional[str] = None,         # existing
    player_alias: Optional[str] = None,        # existing
    min_confidence: Optional[float] = None,    # existing
    limit: Optional[int] = None,               # existing
    # Phase 6.2 new:
    deck_card_ids: Optional[list[str]] = None,
    deck_card_names: Optional[list[str]] = None,
    candidate_card_ids: Optional[list[str]] = None,
    candidate_card_names: Optional[list[str]] = None,
    allow_fallback: bool = False,
) -> ObservedPlayCoachContextPreview:
```

When `deck_card_ids` is provided, tiered selection is used.
When absent, behavior falls back to the Phase 6.1 single-query path (backwards compatible).

### `ObservedPlayCoachContextPreview` schema additions

Add `retrieval_metadata` field:

```python
class ObservedPlayCoachContextPreview(BaseModel):
    # ... existing fields ...
    retrieval_metadata: Optional[ObservedPlayRetrievalMetadata] = None
    no_relevant_evidence: bool = False
```

New schema:

```python
class ObservedPlayRetrievalMetadata(BaseModel):
    strategy: str                          # e.g. "deck_overlap_v1"
    query_card_ids: list[str]              # deck card IDs used as query terms
    query_card_names: list[str]            # deck card names used
    candidate_card_ids: list[str]          # candidate add cards
    evidence_selected: list[EvidenceSelectionDetail]
    excluded_summary: EvidenceExclusionSummary

class EvidenceSelectionDetail(BaseModel):
    memory_item_id: str
    relevance_score: float
    tier: int                              # 1, 2, or 3
    matched_card_ids: list[str]            # which deck IDs triggered this match
    matched_card_names: list[str]          # which card names matched (raw)
    matched_field: str                     # "actor_card_def_id", "target_card_raw", etc.
    source_log_id: str
    from_winning_game: Optional[bool]

class EvidenceExclusionSummary(BaseModel):
    low_confidence: int
    wrong_archetype: int                   # tier 3 items excluded by no-fallback policy
    source_cap_excluded: int               # items excluded by per-log diversity cap
    unresolved_reference: int
```

---

## 10. Coach Prompt / Context Changes

The prompt block header (`_REVIEW_ONLY_HEADER`) does not need to change.

When `no_relevant_evidence=True`, the block is empty and the Coach prompt is
unmodified — same behavior as flag-off. No new prompt text is injected.

When Tier 1/2 evidence is selected, each evidence item in the block should
optionally include a one-line `relevance_reason` comment to help the LLM
understand why it was selected:

```
1. [log=..., event_id=..., turn=5, confidence=0.95]
   Relevance: actor_card matches deck (Dragapult ex, tier 1)
   Type: attack_used
   Actor: Dragapult ex
   Action: Phantom Dive
   ...
```

This is optional and controlled by a `include_relevance_hint` flag.

The `observed_play_acknowledgment` requirement from Phase 6.1 is unchanged.
Every injected round must cite evidence IDs or provide `not_used_reason`.

---

## 11. coach-debug / UI Visibility Changes

### coach-debug endpoint additions

`GET /api/simulations/{id}/coach-debug` should surface per-round retrieval
metadata:

```json
{
  "analysis_rounds": [
    {
      "round": 1,
      "block_injected": true,
      "evidence_ids_available": [...],
      "retrieval_metadata": {
        "strategy": "deck_overlap_v1",
        "query_card_ids": ["sv06-130", "sv06-127"],
        "query_card_names": ["Dragapult ex", "Dreepy"],
        "evidence_selected": [
          {
            "memory_item_id": "...",
            "relevance_score": 0.97,
            "tier": 1,
            "matched_card_ids": ["sv06-130"],
            "matched_card_names": ["Dragapult ex"],
            "matched_field": "actor_card_def_id",
            "source_log_id": "...",
            "from_winning_game": true
          }
        ],
        "excluded_summary": {
          "low_confidence": 3,
          "wrong_archetype": 12,
          "source_cap_excluded": 1,
          "unresolved_reference": 2
        }
      },
      "no_relevant_evidence": false,
      ...
    }
  ]
}
```

### Observed Play UI additions (CoachContextPreviewSection)

When `retrieval_metadata` is present, the preview section should show:

- **Strategy label**: "Deck-overlap retrieval (Phase 6.2)"
- **Query cards**: list of card names used as match terms
- **Evidence table**: existing evidence table + Tier column + Relevance Score column + Matched Card column
- **Exclusion summary**: "12 items excluded (wrong archetype), 3 excluded (low confidence)"
- **No-relevant-evidence state**: banner "No relevant observed-play evidence found for this deck."
  in place of the evidence block (instead of injecting 8 off-archetype items)

---

## 12. Testing Plan (Backend)

1. **Tier 1 match outranks global high-confidence** — given a deck containing
   Dragapult ex (`sv06-130`), a medium-confidence item with `actor_card_def_id=sv06-130`
   must be selected before a higher-confidence item with no deck card match.

2. **Candidate card match is included** — a card in `candidate_card_ids` but not
   currently in the deck must still be matched if it appears in actor/target.

3. **Tier 2 ILIKE fallback works** — an item with `actor_card_raw="Dragapult ex"`
   but `actor_card_def_id=None` (unresolved) is selected in Tier 2 when
   `deck_card_names` includes "Dragapult ex".

4. **Source diversity cap respected** — if one log produced 10 qualifying items,
   at most 2 appear in the output.

5. **No relevant evidence returns empty block** — when no deck card IDs or names
   match any memory item actor/target, `would_inject=False`,
   `no_relevant_evidence=True`, prompt block is empty.

6. **Win/loss weighting is a tiebreaker only** — a losing-game item with higher
   base confidence still beats a winning-game item with much lower confidence
   (bonus is small, not a gate).

7. **Wrong archetype evidence excluded when better exists** — with 8+ Tier 1/2
   items available, no Tier 3 (global) items appear.

8. **Flag-off behavior unchanged** — with `OBSERVED_PLAY_MEMORY_ENABLED=false`,
   `_fetch_observed_play_block()` returns `("", [])` regardless of deck context args.

9. **`retrieval_metadata` populated** — selected items include `tier`, `relevance_score`,
   `matched_card_ids`, `matched_field`, `from_winning_game`.

10. **Exclusion summary counts are correct** — `excluded_summary.wrong_archetype`
    equals the number of items that would have been selected by the Phase 6.1
    query but were displaced by Tier 1/2 items.

11. **Observed-play memory tables remain read-only** — no writes to any observed-play
    table during retrieval or injection.

12. **Backwards-compatible no-args call** — calling `build_coach_context_preview(db)`
    with no deck args continues to use the Phase 6.1 single-query path.

## Testing Plan (Frontend)

1. **CoachContextPreviewSection shows Tier/Score columns** when `retrieval_metadata`
   is present.
2. **No-relevant-evidence banner renders** when `no_relevant_evidence=true`.
3. **Exclusion summary renders** ("N items excluded — wrong archetype").
4. **Query card list renders** with deck card names.
5. **Evidence rows show matched card** column.
6. **Existing Phase 6.1 tests still pass** — flag-off, would_inject, evidence count.
7. **DeckChangesTile and DeckEvolutionPanel tests unchanged**.

---

## 13. Migration / Schema Impact

**No new migrations required for Phase 6.2a–6.2c.**

All required fields already exist:
- `ObservedPlayMemoryItem.actor_card_def_id`, `target_card_def_id`, `related_card_def_id` (indexed)
- `ObservedPlayMemoryItem.actor_card_raw`, `target_card_raw` (for ILIKE)
- `ObservedPlayLog.winner_alias`, `self_player_index` (for outcome weighting)
- `ObservedPlayLog.id` (for source diversity join)

A future migration could add a `deck_archetype_label TEXT` column to
`observed_play_logs` and a `relevance_score FLOAT` column to
`observed_play_memory_items` if retrieval performance requires it. Defer.

---

## 14. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| ILIKE on card names is slow at scale | Tier 2 runs only if Tier 1 doesn't fill the limit; add GIN index on `actor_card_raw` if needed |
| Name collisions in ILIKE (e.g. "Pikachu" matching "Pikachu ex") | Accept — both are in the deck family; false positives are minor for advisory evidence |
| Tier 3 fallback injecting irrelevant items | Default `allow_fallback=False`; only the preview endpoint enables it |
| LLM still ignores evidence even when relevant | Phase 6.1 ack enforcement handles this; Phase 6.2 improves retrieval, not LLM compliance |
| `actor_card_def_id` is null for many items | Tier 2 ILIKE handles this; Tier 1 will simply return fewer matches |
| `self_player_index` null on some logs | Win/loss weighting treated as `from_winning_game=None`; no bonus, no penalty |
| New query is slower than Phase 6.1 single query | All joins are on indexed FK columns; cap at 8 items; should be acceptable |
| Backwards compatibility break | `deck_card_ids=None` path explicitly preserved as Phase 6.1 fallback |

---

## 15. Explicit Non-Goals

Phase 6.2 must not:

- Write to `card_performance`, `match_events`, `embeddings`, Neo4j, pgvector, or any
  game-state table.
- Change AI Player behavior, simulator mutation logic, or deck builder logic.
- Store per-item relevance scores in the database.
- Add archetype labels or deck-identity resolution to logs (future phase).
- Use vector similarity / semantic search (Phase 7).
- Change how `observed_play_acknowledgment` is required or how LLM repair works.
- Force Coach to recommend swaps based on observed-play evidence.

---

## 16. Proposed Implementation Phases

### Phase 6.2a — Backend relevance service

**Scope:**
- Extend `build_coach_context_preview()` signature with optional deck context params.
- Implement `_select_tiered_evidence()` pure function:
  - Tier 1: `actor_card_def_id IN (deck_ids)` query
  - Tier 2: ILIKE name match query for Tier 1 misses
  - Tier 3: global fallback (only when `allow_fallback=True`)
- Add source diversity cap (max 2 per log).
- Add win/loss weighting join (tiebreaker boost).
- Return `retrieval_metadata` (strategy, selected items, exclusion summary).
- Add `no_relevant_evidence` field to `ObservedPlayCoachContextPreview`.
- New Pydantic schemas: `ObservedPlayRetrievalMetadata`, `EvidenceSelectionDetail`,
  `EvidenceExclusionSummary`.
- All Phase 6.1 tests still pass.
- New backend tests (items 1–12 from §12).

### Phase 6.2b — Coach context integration

**Scope:**
- Update `_fetch_observed_play_block()` to accept and pass deck/candidate context.
- Update call in `analyze_and_mutate()` to pass `deck_ids`, deck card names,
  candidate IDs.
- Persist `retrieval_metadata` in `simulations.observed_play_meta` per-round JSONB.
- Update `GET /api/simulations/{id}/coach-debug` to surface `retrieval_metadata`
  per round.
- Optional: add relevance hint lines to evidence prompt block.
- Tests: `retrieval_metadata` appears in coach-debug; no-relevant-evidence
  suppresses injection.

### Phase 6.2c — Debug / UI visibility

**Scope:**
- `CoachContextPreviewSection`: Tier/Score/MatchedCard columns, exclusion summary,
  no-relevant-evidence banner, query card list.
- Frontend tests (items 1–7 from §12).

### Phase 6.2d — Manual validation

**Manual test with Dragapult ex deck and `OBSERVED_PLAY_MEMORY_ENABLED=true`:**

1. Run a simulation.
2. Check celery logs: "OBSERVED_PLAY evidence fetch: would_inject=True"
3. Check `coach-debug.retrieval_metadata.query_card_ids` includes Dragapult ex IDs.
4. Check at least one `evidence_selected` item has `tier=1` and `matched_card_names`
   containing a deck card.
5. Check `excluded_summary.wrong_archetype > 0` if corpus has off-archetype items.
6. Run with a deck that has no matching corpus items → verify `no_relevant_evidence=true`
   and Coach prompt is unmodified.
7. Confirm observed-play memory table counts unchanged (User Check 4 recheck).

---

## 17. Acceptance Criteria

Phase 6.2 is complete when:

1. ✅ Coach receives evidence matching at least one card in the current deck (Tier 1 or 2)
   when such items exist in the corpus.
2. ✅ If no deck-relevant evidence exists, `would_inject=False` with `reason="no relevant
   observed-play evidence found"` and Coach prompt is unmodified.
3. ✅ `coach-debug` exposes `retrieval_metadata` per round: strategy, query cards,
   selected item tiers/scores/matched fields, exclusion summary.
4. ✅ Source diversity: no more than 2 items from the same log in a single retrieval.
5. ✅ Win/loss weighting is applied as a tiebreaker; losing-game evidence not excluded.
6. ✅ `OBSERVED_PLAY_MEMORY_ENABLED=false` path unchanged (no regression).
7. ✅ Observed-play memory tables remain read-only.
8. ✅ No AI Player, simulator mutation, deck builder, pgvector, Neo4j, `match_events`,
   or `card_performance` integration.
9. ✅ Manual test: Dragapult ex deck retrieves Dragapult/Dreepy/Drakloak evidence
   when available.
10. ✅ Manual test: deck with no matching corpus items produces no-evidence state.
11. ✅ All Phase 6.1 backend tests pass unchanged.
12. ✅ All new Phase 6.2 backend and frontend tests pass.

---

## 18. Open Questions for the User

Before implementation begins, please confirm:

1. **Tier 3 fallback behavior** — Should the simulation path ever fall back to
   global evidence when no deck-relevant evidence exists?
   - Option A: No fallback — inject nothing if no relevant evidence (recommended).
   - Option B: Fallback with warning injected into block ("No deck-specific evidence
     found; showing general corpus evidence for context.").

2. **Source diversity cap** — Is 2 items per log the right default?
   With 8 evidence slots and potentially many logs, 2 allows 4 different logs.
   Should this be configurable via `OBSERVED_PLAY_MEMORY_MAX_ITEMS_PER_LOG`?

3. **Relevance hint in prompt block** — Should the evidence block include a
   one-line "Relevance: actor_card matches deck (Dragapult ex)" comment per item?
   This helps the LLM understand why the item was included but adds token cost.

4. **Win/loss gate vs. tiebreaker** — Should items from losing games be excluded
   entirely, or ranked lower (tiebreaker only)?
   - Exclusion: more aggressive, but risks sparse evidence when few winning-game
     items exist for the deck.
   - Tiebreaker (recommended): safer, maintains corpus breadth.

5. **Preview endpoint fallback** — Should the `GET /coach-context-preview` endpoint
   (used for UI debugging) allow `allow_fallback=True` by default so developers
   can still see the full global corpus?

---

## Appendix A — Key Files for Implementation

| File | Role |
|---|---|
| `backend/app/observed_play/coach_context.py` | Main entry point; add tiered selection |
| `backend/app/observed_play/readiness_service.py` | Shared filter helper; minimal changes needed |
| `backend/app/observed_play/schemas.py` | Add `ObservedPlayRetrievalMetadata`, etc. |
| `backend/app/coach/analyst.py` | Update `_fetch_observed_play_block()` call |
| `backend/app/api/simulations.py` | Surface `retrieval_metadata` in coach-debug |
| `backend/app/api/observed_play.py` | Pass deck context from preview query params |
| `frontend/src/pages/ObservedPlay.tsx` | CoachContextPreviewSection upgrades |
| `frontend/src/types/observedPlay.ts` | New schema types |
| `backend/tests/test_observed_play/test_coach_context.py` | Main test file |
| `backend/tests/test_coach/test_analyst.py` | Integration tests |

## Appendix B — Current Config Keys (unchanged)

```python
OBSERVED_PLAY_MEMORY_ENABLED: bool = False
OBSERVED_PLAY_MEMORY_MAX_EVIDENCE: int = 8
OBSERVED_PLAY_MEMORY_MIN_CONFIDENCE: float = 0.85
```

Proposed new config keys for Phase 6.2:

```python
OBSERVED_PLAY_MEMORY_MAX_ITEMS_PER_LOG: int = 2
OBSERVED_PLAY_MEMORY_ALLOW_FALLBACK: bool = False
```
