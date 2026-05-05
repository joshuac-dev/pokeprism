# PokéPrism Design Review Request: Observed Play Memory from Imported PTCGL Battle Logs

## Purpose

I want to add a new feature area to PokéPrism that imports real Pokémon TCG Live battle logs, preserves them, parses them into structured game events, and feeds high-confidence observed human play patterns into the existing PokéPrism memory stack.

This is not a request to write code yet.

This is a design-review and architecture-alignment request. Please read the existing project documentation first, especially:

- `docs/PROJECT.md`
- `docs/STATUS.md`
- `docs/CHANGELOG.md`
- Current card database / card list files
- Existing memory, Coach, Player, simulation, event, and dashboard code
- Existing database models and migrations
- Existing Neo4j graph-memory code
- Existing pgvector / embeddings code
- Existing frontend pages and API patterns

`PROJECT.md` remains the source of truth. If anything below conflicts with the current architecture, point it out and propose a corrected design that fits the project.

The goal is to make sure this proposed feature is fully thought through before I ask GitHub Copilot to implement it.

---

## Feature Name

Preferred name:

### Observed Play Memory

Alternate names:

- Human Battle Log Memory
- PTCGL Battle Log Importer
- Human Play Corpus
- Real-Game Memory Layer

I prefer **Observed Play Memory** because the important concept is not just importing logs. The goal is to extract useful evidence from real games and make that evidence available to the Coach and eventually the AI Player.

---

## Current User Workflow

I play Pokémon TCG Live on iPhone and Mac.

At the end of games, I use the PTCGL export/copy feature to copy the battle log.

I currently use an Apple Shortcut to save the copied log directly into a markdown file on iCloud Drive.

Over time, I accumulate many `.md` battle logs.

I want PokéPrism to eventually ingest these logs through a frontend upload page, preferably supporting both:

1. Uploading individual `.md` battle log files.
2. Uploading a `.zip` containing many `.md` battle logs.

I do not want the first version to depend directly on iCloud integration. The Apple Shortcut can keep producing markdown files. PokéPrism only needs a way to ingest uploaded files or files dropped into an import folder.

---

## High-Level Concept

PokéPrism already has a memory-first architecture.

The project does not fine-tune models. Instead, it builds a durable memory stack using PostgreSQL, pgvector, Neo4j, and LLM context to improve future play and deck mutation decisions.

This new feature should extend that philosophy by importing real human game logs as a new source of observed play data.

The logs contain thousands of real player decisions, including:

- Opening setup choices
- Draw sequencing
- Pokémon played to Active or Bench
- Evolution timing
- Energy attachment decisions
- Trainer usage
- Supporter sequencing
- Stadium replacement
- Tool attachment
- Retreat decisions
- Forced switch effects
- Attacks
- Damage
- Weakness/resistance interactions
- Knock Outs
- Prize taking
- Discards
- Recovery effects
- Board development
- Late-game failure patterns
- Deck-out losses
- Win conditions

The goal is not to blindly imitate these logs.

The goal is to parse them into source-tagged, confidence-scored, outcome-weighted observed play memories.

Those memories should initially inform the Coach during analysis and deck mutation.

Only later, after validation, should they inform the in-game AI Player.

---

## Important Principle

Imported PTCGL logs are **observed human play data**, not simulator-truth data.

They are valuable but incomplete.

They usually do not expose:

- Full hidden hands
- Full deck order
- Every legal alternative
- Player intent
- Whether a human decision was correct
- Full board state in every situation
- Exact card print/version in every case
- Whether the opponent was skilled or misplaying

Therefore, imported log data must be treated as:

- Source-tagged
- Confidence-scored
- Outcome-weighted
- Reprocessable
- Auditable
- Excludable from memory if needed

Do not treat imported human actions as always optimal.

Do not allow noisy parsed data to contaminate Coach or Player memory without confidence gating.

---

## Preferred Architecture

The preferred architecture is:

```text
Frontend Human Logs Upload
        ↓
Backend upload/import API
        ↓
Docker volume archive at /data/ptcgl_logs
        ↓
Raw log preservation
        ↓
Duplicate detection by SHA-256 hash
        ↓
Parser-versioned structured event extraction
        ↓
Card name / card print resolution
        ↓
Confidence scoring
        ↓
Import report and unresolved-card review
        ↓
PostgreSQL imported-log/event tables
        ↓
pgvector state-action-outcome snippets
        ↓
Neo4j observed-play relationships
        ↓
Coach retrieval first
        ↓
AI Player retrieval later, advisory only
```

---

## Docker Volume / File Storage Design

Use a Docker-mounted data volume from the beginning.

Preferred backend-visible paths:

```text
/data/ptcgl_logs/inbox
/data/ptcgl_logs/archive
/data/ptcgl_logs/failed
/data/ptcgl_logs/tmp
```

Purpose:

- `inbox`: optional manual drop location for files copied into the container/volume.
- `archive`: canonical storage for successfully imported raw files.
- `failed`: files that failed import or parse.
- `tmp`: temporary upload/extraction workspace, especially for zip imports.

Even though the preferred user-facing workflow is frontend upload, the volume structure should support manual import later.

The repo should also gitignore any local development equivalent, such as:

```text
data/ptcgl_logs/
```

Important:

- Do not commit thousands of battle logs to Git.
- Keep a small curated fixture set in the repo for parser tests only.
- Raw user logs should live in Docker volume storage and/or the database, not source control.

---

## Frontend Feature: Human Logs Page

Add a frontend page for importing and inspecting PTCGL logs.

Possible route:

```text
/human-logs
```

or:

```text
/observed-play
```

or as a tab under existing Memory pages.

The page should support the following features.

### Upload Panel

Allow upload of:

- `.md`
- `.markdown`
- `.txt` if needed
- `.zip` containing multiple markdown files

The UI should clearly show:

- Upload progress
- Number of files detected
- Number of files accepted
- Number rejected due to unsupported type
- Number skipped because duplicate hash already exists
- Number imported successfully
- Number failed

### Import History Table

Show historical imports with columns like:

- Imported at
- Original filename
- Source type
- Parse status
- Parser version
- Player names
- Winner
- Win condition
- Event count
- Recognized card count
- Unresolved card count
- Confidence score
- Warnings count
- Errors count
- Whether memory ingestion is active
- Actions: view, reparse, exclude from memory, include in memory, delete/archive if supported

### Import Summary Report

After each batch import, show a visible report such as:

```text
Imported 193 of 200 logs.
7 failed.
4,812 events parsed.
312 unique card names recognized.
28 unresolved card names.
Average parser confidence: 0.84.
Top unresolved cards: Gravity Gemstone, Basic Psychic Energy, Team Rocket's Watchtower.
Most common parse warnings: unknown card version, hidden draw event, unresolved win condition.
```

This is important. Silent import failures or silent low-confidence parsing would be dangerous.

### Unresolved / Ambiguous Cards Table

Show unresolved and ambiguous card names.

Columns:

- Raw name from log
- Number of occurrences
- Example log
- Example event
- Candidate card matches
- Current resolution status
- Confidence
- Manual override
- Apply mapping globally?
- Reparse affected logs?

This should become a card identity resolver UI.

### Failed Logs Table

Show failed imports separately.

Columns:

- Original filename
- Error type
- Error message
- Parser version
- Import timestamp
- Actions: retry, download raw, mark ignored

### Parsed Log Viewer

For each imported log, provide a parsed event viewer.

This does not need full animation.

It should show a turn-by-turn reconstruction with confidence annotations.

Example:

```text
Setup
- Player A active: Dwebble
- Player A bench: Munkidori
- Player B active: Dunsparce

Turn 1 — Player A
- Drew Poké Pad
- Attached Basic Psychic Energy to Dwebble
- Played Poké Pad
- Drew Crustle
- Ended turn

Turn 2 — Player B
- Played Ultra Ball
- Discarded Ethan's Sudowoodo and Xerosic's Machinations
- Searched Latias ex
- ...
```

Each event should show confidence and card resolution status.

This lets me spot parser mistakes before the data affects memory.

---

## Backend API Design

Please review existing API naming conventions and suggest final route names that match the project.

Candidate endpoints:

```text
POST /api/human-logs/upload
POST /api/human-logs/import/inbox
GET  /api/human-logs/imports
GET  /api/human-logs/imports/{id}
GET  /api/human-logs/imports/{id}/events
POST /api/human-logs/imports/{id}/reparse
POST /api/human-logs/imports/{id}/exclude
POST /api/human-logs/imports/{id}/include
GET  /api/human-logs/unresolved-cards
POST /api/human-logs/unresolved-cards/{id}/resolve
GET  /api/human-logs/import-batches
GET  /api/human-logs/import-batches/{id}
```

Possible upload behavior:

- Single `.md` creates one import batch with one log.
- `.zip` creates one import batch with many logs.
- Backend extracts zip into tmp storage.
- Each file is hashed.
- Duplicate hashes are skipped and reported.
- Each accepted file is archived.
- Each raw file gets a database record.
- Parser runs synchronously for small uploads or asynchronously for larger batches.
- Frontend polls or receives WebSocket updates for batch import progress.

Please evaluate whether this should use Celery because the project already uses Celery for simulation orchestration.

Likely recommendation:

- Small single-file uploads can be parsed inline.
- Zip/bulk imports should be Celery tasks.
- UI should display import progress and final report.

---

## Database Design: Raw Logs

Please review existing SQLAlchemy model patterns and migrations.

Conceptual model:

### `observed_play_logs`

Stores one raw imported battle log.

Fields:

```text
id
source
source_subtype
original_filename
stored_path
sha256_hash
raw_markdown
file_size_bytes
imported_at
import_batch_id
parser_version
parse_status
memory_status
player_1_name_raw
player_2_name_raw
player_1_alias
player_2_alias
self_player_detected
winner_raw
winner_alias
win_condition
game_started_at
game_ended_at
turn_count
event_count
recognized_card_count
unresolved_card_count
ambiguous_card_count
confidence_score
errors_json
warnings_json
metadata_json
created_at
updated_at
```

Possible values:

`source`:

```text
ptcgl_export
manual_upload
shortcut_upload_future
```

`parse_status`:

```text
pending
parsed
parsed_with_warnings
failed
excluded
needs_reparse
```

`memory_status`:

```text
not_ingested
eligible
ingested_postgres
ingested_vector
ingested_graph
excluded_from_memory
```

Important constraints:

- Unique constraint on `sha256_hash`.
- Parser version tracked.
- Raw markdown preserved exactly as imported.
- Stored path preserved.
- Parse warnings/errors stored.

Question for Claude:

Should raw markdown be stored in PostgreSQL, filesystem, or both?

Preferred answer:

- Store canonical raw file in Docker volume archive.
- Store raw markdown in DB if practical for easier reparse/debugging.
- If file size becomes a concern, store raw only on filesystem and keep hash/path in DB.
- For now, battle logs are likely small enough that DB storage is acceptable.

---

## Database Design: Import Batches

Conceptual model:

### `observed_play_import_batches`

Stores one upload/import operation.

Fields:

```text
id
source
uploaded_filename
original_file_count
accepted_file_count
duplicate_file_count
failed_file_count
imported_file_count
skipped_file_count
started_at
finished_at
status
summary_json
created_by
errors_json
warnings_json
created_at
updated_at
```

Status values:

```text
pending
running
completed
completed_with_warnings
failed
cancelled
```

The import batch powers the frontend report.

---

## Database Design: Parsed Events

Conceptual model:

### `observed_play_events`

Stores normalized events parsed from imported logs.

Fields:

```text
id
observed_play_log_id
import_batch_id
event_index
turn_number
phase
player_raw
player_alias
actor_type
event_type
raw_line
raw_block
card_name_raw
resolved_card_id
resolved_card_name
resolved_card_confidence
target_card_name_raw
target_resolved_card_id
zone
target_zone
amount
damage
base_damage
weakness_damage
resistance_delta
healing_amount
energy_type
prize_count_delta
deck_count_delta
hand_count_delta
discard_count_delta
event_payload_json
visible_state_before_json
visible_state_after_json
confidence_score
confidence_reasons_json
parser_version
created_at
```

Event types should include at least:

```text
setup
coin_flip_choice
coin_flip_result
turn_start
draw
draw_hidden
play_basic_to_active
play_basic_to_bench
evolve
attach_energy
play_item
play_supporter
play_stadium
replace_stadium
play_tool
ability_used
retreat
switch_active
attack_used
damage_dealt
damage_breakdown
knockout
prize_taken
discard
shuffle_deck
search_deck
recover_from_discard
heal
special_condition
prevent_damage
end_turn
game_end
unknown
```

Important:

- Preserve raw line or raw block for every event.
- Confidence should exist at the event level.
- Hidden draws should be represented differently from known draws.
- Ambiguous card identity should lower confidence.
- Events should be source-tagged as imported/human observed data.
- Do not mix these directly with native `match_events` unless the schema already supports source differentiation cleanly.

Question for Claude:

Should imported events reuse the existing `match_events` table or use a parallel table?

Preferred direction:

- Use a parallel table initially, or ensure strong source separation if using `match_events`.
- Do not pollute simulator-native event tables unless the existing schema is explicitly designed for multi-source events.
- Later, views can unify simulated and imported events for analytics.

---

## Database Design: Card Resolution

Conceptual model:

### `observed_card_mentions`

Tracks card names detected in imported logs.

Fields:

```text
id
observed_play_log_id
raw_card_name
normalized_card_name
occurrence_count
first_event_id
resolution_status
resolved_card_id
resolved_card_name
candidate_cards_json
confidence_score
manual_override
override_reason
created_at
updated_at
```

Resolution statuses:

```text
resolved_exact
resolved_by_context
ambiguous
unresolved
manual_resolved
ignored
```

Also consider a global mapping table:

### `observed_card_resolution_rules`

Fields:

```text
id
raw_name_pattern
normalized_name
resolved_card_id
confidence_score
scope
created_by
created_at
updated_at
```

Scope values:

```text
global
format_specific
deck_specific
player_specific
date_range_specific
```

This lets manual corrections apply to future imports.

Example problem:

PTCGL logs may say:

```text
Dunsparce
Clefairy
Dedenne
Basic Psychic Energy
Battle Cage
Gravity Gemstone
```

Depending on available card pool, some names may map cleanly, some may be ambiguous, some may not yet exist in the implemented database.

The resolver should never guess silently.

---

## Parser Design

The parser should be deliberately conservative.

Input:

- Raw markdown exported from PTCGL.
- Original filename.
- Optional user metadata if provided later.

Output:

- Raw log record.
- Parsed event list.
- Card mentions.
- Import warnings/errors.
- Confidence score.
- Optional reconstructed visible state.
- Optional memory snippets.

The parser should support the common structure in PTCGL logs:

```text
Setup
Player A chose heads/tails.
Player B won the coin toss.
Player B decided to go first.
Player A drew 7 cards for the opening hand.
Player B drew 7 cards for the opening hand.
- 7 drawn cards.
   • Card Name, Card Name, Card Name
Player A played X to the Active Spot.
Player B played Y to the Bench.

Player A's Turn
Player A drew Card Name.
Player A attached Energy to Pokémon in the Active Spot.
Player A played Trainer.
- Result line.
Player A ended their turn.

Player B's Pokémon used Attack on Player A's Pokémon for N damage.
- Damage breakdown:
   • Base damage: N damage
   • Weakness to Type: N damage
   • Total damage: N damage

Player A's Pokémon was Knocked Out!
Player B took a Prize card.
Card Name was added to Player B's hand.
```

The parser should initially target high-confidence events only.

Do not try to fully infer hidden state in v1.

Do not try to parse every possible card-specific effect in v1.

Do parse:

- Turn boundaries
- Active/bench setup
- Known draws
- Hidden draws as hidden
- Card play events
- Energy attachments
- Evolutions
- Trainer usage
- Stadium play/replacement
- Retreat
- Active switches
- Attacks
- Damage amounts
- Damage breakdowns
- KOs
- Prize taking
- Discards
- Recovery from discard
- Game end / winner / win condition if present

---

## Parser Versioning and Reprocessing

Parser versioning must be first-class.

Every parsed log and parsed event should store:

```text
parser_version
```

When parser behavior improves, the system should be able to reparse old logs.

UI should eventually show:

```text
128 logs were parsed with parser v1.1.
Current parser is v1.3.
Reprocess old logs?
```

Reprocessing should:

- Preserve raw log ID.
- Replace or version parsed events safely.
- Avoid duplicate memory ingestion.
- Recompute card mentions.
- Recompute confidence.
- Recompute memory snippets.
- Recompute graph relationships if needed.

Question for Claude:

Should reparsing overwrite parsed events or create event-parse-version history?

Preferred initial design:

- Overwrite derived parsed events for that raw log while preserving raw log and parser version.
- Keep enough metadata to audit what happened.
- If inexpensive, store parse run history separately.

---

## Confidence Scoring

Confidence should exist at multiple levels:

1. Log-level confidence.
2. Event-level confidence.
3. Card-resolution confidence.
4. Derived-memory confidence.
5. Graph-edge confidence.

Suggested thresholds:

```text
0.00–0.59: Store only. Do not use for Coach or Player.
0.60–0.79: Show in reports. Use cautiously for aggregate analytics only.
0.80–0.89: Eligible for Coach retrieval.
0.90–1.00: Eligible for high-confidence Coach memory and later Player advisory memory.
```

These numbers can be changed after testing.

Confidence should be reduced by:

- Unresolved card names
- Ambiguous card identities
- Unknown event types
- Missing winner
- Missing turn boundaries
- Incomplete log
- Parser warnings
- Unsupported card effects
- Hidden state dependency
- Multiple possible interpretations
- Format/card database mismatch

Confidence should be increased by:

- Exact card name match
- Clear event pattern
- Clear turn/player ownership
- Clear target
- Clear numeric result
- Clear attack/damage/KO relationship
- Clear winner/win condition
- Cross-event consistency

Example high-confidence event:

```text
gehejo evolved Dwebble to Crustle in the Active Spot.
```

Example lower-confidence event:

```text
Leaguewolf drew a card.
```

This is known as a draw event, but the card identity is hidden.

Example ambiguous event:

```text
Leaguewolf played Dunsparce.
```

May require card identity resolution depending on card pool.

---

## Memory Ingestion Stages

Do not feed all parsed data into all memory systems immediately.

Use staged ingestion.

### Stage 1: Raw Archive Only

- Store raw markdown.
- Store metadata.
- No parsed memory usage.

### Stage 2: Structured Parse

- Parse events.
- Resolve cards.
- Show import report.
- No Coach/Player usage yet.

### Stage 3: PostgreSQL Analytics

- Store structured events.
- Compute basic aggregate reports.
- Identify card usage, sequencing, outcomes, failure modes.

### Stage 4: pgvector Snippets

Create state/action/outcome memory snippets.

Examples:

```text
Turn 2: Player evolved Dwebble to Crustle, played Crispin, attached Grass and Darkness Energy, then used Superb Scissors for a Knock Out.
```

```text
Late game: Player repeatedly used draw/search effects and eventually lost by deck-out.
```

```text
Opponent used Clefairy's Follow Me to force Munkidori Active, disrupting Crustle's attack plan.
```

Each snippet should include:

- Source log ID
- Source event IDs
- Cards involved
- Turn number
- Outcome
- Confidence score
- Whether player eventually won
- Whether sequence led to a prize swing, deck-out, KO, etc.

### Stage 5: Neo4j Observed Relationships

Create source-tagged graph relationships.

Possible edge types:

```text
SETS_UP
ENABLES_ATTACK
DISRUPTS
PROTECTS_FROM
RECOVERS
FOLLOWS
FOLLOWED_BY
ASSOCIATED_WITH_WIN
ASSOCIATED_WITH_LOSS
ASSOCIATED_WITH_DECKOUT_RISK
LEADS_TO_KO
LEADS_TO_PRIZE
LEADS_TO_RETREAT
FORCES_SWITCH
STRANDS_ACTIVE
ACCELERATES_ENERGY
```

Examples:

```text
Crispin ENABLES_ATTACK Crustle
Buddy-Buddy Poffin SETS_UP Rellor
Clefairy DISRUPTS Crustle
Battle Cage PROTECTS_FROM Crustle
Night Stretcher RECOVERS Dedenne
Repeated draw/search sequence ASSOCIATED_WITH_DECKOUT_RISK
```

Every edge should include properties:

```text
source = ptcgl_import
games_observed
events_observed
wins_after
losses_after
avg_prize_delta_after
avg_turns_until_ko
confidence
first_seen
last_seen
parser_version
```

### Stage 6: Coach Retrieval

The Coach may use imported memory as advisory evidence during analysis/deck mutation.

Example Coach prompt memory packet:

```text
Observed Play Memory:
- In 14 imported PTCGL logs, Crispin was played before a multi-energy attacker became active within 1 turn. 9 of those sequences led to a prize within 2 turns. Confidence: 0.86.
- In 6 imported logs involving Crustle, forced-switch effects that moved a non-attacker Active delayed Crustle's next attack by at least 1 turn. Confidence: 0.81.
- In 3 imported losses, repeated late-game draw/search effects were associated with deck-out. Confidence: 0.78.
```

The Coach should use this as evidence, not truth.

### Stage 7: AI Player Advisory Retrieval

Only after Coach usage is validated should imported memories be available to the live AI Player.

Player retrieval must be advisory.

The action validator remains authoritative.

Imported memory must not create illegal actions.

The Player prompt should clearly distinguish:

- Current legal actions
- Simulator-derived memory
- Imported observed human memory
- Low-confidence warnings

---

## Coach Integration

Coach integration should happen before Player integration.

Reason:

The Coach already works with aggregate performance and deck mutation.

Imported human logs are more appropriate as strategic evidence than as immediate tactical control at first.

The Coach should be able to ask:

- Which cards are often used together in real games?
- Which cards are setup pieces rather than attackers?
- Which cards appear before prize-taking turns?
- Which cards are linked to deck-out risk?
- Which cards are linked to failed board development?
- Which cards look weak in simulation but valuable in observed play?
- Which cards look strong in simulation but poor in observed play?
- Which observed human sequences does the simulator never discover?
- Which logs suggest a missing or buggy card effect?

Coach prompt additions should be compact.

Do not dump raw logs into the prompt.

Give summarized, filtered, high-confidence evidence.

This must respect existing Coach protections, especially:

- Primary evolution line protection
- Support-line handling
- Regression detection
- Deck rollback
- Coach skip after repeated regressions
- Performance history

Observed Play Memory should not override those safety systems.

---

## Player Integration

Player integration should be delayed.

When eventually added, the Player could retrieve similar state-action-outcome memories at decision time.

Example:

```text
Current situation:
- Player has powered Crustle on Bench.
- Opponent has forced Munkidori Active.
- Legal actions include retreat, attach, pass, play draw supporter.

Relevant Observed Play Memories:
- In similar imported games, players who immediately retreated into the powered attacker recovered tempo and took a prize within 1 turn in 7/10 cases.
- In similar imported games, passing with the non-attacker Active led to delayed prize-taking and eventual loss in 4/6 cases.
```

Important restrictions:

- Retrieval should not exceed prompt budget.
- Only top 3–5 memories should be included.
- Memories must be source-tagged and confidence-scored.
- Do not include low-confidence memories.
- Do not include raw logs unless debugging.
- Do not let imported memories bypass rules/action validation.

---

## Observed Value vs Causal Value

The system must distinguish simple correlation from stronger sequence evidence.

Weak evidence:

```text
Card X appears in many winning games.
```

Stronger evidence:

```text
Card X was played one turn before Card Y became powered and took a prize.
```

Strongest practical evidence from logs:

```text
Specific sequence:
Buddy-Buddy Poffin → bench setup
Crispin → energy acceleration
Evolution into attacker
Attack → KO
Prize taken within 1 turn
Player later won
```

Graph and Coach summaries should prefer sequence-based evidence over simple co-occurrence.

Do not overstate causal claims.

Use language like:

- "associated with"
- "observed before"
- "commonly followed by"
- "linked to"
- "often appears in sequences where"

Avoid language like:

- "causes"
- "guarantees"
- "proves"

unless the evidence is genuinely deterministic within the game rules.

---

## Failure-Mode Tagging

The importer should mine losses aggressively.

Failures are often more valuable than wins.

Possible failure tags:

```text
deckout_loss
stranded_active
missed_attack_turn
orphaned_evolution_line
overcommitted_energy
lost_primary_attacker
no_secondary_attacker
poor_prize_trade
bench_liability
resource_exhaustion
stadium_disruption
late_game_draw_risk
failed_setup
supporter_whiff
search_whiff
retreat_cost_problem
energy_color_mismatch
```

These should be derived conservatively.

Example:

If a player loses by deck-out after repeated draw/search/shuffle effects, tag:

```text
deckout_loss
late_game_draw_risk
resource_exhaustion
```

These failure tags can later be surfaced to the Coach.

Example Coach warning:

```text
Observed logs show this deck shell can lose by deck-out when late-game draw/search effects are overused. Avoid mutations that increase draw-only cards without improving win closure.
```

---

## Human-vs-Simulator Disagreement Reports

This should eventually become a major diagnostic feature.

Create reports that compare imported observed play memory against PokéPrism simulation memory.

Interesting disagreement types:

### Card Looks Weak in Simulation but Strong in Observed Logs

Possible meanings:

- Simulator heuristic is using the card poorly.
- AI Player is missing a sequencing pattern.
- Card effect is implemented incorrectly.
- Card has support value not captured by current metrics.
- Human players are using it in a specific archetype context.

### Card Looks Strong in Simulation but Weak in Observed Logs

Possible meanings:

- Simulator environment is unrealistic.
- Opponent heuristics are too weak against the card.
- Humans counterplay it better.
- The card is win-more.
- The card creates hidden risks such as deck-out or bench liability.

### Human Logs Use a Sequence the Simulator Never Finds

Possible meanings:

- Heuristic Player is too shallow.
- AI Player prompt lacks relevant context.
- Coach does not value the sequence.
- The sequence depends on an effect not yet implemented.

### Imported Logs Reference Cards/Effects Not Implemented

Possible meanings:

- Card pool expansion needs prioritization.
- Effect registry missing support.
- Parser sees real-world usage before simulator can model it.

This report should feed bug-smashing and card implementation priorities.

---

## Privacy / Anonymization

PTCGL logs include user and opponent names.

Raw logs can preserve exact text privately.

Analytics and memory should normalize identities.

Suggested aliases:

```text
self
opponent_001
opponent_002
unknown_player
```

Possible fields:

```text
player_1_name_raw
player_2_name_raw
player_1_alias
player_2_alias
```

Do not use opponent usernames as meaningful graph-memory nodes.

Do not surface opponent names unnecessarily in summaries.

Consider allowing the user to define their own PTCGL username(s), so the importer can label:

```text
self_action
opponent_action
```

This matters because my own decisions and opponent decisions may deserve different weights.

---

## Source Weighting

Not all imported decisions are equally valuable.

Possible source weights:

```text
self_action
opponent_action
unknown_action
tournament_log_future
testing_partner_future
ladder_game
```

Initial version can simply distinguish:

```text
self
opponent
unknown
```

Later, weights could be adjusted:

- My own games may be more relevant to my deck-building goals.
- Opponent actions may reveal common meta behavior.
- Tournament/testing logs may deserve higher weight.
- Weird ladder games may deserve lower weight.

Do not overcomplicate v1, but keep the schema flexible enough.

---

## Format Rotation / Memory Decay

Pokémon TCG formats change.

Old logs may become less relevant after rotation or new set releases.

Imported memories should track:

```text
game_date
import_date
format_label
card_pool_snapshot
regulation_marks_detected
sets_detected
```

If exact format detection is hard, start with import date and detected card set list.

Coach retrieval should eventually prefer:

- Current format
- Recent logs
- Logs involving currently legal cards
- Logs involving the tested deck/archetype

Do not delete old logs.

Use decay or filtering instead.

---

## Prompt Budget Management

Local models have limited context and speed constraints.

Do not pass raw logs into Coach or Player prompts except for debugging.

Memory retrieval should provide compact summaries.

Good:

```text
Observed Play Memory:
- 11 high-confidence imported games show Crispin commonly enabling multi-energy attackers by turn 2–3.
- 4 imported losses with this shell involved late-game deck-out after repeated draw/search effects.
- Forced-switch effects repeatedly disrupted Crustle by pulling Munkidori Active.
```

Bad:

```text
Paste 5 full battle logs into the prompt.
```

Prompt packets should be:

- Short
- Source-tagged
- Confidence-scored
- Outcome-aware
- Relevant to the current deck/matchup/decision
- Limited to top N memories

---

## Exclusion / Do-Not-Learn Mechanism

The UI should allow logs to be excluded from memory.

Reasons:

- Meme deck
- Obvious misplays
- Incomplete log
- Parser failure
- Bugged PTCGL export
- Irrelevant format
- Duplicate variant
- Test file
- Low-quality game
- User simply does not want it used

Suggested memory status values:

```text
active
archived_only
excluded_from_memory
failed_parse
needs_review
```

Excluding a log should not necessarily delete the raw archive.

It should prevent derived memories from being used in Coach/Player retrieval.

---

## Golden-Log Parser Test Suite

Keep a small curated test fixture set in the repo.

Do not store all logs in Git.

Store only representative fixtures.

Suggested fixture categories:

```text
basic_setup.md
known_draws_and_hidden_draws.md
evolution.md
energy_attachment.md
trainer_search.md
stadium_replacement.md
retreat_and_switch.md
attack_damage_ko_prize.md
weakness_damage_breakdown.md
deckout_loss.md
ambiguous_card_name.md
unresolved_card.md
failed_or_incomplete_log.md
zip_import_batch.md
```

Each fixture should have expected parsed output.

This protects the parser from regressions.

---

## Direct Apple Shortcut Upload: Future Feature

Do not implement first unless easy.

Future workflow:

```text
PTCGL export/copy
↓
Apple Shortcut
↓
POST battle log to PokéPrism endpoint
↓
Log appears in Observed Play Memory
```

This could use the same backend upload endpoint.

Potential needs:

- Local network URL
- Optional API token
- Plain text body upload
- Filename generated from timestamp
- Response showing import success/failure

This should be considered later convenience, not core MVP.

---

## MVP Recommendation

Please evaluate this MVP and adjust if needed.

### MVP Scope

1. Docker volume paths for `/data/ptcgl_logs`.
2. Frontend upload page for `.md` and `.zip`.
3. Backend upload endpoint.
4. SHA-256 duplicate detection.
5. Raw markdown archive.
6. Raw log DB record.
7. Parser v1 for high-confidence events.
8. Card mention extraction.
9. Basic card resolution against existing card DB.
10. Unresolved/ambiguous card reporting.
11. Import batch report.
12. Parsed event viewer.
13. Parser fixture tests.
14. No Coach integration yet.
15. No Player integration yet.

### MVP Success Criteria

- Can upload a zip of battle logs.
- Duplicates are skipped.
- Raw logs are preserved.
- Parser extracts major events.
- Import report is visible and accurate.
- Unresolved cards are shown.
- Failed logs are inspectable.
- Reparse path is designed even if not fully implemented.
- No parsed data affects Coach or Player yet.

---

## Phase 2 Recommendation: Analytics and PostgreSQL Memory

After MVP:

1. Store parsed events durably.
2. Add aggregate reports:
   - Most common cards
   - Most common attacks
   - Most common supporters
   - Most common setup sequences
   - KO sources
   - Prize-taking cards
   - Deck-out losses
   - Failure tags
   - Cards associated with wins/losses
3. Add confidence gating.
4. Add include/exclude from memory controls.
5. Add manual card resolution UI.
6. Add reparse support.

No Coach/Player integration yet unless data quality looks good.

---

## Phase 3 Recommendation: Coach-Only Observed Memory

After parser reliability is acceptable:

1. Generate compact observed-play summaries.
2. Feed only high-confidence summaries to Coach.
3. Clearly label them as imported observed human play evidence.
4. Keep existing Coach guardrails authoritative:
   - Primary line protection
   - Support line handling
   - Regression detection
   - Rollback
   - Coach skip logic
5. Run A/B testing:
   - Coach with simulation memory only
   - Coach with simulation + observed play memory
6. Measure:
   - Win rate
   - Regression frequency
   - Bad swaps
   - Primary-line preservation
   - Deck-out losses
   - Stability of mutations
   - Whether Coach explanations improve

---

## Phase 4 Recommendation: pgvector and Neo4j

After Coach-only usage is validated:

1. Create state/action/outcome snippets.
2. Embed snippets with existing embedding infrastructure.
3. Add Neo4j source-tagged observed-play edges.
4. Add graph confidence scoring.
5. Add human-vs-simulator disagreement reports.
6. Add archetype inference.
7. Add failure-mode memory retrieval.

---

## Phase 5 Recommendation: Player Advisory Retrieval

Only after previous phases are stable:

1. Retrieve similar imported state/action/outcome memories at AI Player decision time.
2. Limit to top 3–5 memories.
3. Include only high-confidence memory.
4. Keep action validator authoritative.
5. Never allow imported memory to create illegal actions.
6. Do not include raw logs in Player prompt.
7. Measure whether Player decisions improve.

---

## Archetype Inference

Because logs may not include full decklists, infer archetypes from observed cards.

Examples:

```text
Crustle / Munkidori
Dragapult ex
N's Zoroark
Team Rocket
Lillie / Clefairy engine
```

Archetype inference should be probabilistic.

Fields:

```text
archetype_label
confidence
supporting_cards
supporting_events
```

This helps Coach retrieval:

```text
Observed logs from similar Crustle/Munkidori shells show...
```

Do not require archetype inference in MVP, but design schema so it can be added later.

---

## Replay / Reconstruction Viewer

The parsed log viewer should eventually reconstruct visible state.

Not full game simulation.

Just visible state from logs:

- Active Pokémon
- Bench Pokémon
- Attached known energy
- Stadium
- Discarded cards
- Prize count when visible
- Turn number
- Last attack
- Last KO
- Winner/win condition

This viewer helps debug parser mistakes.

It also helps compare imported logs to simulator-generated event streams.

---

## Required Design Questions for Claude to Answer

Please review and answer these before implementation:

1. Should imported observed events use the existing `match_events` table or a new parallel table?
2. How should imported log data integrate with existing simulation IDs, match IDs, and dashboard APIs?
3. Should raw markdown be stored in PostgreSQL, filesystem, or both?
4. Should large zip imports use Celery from day one?
5. What database migrations are needed?
6. What frontend page structure best fits the current UI?
7. What existing components can be reused?
8. What existing memory APIs should be extended instead of duplicated?
9. How should confidence thresholds be represented?
10. How should unresolved cards be linked to current card DB records?
11. How should ambiguous card versions be handled when only a name appears in PTCGL logs?
12. How should parser versioning and reparse be implemented?
13. How should derived memory be invalidated/rebuilt after reparse?
14. How should Neo4j edges be source-tagged to distinguish imported human logs from simulator data?
15. How should pgvector snippets be generated and retrieved?
16. How should Coach prompts receive observed play memory without bloating context?
17. What should be the first safe Coach-only integration point?
18. What metrics should be used for A/B testing Coach impact?
19. How should Player integration be delayed and protected?
20. What tests are required to prevent parser and memory regressions?
21. What risks does this design introduce?
22. What parts conflict with `PROJECT.md` or existing implementation?
23. What simpler MVP would still preserve the long-term design?

---

## Non-Goals for Initial Implementation

Do not initially implement:

- Direct iCloud integration.
- Direct Apple Shortcut endpoint unless trivial.
- Full game-state reconstruction.
- Full hidden-state inference.
- Fine-tuning.
- Raw-log prompt stuffing.
- Player decision integration.
- Automatic trust in all human decisions.
- Automatic card identity guessing without confidence.
- Silent memory ingestion of low-confidence parses.
- Deleting raw logs after parsing.
- Storing all user battle logs in Git.

---

## Safety / Quality Guardrails

Observed Play Memory must obey these rules:

1. Preserve raw logs exactly.
2. Track parser version.
3. Detect duplicates.
4. Expose import failures.
5. Expose unresolved cards.
6. Expose confidence scores.
7. Allow reparse.
8. Allow exclusion from memory.
9. Source-tag all imported memory.
10. Do not treat human actions as automatically optimal.
11. Do not feed low-confidence data to Coach or Player.
12. Do not bypass the existing action validator.
13. Do not override Coach deck-protection safeguards.
14. Do not bloat LLM prompts with raw logs.
15. Keep implementation compatible with Docker deployment.

---

## Expected Final Deliverable from Claude

Please produce a refined design document that:

1. Confirms whether this design fits PokéPrism.
2. Identifies conflicts with the current architecture.
3. Recommends exact table/model names.
4. Recommends exact API routes.
5. Recommends frontend page/component structure.
6. Recommends Celery vs inline processing.
7. Recommends parser architecture.
8. Recommends card-resolution architecture.
9. Recommends memory-ingestion stages.
10. Recommends Coach integration strategy.
11. Recommends when/how Player integration should happen.
12. Identifies missing edge cases.
13. Identifies test coverage required.
14. Produces an implementation-phase plan that can later be converted into Copilot prompts.
15. Does not write production code yet.

The output should be comprehensive enough that I can later ask Claude to produce phase-by-phase GitHub Copilot prompts for implementation.
