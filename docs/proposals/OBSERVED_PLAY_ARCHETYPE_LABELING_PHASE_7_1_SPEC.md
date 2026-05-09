# Phase 7.1a — Archetype Labeling Schema/API Design

> Design/spec only. This document does not implement application code,
> migrations, retrieval behavior, Coach strategy, simulator gameplay, AI Player
> behavior, pgvector retrieval, Neo4j writes, `match_events` writes,
> `card_performance` writes, or observed-play ingestion changes.

> Phase 7.1b update: the backend deterministic preview slice is now implemented
> in `backend/app/observed_play/archetype_labels.py` with read-only preview
> endpoints for decks and observed logs. Labels are still not persisted by
> default and are not used for retrieval ranking.

---

## 1. Executive Summary

Phase 7.1 should introduce deck/log archetype labels as visible, reviewable
context before those labels affect evidence retrieval. The first implementation
slice should prefer deterministic suggestions plus manual correction, support
multiple labels per deck/log, and preserve the Phase 6 rule that observed-play
memory is advisory-only and verifiable.

Recommended path:

1. Define a canonical label JSON shape.
2. Add backend deterministic preview functions for decks and observed logs.
3. Display suggested/manual labels in the UI with evidence and review status.
4. Persist labels only after explicit user action, preferably through existing
   metadata fields for the first slice.
5. Integrate labels into retrieval later as a bounded ranking signal, not a hard
   filter.

Important constraints:

- This is still advisory-only.
- This is design/spec only.
- No code or migrations are implemented by this document.
- Phase 7.1 should start with labels visible/reviewable before labels affect
  retrieval ranking.
- No claim should be made that observed-play memory improves gameplay outcomes
  until later evaluation proves that.

---

## 2. Current Data Model and Relevant Fields

This section records current repo names and fields to avoid designing against
invented schema.

### Deck model

`backend/app/db/models.py` defines:

- `Deck`
  - `id`
  - `name`
  - `archetype`
  - `deck_text`
  - `card_count`
  - `source`
  - `created_at`
- `DeckCard`
  - `deck_id`
  - `card_tcgdex_id`
  - `quantity`

`Deck.archetype` already exists as a nullable text field. It is currently useful
for a primary/manual deck label, but it cannot represent multi-label state,
source, confidence, review status, evidence, or history by itself.

`Deck.deck_text` and `DeckCard.card_tcgdex_id` / `DeckCard.quantity` are the
best current inputs for deterministic deck-card inference. In simulation code,
deck text is also parsed by helpers in `backend/app/tasks/simulation.py`, and
simulation decks may exist as cloned `Deck` rows with `source="simulation"`.

### Parsed deck representations

Relevant current representations:

- DB-backed deck rows: `Deck` plus `DeckCard`.
- Text decks: `Deck.deck_text`, simulation request `deck_text`, and
  `opponent_deck_texts`.
- Frontend parser utility: `frontend/src/utils/deckParser.ts` exposes a
  `DeckCard` interface for UI-side display/validation.
- Simulation detail/final-deck types in `frontend/src/types/simulation.ts`
  include deck card entries for display, but those are not an archetype label
  contract today.

The backend implementation should infer labels from authoritative backend card
IDs where possible, not from frontend-only parsing.

### ObservedPlayLog

`ObservedPlayLog` is the canonical imported battle log row. Relevant fields:

- `id`
- `source`
- `original_filename`
- `sha256_hash`
- `raw_content`
- `parse_status`
- `memory_status`
- `memory_item_count`
- `last_memory_ingested_at`
- `parser_version`
- `player_1_name_raw`
- `player_2_name_raw`
- `player_1_alias`
- `player_2_alias`
- `self_player_index`
- `winner_raw`
- `winner_alias`
- `win_condition`
- `turn_count`
- `event_count`
- `recognized_card_count`
- `unresolved_card_count`
- `ambiguous_card_count`
- `card_mention_count`
- `card_resolution_status`
- `resolver_version`
- `confidence_score`
- `errors_json`
- `warnings_json`
- `metadata_json`

`ObservedPlayLog.metadata_json` is the main no-migration candidate for log-level
and per-player labels.

### ObservedPlayEvent

`ObservedPlayEvent` contains parsed event rows. Relevant fields for label
evidence:

- `id`
- `observed_play_log_id`
- `event_index`
- `turn_number`
- `phase`
- `player_raw`
- `player_alias`
- `actor_type`
- `event_type`
- `raw_line`
- `card_name_raw`
- `target_card_name_raw`
- `event_payload_json`
- `confidence_score`
- `parser_version`

Events are useful as evidence IDs for observed-log inference, especially when a
label is suggested because a player repeatedly evolved, attacked with, benched,
or attached to a core card line.

### Observed card mentions

`ObservedCardMention` records extracted/resolved card mentions:

- `id`
- `observed_play_log_id`
- `observed_play_event_id`
- `mention_index`
- `mention_role`
- `raw_name`
- `normalized_name`
- `resolved_card_def_id`
- `resolved_card_name`
- `resolution_status`
- `resolution_confidence`
- `resolution_method`
- `resolution_reason`
- `candidate_count`
- `candidates_json`
- `source_event_type`
- `source_field`
- `source_payload_path`

This is the safest source for deterministic observed-log label inference because
it links a player/event context to resolved card IDs without reading raw text
heuristically.

### ObservedPlayMemoryItem

`ObservedPlayMemoryItem` is the normalized memory fact used by Coach evidence
retrieval. Relevant fields:

- `id`
- `observed_play_log_id`
- `observed_play_event_id`
- `memory_type`
- `memory_key`
- `turn_number`
- `phase`
- `player_alias`
- `actor_card_raw`
- `actor_card_def_id`
- `actor_resolution_status`
- `target_card_raw`
- `target_card_def_id`
- `target_resolution_status`
- `related_card_raw`
- `related_card_def_id`
- `related_resolution_status`
- `action_name`
- `confidence_score`
- `source_event_type`
- `source_raw_line`
- `source_payload_json`
- `metadata_json`

`ObservedPlayMemoryItem.metadata_json` is available but should not be the first
place to store log/deck labels. It is more appropriate for per-memory derived
details if later retrieval needs denormalized label snapshots.

### Simulations and coach-debug metadata

`Simulation.observed_play_meta` is nullable JSONB storing per-round injection
state for coach-debug. `DeckMutation.observed_play_meta` stores mutation-level
observed-play debug metadata when mutations are produced.

Current coach-debug response shape is represented by:

- `backend/app/observed_play/schemas.py`
  - `EvidenceSelectionDetail`
  - `EvidenceExclusionSummary`
  - `ObservedPlayRetrievalMetadata`
  - `ObservedPlayCoachContextPreview`
- `frontend/src/types/observedPlay.ts`
  - `EvidenceSelectionDetail`
  - `ObservedPlayRetrievalMetadata`
  - `ObservedPlayCoachContextPreview`
- `frontend/src/types/simulation.ts`
  - `CoachDebugAnalysisRound`
  - `CoachDebugResponse`

Current `ObservedPlayRetrievalMetadata` fields:

- `strategy`
- `deck_card_ids`
- `deck_card_names`
- `candidate_card_ids`
- `candidate_card_names`
- `allow_fallback`
- `max_items_per_log`
- `no_relevant_evidence`
- `evidence_selected`
- `excluded_summary`

Future label integration can extend retrieval metadata with label context, but
Phase 7.1b should first display labels without changing retrieval ranking.

---

## 3. Label Concepts and Vocabulary

### Label types

- `archetype`: Main deck identity such as `Dragapult ex`, `Charizard ex`, or
  `Crustle`.
- `package`: Reusable card cluster or engine such as `Psychic draw engine`,
  `Rare Candy Stage 2 package`, or `Poison/Burn package`.
- `strategy`: Tactical pattern such as `spread damage`, `control`,
  `aggressive opener`, `resource recovery`, or `bench pressure`.
- `matchup`: Pairwise context such as `Dragapult ex vs Crustle`. This should be
  future/derived, not the first persisted label.
- `format_rotation`: Future-only if labels need to distinguish card legality or
  rotation-era drift.

Labels describe context. They do not define card rules, legal actions, or
gameplay strategy by themselves.

### Label sources

- `manual`: User-created or user-edited label.
- `deck_cards`: Deterministic inference from a deck list / `DeckCard` rows.
- `observed_log`: Deterministic inference from observed log events, card
  mentions, and memory items.
- `llm_suggestion`: Future/review-only source. Must not be auto-accepted.
- `imported`: Future source if the user imports labels from another system.

### Review statuses

- `suggested`: System-generated and not yet accepted.
- `accepted`: User or trusted workflow accepted the label.
- `rejected`: User rejected the suggestion.
- `edited`: User changed label text, type, or metadata.
- `stale`: Source evidence changed after reparse, reingest, or deck edit.
- `needs_review`: Label may still be useful, but confidence/evidence changed or
  the source is ambiguous.

Manual `accepted` and `edited` labels override inferred labels with the same
`canonical_key` and `label_type`.

### Confidence ranges

- `1.0`: Manual accepted/edited label.
- `0.80-0.95`: Strong deterministic deck-list inference.
- `0.60-0.80`: Observed-log inference from repeated resolved evidence.
- `<0.60`: Suggestion/display-only. Do not use for retrieval ranking.

Confidence is not gameplay truth. It is only the system's confidence that the
label describes the deck/log context.

---

## 4. Label JSON Shape

Use a canonical object so Option A metadata storage can migrate cleanly to
normalized tables later.

```json
{
  "schema_version": 1,
  "label": "Dragapult ex",
  "canonical_key": "dragapult_ex",
  "label_type": "archetype",
  "source": "deck_cards",
  "confidence": 0.92,
  "review_status": "suggested",
  "player_alias": null,
  "evidence_card_ids": ["sv06-130", "sv06-129", "sv06-128"],
  "evidence_card_names": ["Dragapult ex", "Drakloak", "Dreepy"],
  "evidence_counts": {
    "sv06-130": 3,
    "sv06-129": 3,
    "sv06-128": 4
  },
  "evidence_event_ids": [],
  "evidence_memory_item_ids": [],
  "created_at": "2026-05-09T00:00:00Z",
  "updated_at": "2026-05-09T00:00:00Z",
  "reviewed_at": null,
  "reviewed_by": null,
  "notes": null
}
```

Field rules:

- `label`: user-facing label text.
- `canonical_key`: stable lowercase key, normalized for matching and migration.
- `label_type`: one of the label types in this spec.
- `source`: one of the label sources in this spec.
- `confidence`: float between `0.0` and `1.0`.
- `review_status`: one of the review statuses in this spec.
- `player_alias`: nullable. Required for observed-log labels when the label
  applies to only one player in a two-player log.
- `evidence_card_ids`: TCGdex IDs when known.
- `evidence_card_names`: card names used to explain the label.
- `evidence_counts`: counts by card ID, card name, memory type, or rule key.
- `evidence_event_ids`: `ObservedPlayEvent.id` values for log labels.
- `evidence_memory_item_ids`: `ObservedPlayMemoryItem.id` values for memory
  evidence.
- `created_at` / `updated_at` / `reviewed_at`: ISO 8601 UTC strings.
- `reviewed_by`: nullable local user identifier if a user model exists later.
- `notes`: user or system note.
- `schema_version`: integer used for migration and stale-label detection.

### Example 1: deck label

```json
{
  "schema_version": 1,
  "label": "Dragapult ex",
  "canonical_key": "dragapult_ex",
  "label_type": "archetype",
  "source": "deck_cards",
  "confidence": 0.92,
  "review_status": "suggested",
  "player_alias": null,
  "evidence_card_ids": ["sv06-130", "sv06-129", "sv06-128"],
  "evidence_card_names": ["Dragapult ex", "Drakloak", "Dreepy"],
  "evidence_counts": {"sv06-130": 3, "sv06-129": 3, "sv06-128": 4},
  "evidence_event_ids": [],
  "evidence_memory_item_ids": [],
  "created_at": "2026-05-09T00:00:00Z",
  "updated_at": "2026-05-09T00:00:00Z",
  "reviewed_at": null,
  "reviewed_by": null,
  "notes": "Suggested from full deck list."
}
```

### Example 2: observed-log label for one player

```json
{
  "schema_version": 1,
  "label": "Crustle",
  "canonical_key": "crustle",
  "label_type": "archetype",
  "source": "observed_log",
  "confidence": 0.73,
  "review_status": "suggested",
  "player_alias": "player_2",
  "evidence_card_ids": ["sv07-076", "sv07-075"],
  "evidence_card_names": ["Crustle", "Dwebble"],
  "evidence_counts": {"resolved_mentions": 7, "core_line_mentions": 5},
  "evidence_event_ids": [12041, 12057, 12103],
  "evidence_memory_item_ids": [
    "13a69362-22fa-4d93-9a30-3f1df09077c1",
    "b7bc83f5-c7ef-40fd-929a-0fb69487a51e"
  ],
  "created_at": "2026-05-09T00:00:00Z",
  "updated_at": "2026-05-09T00:00:00Z",
  "reviewed_at": null,
  "reviewed_by": null,
  "notes": "Suggested from repeated resolved mentions for player_2."
}
```

### Example 3: strategy/package label

```json
{
  "schema_version": 1,
  "label": "Poison/Burn package",
  "canonical_key": "poison_burn_package",
  "label_type": "package",
  "source": "deck_cards",
  "confidence": 0.86,
  "review_status": "suggested",
  "player_alias": null,
  "evidence_card_ids": ["sv10-020", "sv10-019"],
  "evidence_card_names": ["Salazzle ex", "Salandit"],
  "evidence_counts": {"poison_related_cards": 4, "burn_related_cards": 2},
  "evidence_event_ids": [],
  "evidence_memory_item_ids": [],
  "created_at": "2026-05-09T00:00:00Z",
  "updated_at": "2026-05-09T00:00:00Z",
  "reviewed_at": null,
  "reviewed_by": null,
  "notes": "Package label only; not a rules assertion."
}
```

### Example 4: manually corrected label

```json
{
  "schema_version": 1,
  "label": "Fire toolbox",
  "canonical_key": "fire_toolbox",
  "label_type": "archetype",
  "source": "manual",
  "confidence": 1.0,
  "review_status": "edited",
  "player_alias": null,
  "evidence_card_ids": ["sv03-125", "sv04-024"],
  "evidence_card_names": ["Charizard ex", "Armarouge"],
  "evidence_counts": {"manual_override": 1},
  "evidence_event_ids": [],
  "evidence_memory_item_ids": [],
  "created_at": "2026-05-09T00:00:00Z",
  "updated_at": "2026-05-09T00:10:00Z",
  "reviewed_at": "2026-05-09T00:10:00Z",
  "reviewed_by": "local_user",
  "notes": "User corrected from Charizard ex because deck is broader toolbox."
}
```

### Example 5: stale/rejected inferred label

```json
{
  "schema_version": 1,
  "label": "Charizard ex",
  "canonical_key": "charizard_ex",
  "label_type": "archetype",
  "source": "deck_cards",
  "confidence": 0.84,
  "review_status": "rejected",
  "player_alias": null,
  "evidence_card_ids": ["sv03-125"],
  "evidence_card_names": ["Charizard ex"],
  "evidence_counts": {"sv03-125": 1},
  "evidence_event_ids": [],
  "evidence_memory_item_ids": [],
  "created_at": "2026-05-09T00:00:00Z",
  "updated_at": "2026-05-09T00:12:00Z",
  "reviewed_at": "2026-05-09T00:12:00Z",
  "reviewed_by": "local_user",
  "notes": "Rejected: one-off attacker, not deck identity."
}
```

---

## 5. Storage Options

### Option A — No migration, metadata_json first

Use existing fields:

- `Deck.archetype`: primary accepted/manual deck archetype when a single primary
  label is appropriate.
- `ObservedPlayLog.metadata_json`: log-level and per-player labels.
- `ObservedPlayMemoryItem.metadata_json`: only for optional denormalized label
  snapshots later.
- `Simulation.observed_play_meta`: retrieval/debug snapshots when label influence
  is eventually used.

Recommended JSON keys:

```json
{
  "archetype_labeling": {
    "schema_version": 1,
    "labels": [],
    "player_labels": {
      "player_1": [],
      "player_2": []
    },
    "last_inferred_at": "2026-05-09T00:00:00Z",
    "last_reviewed_at": null,
    "inference_version": "archetype_labels_v1",
    "source_fingerprint": {
      "parser_version": "1.0",
      "resolver_version": "1.0",
      "memory_item_count": 42,
      "event_count": 185,
      "deck_card_count": null
    }
  }
}
```

For deck metadata, because `Deck` currently has no `metadata_json`, the
no-migration path has two choices:

- Store only the primary manual label in `Deck.archetype` and keep additional
  deck-label state preview-only until a migration.
- Store multi-label deck state outside `Deck` only in simulation/debug metadata
  until a migration.

Pros:

- No migration in the first slice.
- Low blast radius.
- Works well for observed logs because `ObservedPlayLog.metadata_json` already
  exists.
- Easy to remove by clearing a metadata key.
- Lets UI/review concepts prove value before schema work.

Cons:

- `Deck` lacks a JSON metadata field, so deck multi-label persistence is awkward.
- Querying labels across logs requires JSONB expressions or app-side filtering.
- No relational constraints on canonical keys, label types, or review statuses.
- No clean cross-deck label index.
- Harder to audit label edit history.

Query limitations:

- Listing logs by label can use JSONB containment later, but would be less clear
  than a normalized table.
- Listing decks by secondary/package labels is not practical without a migration.
- Bulk analytics by label will be brittle if performed directly against JSON.

Migration escape hatch:

- Keep canonical label objects stable.
- Keep `schema_version` on each label object.
- Keep labels under a single metadata key: `archetype_labeling`.
- Future migrations can read `ObservedPlayLog.metadata_json["archetype_labeling"]`
  and `Deck.archetype`, then write normalized rows.

### Option B — Minimal migration

Add nullable JSONB fields:

- `decks.archetype_labels`
- `observed_play_logs.archetype_labels`

Pros:

- Multi-label support for both decks and logs.
- Clearer than overloading `Deck.archetype`.
- Still simple and reversible.
- Easier API implementation than normalized tables.
- Avoids mixing parser diagnostics and label review state in one JSON blob.

Cons:

- Requires a migration.
- Still lacks relational constraints.
- Still not ideal for cross-label analytics.
- Edit history remains manual unless the JSON includes history.

Choose this instead of Option A if:

- Phase 7.1b must persist multi-label deck state immediately.
- UI editing is required in the first implementation slice.
- Retrieval ranking integration is expected soon after display/review.

### Option C — Normalized label tables

Possible tables:

- `archetype_labels`
  - canonical label definitions / taxonomy rows.
- `deck_archetype_labels`
  - deck-to-label assignments.
- `observed_play_log_archetype_labels`
  - log/player-to-label assignments.

Potential columns:

- `id`
- `canonical_key`
- `label`
- `label_type`
- `source`
- `confidence`
- `review_status`
- `player_alias`
- evidence JSONB fields
- timestamps
- `schema_version`

Pros:

- Best queryability and constraints.
- Supports analytics, filters, audit history, and label taxonomies.
- Clean indexing by label, source, review status, and player alias.
- Best long-term storage for matchup-aware and evaluation work.

Cons:

- Highest migration/design cost.
- Requires more API and test surface.
- Easier to overbuild before label UX is validated.

Defer until:

- Labels are proven useful in UI review.
- Retrieval ranking needs indexed label joins.
- The taxonomy becomes stable enough to enforce.
- The user wants label edit history and auditability.

### Recommendation

Use Option A for Phase 7.1a/7.1b if the first implementation is preview-only or
log-label persistence only. Design the JSON shape exactly as if it will migrate
to Option C later.

If Phase 7.1b must persist user-editable multi-label deck state immediately,
choose Option B instead. `Deck.archetype` alone is not enough for the user
decisions in this spec because it cannot support multiple labels or review
metadata.

---

## 6. API Design

Backend service-level APIs should come first. HTTP endpoints should wrap those
services only after the core label contract is stable.

### Service functions

#### `infer_labels_for_deck`

- Signature:
  - `infer_labels_for_deck(deck_id: UUID | None = None, deck_text: str | None = None, persist: bool = False)`
- Reads:
  - `Deck`
  - `DeckCard`
  - `Card`
- Writes:
  - None when `persist=false`.
  - Option A: `Deck.archetype` only after explicit user action for primary
    manual/accepted label.
  - Option B/C: future persistence fields/tables.
- Response:
  - `labels: list[ArchetypeLabel]`
  - `source_fingerprint`
  - `warnings`
- Validation:
  - Require `deck_id` or `deck_text`.
  - Reject invalid deck IDs.
  - Cap deck card count to expected deck limits.
- Errors:
  - `404` deck not found if wrapped by HTTP.
  - `422` invalid request.

#### `infer_labels_for_observed_log`

- Signature:
  - `infer_labels_for_observed_log(log_id: UUID, persist: bool = False)`
- Reads:
  - `ObservedPlayLog`
  - `ObservedPlayEvent`
  - `ObservedCardMention`
  - `ObservedPlayMemoryItem`
- Writes:
  - None when `persist=false`.
  - `ObservedPlayLog.metadata_json["archetype_labeling"]` only after explicit
    action if Option A persistence is enabled.
- Response:
  - `log_id`
  - `player_labels: {"player_1": [...], "player_2": [...]}`
  - `log_labels`
  - `source_fingerprint`
  - `warnings`
- Validation:
  - Log must exist.
  - Parsed/resolved data may be missing; return warnings, not a crash.
- Errors:
  - `404` log not found.
  - `409` log not parsed if persistence is requested and no evidence exists.

#### `list_labels_for_deck`

- Reads:
  - `Deck.archetype`, future label storage.
- Writes:
  - No.
- Safe/read-only:
  - Yes.
- Response:
  - `deck_id`
  - `labels`
  - `primary_label`
  - `warnings`

#### `list_labels_for_observed_logs`

- Reads:
  - `ObservedPlayLog.metadata_json`
- Writes:
  - No.
- Safe/read-only:
  - Yes.
- Response:
  - Paginated log-label summary.
- Validation:
  - Pagination required.
  - Optional `label`, `canonical_key`, `review_status`, `player_alias` filters.

#### `accept_label`

- Writes:
  - Yes.
- Behavior:
  - Set `review_status="accepted"`.
  - Set `confidence=1.0` only when the source becomes `manual`; otherwise keep
    original confidence but record review acceptance.
  - Do not overwrite an existing manual accepted label unless explicitly told to
    replace it.
- Expected errors:
  - `404` target not found.
  - `409` conflicting manual label.
  - `422` invalid label object.

#### `reject_label`

- Writes:
  - Yes.
- Behavior:
  - Set `review_status="rejected"`.
  - Retain rejected labels for audit/history unless the user chooses permanent
    deletion later.
- Expected errors:
  - `404`, `422`.

#### `edit_label`

- Writes:
  - Yes.
- Behavior:
  - Update `label`, `canonical_key`, `label_type`, `notes`.
  - Set `source="manual"` and `review_status="edited"`.
  - Set `confidence=1.0`.
- Expected errors:
  - `409` if canonical key conflicts with another accepted manual label.

#### `add_manual_label`

- Writes:
  - Yes.
- Request:
  - `target_type`
  - `target_id`
  - `label`
  - `label_type`
  - `player_alias`
  - `notes`
- Response:
  - Created label.
- Validation:
  - `player_alias` is allowed for observed logs and ignored/rejected for decks.
  - `label_type` must be known.

#### `remove_manual_label`

- Writes:
  - Yes.
- Recommendation:
  - Prefer soft removal by marking `review_status="rejected"` or
    `review_status="stale"` rather than deleting immediately.

#### `bulk_infer_labels_for_observed_logs`

- Writes:
  - Optional.
- Recommendation:
  - Initial version should be preview/report-only.
- Validation:
  - Pagination/batch limits required.
  - Explicit `persist=true` required for writes.

#### `preview_labels_without_saving`

- Reads:
  - Deck/log evidence only.
- Writes:
  - No.
- Safe/read-only:
  - Yes.
- This should be the default mode for Phase 7.1b.

#### `get_label_taxonomy`

- Reads:
  - Static config or future table.
- Writes:
  - No.
- Response:
  - Known canonical labels, aliases, type, seed evidence card names/IDs if
    available.

### Candidate HTTP endpoints

Use `/api/observed-play/archetype-labels` namespace for observed-play label
operations. Deck-only operations can live under `/api/decks/{deck_id}/...` once
the deck API pattern is inspected during implementation.

#### `POST /api/observed-play/archetype-labels/preview-deck`

Request:

```json
{
  "deck_id": "uuid-or-null",
  "deck_text": "optional deck text",
  "include_package_labels": true
}
```

Response:

```json
{
  "target_type": "deck",
  "target_id": "uuid-or-null",
  "labels": [],
  "warnings": [],
  "persisted": false
}
```

Writes: no.

#### `POST /api/observed-play/logs/{log_id}/archetype-labels/preview`

Request:

```json
{
  "include_memory_items": true,
  "include_card_mentions": true
}
```

Writes: no.

#### `GET /api/observed-play/logs/{log_id}/archetype-labels`

Writes: no.

Response includes stored labels plus optional fresh suggestions if
`include_suggestions=true`.

#### `POST /api/observed-play/logs/{log_id}/archetype-labels`

Adds a manual label. Writes yes.

#### `PATCH /api/observed-play/logs/{log_id}/archetype-labels/{canonical_key}`

Accepts, rejects, edits, or marks stale. Writes yes.

#### `GET /api/observed-play/archetype-labels/taxonomy`

Writes: no. Returns known labels and aliases.

HTTP implementation should distinguish read-only preview endpoints from write
endpoints in route names, tests, and UI copy.

---

## 7. Deterministic Inference Design

### Deck-card inference

Inputs:

- `DeckCard.card_tcgdex_id`
- `DeckCard.quantity`
- joined `Card.name`, `Card.category`, `Card.stage`, `Card.types`,
  `Card.attacks`, `Card.abilities`, `Card.trainer_type`, `Card.energy_type`
- fallback parsed `Deck.deck_text` when `DeckCard` rows are absent

Rules:

1. Identify high-count Pokemon lines.
   - Group by evolution line when `Card.evolve_from` and names are available.
   - Weight higher-stage and Pokemon ex cards more heavily.
2. Identify main attackers / Pokemon ex.
   - Cards with `ex` in the name and multiple copies are strong archetype
     candidates.
   - Repeated attack use in observed logs can support but not replace deck-list
     evidence.
3. Identify core evolution line.
   - Stage 2 line with 3-4 basics and 2-4 final evolution cards indicates an
     archetype candidate.
4. Identify energy profile.
   - Dominant basic/special energy types can support package/strategy labels.
5. Identify strategy tags.
   - Use card names, attacks, abilities, and known taxonomy aliases for
     `poison`, `burn`, `spread`, `control`, `acceleration`, `mill`, `tank`, or
     `setup`.
6. Identify engine/package tags.
   - Examples: draw engine, Rare Candy Stage 2 package, Psychic package,
     Fire toolbox.

Confidence:

- `0.90-0.95`: complete/high-count core line plus main attacker.
- `0.80-0.90`: strong main attacker but incomplete line.
- `0.65-0.80`: package/strategy inferred from multiple support cards.
- `<0.60`: display-only suggestion.

### Observed-log inference

Inputs:

- `ObservedCardMention.resolved_card_def_id`
- `ObservedCardMention.resolved_card_name`
- `ObservedCardMention.source_event_type`
- `ObservedPlayEvent.player_alias`
- `ObservedPlayMemoryItem.player_alias`
- `ObservedPlayMemoryItem.actor_card_def_id`
- `ObservedPlayMemoryItem.target_card_def_id`
- `ObservedPlayMemoryItem.related_card_def_id`
- `ObservedPlayMemoryItem.memory_type`
- `ObservedPlayMemoryItem.action_name`

Rules:

1. Infer separately per `player_alias`.
2. Use resolved card mentions before raw card names.
3. Require repeated core mentions or key evolved Pokemon.
4. Do not infer high-confidence archetype from one-off cards.
5. Identify both players in the same log.
6. Preserve uncertainty when player attribution is missing or mixed.
7. Lower confidence when `card_resolution_status` is `needs_review` or the log
   has many unresolved/ambiguous cards.

Confidence:

- `0.75-0.80`: repeated resolved core line for one player.
- `0.60-0.75`: repeated key card mentions but incomplete line.
- `<0.60`: display-only, especially when based on raw names or one event.

### Example rules

These are illustrative. Implementation must use card IDs from the local card DB
and should not assume every listed card ID is available.

#### Dragapult ex

Suggest `Dragapult ex` when:

- Deck has repeated `Dragapult ex` plus its evolution line, or
- Observed log shows repeated resolved mentions of Dragapult-line cards for one
  player.

Supporting package labels may include `Psychic`, `Stage 2 setup`, or
`spread damage` only if evidence supports them.

#### Salazzle ex / poison-burn

Suggest `Salazzle ex` when:

- Deck has repeated Salandit/Salazzle ex line, or
- Observed log shows repeated Salazzle ex mentions or attacks/abilities tied to
  poison/burn effects.

Suggest package/strategy labels such as `Poison/Burn package` at lower
confidence unless multiple supporting cards/events exist.

#### Crustle / Dwebble line

Suggest `Crustle` when:

- Deck has repeated Dwebble/Crustle line, or
- Observed log has repeated resolved Dwebble/Crustle mentions for the same
  player.

Do not infer the label from a single target/knockout involving Crustle.

#### Charizard ex

Suggest `Charizard ex` when:

- Deck has a Charizard ex line and supporting evolution structure.
- Observed log shows repeated resolved Charizard-line events for the same
  player.

If Charizard ex appears as a one-off attacker in a broader Fire deck, prefer
`Fire toolbox` if other evidence supports that.

#### Generic Fire toolbox

Suggest `Fire toolbox` when:

- Deck has multiple unrelated Fire attackers/packages and no single dominant
  evolution line.
- Fire energy profile is dominant.
- Multiple Fire support cards exist.

Confidence should usually be lower than a specific archetype label.

#### Unknown/ambiguous deck

Return no archetype label, or return display-only `Unknown/ambiguous` with
confidence below `0.60`, when:

- No repeated core line exists.
- Mentions are one-off or mostly unresolved.
- Multiple archetypes appear with similar weak evidence.

Unknown should not be used for retrieval ranking.

---

## 8. Manual Review/Edit Workflow

User actions:

- Accept suggested label.
- Reject suggested label.
- Edit label text.
- Change label type.
- Add manual label.
- Mark label stale.
- Restore rejected label.
- Show evidence behind label.

Rules:

- Inference must not overwrite manual `accepted` or `edited` labels.
- Manual labels override inferred labels with the same `canonical_key`.
- Rejected inferred labels should stay available for audit/history unless the
  user explicitly clears history later.
- Re-running inference should update suggestions, mark stale labels when source
  fingerprints change, and preserve manual labels.

UI surfaces:

- `/observed-play` log table: compact label chips per log/player.
- Observed-play log detail drawer/modal: full labels, evidence, review controls.
- Deck detail/edit surface: deck labels and primary archetype.
- Simulation setup: preview labels for selected user/opponent decks.
- Dashboard retrieval debug tile: show label context once labels affect
  retrieval ranking.

Evidence display should show:

- Evidence cards.
- Counts.
- Source events/memory item IDs.
- Player alias for observed-log labels.
- Confidence and review status.

---

## 9. Retrieval Integration Design

Labels should not affect retrieval immediately. Use a staged approach.

### Phase 7.1b: infer/display labels only

- Add deterministic inference preview.
- Display labels in UI.
- No retrieval ranking changes.
- No Coach prompt changes.
- No gameplay changes.

### Phase 7.1d: bounded ranking signal

After labels are visible and manually validated:

- Add label match as a small bounded ranking boost. Implemented in Phase 7.1d
  as `label_strategy=archetype_label_boost_v1` layered onto `deck_overlap_v1`.
- Exact card-ID match still outranks label-only evidence.
- Label-only match cannot override no-relevant-evidence gating unless the user
  explicitly enables label fallback.
- Keep `allow_fallback=false` default.
- Expose every label influence in `coach-debug`.
- Do not broaden the candidate pool in this phase; infer source labels only
  from evidence rows already fetched by Tier 1/Tier 2/Tier 3 retrieval.

Recommended retrieval metadata fields:

- `deck_labels`
- `candidate_labels`
- `source_log_labels`
- `label_strategy`
- `label_ranking_enabled`
- `label_boost`
- `label_match_reason`
- `base_relevance_score`
- `final_relevance_score`

Example metadata extension:

```json
{
  "strategy": "deck_overlap_v1",
  "label_strategy": "archetype_label_boost_v1",
  "label_ranking_enabled": true,
  "deck_labels": [
    {
      "canonical_key": "dragapult-ex",
      "label": "Dragapult ex",
      "label_type": "archetype",
      "source": "deck_cards",
      "confidence": 0.92,
      "review_status": "suggested"
    }
  ],
  "label_boost_cap": 0.10,
  "evidence_selected": [
    {
      "memory_item_id": "uuid",
      "tier": 1,
      "base_relevance_score": 0.95,
      "label_boost": 0.08,
      "final_relevance_score": 1.03,
      "matched_label_keys": ["dragapult-ex"],
      "matched_label_names": ["Dragapult ex"],
      "label_match_reason": "Matched current archetype label Dragapult ex to source log/player label Dragapult ex."
    }
  ]
}
```

Label boost rules:

- Apply only to deterministic labels inferred in-memory for the current request.
- Strong matching archetype labels may add `+0.08`; package/strategy matches
  may add `+0.04`; weak/ambiguous matches add at most `+0.02`.
- Cap total label boost at `<= 0.10`.
- Sort by retrieval tier first, then final relevance score.
- Do not promote Tier 2/label-only evidence above Tier 1 exact card-ID evidence.
- Do not inject evidence solely because a label matched.

---

## 10. UI Design

Surfaces:

- `/observed-play` log list:
  - Show compact chips: label, player alias, status.
  - Keep table readable; collapse secondary labels behind `+N`.
- Observed log detail drawer/modal:
  - Full label list grouped by player.
  - Evidence cards/events.
  - Accept/reject/edit/add controls.
- Deck surfaces:
  - Primary archetype and secondary package/strategy chips.
  - Label preview from deck cards.
  - Manual correction controls when deck editing surface exists.
- Simulation Dashboard retrieval debug tile:
  - Current deck labels.
  - Source log labels for selected evidence.
  - Label boost/reason only after retrieval integration.
- Filters:
  - Optional filter by label on `/observed-play`.
  - Avoid making filters required for the first UI slice.
- Warnings:
  - Low-confidence labels.
  - Unreviewed labels.
  - Stale labels after reparse/reingest/deck edit.

Avoid clutter:

- Use short chips in tables.
- Put evidence and edit controls in detail panels.
- Do not add large explanatory banners to every row.
- Default to showing accepted/manual labels first, then high-confidence
  suggestions, then low-confidence suggestions only in detail views.

---

## 11. Testing Plan

### Backend tests

- Label object validation.
- Canonical key normalization.
- Deck inference: known archetype.
- Deck inference: mixed/toolbox deck.
- Deck inference: unknown/ambiguous deck.
- Deck inference: package/strategy labels.
- Observed-log inference per player.
- Observed-log inference does not merge both players.
- Observed-log inference handles missing resolved cards.
- Manual label overrides inferred label.
- Reject label preserves audit state.
- Edit label sets manual source/confidence.
- Stale labels after reparse/reingest source fingerprint change.
- Retrieval unchanged while labels are display-only.
- Later retrieval label boost does not outrank exact card-ID evidence.
- No writes during read-only preview.
- Metadata-only persistence preserves unrelated `metadata_json` keys.

### Frontend tests

- Label chips render in log list.
- Multiple labels collapse without table overflow.
- Low-confidence labels show warning.
- Accepted/manual labels sort before suggestions.
- Accept/reject/edit flow.
- Evidence behind label visible.
- Player-specific labels render separately for observed logs.
- Dashboard shows label influence when present.
- Old logs/decks without labels still render.
- API type guards tolerate missing optional label metadata.

---

## 12. Migration and Rollback Strategy

### Metadata-only rollback

If Option A is used:

- Clear `ObservedPlayLog.metadata_json["archetype_labeling"]`.
- Clear or restore `Deck.archetype` only for labels created by this feature.
- Do not touch observed events, card mentions, memory items, or ingestion rows.
- Do not alter raw logs or parser output.

### Clearing labels

Expose an admin/dev utility or endpoint only after implementation review:

- Clear labels for one log.
- Clear labels for one deck.
- Clear all suggested labels while preserving manual labels.
- Mark all labels stale after taxonomy changes.

### Future migration to normalized tables

Migration path:

1. Create normalized tables.
2. Read `ObservedPlayLog.metadata_json["archetype_labeling"]`.
3. Read `Deck.archetype` as a primary manual/imported label when present.
4. Insert label definitions and assignments.
5. Preserve source evidence, confidence, review status, and timestamps.
6. Leave metadata in place for one release as backup or add a migration marker.

### Stale labels after reparse/reingest

Use `source_fingerprint`:

- `parser_version`
- `resolver_version`
- `event_count`
- `memory_item_count`
- `card_mention_count`
- deck card count/hash for decks

If the fingerprint changes:

- Manual labels remain accepted but may show a "source changed" warning.
- Suggested labels become `stale` or `needs_review`.
- Re-run inference creates new suggestions without overwriting manual labels.

### schema_version

Every label object and parent metadata block should include `schema_version`.
This lets future code migrate or ignore older label objects safely.

---

## 13. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Mislabeling | Keep labels reviewable, show evidence, keep suggestions below manual labels. |
| Small corpus overfitting | Avoid label-only retrieval at first; require manual validation. |
| Multi-archetype decks | Support multiple labels and package/strategy labels from the start. |
| Ambiguous package labels | Separate `archetype`, `package`, and `strategy`; show confidence. |
| Archetype drift across rotations | Add future format/rotation metadata; keep taxonomy editable. |
| Labels treated as rules | UI/API copy must state labels are context, not card rules. |
| Stale labels after reparse | Use source fingerprints and stale/needs-review statuses. |
| UI clutter | Use compact chips and detail panels; collapse low-priority labels. |
| User over-trust | Show confidence/source/review status with every label. |
| Brittle deterministic rules | Keep rules simple, test known/ambiguous cases, prefer taxonomy aliases over ad hoc strings. |

---

## 14. Recommended Phase 7.1 Implementation Sequence

### Phase 7.1a — spec/design

Goal:

- Define label concepts, storage options, API shape, inference rules, UI plan,
  test plan, and acceptance criteria.

Files likely touched:

- Docs only.

Tests:

- `git diff --check`.

Acceptance criteria:

- Design names current repo fields.
- Recommends storage/API path.
- Preserves safety boundaries.

Manual checks:

- Confirm no code/migration files changed.

### Phase 7.1b — backend label inference preview

Goal:

- Add deterministic backend label inference for decks and observed logs.
- Default to preview-only.
- Optionally persist only after explicit action.
- Implemented in Phase 7.1b as read-only preview only; persistence remains
  deferred.

Files likely touched:

- `backend/app/observed_play/archetype_labels.py` or similar new service.
- `backend/app/observed_play/schemas.py`.
- `backend/app/api/observed_play.py`.
- Backend tests under `backend/tests/test_observed_play/` or existing observed
  play API tests.

Tests:

- Backend label validation/inference tests.
- Read-only preview tests.
- Old log/deck compatibility tests.

Acceptance criteria:

- Preview endpoints write nothing.
- Labels include source/confidence/review status/evidence.
- Manual labels are not overwritten if persistence is included.
- Implemented seed labels: Dragapult ex, Salazzle ex, Crustle, Charizard ex,
  Gardevoir ex, Fire toolbox, Poison/Burn strategy, Spread damage, Stage 2
  setup, and Psychic engine.

Manual checks:

- Preview labels for Dragapult, Salazzle, Crustle, Charizard, toolbox, and
  unknown/ambiguous examples.

### Phase 7.1c — UI label display/review

Goal:

- Display labels in `/observed-play` and deck/dashboard surfaces.
- Implemented as read-only preview display only. No persistence-backed review
  controls are available yet, so accept/reject/edit remains deferred.

Files likely touched:

- `frontend/src/types/observedPlay.ts`.
- `frontend/src/api/observedPlay.ts`.
- `frontend/src/api/decks.ts`.
- `frontend/src/pages/ObservedPlay.tsx`.
- `frontend/src/pages/Dashboard.tsx`.
- New observed-play label components.
- There is no dependency on the stubbed `GET /api/decks/` list endpoint.

Tests:

- Label chips render.
- Evidence panel renders.
- Observed-log labels render grouped by player.
- Dashboard does not call deck preview without `user_deck_id`.
- Dashboard remains usable when preview fetch fails.
- Old logs/decks without labels render.
- Phase 7.1c validation: frontend tests passed (`362 passed`) and frontend
  production build passed.

Acceptance criteria:

- Labels visible and reviewable.
- Low-confidence/unreviewed labels are visually distinct.
- Tables remain readable.
- UI copy says labels are advisory/read-only, not card rules, and not currently
  used for Coach retrieval ranking.
- Labels are not persisted and no edit/accept/reject controls are exposed.

Manual checks:

- Check dark mode, long labels, multi-label rows, and logs with both players
  labeled.
- Endpoint smoke checks confirmed Dragapult, Gardevoir, Crustle,
  unknown/no-label, and mixed/ambiguous observed-log payloads are still shaped
  for the UI surfaces.

### Phase 7.1d — retrieval metadata/ranking integration

Goal:

- Add bounded label boost after display/review has been validated.
- Expose label influence in coach-debug and Dashboard tile.
- Implemented in Phase 7.1d without persistence or candidate-pool expansion.

Files likely touched:

- `backend/app/observed_play/coach_context.py`.
- `backend/app/observed_play/schemas.py`.
- `backend/app/coach/analyst.py` only to pass labels/metadata if needed.
- Frontend retrieval metadata types/components.
- Backend and frontend tests.

Tests:

- Exact card-ID evidence outranks label-only evidence.
- Label boost capped.
- `allow_fallback=false` remains default.
- No relevant evidence remains no injection unless explicit label fallback is
  enabled.
- Read-only retrieval guarantees still pass.
- Existing no-label behavior remains unchanged.
- Dashboard retrieval debug displays label strategy, boost, matched labels, and
  label match reason.

Acceptance criteria:

- Label influence is visible and bounded.
- No Coach strategy or gameplay logic changes.
- No migrations, label persistence, hard filtering, or label-only candidate
  expansion.

Manual checks:

- Compare Dashboard retrieval debug tile before/after label integration on
  matching and non-matching corpora.

### Phase 7.1e — manual validation across archetypes

Goal:

- Validate labels and retrieval debug across several archetypes and ambiguous
  logs.

Files likely touched:

- Docs/report only unless bugs are found.

Tests:

- Targeted backend/frontend tests from 7.1b-7.1d.

Acceptance criteria:

- Labels are inspectable and correctable.
- Retrieval debug explains label influence.
- No gameplay improvement claim is made.

Manual checks:

- Dragapult ex.
- Salazzle ex / poison-burn.
- Crustle.
- Charizard ex.
- Fire toolbox.
- Unknown/ambiguous.

---

## 15. Acceptance Criteria for Phase 7.1

- Labels support multiple values.
- Labels show source, confidence, and review status.
- Labels are manually correctable.
- Manual labels override inferred labels.
- Observed logs can label both players separately.
- Labels preserve evidence cards/events/memory items where available.
- Retrieval remains unchanged until the retrieval integration phase.
- Later label boost is visible and bounded.
- Exact card evidence outranks label-only evidence.
- Flag-off behavior is unchanged.
- Observed-play corpus remains read-only during retrieval.
- No AI Player control.
- No simulator gameplay change.
- No Coach strategy change.
- No deck-builder behavior change.
- No `card_performance` writes.
- No `match_events` writes.
- No Neo4j writes.
- No pgvector writes.
- No observed-play ingestion behavior changes.
- No claim of gameplay improvement.

---

## 16. Open Questions for the User

1. Should Phase 7.1 start no-migration with `metadata_json`, or use a minimal
   migration immediately?
2. Should labels be persisted immediately or preview-only first?
3. Should user-editable labels be required in the first implementation slice?
4. Should labels be stored on logs, decks, or both in the first slice?
5. Should observed-log labels be per-player from the beginning?
6. Which archetypes should be seeded first?
7. Should labels be used for retrieval ranking immediately after display is
   working, or only after manual validation?
8. How much UI editing is enough for the first pass?
9. Should rejected labels be retained for audit/history?
10. Should `Deck.archetype` be treated as a legacy primary label, or should new
    label state avoid writing it until a migration exists?
11. Should low-confidence labels be hidden by default outside detail views?
12. Should taxonomy aliases be configured in code first, or editable through UI
    later?

---

## 17. Final Recommendation

Start Phase 7.1b with a no-migration deterministic backend label inference
preview:

- Return labels for decks and observed logs.
- Persist nothing by default.
- If persistence is included, write only after explicit user action and use
  `ObservedPlayLog.metadata_json["archetype_labeling"]` for log labels.
- For deck labels, use `Deck.archetype` only for a single accepted/manual
  primary label; defer multi-label deck persistence to a minimal migration if
  UI editing is required.
- Display labels in UI before retrieval uses them.
- Do not change Coach strategy, simulator gameplay, AI Player behavior,
  observed-play ingestion, pgvector, Neo4j, `match_events`, `card_performance`,
  deck-builder behavior, or runtime gameplay logic.

If the user wants editable multi-label deck labels in the first implementation
slice, choose Option B (`decks.archetype_labels`, `observed_play_logs.archetype_labels`)
instead of forcing an awkward no-migration design.
