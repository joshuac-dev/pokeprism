# Phase 7.0 — Observed-Play Intelligence Planning

> Planning/design only. Do not treat this document as implementation evidence.
> Phase 7 has not started. No code, migrations, Coach strategy, simulator
> behavior, AI Player behavior, pgvector retrieval, Neo4j writes, match_events
> writes, or card-performance writes are added by this plan.

---

## 1. Executive Summary

Observed-play memory is now useful as visible, deck-contextual, advisory evidence
for the Coach. Phase 6.2 proved that the system can ingest PTCGL logs, parse and
resolve card references, create memory items, gate corpus readiness, retrieve
evidence by deck overlap, inject it only behind `OBSERVED_PLAY_MEMORY_ENABLED`,
and expose retrieval decisions in the simulation Dashboard.

Phase 7 should move carefully from "event-level evidence shown to the Coach" to
"strategic knowledge that can eventually help the Coach and AI Player make
smarter, more human-like decisions." The next step should not be semantic search
or AI Player control. The safest next slice is:

**Phase 7.1 — Deck Archetype Labeling and Log/Deck Tags.**

Why this first:

- It is inspectable and manually correctable.
- It improves retrieval relevance without relying on opaque embeddings.
- It creates structure needed for matchup-aware retrieval and later strategic
  summaries.
- It can start with no schema migration by using existing `Deck.archetype` and
  `ObservedPlayLog.metadata_json`, then graduate to normalized tables if needed.
- It keeps observed-play memory advisory-only and does not alter gameplay.

Phase 7 should explicitly avoid claiming outcome improvement until Coach A/B
evaluation exists and produces evidence.

---

## 2. Current Baseline After Merge

Merged baseline:

- Observed-play raw import and archive are implemented.
- Battle logs can be parsed, re-parsed, resolved, ingested, and re-ingested.
- Observed-play memory items are stored in dedicated `observed_play_*` tables,
  not simulator `match_events`.
- Corpus readiness scorecard exists.
- `GET /api/observed-play/coach-evidence` exists as a read-only advisory
  evidence endpoint.
- Coach prompt injection exists behind `OBSERVED_PLAY_MEMORY_ENABLED=false` by
  default.
- Backend and celery-worker read the same flag through compose/env.
- Deck-contextual retrieval exists:
  - Tier 1: exact card-ID match.
  - Tier 2: card-name fallback.
  - Tier 3: global fallback only when explicitly allowed.
- Dashboard "Observed-Play Retrieval Debug" tile exposes per-round retrieval
  metadata, no-relevant-evidence, and acknowledgment details.
- Retrieval is read-only with respect to the observed-play corpus.
- `frontend/node_modules` is no longer tracked by git and remains ignored.

Current relevant data model:

- `Deck.archetype` exists as a text field.
- `Simulation.user_deck_name` and `SimulationOpponent.deck_name` preserve user
  and opponent deck names.
- `ObservedPlayLog.metadata_json` can hold experimental labels without a
  migration.
- `ObservedPlayMemoryItem.metadata_json` can hold derived evidence metadata
  without a migration.
- `simulations.observed_play_meta` already stores retrieval debug metadata.
- `embeddings` exists for pgvector generally, but observed-play semantic
  retrieval is not implemented.

Current limitation:

- Retrieval knows deck/candidate cards but not archetype or matchup.
- Observed-play logs do not have authoritative deck archetype labels.
- The system has no validated way to distinguish "a human did this" from "this
  was strategically correct."
- The impact of observed-play evidence on Coach recommendation quality is not
  measured.

---

## 3. Non-Goals and Safety Boundaries

Phase 7 planning must preserve these boundaries:

- Do not implement Phase 7 in this document.
- Do not change application code as part of planning.
- Do not change Coach strategy.
- Do not change simulator gameplay logic.
- Do not change AI Player behavior.
- Do not add pgvector migrations.
- Do not add Neo4j writes.
- Do not add `card_performance` writes.
- Do not add `match_events` writes.
- Do not alter observed-play ingestion behavior.
- Do not alter deck-builder behavior.
- Do not treat labels, memories, or observed human actions as card rules.
- Do not claim observed-play memory improves gameplay outcomes yet.

Any Phase 7 implementation should remain:

- Advisory-only.
- Visible in debug UI.
- Manually inspectable.
- Reversible or correctable by the user.
- Read-only during retrieval with respect to the observed-play corpus.
- Explicit about uncertainty and source evidence.

---

## 4. Candidate Direction A: Deck Archetype Labeling

### Goal

Classify observed-play logs, user decks, simulation decks, and possibly memory
items by archetype or core package:

- `Dragapult ex`
- `Salazzle ex`
- `Crustle`
- `Gardevoir`
- `Charizard`
- `Fire toolbox`
- `Psychic draw engine`
- `Poison/Burn strategy`

### Can archetype be inferred from deck card IDs?

For simulator decks, yes, partially. The system already has deck card IDs and
card names. A deterministic inference service can inspect quantities and key
cards:

- Primary attacker line: repeated Pokemon ex/V/main attackers.
- Evolution chain: highest-count or highest-stage line.
- Engine package: draw/search/recovery clusters.
- Energy profile: dominant type(s).
- Strategy tags: poison, burn, spread damage, mill, tank, acceleration, control.

This is not enough for a perfect label, but it can produce candidate labels with
confidence and evidence.

### Can archetype be inferred from observed logs?

Partially. PTCGL logs do not contain full deck lists, but observed logs provide:

- Repeated actor/target/related card mentions.
- Resolved card IDs from `observed_card_mentions`.
- Memory items with actor/target/related card IDs.
- Winner/self player signals.
- Common action names and event types.

Log inference should be lower confidence than deck-list inference unless enough
resolved card mentions identify a core package. A log should support multiple
labels because both players appear in the same battle log.

### Manual, automatic, or hybrid?

Hybrid is safest:

- Deterministic inference suggests labels and confidence.
- User can accept, edit, remove, or add labels.
- Manual labels override inferred labels for retrieval ranking.
- Future LLM suggestions can be added only after deterministic labels and UI
  review exist.

### Multi-label support

Required. A single deck/log can be:

- `Dragapult ex`
- `Psychic draw engine`
- `Spread damage`
- `Stage 2 setup`

Labels should have kind/category:

- `archetype`
- `package`
- `strategy`
- `matchup`
- `format/rotation` later if needed

### UI/debug visibility

Labels should appear in:

- `/observed-play` raw logs table or detail panel.
- Log memory items/analytics views.
- Simulation setup or deck summary if inferred from deck list.
- Dashboard retrieval debug tile.
- `coach-debug` retrieval metadata when labels influence ranking.

### Retrieval benefit

Labels should improve retrieval by:

- Boosting exact-card matches from same archetype/package.
- Suppressing off-archetype evidence when exact deck overlap is sparse.
- Explaining "why this memory was selected" with label-match metadata.
- Preparing for matchup-aware retrieval by establishing labels for both sides.

Labels must not replace exact card evidence. Exact card-ID matches remain the
strongest retrieval signal.

---

## 5. Candidate Direction B: Matchup-Aware Retrieval

### Goal

Retrieve memories based on both the current deck and opponent deck/threats:

- `Dragapult ex` vs `Crustle`
- `Salazzle ex` vs `Dragapult ex`
- Fire deck vs Grass-weak deck
- Setup decks vs aggressive openers

### Current opponent data

Simulator data currently has:

- `SimulationOpponent.deck_id`
- `SimulationOpponent.deck_name`
- Opponent `Deck.deck_text`
- Match rows with `p1_deck_name` / `p2_deck_name`

Observed logs have player aliases and card mentions, but no authoritative deck
lists. Opponent archetype inference from logs is possible only from observed
card mentions and should be treated as lower confidence.

### Passing opponent context to retrieval

Future retrieval can pass:

- User deck card IDs and names.
- Opponent deck card IDs and names.
- User archetype labels.
- Opponent archetype labels.
- Threat labels such as `spread`, `mill`, `poison`, `aggressive opener`.

### Scoring idea

Use additive, bounded boosts:

- Strong boost: current deck exact card overlap.
- Medium boost: opponent exact card overlap.
- Medium boost: same archetype label.
- Small boost: same strategy/package label.
- Small boost: same win/loss scenario or win condition.
- Penalty: source monopoly, unresolved references, low confidence.

### Unknown one-sided matchups

If only one side is known:

- Use current deck labels and exact cards.
- Do not globally fallback unless explicitly allowed.
- Mark matchup fields as unknown in retrieval metadata.

### Assessment

High user value, but it depends on labels. It should come after Phase 7.1 so
matchup retrieval can be explainable and debuggable.

---

## 6. Candidate Direction C: Semantic / Vector Retrieval

### Goal

Use embeddings to retrieve strategically similar observed memories even when
exact card names do not match:

- missed energy attachment sequencing
- early setup failure
- Boss's Orders targeting support Pokemon
- bench liability punished
- resource recovery after knockout
- bad prize trade

### What text should be embedded?

Possible embedding units:

1. Raw lines
   - Lowest engineering effort.
   - Highest noise and weakest semantics.

2. Parsed event summaries
   - Better structure.
   - Still event-local and may miss multi-step patterns.

3. Memory item summaries
   - Natural fit for existing `observed_play_memory_items`.
   - Can include source event type, card IDs, action, turn, and confidence.

4. Multi-event turn windows
   - Better strategic signal.
   - Requires window extraction and source grounding.

5. Whole-game summaries
   - Useful for archetype/matchup context.
   - Higher hallucination risk if LLM-generated.

6. Coach recommendations
   - Useful for evaluation later.
   - Should not be mixed into observed human play evidence without source tags.

Recommended eventual unit: grounded memory-item summary plus optional
deterministic turn-window summary, never raw unreviewed LLM prose alone.

### Model and locality

Use the local configured embedding model (`OLLAMA_EMBED_MODEL`, currently
`nomic-embed-text`) unless a later explicit product decision allows external
embedding services. Local-only is consistent with the repository's self-hosted
architecture.

### Migration impact

Potential options:

- Reuse `embeddings` with `source_type='observed_play_memory_item'`.
- Add observed-play-specific embedding metadata columns/table for freshness,
  embedding version, source event IDs, and source hash.
- Add vector indexes if query volume grows.

Any pgvector change should be a later phase, not Phase 7.1.

### Refresh after reparse/reingest

Embeddings must be invalidated or regenerated when:

- A log is re-parsed.
- Card mentions are re-resolved.
- Memory is re-ingested.
- Summary text or embedding model version changes.

This needs explicit source hashing and versioning before semantic retrieval can
be trusted.

### False strategic analogies

Mitigations:

- Never use semantic similarity alone.
- Require confidence/readiness gates.
- Combine with exact card/archetype/matchup filters.
- Show semantic match reason and source text in debug UI.
- Keep global semantic fallback opt-in.

### Assessment

High long-term value, but higher risk. It should follow labels and evaluation,
not precede them.

---

## 7. Candidate Direction D: Strategic Pattern Extraction

### Goal

Create higher-level memories from observed play, not just event-level memories:

- setup patterns
- sequencing patterns
- common misplays
- comeback lines
- prize-map decisions
- target priority
- energy attachment priorities
- retreat/switch decisions
- bench management
- when a card is dead weight
- when a package underperforms

### Rule-based, LLM, or both?

Use both, staged:

- Start with deterministic rule extraction for simple patterns:
  - early setup success/failure
  - repeated energy attachment target
  - repeated retreat/switch pattern
  - prize race / KO timing
  - target priority from `gust` or attack target events
- Add LLM summarization only after source windows are deterministic and the UI
  can review/edit the result.

### Grounding and evidence

Every strategic pattern must preserve:

- source log ID
- source event IDs
- source memory item IDs
- event window boundaries
- parser/resolver/ingestion version
- confidence and blockers

Pattern text should quote or summarize source events, not invent card rules or
private intent.

### Confidence scoring

Confidence should combine:

- parser confidence
- card resolution confidence
- number of supporting events/logs
- source diversity
- whether pattern appears in a won/lost game
- manual review status

LLM-generated summaries should start as `needs_review` regardless of text
quality.

### User review/edit

Strategic patterns need a review workflow before they influence retrieval:

- approve/reject/edit pattern
- mark "not strategic" or "misplay"
- attach labels
- see all source events

### Assessment

Very high value, but too easy to overclaim. It should follow labels and Coach
A/B evaluation scaffolding.

---

## 8. Candidate Direction E: Coach A/B Evaluation

### Goal

Measure whether observed-play evidence changes Coach recommendations in useful
ways:

- same simulation with flag off vs flag on
- exact-card retrieval vs archetype-label retrieval
- prompt with vs without archetype labels
- mutation quality comparison
- human review score

### Metrics

Possible metrics:

- recommendation delta: cards removed/added changed or not
- evidence acknowledgment quality
- evidence IDs used
- not-used reasons
- number of swaps
- mutation legality / candidate validity
- post-mutation win-rate change in H/H simulation
- regression risk
- human review score

### Comparing recommendations

Use paired runs:

- Same deck, same opponents, same candidate pool.
- Same random seed if simulator supports it later.
- Same Coach model and model options.
- Compare JSON recommendations before applying changes.

### Influence explanation

Coach should continue to include `observed_play_acknowledgment`. Later A/B mode
could require an explicit "observed-play influence" field, but only for
evaluation and debug, not strategy enforcement.

### Avoiding overfitting

- Require multiple decks/archetypes.
- Report corpus size and source diversity.
- Separate exploratory results from merge criteria.
- Avoid declaring gameplay improvement from one or two runs.

### Assessment

Important before claiming value, but it benefits from a clearer intervention to
test. Archetype labels provide that intervention.

---

## 9. Candidate Direction F: Future AI Player Influence

### Goal

Eventually help the gameplay AI make more human-like decisions:

- opening setup
- sequencing
- target choice
- prize trade
- retreat/switch decisions
- benching decisions
- energy attachment

### Not immediate

This is future planning only. Observed-play memory must not affect runtime
gameplay until it has passed stricter gates than Coach prompt evidence.

### Safety gates before gameplay influence

Before any AI Player use:

- Coach-only evaluation shows useful, non-regressive signal.
- Strategic memories are source-grounded and reviewed.
- Retrieval has false-positive controls.
- Runtime prompts can fit memory without crowding out legal action context.
- AI Player output remains legal-action constrained.
- Debug UI shows which observed-play memories affected decisions.
- There is an off switch independent of Coach injection.

### Distinguishing "did this" from "should have done this"

Observed logs only prove that a human action occurred. They do not prove the
action was correct. The system needs intermediate representations:

- observed action
- inferred context
- outcome after action
- alternative available actions, if known
- confidence in interpretation
- review status

Until then, AI Player should treat observed-play memory as examples, not
policy.

---

## 10. Comparison Matrix

| Direction | User value | Implementation risk | Schema/migration impact | UI impact | Testing complexity | Hallucination / false inference risk | pgvector / Neo4j dependency | Expected Coach usefulness | Suitability as next phase |
|---|---|---:|---:|---:|---:|---:|---:|---|---|
| A. Deck archetype labeling | High: users can understand and correct retrieval context | Low-Medium | Low if JSONB/no-migration first; Medium if normalized labels | Medium | Medium | Medium if auto-only; Low-Medium with review | None | Medium-High, especially for relevance | Best |
| B. Matchup-aware retrieval | High: addresses real match context | Medium | Medium if labels/matchup metadata are persisted | Medium | Medium-High | Medium | None initially | High once labels exist | Good after A |
| C. Semantic/vector retrieval | High long-term | High | Medium-High; embedding freshness/versioning needed | Medium | High | High without filters/review | pgvector required; Neo4j not required | Medium-High but noisy initially | Defer |
| D. Strategic pattern extraction | Very high long-term | High | Medium-High if new pattern tables | High | High | High with LLM summaries | None initially; vector later optional | High if reviewed | Defer until labels/eval |
| E. Coach A/B evaluation | High for confidence and claims | Medium | Low-Medium depending persistence | Medium | High | Low, measures rather than infers | None | Indirect but necessary | Good after A or alongside late A |
| F. Future AI Player influence | Very high if safe | Very high | Unknown / likely high | High | Very high | Very high | Maybe pgvector later | Not Coach-focused | Not next |

---

## 11. Recommended Next Slice

Recommended next phase:

**Phase 7.1 — Deck Archetype Labeling and Log/Deck Tags.**

Phase 7.1a schema/API design is now specified in
`docs/proposals/OBSERVED_PLAY_ARCHETYPE_LABELING_PHASE_7_1_SPEC.md`. That
document turns this roadmap recommendation into an implementation-ready design;
it does not implement Phase 7.1.

This matches the user's stated preference, and review does not reveal a safer or
more valuable immediate alternative.

Justification:

- It directly addresses the remaining Phase 6.2 relevance gap: card overlap is
  helpful, but archetype and package identity remain missing.
- It can be implemented incrementally and inspected in UI before it affects
  retrieval.
- It does not require pgvector, Neo4j, or gameplay changes.
- It can start with a no-migration option using existing JSONB metadata and
  `Deck.archetype`.
- It creates reusable structure for matchup-aware retrieval, semantic filtering,
  strategic pattern extraction, and A/B experiments.
- It is easy to explain in `coach-debug`: "selected because exact card matched;
  boosted because source log label matched Dragapult ex."

Non-recommended as first Phase 7 slice:

- Semantic/vector retrieval: powerful but too opaque before labels and
  evaluation exist.
- Strategic pattern extraction: valuable but higher risk of hallucinated
  strategy without a review workflow.
- AI Player influence: explicitly too early.
- A/B evaluation alone: valuable, but it needs a concrete intervention to test.
  Labels provide a low-risk intervention.

---

## 12. Proposed Phase 7.1 Design

### 12.1 Schema Options

#### Option 1: No-migration first slice

Use existing fields:

- `Deck.archetype`
  - Store a primary user-facing label for explicit deck names/manual overrides.
- `ObservedPlayLog.metadata_json`
  - Store experimental labels:
    - `archetype_labels`
    - `package_labels`
    - `strategy_labels`
    - `label_sources`
    - `label_confidence`
    - `label_review_status`
- `ObservedPlayMemoryItem.metadata_json`
  - Optionally copy source labels into items during reingest later, or compute
    by joining log metadata at retrieval time.
- `simulations.observed_play_meta`
  - Store retrieval-time label metadata for debug only.

Pros:

- Fastest and lowest risk.
- No migration.
- Easy to revert.
- Good for validating UI and retrieval semantics.

Cons:

- Harder to query efficiently at scale.
- JSON shape must be versioned carefully.
- Manual label audit history is limited.

Best use: Phase 7.1a/7.1b prototype and validation.

#### Option 2: Minimal migration

Add nullable JSONB fields:

- `decks.archetype_labels JSONB`
- `observed_play_logs.archetype_labels JSONB`

Pros:

- Still simple.
- Easier API contract than generic metadata.

Cons:

- Adds schema before the model is proven.
- Still not normalized for filtering/history.

Best use: only if JSONB metadata becomes too awkward.

#### Option 3: Normalized label tables

Possible tables:

- `archetype_labels`
  - `id`
  - `label`
  - `label_type`
  - `canonical_key`
  - `description`
- `deck_archetype_labels`
  - `deck_id`
  - `label_id`
  - `source`
  - `confidence`
  - `review_status`
- `observed_play_log_archetype_labels`
  - `observed_play_log_id`
  - `player_alias`
  - `label_id`
  - `source`
  - `confidence`
  - `review_status`
- later: `simulation_archetype_labels`

Pros:

- Queryable and auditable.
- Supports multiple labels and user review cleanly.
- Better for matchup-aware retrieval.

Cons:

- More migration/API/UI work.
- Premature if label taxonomy changes quickly.

Best use: after no-migration validation proves the shape.

### 12.2 Manual Labels vs Inferred Labels

Recommended model: hybrid.

Label sources:

- `manual`: user-entered or user-corrected.
- `deck_cards`: deterministic inference from a deck list.
- `observed_log`: deterministic inference from resolved mentions in a log.
- `llm_suggestion`: future, review-required suggestion.

Precedence:

1. Manual accepted label.
2. High-confidence deck-card inference.
3. High-confidence observed-log inference.
4. Unreviewed suggestions for display only.

Manual labels should never be overwritten by inference.

### 12.3 Label Confidence

Confidence should be explicit:

- `1.0`: manual accepted label.
- `0.80-0.95`: strong deck-list inference with key cards and counts.
- `0.60-0.80`: observed-log inference with repeated resolved core cards.
- `<0.60`: suggestion only; not used for retrieval ranking.

Confidence should be accompanied by evidence:

- matched card IDs
- matched card names
- quantities when known
- observed mention counts
- source player alias for observed logs

### 12.4 Multi-Label Support

Each deck/log should support multiple labels:

```json
[
  {
    "label": "Dragapult ex",
    "label_type": "archetype",
    "source": "deck_cards",
    "confidence": 0.93,
    "review_status": "suggested",
    "evidence_card_ids": ["sv06-130", "sv06-129", "sv06-128"]
  },
  {
    "label": "Spread damage",
    "label_type": "strategy",
    "source": "deck_cards",
    "confidence": 0.75,
    "review_status": "suggested",
    "evidence_card_ids": ["sv06-130"]
  }
]
```

### 12.5 Sources of Labels

Deck cards:

- Best source for simulator/user decks.
- Can infer primary archetype from core lines and card counts.

Observed logs:

- Best source for imported PTCGL logs.
- Must track player alias because each log has two players.
- Should require enough resolved mentions before assigning a confident label.

User override:

- Required for correction and trust.
- Should be visible in retrieval debug.

Future LLM suggestion:

- Useful for taxonomy expansion.
- Must be marked `needs_review` and source-grounded.
- Should not affect retrieval until accepted or high-confidence deterministic
  logic confirms it.

### 12.6 UI Display

Suggested UI surfaces:

- `/observed-play` log table:
  - compact label chips.
  - warning icon for unreviewed/inferred labels.
- Log detail:
  - labels by player alias.
  - evidence cards/mentions behind each label.
  - edit/accept/reject controls.
- Memory analytics:
  - filter by label.
  - group source items by label.
- Simulation setup / deck upload:
  - show inferred deck labels after parsing deck cards.
  - allow manual archetype name to seed labels.
- Dashboard retrieval debug:
  - show current deck labels, source log labels, and any label match boost.

Avoid clutter by showing only primary label chips by default and expanding to
full evidence on demand.

### 12.7 Retrieval Integration

Labels should first be surfaced in debug only. Once validated, retrieval can use
labels as a ranking signal:

- Do not replace Tier 1 exact card-ID matching.
- Apply a bounded boost to evidence from matching archetype/package labels.
- Apply a penalty or suppression to evidence from clearly conflicting labels
  when no exact-card match exists.
- Keep `allow_fallback=false` default.
- Expose label effects in retrieval metadata:
  - `deck_labels`
  - `source_log_labels`
  - `label_match`
  - `label_boost`
  - `label_reason`

Example debug reason:

```text
deck_card Dragapult ex matched actor_card_def_id; label boost: source log label Dragapult ex matched current deck label Dragapult ex
```

### 12.8 Coach-Debug Representation

Add planned retrieval metadata fields:

```json
{
  "current_deck_labels": [
    {"label": "Dragapult ex", "type": "archetype", "source": "deck_cards", "confidence": 0.93}
  ],
  "evidence_selected": [
    {
      "memory_item_id": "...",
      "tier": 1,
      "match_source": "deck_card",
      "label_match": true,
      "label_boost": 0.05,
      "label_reason": "source log label Dragapult ex matched current deck label Dragapult ex"
    }
  ]
}
```

These fields are debug/explanation fields, not gameplay-control fields.

### 12.9 Advisory-Only Boundary

Labels remain advisory-only:

- They can rank observed-play evidence.
- They can explain retrieval.
- They cannot override card text, card database facts, simulator state, or
  legal action validation.
- They cannot write to `match_events`, `card_performance`, Neo4j, or pgvector.
- They cannot affect AI Player runtime decisions in Phase 7.1.

### 12.10 Preventing Labels From Becoming Rules

Mitigations:

- Prompt/debug copy: "labels describe source context, not card rules."
- Retrieval metadata distinguishes exact card evidence from label boost.
- Labels have confidence and review status.
- Manual correction is available.
- Label boost is bounded and cannot promote evidence below readiness/confidence
  gates.
- Tests assert exact-card relevance outranks label-only relevance.

---

## 13. Proposed Implementation Phases

### Phase 7.1a — Planning and Schema Design

- Finalize label JSON shape or decide on migration.
- Define label taxonomy conventions.
- Define confidence/review status vocabulary.
- Define API response shapes.
- No runtime behavior changes.
- Detailed spec:
  `docs/proposals/OBSERVED_PLAY_ARCHETYPE_LABELING_PHASE_7_1_SPEC.md`.

### Phase 7.1b — Backend Archetype Inference Service

- Implement deterministic deck-card inference.
- Implement deterministic observed-log inference from resolved mentions.
- Return labels as suggested metadata.
- Unit-test known archetypes and mixed/unknown cases.
- Keep retrieval unchanged initially.

### Phase 7.1c — UI Label Display / Edit / Review

- Show labels on `/observed-play` logs and deck surfaces.
- Add accept/edit/reject flow if persistence is included.
- Show evidence behind labels.
- Keep labels visible but non-authoritative.

### Phase 7.1d — Retrieval Integration as Ranking Signal

- Pass current deck labels into observed-play retrieval.
- Join or load source log labels.
- Add bounded label boost only after exact-card/name tiers.
- Surface label influence in `coach-debug`.
- Keep flag-off behavior unchanged.

### Phase 7.1e — Manual Validation Across Archetypes

- Validate Dragapult, Salazzle, Crustle, Charizard, and at least one ambiguous
  toolbox deck.
- Confirm labels are visible and correctable.
- Confirm label-only matches do not override exact-card matches.
- Confirm observed-play corpus tables are not mutated during retrieval.
- Confirm no gameplay, AI Player, pgvector, Neo4j, match_events, or
  card-performance writes.

### Phase 7.2 — Matchup-Aware Retrieval

- Use labels from both current deck and opponent deck.
- Add matchup relevance metadata.
- Keep fallback conservative.

### Phase 7.3 — Coach A/B Evaluation Harness

- Compare flag-off vs flag-on and exact-card vs label-aware retrieval.
- Persist evaluation records only if needed.
- Create human review rubric.

### Phase 7.4 — Strategic Pattern Extraction Planning / Prototype

- Define grounded event windows and review workflow.
- Avoid LLM summaries until source windows are deterministic.

### Phase 7.5+ — Semantic Retrieval and AI Player Planning

- Add vector retrieval only after labels/evaluation exist.
- Keep AI Player influence behind later explicit safety gates.

---

## 14. Acceptance Criteria

For Phase 7.1:

- Labels are visible and reviewable on relevant observed-play and deck surfaces.
- Labels can be manually corrected or overridden.
- Labels support multiple values per deck/log.
- Label source and confidence are visible.
- Inferred labels show evidence cards/mentions.
- Retrieval debug explains when label match influenced evidence selection.
- Labels do not override exact card evidence.
- Label-only matches cannot bypass readiness/confidence gates.
- Flag-off behavior is unchanged.
- `OBSERVED_PLAY_MEMORY_ENABLED=false` still prevents prompt injection.
- Observed-play corpus remains read-only during retrieval.
- No AI Player control.
- No simulator gameplay change.
- No Coach strategy change beyond optional retrieval ranking metadata if Phase
  7.1d is explicitly implemented.
- No `card_performance` writes.
- No `match_events` writes.
- No Neo4j writes.
- No pgvector writes.
- No deck-builder behavior changes.
- No claim is made that labels or observed-play evidence improve gameplay
  outcomes until A/B evaluation supports it.

---

## 15. Risks and Mitigations

### Mislabeling decks

Risk: inferred labels are wrong and retrieval becomes less relevant.

Mitigations:

- Use confidence thresholds.
- Show evidence behind labels.
- Let user correct labels.
- Keep exact-card matches higher priority than labels.

### Small corpus overfitting

Risk: a few logs dominate label behavior.

Mitigations:

- Keep source diversity cap.
- Display source counts.
- Avoid strong label boosts until multiple sources exist.
- Do not claim outcome improvement.

### Archetype drift across rotations

Risk: a label such as `Charizard` changes meaning across sets.

Mitigations:

- Store evidence card IDs and set IDs.
- Consider future format/rotation labels.
- Keep labels editable and versioned.

### Multi-archetype decks

Risk: one primary label hides important packages.

Mitigations:

- Support multiple label types.
- Show primary plus secondary labels.
- Do not force a single archetype.

### False confidence

Risk: users treat a confident label as proof of strategic correctness.

Mitigations:

- Label source context separately from recommendation confidence.
- Use "suggested" / "accepted" review states.
- Include "labels are not rules" copy in debug and docs.

### Labels being treated as rules

Risk: Coach or future AI Player infers card behavior from labels.

Mitigations:

- Prompt boundary: card DB/rules text wins.
- Retrieval metadata separates label boost from evidence content.
- Tests assert labels do not alter legal/action logic.

### User confusion

Risk: labels, packages, and strategies blur together.

Mitigations:

- Use label types.
- Keep UI chips concise.
- Provide evidence drilldown.

### UI clutter

Risk: observed-play pages become dense.

Mitigations:

- Show primary labels by default.
- Collapse secondary labels/evidence.
- Use filters and detail panels instead of wide tables.

---

## 16. Open Questions for the User

Before implementation, decide:

1. Should Phase 7.1 start with manual archetype labels, automatic labels, or
   both at once?
2. Should labels live on logs, decks, simulations, or all three?
3. Should observed-play log labels be per-log only or per-player within a log?
4. Should labels be user-editable in the first implementation slice?
5. Should the system support multiple labels per deck/log from day one?
6. Should label types be limited to `archetype`, `package`, and `strategy`, or
   should matchup/threat labels also be included immediately?
7. Should archetype labels be used only for retrieval ranking, or also for
   filtering in `/observed-play` and analytics?
8. How aggressive should fallback retrieval be when no archetype match exists?
9. Should Phase 7.1 avoid migrations if possible and validate JSONB metadata
   first?
10. Should manual labels be required before label-aware retrieval affects Coach
    prompts?
11. What label taxonomy should be seeded first: current local corpus labels,
    common meta archetypes, or user-defined labels only?
12. Should label confidence be shown as a numeric score, a badge
    (`high/medium/low`), or both?
13. Should inferred labels be regenerated automatically after reparse/reingest,
    or only on explicit user action?
14. Should label corrections be global rules, per-log overrides, or both?
15. What manual validation archetypes should be required before Phase 7.1 is
    considered complete?
