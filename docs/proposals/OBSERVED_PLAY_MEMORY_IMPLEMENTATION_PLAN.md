# Observed Play Memory — Implementation Plan

> Source material: `docs/proposals/OBSERVED_PLAY_MEMORY_DESIGN_REVIEW.md`
>
> This document refines that proposal into an implementation-ready plan for the
> current PokéPrism codebase. Do not treat it as a replacement for the original
> proposal — read both.
>
> **Phase 0 only.** No production code has been written. No migrations have been
> added. No routes have been registered. This document is the plan.

---

## 1. Executive Summary

**What is Observed Play Memory?**

Observed Play Memory is a new PokéPrism feature area that imports real Pokémon
TCG Live (PTCGL) battle logs, archives them, parses them into structured game
events, and makes high-confidence observed human play patterns available to the
Coach and eventually the AI Player.

The user copies a PTCGL battle log (exported via an Apple Shortcut into a `.md`
file), uploads it via a new frontend page, and PokéPrism stores, parses, and
reports on the resulting game events without polluting the simulator's own event
tables.

**Why does it belong in PokéPrism?**

PokéPrism already has a memory-first architecture: simulator outcomes flow into
PostgreSQL card performance, pgvector state-action-outcome snippets, and a Neo4j
co-play/synergy graph. The AI Player and Coach both retrieve from this memory
stack. Adding human-observed evidence closes a fundamental gap: the simulator
only knows what it can discover through its own limited play. Real human games
contain sequencing patterns, setup priorities, and failure modes the simulator
may never reproduce on its own.

**Why must imported logs be source-tagged, confidence-scored, and gated?**

PTCGL logs are partial observers. They do not expose hidden hands, full deck
order, player intent, or whether decisions were correct. A human may misplay.
The opponent's skill level is unknown. The same card name may refer to different
prints. The parser may misidentify events. Noisy data that contaminated Coach or
Player prompts without gating would degrade decision quality instead of improving
it. Source-tagging and confidence scoring allow every imported memory to be
audited, excluded, and decayed independently of simulator-truth memory.

**What should the MVP do? What should it not do?**

The MVP ends at a working upload-parse-report cycle with no memory ingestion:

| In MVP | Out of MVP |
|---|---|
| Docker log volume + `.gitignore` | Coach/Player memory ingestion |
| Upload `.md`/`.markdown`/`.txt`/`.zip` | pgvector snippets |
| Import batch record | Neo4j observed-play edges |
| Raw log record with SHA-256 dedup | Format-decay/reranking |
| Raw archive on filesystem + DB | Human-vs-simulator disagreement reports |
| Parser v1 — high-confidence events only | Tournament-log support |
| Card mention extraction | User PTCGL username setting |
| Card resolution v1 — exact + normalized | Failure-mode tagging (deferred) |
| Unresolved/ambiguous card reporting | Full board-state reconstruction |
| Import summary report | Replay animation |
| Parsed event viewer API | |
| Parser fixture tests | |

---

## 2. Fit with Current Architecture

### PostgreSQL / SQLAlchemy models (`backend/app/db/models.py`)

The current schema has:
- `cards` — card definitions with `tcgdex_id` PK
- `decks`, `deck_cards` — user/opponent deck records
- `simulations`, `simulation_opponents`, `simulation_opponent_results`
- `rounds`, `matches`, `match_events`, `decisions`
- `deck_mutations`, `card_performance`
- `embeddings` — pgvector source-typed rows (source_type field is open text)

**Fit:** good. The new observed-play tables live alongside existing tables. No
existing table needs modification in the MVP. The `embeddings` table's
`source_type` text field already supports future `observed_play` source type
without schema change.

**No conflict with PROJECT.md:** PROJECT.md's Appendix B schema predates this
feature; it does not conflict because it does not define observed-play tables.

### Alembic migrations (`backend/alembic/versions/`)

Five migrations exist, the latest being `5b7e9c2d4a11`. New migrations for
observed-play tables will extend this chain cleanly in Phase 1.

### Simulation/match event tables

`match_events` has a `match_id` FK that requires an existing `matches` row.
Observed-play events have no simulator match. Using `match_events` for observed
data would require nullable `match_id` and a `source` discriminator column —
a structural mismatch. **A parallel table is the correct design** (see §6).

### Neo4j graph memory (`backend/app/memory/graph.py`, `backend/db/graph.py`)

`GraphMemoryWriter` currently writes `:Card`, `:Deck`, `:DeckSynergy`, and
outcome edges from simulator matches. The new feature will eventually add
source-tagged observed-play edges. No conflict; graph is additive.

### pgvector/embeddings (`backend/app/db/models.py:Embedding`)

`source_type` is already an open text field. Future observed-play embeddings
use `source_type = "observed_play"` without schema change.

### Coach (`backend/app/coach/`)

Coach currently uses card performance, graph synergy data, and deck mutations.
Observed Play Memory is **not** wired to Coach in the MVP. Phase 6 adds a
compact advisory packet.

### AI Player (`backend/app/players/ai_player.py`)

AI Player retrieves memory at decision time. **No change in MVP or Phase 6.**
Player integration is Phase 8, conditional on Coach validation passing first.

### Frontend pages/API patterns

Current pages: Coverage, Dashboard, History, Memory, SimulationLive,
SimulationSetup. All use the same pattern: React page → `frontend/src/api/`
axios module → `/api/…` FastAPI router. The new `/observed-play` page follows
identical patterns.

Current API modules: `cards.ts`, `decks.ts`, `history.ts`, `memory.ts`,
`simulations.ts`. A new `observedPlay.ts` module will be added.

### Celery/background work

`run_simulation` is the sole Celery task today, dispatched from
`backend/app/api/simulations.py` with `run_simulation.delay(str(sim.id))`.
New import tasks follow the same pattern (task module, delay call, DB status
polling). No architectural change to Celery infrastructure is needed.

### Docker volumes

`docker-compose.yml` currently defines named volumes for `ollama_data`,
`postgres_data`, `neo4j_data`, and `redis_data`. The backend container mounts
`./backend/app:/app/app` (code hot-reload). **No log volume exists yet.**
Phase 1 adds a `ptcgl_logs_data` named volume mapped to `/data/ptcgl_logs` in
the backend container.

### Conflicts/mismatches found

- `PROJECT.md` does not describe this feature — it is new, not a conflict.
- The branch `feature/observed-play-memory` was created from `main` at commit
  `74a58ab` (same as `origin/main`). The branch is clean and up to date.
- No existing code or table is modified by the MVP.

---

## 3. Final MVP Boundary

The recommended MVP from §1 is accepted with one clarification:

**Failure-mode tagging** (e.g., `deckout_loss`, `stranded_active`) is
**deferred to Phase 5**, not Phase 2–3. The parser in v1 should not try to
classify complex game patterns; it should extract structured events and let
higher-level analytics infer failure modes later.

**Reparse-on-rule-change** (trigger all unresolved logs to reparse when a
manual resolution rule is added) is deferred to Phase 3. Phase 2 parser runs
once at import time; Phase 3 adds the full resolution-rule UI and reparse
trigger.

---

## 4. Branch and Merge Strategy

- **Feature branch:** `feature/observed-play-memory` (currently at `74a58ab`,
  identical to `origin/main`).
- **Development:** all Observed Play Memory code committed to this branch only.
- **`main` stays stable:** no observed-play production code lands on `main` until
  the MVP acceptance criteria pass.
- **Phase commits:** each phase should be committed as a coherent unit with a
  descriptive commit message (`feat(observed-play): phase-N …`).
- **Rebase policy:** optionally rebase from `main` when main receives significant
  changes that affect shared infrastructure (e.g., new card tables, Celery
  changes). Avoid frequent merge commits.
- **Merge to `main`:** only after Phase 4 (frontend page) acceptance criteria
  pass and manual validation confirms the upload-parse-report cycle is stable.
- **No raw logs committed:** only curated parser fixtures (small, anonymized,
  purpose-built test inputs) may live under `backend/tests/fixtures/observed_play/`.

---

## 5. Storage and Docker Volume Plan

### Docker volume

Add to `docker-compose.yml` in Phase 1:

```yaml
volumes:
  ptcgl_logs_data:   # add to top-level volumes block

services:
  backend:
    volumes:
      - ./backend/app:/app/app           # existing
      - ptcgl_logs_data:/data/ptcgl_logs # new
  celery-worker:
    volumes:
      - ./backend/app:/app/app           # existing
      - ptcgl_logs_data:/data/ptcgl_logs # new — worker writes archives too
```

Both backend and celery-worker need access because ZIP imports are Celery tasks.

### Paths inside the container

```
/data/ptcgl_logs/inbox/     — optional manual drop location (future)
/data/ptcgl_logs/archive/   — canonical raw file storage
/data/ptcgl_logs/failed/    — files that failed import or parse
/data/ptcgl_logs/tmp/       — upload extraction workspace (ZIP)
```

### Local dev path and `.gitignore`

```
data/ptcgl_logs/
```

Add to `.gitignore` in Phase 0.

### Raw storage: DB and filesystem both

- Store raw markdown content in `observed_play_logs.raw_content` (PostgreSQL).
  PTCGL logs are typically 5–80 KB; this is manageable. Storing in DB simplifies
  reparse (no filesystem dependency) and makes debugging easy.
- Also write canonical file to `/data/ptcgl_logs/archive/{sha256_hash[:2]}/{sha256_hash}.md`.
  The archive is the long-term backup and enables manual inspection without DB queries.
- `stored_path` column records the relative archive path.

### Archive filename convention

```
{sha256_hash[:2]}/{sha256_hash}.{original_extension}
```

Example: `ab/abcdef1234…789.md`

The first two hex characters form a subdirectory to avoid filesystem flat-directory
limits on large corpora. This is the same strategy used by Git's object store.

### Duplicate hash behavior

If `sha256_hash` already exists in `observed_play_logs`:
- Do not re-import.
- Increment the batch `duplicate_file_count`.
- Return the existing `log_id` in the batch summary.
- Log a `"duplicate"` entry in `batch.summary_json`.

### Failed file behavior

- Write the raw file to `/data/ptcgl_logs/failed/{timestamp}_{original_filename}`.
- Create an `observed_play_logs` row with `parse_status = "failed"`.
- Store the error in `errors_json`.
- The failed directory is inspectable manually without needing the database.

### Tmp cleanup

- After a ZIP is extracted and processed, delete the tmp extraction directory.
- If the Celery task crashes, a periodic cleanup job (Phase 5 or later) can
  sweep `/data/ptcgl_logs/tmp` for directories older than 24 hours.

---

## 6. Database Model Plan

All new tables are prefixed `observed_play_` or `observed_card_`. No existing
tables are modified. Alembic migrations added one per phase with downgrade stubs.

---

### `observed_play_import_batches`

**Purpose:** One row per upload operation (single file or ZIP). Powers the
frontend import report.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | default `uuid4()` |
| `source` | Text | `"upload_single"`, `"upload_zip"`, `"inbox_scan"` |
| `uploaded_filename` | Text | original filename as submitted |
| `celery_task_id` | Text nullable | populated for async ZIP imports |
| `status` | Text | `pending`, `running`, `completed`, `completed_with_warnings`, `failed`, `cancelled` |
| `original_file_count` | Integer default 0 | files in ZIP or 1 for single |
| `accepted_file_count` | Integer default 0 | passed type/size check |
| `duplicate_file_count` | Integer default 0 | skipped — hash already exists |
| `failed_file_count` | Integer default 0 | parse/archive failure |
| `imported_file_count` | Integer default 0 | successfully parsed and archived |
| `skipped_file_count` | Integer default 0 | unsupported type etc. |
| `started_at` | TIMESTAMP tz | |
| `finished_at` | TIMESTAMP tz | |
| `summary_json` | JSONB | top unresolved cards, warnings list, per-file outcomes |
| `errors_json` | JSONB | fatal batch errors |
| `warnings_json` | JSONB | non-fatal batch warnings |
| `created_at` | TIMESTAMP tz server_default now() | |
| `updated_at` | TIMESTAMP tz | |

Indexes: `(status)`, `(created_at DESC)`.

No unique constraints beyond PK.

---

### `observed_play_logs`

**Purpose:** One row per raw imported battle log. The authoritative source record.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `import_batch_id` | UUID FK → `observed_play_import_batches.id` | nullable (future inbox imports) |
| `source` | Text | `"ptcgl_export"`, `"manual_upload"` |
| `original_filename` | Text | |
| `stored_path` | Text | relative path in archive volume |
| `sha256_hash` | Text | hex string |
| `raw_content` | Text | full raw markdown stored in DB |
| `file_size_bytes` | Integer | |
| `parse_status` | Text | `pending`, `parsed`, `parsed_with_warnings`, `failed`, `excluded`, `needs_reparse` |
| `memory_status` | Text | `not_ingested`, `eligible`, `ingested_postgres`, `ingested_vector`, `ingested_graph`, `excluded_from_memory` |
| `parser_version` | Text | `"1.0"` etc. |
| `player_1_name_raw` | Text | exactly as in log |
| `player_2_name_raw` | Text | |
| `player_1_alias` | Text | `"self"`, `"opponent_001"`, etc. |
| `player_2_alias` | Text | |
| `self_player_index` | Integer nullable | 1 or 2 if self detected |
| `winner_raw` | Text | player name string from log |
| `winner_alias` | Text | |
| `win_condition` | Text nullable | `"prizes"`, `"deck_out"`, `"no_bench"`, `"unknown"` |
| `game_date_detected` | Date nullable | if extractable from log metadata |
| `turn_count` | Integer default 0 | |
| `event_count` | Integer default 0 | parsed events |
| `recognized_card_count` | Integer default 0 | |
| `unresolved_card_count` | Integer default 0 | |
| `ambiguous_card_count` | Integer default 0 | |
| `confidence_score` | Float | 0.0–1.0 |
| `errors_json` | JSONB | list of {code, message, line} |
| `warnings_json` | JSONB | |
| `metadata_json` | JSONB | parser metadata, detected sets, regulation marks |
| `created_at` | TIMESTAMP tz server_default now() | |
| `updated_at` | TIMESTAMP tz | |

Indexes: `(sha256_hash)` UNIQUE, `(import_batch_id)`, `(parse_status)`,
`(memory_status)`, `(created_at DESC)`.

**Unique constraint:** `sha256_hash` — prevents duplicate imports.

---

### `observed_play_events`

**Purpose:** Structured events parsed from a raw log. Parallel to `match_events`,
not reusing it. (See rationale below.)

| Column | Type | Notes |
|---|---|---|
| `id` | BigInteger PK autoincrement | |
| `observed_play_log_id` | UUID FK → `observed_play_logs.id` ondelete CASCADE | |
| `import_batch_id` | UUID | denormalized for fast batch queries |
| `event_index` | Integer | 0-based sequential position within log |
| `turn_number` | Integer nullable | null during setup phase |
| `phase` | Text | `"setup"`, `"turn"`, `"game_end"` |
| `player_raw` | Text nullable | player name string from log |
| `player_alias` | Text nullable | `"self"`, `"opponent_001"` |
| `actor_type` | Text nullable | `"self"`, `"opponent"`, `"unknown"` |
| `event_type` | Text | see taxonomy below |
| `raw_line` | Text | source line(s) verbatim |
| `raw_block` | Text nullable | multi-line raw block if applicable |
| `card_name_raw` | Text nullable | primary card name as in log |
| `resolved_card_id` | Text nullable FK → `cards.tcgdex_id` | |
| `resolved_card_name` | Text nullable | |
| `resolved_card_confidence` | Float nullable | 0.0–1.0 |
| `target_card_name_raw` | Text nullable | |
| `target_resolved_card_id` | Text nullable FK → `cards.tcgdex_id` | |
| `zone` | Text nullable | `"active"`, `"bench"`, `"hand"`, `"deck"`, `"discard"`, `"prizes"` |
| `target_zone` | Text nullable | |
| `damage` | Integer nullable | total damage applied |
| `base_damage` | Integer nullable | |
| `weakness_damage` | Integer nullable | |
| `resistance_delta` | Integer nullable | |
| `healing_amount` | Integer nullable | |
| `prize_count_delta` | Integer nullable | |
| `event_payload_json` | JSONB | all other event-specific fields |
| `confidence_score` | Float | 0.0–1.0 event-level confidence |
| `confidence_reasons_json` | JSONB | list of reason strings |
| `parser_version` | Text | |
| `created_at` | TIMESTAMP tz server_default now() | |

Indexes: `(observed_play_log_id, event_index)` UNIQUE,
`(observed_play_log_id)`, `(event_type)`, `(resolved_card_id)`,
`(import_batch_id)`.

**Why parallel table and not `match_events`?**

`match_events` has `match_id NOT NULL FK → matches`. Observed events have no
simulator match. Adding `match_id` as nullable with a `source` discriminator
would make every query that joins `match_events` for simulator data filter by
source — a constant footgun. The observed event schema also needs fields that
`match_events` doesn't: `raw_line`, `raw_block`, `confidence_score`,
`resolved_card_confidence`, `player_alias`, `actor_type`. A parallel table is
cleaner, avoids contaminating simulator analytics, and allows schema evolution
at independent pace. Future SQL views can union them for cross-source analytics.

---

### `observed_card_mentions`

**Purpose:** Per-card-name resolution record for one log. Tracks every distinct
raw card name seen in a log and its resolution status.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `observed_play_log_id` | UUID FK → `observed_play_logs.id` ondelete CASCADE | |
| `raw_card_name` | Text | exactly as in log |
| `normalized_card_name` | Text | lowercase, stripped |
| `occurrence_count` | Integer | times seen in this log |
| `resolution_status` | Text | `resolved_exact`, `resolved_normalized`, `resolved_by_rule`, `ambiguous`, `unresolved`, `ignored` |
| `resolved_card_id` | Text nullable FK → `cards.tcgdex_id` | |
| `resolved_card_name` | Text nullable | |
| `candidate_cards_json` | JSONB | list of {tcgdex_id, name, confidence} candidates |
| `confidence_score` | Float | 0.0–1.0 |
| `resolution_rule_id` | UUID nullable FK → `observed_card_resolution_rules.id` | applied rule if any |
| `manual_override` | Boolean default false | |
| `override_reason` | Text nullable | |
| `created_at` | TIMESTAMP tz server_default now() | |
| `updated_at` | TIMESTAMP tz | |

Indexes: `(observed_play_log_id)`, `(resolution_status)`,
`(raw_card_name)`, `(resolved_card_id)`.

Unique: `(observed_play_log_id, raw_card_name)` — one resolution record per
distinct name per log.

---

### `observed_card_resolution_rules`

**Purpose:** Global manual correction rules mapping raw card name patterns to
resolved card IDs. Applied on import and reparse.

| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `raw_name_pattern` | Text | exact or normalized pattern to match |
| `match_mode` | Text | `"exact"`, `"normalized"`, `"prefix"` |
| `resolved_card_id` | Text nullable FK → `cards.tcgdex_id` | null = mark as ignored |
| `resolved_card_name` | Text nullable | |
| `confidence_score` | Float default 1.0 | assigned to matched mentions |
| `scope` | Text default `"global"` | `"global"`, `"format_specific"`, `"deck_specific"` |
| `scope_context_json` | JSONB nullable | e.g., `{"format": "E"}` |
| `created_by` | Text default `"user"` | |
| `notes` | Text nullable | |
| `created_at` | TIMESTAMP tz server_default now() | |
| `updated_at` | TIMESTAMP tz | |

Indexes: `(raw_name_pattern)`, `(scope)`.
Unique: `(raw_name_pattern, match_mode, scope)`.

---

## 7. Parser Architecture

### Module layout

```
backend/app/observed_play/
    __init__.py
    constants.py        — PARSER_VERSION, event type enums, phase enums
    patterns.py         — compiled regex patterns for log line matching
    parser.py           — main ParsedLog dataclass + parse_log() entry point
    confidence.py       — ConfidenceScorer: event-level and log-level
    card_resolution.py  — CardResolver: DB-backed card name resolution
    storage.py          — archive_file(), compute_sha256(), path helpers
    importer.py         — ImportOrchestrator: coordinates parse + DB write
    schemas.py          — Pydantic request/response schemas for API layer
    tasks.py            — Celery import task (ZIP/bulk)
```

### Parser version constant

```python
# backend/app/observed_play/constants.py
PARSER_VERSION = "1.0"
```

Stored as a string on every `observed_play_logs` row and every
`observed_play_events` row. On parser improvement, bump to `"1.1"` etc.

### Event type taxonomy

```python
class ObservedEventType(str, Enum):
    # Setup phase
    COIN_FLIP_CHOICE   = "coin_flip_choice"
    COIN_FLIP_RESULT   = "coin_flip_result"
    TURN_ORDER_CHOICE  = "turn_order_choice"
    OPENING_HAND_DRAW  = "opening_hand_draw"    # hand visible in log
    OPENING_HAND_DRAW_HIDDEN = "opening_hand_draw_hidden"  # only count known
    MULLIGAN           = "mulligan"
    PLAY_TO_ACTIVE     = "play_to_active"
    PLAY_TO_BENCH      = "play_to_bench"

    # Turn events
    TURN_START         = "turn_start"
    DRAW               = "draw"                 # card name visible
    DRAW_HIDDEN        = "draw_hidden"          # count only
    EVOLVE             = "evolve"
    ATTACH_ENERGY      = "attach_energy"
    PLAY_ITEM          = "play_item"
    PLAY_SUPPORTER     = "play_supporter"
    PLAY_STADIUM       = "play_stadium"
    REPLACE_STADIUM    = "replace_stadium"
    PLAY_TOOL          = "play_tool"
    ABILITY_USED       = "ability_used"
    RETREAT            = "retreat"
    SWITCH_ACTIVE      = "switch_active"
    SEARCH_DECK        = "search_deck"
    DISCARD            = "discard"
    RECOVER_FROM_DISCARD = "recover_from_discard"
    SHUFFLE_DECK       = "shuffle_deck"
    HEAL               = "heal"
    SPECIAL_CONDITION  = "special_condition"
    END_TURN           = "end_turn"

    # Combat
    ATTACK_USED        = "attack_used"
    DAMAGE_DEALT       = "damage_dealt"
    DAMAGE_BREAKDOWN   = "damage_breakdown"
    KNOCKOUT           = "knockout"
    PRIZE_TAKEN        = "prize_taken"
    PRIZE_CARD_REVEALED = "prize_card_revealed"  # if log reveals it

    # Game end
    GAME_END           = "game_end"

    # Fallback
    UNKNOWN            = "unknown"
```

### Raw line/block preservation

Every event row stores:
- `raw_line`: the source text line(s) that produced this event.
- `raw_block`: the full multi-line block when an event spans more than one line
  (e.g., damage breakdown with sub-bullets).

This is non-negotiable. Raw preservation allows debugging parser mistakes and
re-parsing without needing the archive file.

### Hidden vs known draws

`DRAW` is emitted when the log reveals the card name (e.g., opening hand, or
when a card search shows what was found). `DRAW_HIDDEN` is emitted when the log
says "Player drew a card" without revealing identity. Hidden draws still
increment `hand_count_delta` in `event_payload_json`.

### Confidence scoring (`confidence.py`)

**Event-level confidence** starts at `1.0` and is reduced by:

| Condition | Reduction |
|---|---|
| Card name in event is unresolved | −0.25 |
| Card name is ambiguous (multiple candidates) | −0.15 |
| Event type is `UNKNOWN` | −0.40 |
| Event lacks clear player assignment | −0.10 |
| Hidden draw (card identity unknown) | −0.05 |
| Numeric value missing when expected | −0.10 |

Minimum event confidence: `0.0`.

**Log-level confidence** is computed after parsing as the weighted mean of
all event confidence scores, further penalized by:
- Proportion of unresolved card names × 0.30
- Proportion of `UNKNOWN` events × 0.20
- Missing winner / win condition: −0.10
- Incomplete log (no `GAME_END` event): −0.10

### Card mention extraction

During parsing, every card name token encountered in a recognized event pattern
is added to a running `{raw_name: occurrence_count}` dict. After parsing, this
dict becomes the `observed_card_mentions` rows for the log.

### Card resolution (`card_resolution.py`)

See §8 for the full resolver design.

### Player aliasing

1. At import time, optionally accept a `self_username` parameter in the API.
2. Parser sets `player_1_alias` / `player_2_alias` by matching raw player names
   against known self-usernames.
3. Default aliases: `"self"` (if detected) and `"opponent_001"` / `"unknown"`.
4. `actor_type` on each event: `"self"`, `"opponent"`, or `"unknown"`.

In MVP, the self-username is not stored globally. It is provided per-upload as
an optional request field.

### Winner / win condition extraction

Parser looks for end-game markers:
- `"won the game"` / `"lost the game"` → `winner_raw`
- `"ran out of cards"` / `"deck out"` → `win_condition = "deck_out"`
- `"has no Pokémon"` / `"no Pokémon in play"` → `win_condition = "no_bench"`
- Default: `win_condition = "prizes"` if six prize events detected for winner

If none found: `winner_raw = null`, `win_condition = "unknown"`.

### Error/warning handling

The parser never raises an exception on malformed input. It stores errors in
`errors_json` (fatal: event block skipped) and `warnings_json` (non-fatal:
confidence reduced). This ensures partial-parse results are still stored and
reportable.

### Golden fixture testing

Fixtures live at:
```
backend/tests/fixtures/observed_play/
    sample_crustle_win.md      — anonymized, curated log; self wins
    sample_crustle_loss.md     — anonymized, curated log; self loses
    sample_mulligan.md         — log with mulligans
    sample_missing_winner.md   — truncated log, no game-end marker
    sample_unknown_cards.md    — log with card names not in DB
```

Tests in `backend/tests/test_observed_play/test_parser.py` assert:
- specific event types at specific indexes;
- confidence scores within expected ranges;
- card mentions extracted correctly;
- known draw vs hidden draw classification;
- win condition extraction.

---

## 8. Card Resolution Architecture

### Resolution strategy (ordered by confidence)

1. **Exact match:** `raw_name == cards.name` (case-insensitive). Confidence = 1.0.
2. **Normalized match:** strip punctuation, collapse whitespace, compare.
   Confidence = 0.95 if unique result, lower if multiple.
3. **Rule match:** check `observed_card_resolution_rules` for matching
   `raw_name_pattern`. Confidence = rule's `confidence_score`.
4. **Candidate list:** fuzzy-match top 5 candidates by normalized Levenshtein
   distance. Store candidates in `candidate_cards_json`. Status = `ambiguous`.
   Confidence = max candidate similarity × 0.6.
5. **Unresolved:** no candidates found. Confidence = 0.0.

### Ambiguity detection

A card name is ambiguous if the exact or normalized match returns more than one
card row (e.g., `"Pikachu"` may match multiple prints). In that case:
- Store all matches as candidates.
- Status = `ambiguous`.
- Do not auto-select based on print popularity — that would be a silent guess.

### Handling basic energy

Basic energy names (`"Basic Fire Energy"`, `"Basic Water Energy"`, etc.) are a
known special case. They are not in the PTCGL log with set numbers. Resolution
rules should pre-map them to canonical basic energy `tcgdex_id` values on first
setup. Include in the fixture test suite.

### Handling same-name multiple prints

When multiple `cards.tcgdex_id` share the same name (different sets):
- If exactly one is in the current regulation mark window (if detectable from
  the log), prefer it but mark confidence 0.85.
- Otherwise mark as `ambiguous` and populate candidates.

### Unresolved card reporting

`GET /api/observed-play/unresolved-cards` returns:
```json
[
  {
    "raw_card_name": "Gravity Gemstone",
    "occurrence_count": 47,
    "resolution_status": "unresolved",
    "example_log_id": "…",
    "candidate_cards": []
  }
]
```
This is the primary queue for manual resolution work.

### Manual resolution rules

A user adds a resolution rule via `POST /api/observed-play/resolution-rules`:
```json
{
  "raw_name_pattern": "Gravity Gemstone",
  "match_mode": "exact",
  "resolved_card_id": "sv09-140",
  "confidence_score": 1.0
}
```

The rule is stored in `observed_card_resolution_rules`. On next reparse of
affected logs, the resolver applies the rule. In Phase 3, the UI exposes a
"Apply rule & reparse affected logs" button.

### Reparse behavior

When a resolution rule is added, the system marks affected `observed_play_logs`
rows as `parse_status = "needs_reparse"`. A subsequent `POST /api/observed-play/logs/{log_id}/reparse`
or a batch reparse task re-runs the parser and resolver, replacing derived rows.

### Never silently guess

The resolver must never auto-select a low-confidence candidate without flagging
it. Any resolution confidence < 0.80 must be visible in the import report and
the unresolved cards table.

---

## 9. API Route Plan

All routes live under the `/api/observed-play` prefix, registered in
`backend/app/api/router.py`. Naming follows the existing project convention
(kebab-case paths, snake_case schemas, standard 2xx/4xx/5xx).

---

### `POST /api/observed-play/upload`

Upload a single `.md`/`.markdown`/`.txt` or a `.zip` file.

**Request:** `multipart/form-data`
```
file: UploadFile
self_username: str (optional, form field)
```

**Response (201):**
```json
{
  "batch_id": "uuid",
  "status": "completed",            // or "running" for zip
  "imported": 1,
  "duplicates": 0,
  "failed": 0,
  "celery_task_id": null            // populated for async zip
}
```

**Sync vs async:**
- Single `.md`/`.txt`: parse inline, return completed batch immediately.
- `.zip`: enqueue Celery task, return `status = "running"` + `celery_task_id`.

**Error cases:**
- Unsupported file type → 422
- File too large (future limit, e.g., 50 MB) → 413
- ZIP with no valid files → 422 with details

---

### `POST /api/observed-play/import/inbox` (Phase 3+)

Trigger an import scan of files manually dropped into `/data/ptcgl_logs/inbox`.
Async Celery task. Not in MVP.

---

### `GET /api/observed-play/batches`

List import batches, most recent first. Paginated.

**Query:** `page=1`, `per_page=20`

**Response:**
```json
{
  "batches": [ { "id", "status", "source", "uploaded_filename",
                 "imported_file_count", "failed_file_count",
                 "duplicate_file_count", "created_at", "finished_at" } ],
  "total": 42,
  "page": 1
}
```

---

### `GET /api/observed-play/batches/{batch_id}`

Full batch detail including `summary_json` and list of log IDs.

---

### `GET /api/observed-play/logs`

List all raw logs with parse summary fields. Paginated, filterable by
`parse_status`, `memory_status`.

---

### `GET /api/observed-play/logs/{log_id}`

Single log detail: all fields including `errors_json`, `warnings_json`, card
mention summary.

---

### `GET /api/observed-play/logs/{log_id}/events`

Paginated event list for a log. Response includes `raw_line`, `event_type`,
`turn_number`, `confidence_score`, `resolved_card_id`.

**Query:** `page`, `per_page`, `turn_number` (optional filter), `min_confidence`.

---

### `POST /api/observed-play/logs/{log_id}/reparse`

Re-run parser on a raw log. Replaces all derived event, card mention rows.
Inline (not Celery) unless log is very large.

**Response:** updated log summary.

---

### `POST /api/observed-play/logs/{log_id}/exclude`

Set `memory_status = "excluded_from_memory"`. No effect in MVP but wires the
field for Phase 6.

### `POST /api/observed-play/logs/{log_id}/include`

Reverse exclusion.

---

### `GET /api/observed-play/unresolved-cards`

All unresolved/ambiguous card mentions across all logs, aggregated by raw name.
Sorted by occurrence count descending.

---

### `POST /api/observed-play/resolution-rules`

Create a manual resolution rule.

**Request:**
```json
{
  "raw_name_pattern": "Gravity Gemstone",
  "match_mode": "exact",
  "resolved_card_id": "sv09-140",
  "confidence_score": 1.0,
  "notes": "added set number after set released"
}
```

**Response (201):** the created rule.

---

## 10. Celery / Background Processing

| Upload type | Parsing strategy | Rationale |
|---|---|---|
| Single `.md`/`.txt` | Inline during HTTP request | Logs are small; < 1 second; user expects immediate feedback |
| `.zip` | Celery task | May contain hundreds of files; must not block the request thread |

### Import progress tracking

- `observed_play_import_batches.status` powers polling.
- Frontend polls `GET /api/observed-play/batches/{batch_id}` every 2 seconds.
- Batch record is updated by the Celery task as each file is processed.
- No WebSocket needed in MVP; polling is consistent with the existing simulation
  progress pattern.

### Celery task structure

```python
# backend/app/observed_play/tasks.py
@celery_app.task(bind=True, max_retries=3, default_retry_delay=10)
def import_zip_batch(self, batch_id: str, zip_path: str, self_username: str | None):
    …
```

Follows the same pattern as `run_simulation` in
`backend/app/tasks/simulation.py`. Task ID stored in `batch.celery_task_id`.

### Retries

On transient failures (DB connection, filesystem error), Celery retries up to 3
times with 10-second delay. On exhausted retries, batch status = `"failed"`.

### Idempotency

The SHA-256 unique constraint on `observed_play_logs` is the primary idempotency
guarantee. If a Celery task is retried after partial completion, already-imported
files are detected as duplicates and skipped safely.

### Reuse of existing Celery infrastructure

The existing Celery app instance, Redis broker, and worker container are reused
directly. No new queue is needed in MVP; the default queue is acceptable.

---

## 11. Frontend Page / Component Plan

### Route

`/observed-play` — matches the feature name. Registered in
`frontend/src/router.tsx` alongside existing page routes.

### Page component

**`ObservedPlayPage`** (`frontend/src/pages/ObservedPlay.tsx`)
- Top-level page shell using `PageShell`.
- Renders upload panel + tabs: Import History, Unresolved Cards, Failed Logs.
- Manages `currentBatchId` state for post-upload report.

---

**`ObservedPlayUploadPanel`** (`frontend/src/components/observed-play/UploadPanel.tsx`)
- Accepts `.md`, `.markdown`, `.txt`, `.zip` via file picker or drag-and-drop.
- Optional `selfUsername` text input.
- Shows upload progress bar.
- On completion: displays import summary (counts: accepted, duplicates, failed).
- Error state: file type rejected, server error.
- Tests: renders, file validation, submit triggers API call, shows results.

---

**`ObservedPlayImportHistoryTable`** (`frontend/src/components/observed-play/ImportHistoryTable.tsx`)
- Table of past batches: filename, status, imported/failed/duplicate counts, date.
- Click a row to view the `ObservedPlayBatchReport`.
- Paginated.
- Tests: renders empty state, renders rows, pagination.

---

**`ObservedPlayBatchReport`** (`frontend/src/components/observed-play/BatchReport.tsx`)
- Shows full batch summary after import or when a historical batch is selected.
- Displays counts, top unresolved cards, warnings list, per-file status list.
- Link to each parsed log viewer.
- Tests: renders counts, renders unresolved card list.

---

**`ObservedPlayLogViewer`** (`frontend/src/components/observed-play/LogViewer.tsx`)
- Shows a single parsed log.
- Setup section at top.
- Turn-by-turn event list.
- Each event shows: raw_line, event_type badge, confidence indicator, card link.
- Filterable by turn number, event type, min confidence.
- "Reparse" button.
- "Exclude from memory" / "Include in memory" toggle.
- Tests: renders events, confidence filter works, reparse calls API.

---

**`ObservedPlayEventTimeline`** (`frontend/src/components/observed-play/EventTimeline.tsx`)
- Visual turn-by-turn condensed view within `LogViewer`.
- Grouping: Setup → Turn 1 → Turn 2 → … → Game End.
- Not full replay animation. Text-only reconstruction.

---

**`ObservedPlayUnresolvedCardsTable`** (`frontend/src/components/observed-play/UnresolvedCardsTable.tsx`)
- Table of all unresolved/ambiguous card names across all logs.
- Columns: raw name, occurrences, status, candidates, actions.
- "Add Resolution Rule" button per row → `ObservedCardResolutionModal`.
- Tests: renders table, opens modal.

---

**`ObservedCardResolutionModal`** (`frontend/src/components/observed-play/CardResolutionModal.tsx`)
- Modal dialog to create a resolution rule for a specific raw card name.
- Card search input to find the `tcgdex_id`.
- "Save rule" submits `POST /api/observed-play/resolution-rules`.
- Option: "Reparse affected logs after saving."
- Tests: opens, searches, saves, closes.

---

**`ObservedPlayFailedLogsTable`** (`frontend/src/components/observed-play/FailedLogsTable.tsx`)
- List of logs with `parse_status = "failed"`.
- Columns: filename, error type, error message, timestamp.
- "Retry" (triggers reparse), "Download raw" (future).
- Tests: renders empty state, renders rows.

---

### API module

`frontend/src/api/observedPlay.ts` — mirrors the existing pattern in
`simulations.ts` / `history.ts`. Exports typed functions:
`uploadLog`, `listBatches`, `getBatch`, `listLogs`, `getLog`,
`getLogEvents`, `reparseLog`, `excludeLog`, `includeLog`,
`listUnresolvedCards`, `createResolutionRule`.

---

## 12. Parsed Log Viewer Plan

The log viewer (`ObservedPlayLogViewer`) reconstructs the game turn-by-turn for
human review. It is **not** a full animated replay.

### Structure

```
Setup
  Coin flip: Player B goes first
  Player A active: Dwebble
  Player A bench: Munkidori, Rellor

Turn 1 — Player B (opponent)            [turn badge]
  [DRAW_HIDDEN] drew a card             [confidence: 0.95]
  [PLAY_SUPPORTER] played Arven         [confidence: 1.0] [card: sv02-166]
  [SEARCH_DECK] searched deck for ...   [confidence: 0.90]
  [END_TURN]

Turn 2 — Player A (self)
  [DRAW] drew Buddy-Buddy Poffin        [confidence: 1.0] [card: sv05-144]
  [PLAY_ITEM] played Buddy-Buddy Poffin [confidence: 1.0] [card: sv05-144]
  [PLAY_TO_BENCH] benched Cleffa        [confidence: 0.90] [card: ⚠ ambiguous]
  ...
```

### Display features

- Raw line collapsible per event (click to expand).
- Confidence badge: green ≥ 0.90, yellow 0.70–0.89, red < 0.70.
- Card resolution status icon: ✓ resolved, ⚠ ambiguous, ✗ unresolved.
- Filter bar: by turn, event type, min confidence, unresolved-only.
- Warnings/errors panel at bottom: parser warnings for this log.
- "Reparse" button at top of viewer.

### What the viewer is not

- Not a board-state animator.
- Not a legal-action validator.
- Not connected to the simulator engine.
- Not a memory editor.

---

## 13. Confidence Scoring Plan

### Thresholds

| Range | Label | Use |
|---|---|---|
| 0.00–0.59 | `low` | Store only. No analytics, Coach, or Player. |
| 0.60–0.79 | `medium` | Aggregate reports and import summary only. |
| 0.80–0.89 | `high` | Future Coach advisory retrieval (Phase 6). |
| 0.90–1.00 | `very_high` | Future Coach memory + Player advisory (Phase 8). |

### Levels

- **Event-level:** computed per event as described in §7.
- **Log-level:** weighted mean of event confidences, with log-level penalties.
- **Card-resolution confidence:** per `observed_card_mentions` row (0.0–1.0).
- **Derived-memory confidence (Phase 6+):** min of (log confidence, card resolution confidence, source weight). A derived memory can never exceed its source log's confidence.
- **Graph-edge confidence (Phase 7+):** aggregated over N contributing events and logs.

### Why no memory ingestion in MVP

Parser quality is unknown until real logs are imported and reviewed. Premature
ingestion of low-quality parsed events into Coach or Player memory could degrade
decision quality in ways that are hard to detect. The MVP's upload-parse-report
cycle gives a full review window before any memory is consumed downstream.

---

## 14. Reparse / Versioning Plan

### Parser version storage

- `PARSER_VERSION = "1.0"` in `backend/app/observed_play/constants.py`.
- Stored as text on `observed_play_logs.parser_version` and on every
  `observed_play_events.parser_version` row.
- Bump to `"1.1"` when parser behavior changes in any way that affects outputs.

### Parse run behavior

Parsing is idempotent within a parser version. Running the same parser on the
same raw log twice produces the same events.

### Reparsing old logs

Reparse is triggered by:
1. User clicks "Reparse" on a log in the UI.
2. User adds a resolution rule and selects "Reparse affected logs."
3. Future: admin bulk-reparse all logs at parser version < current.

### Overwrite vs version history

**MVP decision: overwrite.** Derived events for a log are deleted and replaced
on each reparse. The `parser_version` on the log row is updated. The
`updated_at` timestamp captures when reparse occurred.

If parse run history is needed later, add an `observed_play_parse_runs` table
with `(log_id, parser_version, run_at, event_count, confidence_score)`.

### Derived event invalidation

Before writing new events on reparse, delete all `observed_play_events` WHERE
`observed_play_log_id = log_id`. Same for `observed_card_mentions`. This is
safe because the raw log row is preserved.

### Future memory invalidation

When Phase 6 (Coach) and Phase 7 (pgvector/Neo4j) land, a reparse must also
mark associated memory as stale. At that point the reparse flow will need an
invalidation step. Design this at Phase 6 time; do not build it in Phase 1–5.

### UI warnings for stale parser version

Phase 4 frontend: display a badge on logs where
`log.parser_version != CURRENT_PARSER_VERSION`:
> "Parsed with v1.0 — current parser is v1.1. Reparse recommended."

---

## 15. Future Memory Ingestion Plan

**Not implemented until Phase 6/7. Design only.**

### PostgreSQL analytics (Phase 5)

Aggregate queries over `observed_play_events`:
- Card usage frequency by log win/loss outcome.
- Average turn of first energy attachment by attacker.
- Supporter sequencing patterns.

These are SQL queries, no new tables needed beyond Phase 3.

### pgvector snippets (Phase 7)

State-action-outcome text snippets generated from high-confidence event
subsequences. Stored in `embeddings` table with `source_type = "observed_play"`.

Example snippet:
> "Turn 3: self played Crispin (sv09-145), attached 2 energy to Crustle in
> Active, used Superb Scissors, knocked out opponent Dunsparce, took prize.
> Game eventually won. Confidence: 0.92."

Retrieval uses existing pgvector cosine search infrastructure.

### Neo4j observed-play edges (Phase 7)

New edge types on existing card nodes, tagged `source: "ptcgl_import"`:
```cypher
(:Card {tcgdex_id: "sv09-145"})-[:ENABLES_ATTACK {source: "ptcgl_import", games_observed: 8, confidence: 0.88}]->(:Card {tcgdex_id: "crustle-card-id"})
```

Written by a new `ObservedPlayGraphWriter` class that mirrors `GraphMemoryWriter`
but reads from `observed_play_events` instead of `MatchResult`.

### Coach retrieval (Phase 6)

`backend/app/coach/` gains a new retrieval step that queries:
- Top N pgvector observed-play snippets for the current deck/matchup.
- Summary of confidence-filtered aggregate stats.
- Formatted as compact advisory packet (< 200 tokens).

The Coach prompt receives this as a new section, clearly labeled `[Observed Play Memory]`.

### AI Player retrieval (Phase 8)

Same mechanism as Coach but at decision time. At-most 3 snippets. Source-tagged.
Confidence-filtered (≥ 0.90). Advisory only; action validator remains
authoritative.

---

## 16. Coach Integration Plan (Phase 6)

### First safe integration point

Phase 6 begins only after:
- Phase 3 card resolution UI is stable.
- Phase 5 analytics confirm parsed data quality.
- A manual review of ≥ 20 imported logs has been completed.
- Log-level confidence distribution is checked: ≥ 60% of logs should score ≥ 0.80.

### Requirements

- Only logs with `confidence_score ≥ 0.80` contribute to Coach memory.
- Only events with `confidence_score ≥ 0.80` contribute.
- Prompt packets are compact summaries, not raw log text.
- Packets are limited to top 5 relevant observations.
- Packets are clearly labeled `[Observed Play Memory (advisory)]`.
- Existing Coach safety systems (primary evolution line protection, regression
  detection, deck rollback) remain fully authoritative.
- Observed Play Memory is advisory evidence, not a mutation trigger.

### A/B testing plan

Introduce a `OBSERVED_PLAY_MEMORY_ENABLED` environment variable (default off).
When on, the Coach retrieval includes the advisory packet. Compare simulation
win rates between runs with and without the packet over ≥ 100 matches.

---

## 17. AI Player Integration Deferral

**Player integration is Phase 8. It must not begin before Phase 7.**

### Why delayed

- Parser quality is unknown until Phase 2–3 review.
- Coach integration (Phase 6) validates that observed memories improve strategic
  reasoning before trusting them at the faster tactical (Player) timescale.
- Local model prompt budgets are tight; adding retrieval at decision time
  competes with legal-action context.
- Observed sequences may describe plays that are situationally correct in
  specific board states but harmful if applied mechanically.

### Prerequisites before Phase 8

1. Parser v1 has been in production for ≥ 3 months with active log imports.
2. Card resolution coverage ≥ 85% (unresolved rate < 15%).
3. Log-level confidence ≥ 0.80 for ≥ 70% of imported logs.
4. Phase 6 (Coach) has been stable for ≥ 1 month with no observed regressions.
5. Memory retrieval respects the AI Player prompt budget (≤ 200 tokens for
   observed-play section).
6. Integration test confirms no illegal actions are produced by observed-play
   context.

---

## 18. Human-vs-Simulator Disagreement Reports (Phase 5+)

**Deferred analytics, not MVP. Design only.**

Reports compare `observed_play_events` against simulator `card_performance` and
`match_events` to surface interesting disagreements.

| Report | Description |
|---|---|
| Card weak in sim, strong in observed logs | Low `card_performance.win_rate` but high observed usage before wins |
| Card strong in sim, weak in observed logs | High sim win rate but rarely seen in observed winning lines |
| Human sequences not found in sim | Event subsequences from logs that never appear in `match_events` |
| Cards referenced in logs but missing from coverage | Observed card names with no `cards` row → feeds audit priorities |

These reports live on the `/observed-play` page under a "Diagnostics" tab in
Phase 5.

---

## 19. Privacy / Anonymization Plan

### Raw player names

- `player_1_name_raw` and `player_2_name_raw` store the exact PTCGL usernames
  from the log.
- These are stored only in `observed_play_logs` (not in event rows or Neo4j).
- The DB is local/private to the user; these names do not leave the container.

### Aliases for analytics

- All analytics, Coach prompts, and graph edges use aliases: `"self"`,
  `"opponent_001"`, `"unknown"`.
- `player_1_alias` / `player_2_alias` set at parse time.
- Events reference `player_alias`, not `player_raw`.

### Self-detection

- If the upload request includes `self_username`, the parser sets
  `self_player_index = 1 or 2` and sets the alias to `"self"`.
- If not provided, both players are `"unknown_player"`.

### Opponent usernames in graph

- Opponent PTCGL usernames must NOT become Neo4j nodes or pgvector entries.
- The opponent identity is irrelevant to card strategy learning.
- Graph edges use `"observed_by: self"` as the actor label.

### Future: user PTCGL username setting

Phase 4 or later: allow the user to save their PTCGL username in a settings
table so it auto-detects on every upload without requiring the form field.

---

## 20. Testing Strategy

### By phase

#### Phase 0 (this phase)
- No code tests required. Document only.

#### Phase 1 — Raw archive / import foundation
- `backend/tests/test_observed_play/test_storage.py`: SHA-256 hash, archive path generation, duplicate detection.
- `backend/tests/test_observed_play/test_import_api.py`: upload `.md`, upload `.zip`, duplicate skipped, unsupported type rejected, batch record created.
- `backend/tests/test_observed_play/test_batch_status.py`: GET batches, GET batch/{id}.
- Migration test: tables created, unique constraint on `sha256_hash`.

#### Phase 2 — Parser v1 + events
- `backend/tests/test_observed_play/test_parser.py`: golden fixture assertions (event types, counts, confidence, win condition, card mentions).
- `backend/tests/test_observed_play/test_confidence.py`: event-level reductions, log-level aggregation.
- `backend/tests/test_observed_play/test_event_api.py`: GET logs/{id}/events pagination, turn filter.
- `backend/tests/test_observed_play/test_reparse.py`: reparse replaces events, preserves raw log.

#### Phase 3 — Card resolution UI
- `backend/tests/test_observed_play/test_card_resolver.py`: exact match, normalized match, ambiguous detection, unresolved reporting, resolution rule application.
- `backend/tests/test_observed_play/test_resolution_rules.py`: create rule, reparse trigger.
- Frontend: `CardResolutionModal.test.tsx`, `UnresolvedCardsTable.test.tsx`.

#### Phase 4 — Frontend page
- `frontend/src/pages/ObservedPlay.test.tsx`: upload panel, import history table, failed logs.
- `frontend/src/components/observed-play/UploadPanel.test.tsx`: file validation, submit, result display.
- `frontend/src/components/observed-play/LogViewer.test.tsx`: event list, filter, confidence badges.
- `frontend/src/components/observed-play/BatchReport.test.tsx`: counts, unresolved list.

#### Phase 5+ — Analytics, Coach, Player
- No-memory-ingestion guard test: assert `memory_status = "not_ingested"` for all logs until Phase 6 enabled.
- Coach integration: test that Coach prompt includes `[Observed Play Memory]` section only when enabled and data meets threshold.
- Player integration: integration test that no illegal actions result from observed-play context addition.
- Celery idempotency: import same ZIP twice, confirm dedup prevents double-write.

---

## 21. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Parser overreach — trying to parse every card effect in v1 | Parser v1 targets turn structure and known event patterns only; unknown lines → `UNKNOWN` event with raw preservation |
| Noisy human data lowering average confidence | Confidence gating at all ingestion stages; unresolved card reporting makes noise visible |
| Ambiguous card names causing silent misidentification | Resolver never auto-selects below 0.95 confidence; status clearly flagged as `ambiguous` |
| Raw log privacy — player names in DB | Names stored only in `observed_play_logs`, not in analytics or graph; aliased in all downstream use |
| Prompt bloat — observed memories competing with legal action context | Phase 6+ packets capped at top-5 summaries; ≤ 200 tokens; Coach and Player prompts have existing budget constraints |
| Memory contamination — low-confidence data entering Coach/Player | MVP has zero ingestion; Phase 6 requires ≥ 0.80 log confidence; Phase 8 requires Phase 6 validation first |
| Long-running ZIP imports blocking the request thread | ZIP imports are Celery tasks; single files are inline; no blocking HTTP handlers |
| Duplicate/reparse bugs corrupting events | SHA-256 unique constraint prevents duplicate logs; reparse deletes derived rows before writing new ones |
| Format rotation making old logs less relevant | `game_date_detected`, detected regulation marks stored; Coach retrieval will eventually filter by recency |
| Frontend complexity from too many new components | Components follow identical patterns to existing pages; no novel UI paradigms |
| Merging instability — feature branch drifts from main | Periodic rebases from main; keep branch focused on observed-play only; no engine/coach changes on feature branch until Phase 6 |

---

## 22. Phase-by-Phase Implementation Plan

---

### Phase 0 — Documentation / Scaffolding (current)

**Files touched:**
- `docs/proposals/OBSERVED_PLAY_MEMORY_IMPLEMENTATION_PLAN.md` (this file)
- `.gitignore` (add `data/ptcgl_logs/`)
- `docs/STATUS.md` (branch note)
- `docs/CHANGELOG.md` (design-plan entry)

**Acceptance criteria:**
- Implementation plan committed on feature branch.
- `.gitignore` updated.
- No production code added.
- No migrations added.

**Tests required:** none.

**Rollback:** `git revert` plan commit on feature branch; no code is affected.

---

### Phase 1 — Raw Archive and Import Foundation

**Files likely touched:**
- `backend/app/observed_play/__init__.py`, `constants.py`, `storage.py`, `schemas.py`, `importer.py`, `tasks.py`
- `backend/app/db/models.py` (add new ORM models)
- `backend/alembic/versions/{new_id}_observed_play_foundation.py`
- `backend/app/api/observed_play.py` (new router)
- `backend/app/api/router.py` (register new router)
- `docker-compose.yml` (add `ptcgl_logs_data` volume)
- `backend/tests/test_observed_play/test_storage.py`
- `backend/tests/test_observed_play/test_import_api.py`
- `backend/tests/test_observed_play/test_batch_status.py`

**Acceptance criteria:**
1. `POST /api/observed-play/upload` with a `.md` file creates an `ObservedPlayImportBatch` and an `ObservedPlayLog` row.
2. SHA-256 duplicate detection: uploading the same file twice results in one `imported`, one `duplicate`, no second log row.
3. Unsupported file type returns 422.
4. Raw content stored in `observed_play_logs.raw_content`.
5. Archive file written to `/data/ptcgl_logs/archive/`.
6. `GET /api/observed-play/batches` returns the batch list.
7. Parse status remains `"pending"` (parser not yet built).
8. All Phase 1 tests pass. Existing test suite unaffected.

**Tests required:** storage (hash, path, dedup), import API, batch status API.

**Rollback / stop conditions:** if Docker volume mount causes issues on developer machines, defer volume to Phase 2 and store archive paths only in DB.

---

### Phase 2 — Parser v1 + Golden Fixtures

**Status: COMPLETE** (sessions 22–24)

- Parser v1 with 30+ event types, player aliasing, phase tracking.
- `observed_play_events` table (Alembic `e1f2a3b4c5d6`).
- Reparse endpoint. Frontend events modal.

---

### Phase 2.1 — Parser Hardening Against Real Logs

**Status: COMPLETE** (session 25)

**Problem:** Real PTCGL logs produce ~56% confidence due to 9 common patterns
falling into `unknown` or being misclassified.

**Changes:**
- Fixed 9 parser bugs (see `docs/CHANGELOG.md` and `docs/STATUS.md` session 25 for detail).
- Added 3 new event types: `play_trainer`, `attach_card`, `play_to_bench_hidden`.
- Added parser diagnostics stored in `metadata_json["parser_diagnostics"]`.
- Updated confidence scoring for new event types.
- 42 new parser tests + 2 new API tests. New `real_log_sample.md` fixture.

**Known remaining parser limitations (pre-Phase 3):**
- `PLAYER's CARD used X.` (no target) always classified as `ability_used`; cannot
  distinguish ability from no-target attack without card DB.
- `PLAYER played CARD.` without `(Item)`/`(Supporter)` subtype tag classified as
  generic `play_trainer`; subtype not determinable without card DB.
- Card names are raw text only — no card DB resolution, no `observed_card_mentions`.

**No Phase 3 work in this session.**

---

### Phase 3 — Card Mentions / Resolution UI

**Files likely touched:**
- `backend/app/observed_play/card_resolution.py` (new)
- `backend/app/db/models.py` (`ObservedCardMention`, `ObservedCardResolutionRule`)
- `backend/alembic/versions/{new_id}_observed_card_resolution.py`
- `backend/app/api/observed_play.py` (unresolved-cards + resolution-rules endpoints)
- `backend/tests/test_observed_play/test_card_resolver.py`
- `backend/tests/test_observed_play/test_resolution_rules.py`

**Acceptance criteria:**
1. Card names from parsed events are stored as `ObservedCardMention` rows.
2. Exact-match resolution works for all cards in the fixture with standard names.
3. Basic energy cards resolved correctly.
4. Unresolved cards appear in `GET /api/observed-play/unresolved-cards`.
5. `POST /api/observed-play/resolution-rules` creates a rule.
6. Re-parsing a log applies the rule and updates the mention's `resolution_status`.
7. Log `unresolved_card_count` updated after reparse.

**Tests required:** card resolver (exact, normalized, ambiguous, unresolved, rule application), resolution rules API.

---

### Phase 4 — Frontend Observed Play Page

**Files likely touched:**
- `frontend/src/pages/ObservedPlay.tsx` (new)
- `frontend/src/components/observed-play/*.tsx` (new components)
- `frontend/src/api/observedPlay.ts` (new)
- `frontend/src/router.tsx` (add route)
- `frontend/src/components/layout/Sidebar.tsx` or `NavBar` (add nav link)
- `frontend/src/pages/ObservedPlay.test.tsx`, component test files

**Acceptance criteria:**
1. `/observed-play` route renders the upload panel.
2. Uploading a `.md` file triggers API call and shows import summary.
3. Import history table shows past batches.
4. Batch detail shows per-file status.
5. Log viewer shows turn-by-turn events with confidence badges.
6. Unresolved cards table shows aggregated names.
7. Card resolution modal allows creating a rule.
8. Failed logs table shows parse errors.
9. All Phase 4 tests pass.

**Tests required:** upload panel, import history, batch report, log viewer,
unresolved cards table, card resolution modal, failed logs table.

---

### Phase 5 — Analytics Only

**Files likely touched:**
- `backend/app/api/observed_play.py` (add analytics endpoints)
- `frontend/src/components/observed-play/DiagnosticsTab.tsx` (new)
- `frontend/src/components/observed-play/DisagreementReport.tsx` (new)
- Aggregate SQL queries over `observed_play_events`

**Acceptance criteria:**
1. Analytics endpoint returns card-usage-by-outcome aggregates.
2. Disagreement report shows cards weak in sim but frequent in observed wins.
3. No Coach/Player memory ingestion.
4. `memory_status = "not_ingested"` for all logs (test this explicitly).

---

### Phase 6 — Coach-Only Advisory Integration

**Files likely touched:**
- `backend/app/coach/` (add observed-play retrieval step)
- `backend/app/observed_play/` (add snippet builder)
- Environment variable: `OBSERVED_PLAY_MEMORY_ENABLED`

**Acceptance criteria:**
1. Coach prompt includes `[Observed Play Memory (advisory)]` section when enabled.
2. Only logs with `confidence_score ≥ 0.80` contribute.
3. Existing Coach safety systems (primary evo protection, regression detection) are unaffected.
4. A/B test framework in place.
5. Tests confirm no observed-play content when flag is off.

---

### Phase 7 — pgvector / Neo4j Source-Tagged Memory

**Files likely touched:**
- `backend/app/observed_play/graph_writer.py` (new: `ObservedPlayGraphWriter`)
- `backend/app/memory/` (observed-play embedding builder)
- `backend/app/db/models.py` (no new tables; uses existing `embeddings`)

**Acceptance criteria:**
1. Observed-play events with confidence ≥ 0.85 produce `Embedding` rows with `source_type = "observed_play"`.
2. Neo4j contains observed-play edges tagged `source: "ptcgl_import"`.
3. Reparse invalidates and rebuilds associated embeddings and graph edges.
4. Disagreement report (Phase 5) uses graph data correctly.

---

### Phase 8 — AI Player Advisory Retrieval

**Prerequisites:** Phase 6 stable for ≥ 1 month, prerequisites in §17 met.

**Files likely touched:**
- `backend/app/players/ai_player.py`
- `backend/app/memory/postgres.py` or a new retrieval helper

**Acceptance criteria:**
1. Player prompt includes observed-play advisory section (≤ 200 tokens, ≥ 0.90 confidence only).
2. No illegal actions produced by the addition.
3. Integration test confirms action validator still authoritative.

---

## 22.1 Phase 2.1 — Parser Hardening Against Real Logs

**Status:** Queued. Phase 2 accepted (upload, parse, event storage, events API, reparse all functional). Manual validation of a real log revealed 56% confidence — too low to proceed to Phase 3 card resolution. Parser needs to recognize a broader set of common PTCGL log lines without overclaiming hidden state.

**Trigger:** Manual upload of `2026-05-03 02.15.md` → 290 events, 56% confidence. Common lines falling into `unknown`.

**What to fix (patterns observed in the real log):**

| Bad line | Current | Expected |
|---|---|---|
| `gehejo played Buddy-Buddy Poffin.` | `unknown` | `play_trainer` (or `play_item` from safe map) |
| `DAVIDELIRIUM drew a card.` | `draw` with `card_name_raw="a card"` | `draw_hidden`, amount=1, card_name_raw=null |
| `DAVIDELIRIUM attached Maximum Belt to Riolu...` | `attach_energy` | `attach_tool` or `attach_card` (not energy) |
| `DAVIDELIRIUM evolved Riolu to Mega Lucario ex...` | `unknown` | `evolve`, from=Riolu, to=Mega Lucario ex |
| `DAVIDELIRIUM's Hariyama used Heave-Ho Catcher.` | `unknown` | `ability_used`, card=Hariyama, ability=Heave-Ho Catcher |
| `gehejo's Dwebble used Ascension.` | `unknown` | `attack_used`, card=Dwebble, attack=Ascension, damage=null |
| `DAVIDELIRIUM took a Prize card.` | `unknown` | `prize_taken`, amount=1 |
| `- gehejo drew 2 cards and played them to the Bench.` | `play_to_bench` with `card_name_raw="them"` | `bench_from_deck_hidden`, amount=2, identities unknown |
| `gehejo's Dwebble is now in the Active Spot.` | `unknown` | `switch_active`, card=Dwebble |

**Key constraints:**
- Do not overclaim hidden information (hidden draws stay hidden; bench-from-deck stays anonymous).
- Do not attach card names to "them" / pronouns.
- Do not require card DB resolution.
- Energy detection: use `attach_energy` only when card name contains "Energy" or matches known energy pattern.
- Support both straight apostrophe `'` and curly apostrophe `'` in ability/attack/trainer name patterns.

**Parser diagnostics:** store in `ObservedPlayLog.metadata_json["parser_diagnostics"]`:
- `unknown_count`, `unknown_ratio`, `low_confidence_count`, `event_type_counts`, `top_unknown_raw_lines`.

**Files touched:**
- `backend/app/observed_play/constants.py` — new event type constants.
- `backend/app/observed_play/patterns.py` — new/corrected patterns.
- `backend/app/observed_play/parser.py` — new/corrected match branches; diagnostics population.
- `backend/app/observed_play/confidence.py` — update scoring for new event types.
- `backend/app/db/models.py` — verify `metadata_json` column exists on `ObservedPlayLog` (add if absent).
- `backend/tests/fixtures/observed_play/` — curated fixture lines only (no real log corpus).
- `backend/tests/test_observed_play/test_parser.py` — 17+ new/updated tests.
- `frontend/src/pages/ObservedPlay.tsx` — optional: show parser diagnostics in event modal.
- `frontend/src/pages/ObservedPlay.test.tsx` — update if diagnostics are added.

**Acceptance criteria:**
1. All 9 previously-bad example lines parse correctly (not `unknown`, not misclassified).
2. `draw_hidden` used for "drew a card" / "drew N cards" without named cards.
3. Energy attachment uses `attach_energy` only when card name is energy-like.
4. Evolution, ability, no-damage attack, prize, bench-from-deck-hidden, switch-active all have correct types.
5. `card_name_raw` is never set to a pronoun (`"them"`, `"it"`, `"a card"`).
6. Parser diagnostics present in `metadata_json` for any newly-parsed log.
7. Confidence on a representative curated fixture improves materially from 56% baseline.
8. All Phase 2.1 tests pass (≥ 17 new/updated tests).
9. No card DB resolution / Coach / Player / pgvector / Neo4j / memory ingestion added.
10. `alembic upgrade head` is a no-op (no new migration required unless `metadata_json` column missing).

**Tests required:**
- All 17 tests listed in next-session prompt (draw_hidden singular/plural, trainer plays ×3, evolve, ability ×2 apostrophes, no-damage attack, prize ×2, bench-from-deck-hidden card_name_raw=null, switch_active, non-energy attachment, energy attachment, diagnostics, confidence improvement).

---

## 23. First Implementation Prompt Preview

The next session prompt (Phase 1) will be titled:

**Observed Play Memory Phase 1 — Raw Archive and Import Foundation**

It will instruct the agent to:

1. Add `data/ptcgl_logs/` to `.gitignore` (already done in Phase 0).
2. Add `ptcgl_logs_data` named Docker volume in `docker-compose.yml` for both `backend` and `celery-worker`.
3. Create the `backend/app/observed_play/` module with `__init__.py`, `constants.py`, `storage.py`, `schemas.py`, `importer.py`.
4. Add `ObservedPlayImportBatch` and `ObservedPlayLog` SQLAlchemy models to `backend/app/db/models.py`.
5. Write an Alembic migration creating both tables with all indexes and the `sha256_hash` unique constraint.
6. Add `POST /api/observed-play/upload`, `GET /api/observed-play/batches`, `GET /api/observed-play/batches/{batch_id}`, `GET /api/observed-play/logs`, `GET /api/observed-play/logs/{log_id}` to a new `backend/app/api/observed_play.py`.
7. Register the router in `backend/app/api/router.py`.
8. Write the Celery task stub for ZIP import.
9. Write Phase 1 tests.
10. Run `python3 -m pytest tests/ -x -q` and verify existing baseline is unaffected.
11. Rebuild backend/celery containers and verify volume mounts.
12. Commit on feature branch with `feat(observed-play): phase-1 raw archive foundation`.

The prompt will specify not to implement the parser, card resolution, or any
frontend in Phase 1.

---

*End of Observed Play Memory Implementation Plan.*
*Feature branch: `feature/observed-play-memory`. No production code in this document.*
