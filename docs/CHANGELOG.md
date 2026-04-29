# PokéPrism Changelog

## Phase 13 — Polish, Hardening & Scheduling (2026-04-28/29)

### Summary
Full production hardening and polish across coach intelligence, the simulation engine, and the live console UI. The Coach was destroying decks by removing primary attacker lines (e.g., stripping all Dreepy/Drakloak from a Dragapult ex deck, causing continuous win rate decline). Three coach intelligence fixes were implemented: tiered evolution line protection, win rate regression detection with automatic deck rollback, and full performance history in the Coach prompt. Six UI/console fixes brought the console from showing generic event type names to rich formatted lines with card names, damage, and win conditions. Earlier in the phase (Groups A–G), backend hardening, copy-attack engine, Decision Map, Docker Compose, light mode polish, and Makefile infrastructure were all implemented.

### Coach Intelligence Fixes (1A/1B/1C)

**Fix 1A — Evolution Line Tiered Protection**
- `identify_primary_line()` queries `match_events` for the top damage-dealing/prize-taking/active-turns Pokémon
- PRIMARY line: hard-protected — Coach cannot remove any card in the attacker's evolution chain
- SUPPORT lines: swappable only as complete lines (no orphaned pre-evolutions)
- Tier list injected into Coach prompt each round: `PRIMARY (protected): Dreepy → Drakloak → Dragapult ex`

**Fix 1B — Win Rate Regression Detection**
- Consecutive regression counter: warn on 1st regression → auto-revert deck on 2nd → skip Coach entirely on 3rd
- `best_deck_snapshot` JSONB column added to `simulations` table (Alembic migration `c3e91f7a5b22`)
- `deck_reverted` and `coach_skipped` lifecycle events published to WebSocket and displayed in console

**Fix 1C — Coach Prompt Improvement**
- Full win rate history across all previous rounds in each prompt
- Regression warning with explicit stability instruction ("prioritize stability, make fewer changes")
- Tiered card list (PRIMARY / SUPPORT / UNPROTECTED) in every prompt

### UI/Console Fixes (2A–3B)

**Fix 2A — Rounds to Confirm**: Field existed in code; stale Docker container rebuilt and redeployed  
**Fix 2B — Console card names**: All event types now show card names:
- `T9 [p2] ⚔ Phantom Dive (Dragapult ex) → 120 dmg` (attack_damage)
- `T13 [p2] ★ KO — Dwebble (by Dragapult ex)` (ko)
- `T12 [p1] ↑ Dreepy → Drakloak` (evolve)
- `T4 [p1] ▷ Iono` (play_supporter)
- `T4 [p1] ↔ Retreat Dreepy → Dragapult ex` (retreat)
- New handlers: attack_no_damage, play_stadium, play_tool, switch_active, deck_reverted, coach_skipped
- attack_declared suppressed (redundant with attack_damage); noise events skipped

**Fix 2C — Win condition**: `═══ Match 3 complete — P2 wins (prizes) ═══`  
**Fix 2D — Clickable events**: EventDetail overlay on click; shows event data key/values + AI reasoning for ai_h/ai_ai modes  
**Fix 2E — Deck naming**: Gemma4 needs ~60s for generation; timeout raised 30s → 120s  
**Fix 3A/3B — Match separator and retreat display**: Incorporated in 2C and 2B changes respectively  

### Backend Changes (Groups A–G, earlier in phase)
- **Group A**: DB pool pre-ping/recycle, Ollama retry (3× exponential backoff), `/health` endpoint (7 service checks), WebSocket auto-reconnect, Celery Beat nightly schedule
- **Group B**: Copy-attack engine — `_night_joker` (N's Zoroark ex) and `_gemstone_mimicry` (TR Mimikyu) with depth-limit-1 cycle guard
- **Group C**: `/api/simulations/{id}/decision-graph` endpoint; DecisionMap.tsx D3 two-line labels with action-type colors
- **Group D**: `pgvector>=0.3` in pyproject.toml; production-safe Dockerfile CMD; nginx lazy upstream resolution
- **Group E**: Light mode polish across all pages and dashboard tiles
- **Group F**: Makefile targets; `.dockerignore` files
- **Group G (secondary issues A–E)**: PTCGL deck text parsing (3 format variants), energy type mapping, deck_locked enforcement, target_consecutive_rounds early-stop, PTCGL test coverage

### Key Files Created
- `backend/alembic/versions/c3e91f7a5b22_add_best_deck_snapshot.py`
- `frontend/src/components/simulation/EventDetail.tsx`

### Key Files Modified
- `backend/app/coach/analyst.py` — tiered protection, regression detection, performance history
- `backend/app/coach/prompts.py` — `{performance_history}` variable, tier enforcement instructions
- `backend/app/tasks/simulation.py` — regression state machine, deck_reverted/coach_skipped events
- `backend/app/db/models.py` — `best_deck_snapshot` JSONB column on Simulation
- `backend/app/api/simulations.py` — Gemma timeout 120s, decisions endpoint query filters
- `frontend/src/components/simulation/LiveConsole.tsx` — full rewrite of fmt() with all event handlers
- `frontend/src/pages/SimulationLive.tsx` — EventDetail wiring
- `backend/tests/test_coach/test_analyst.py` — full rewrite with 1A/1B/1C coverage
- `backend/tests/test_tasks/test_simulation_task.py` — TestCheckRegression class

### Test Results
- **215 tests pass** (was 184 entering Phase 13; +31 new tests for coach intelligence)
- `npm run build`: 0 TypeScript errors

---

## Phase 10 — Frontend: Reporting Dashboard (2026-04-28)

### Summary
Built the full post-simulation reporting dashboard at `/dashboard/:id`. 12 tiles covering
summary stats, win rate visualisations, per-opponent breakdowns, prize race curves, AI
decision graph, card swap heatmap, and mutation diff log. Added two backend endpoints to
serve match-level data (prize_progression column is always NULL — prize data derived from
match_events instead). QA found and fixed three bugs: prize race flat lines (deck-out sims
have no KO events), Decision Map gating on unreliable game_mode field, and raw tcgdex IDs
in mutation/swap tiles.

### Key Files Created
- `frontend/src/types/dashboard.ts`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/components/dashboard/SummaryCards.tsx`
- `frontend/src/components/dashboard/WinRateDonut.tsx`
- `frontend/src/components/dashboard/WinRateProgress.tsx`
- `frontend/src/components/dashboard/OpponentWinRateBar.tsx`
- `frontend/src/components/dashboard/MatchupMatrix.tsx`
- `frontend/src/components/dashboard/WinRateDistribution.tsx`
- `frontend/src/components/dashboard/PrizeRaceGraph.tsx`
- `frontend/src/components/dashboard/DecisionMap.tsx` (D3 force graph)
- `frontend/src/components/dashboard/CardSwapHeatMap.tsx`
- `frontend/src/components/dashboard/MutationDiffLog.tsx` (TanStack Table)

### Key Files Modified
- `backend/app/api/simulations.py` — GET /{id}/matches, GET /{id}/prize-race, card name resolution in mutations endpoint
- `backend/tests/test_api/test_simulations.py` — +10 tests
- `frontend/src/api/simulations.ts` — 4 new API functions
- `frontend/src/pages/SimulationLive.tsx` — "View Report" button
- `frontend/package.json` — recharts, d3, @types/d3, @tanstack/react-table

### Test Results
- **153 tests pass** (was 145; +8 backend: TestGetSimulationMatches×4, TestGetSimulationPrizeRace×4)
- `npm run build`: 0 TypeScript errors

---

## Phase 9 — Frontend: Live Console & Match Viewer (2026-04-29)

### Summary
Built the full SimulationLive page with xterm.js console for event streaming and replay.
Added three backend endpoints (buffered event history, AI decision log, cancel). Implemented
event normalisation to bridge the WS (`event` field) vs REST (`event_type` field) shape
mismatch. H/H simulations (which complete before the browser subscribes) now load their full
event history on page mount via GET /events. Console supports "Load earlier events" for
large runs (>500 events). Cancel sets DB status; the Celery task polls and stops at the
next round boundary.

### Key Files Created
- `backend/` — GET /api/simulations/:id/events, GET /decisions, POST /cancel (in simulations.py)
- `frontend/src/types/simulation.ts` — shared TS types + `normaliseEvent()`
- `frontend/src/components/simulation/LiveConsole.tsx` — xterm.js terminal with color-coded events
- `frontend/src/components/simulation/SimulationStatus.tsx` — status + round progress + cancel button
- `frontend/src/components/simulation/DeckChangesTile.tsx` — deck swap history with win-rate deltas
- `frontend/src/components/simulation/DecisionDetail.tsx` — AI decisions slide-over panel

### Key Files Modified
- `backend/app/api/simulations.py` — added 3 endpoints, redis/Decision/MatchEvent imports
- `backend/app/tasks/simulation.py` — cancellation check at start of each round
- `frontend/src/api/simulations.ts` — getSimulationEvents, getSimulationDecisions, cancelSimulation
- `frontend/src/stores/simulationStore.ts` — Phase 9 state (prependEvents, mutations, etc.)
- `frontend/src/hooks/useSimulation.ts` — init fetch + loadEarlierEvents + WS mutation tracking
- `frontend/src/pages/SimulationLive.tsx` — full page (replaces Phase 8 stub)

### Test Results
- **145 tests pass** (was 135; +10: TestGetSimulationEvents×4, TestGetSimulationDecisions×2, TestCancelSimulation×4)
- `npm run build`: 0 TypeScript errors, 1627 modules

---

## Phase 8 — Frontend: Core Layout & Simulation Setup (2026-04-27/29)

### Summary
Built the complete React/Vite/TypeScript frontend from scratch. Dark-mode-first design
(slate-950 palette, electric blue accent). Full routing, layout components, and Simulation
Setup page with deck paste/parse, opponent deck management, excluded-cards chip UI, and
POST /api/simulations submit flow. Backend cards API replaced 501 stub with real pg_trgm
search. Three bugs found and fixed during visual QA: excluded-cards dropdown wiring,
500 on form submit (deck parser format mismatch), and dark/light toggle not applying to `<html>`.

### Key Files Created
- `frontend/` — all 36 source files (config, components, pages, stores, hooks, utils)
- `backend/app/api/cards.py` — pg_trgm search, paginated list, detail endpoints
- `backend/tests/test_api/test_cards.py` — 9 tests

### Test Results
- **135 tests pass** entering Phase 9 (was 126 after Phase 7)
- `npm run build`: 0 TypeScript errors, 1627 modules (post-Phase-9 xterm install)
- Visual QA: all 7 checklist items pass (2026-04-29)

---

## Phase 5 — AI Player (2026-04-27)

### Summary
Implemented `AIPlayer(BasePlayer)` backed by Qwen3.5:9B-Q4_K_M via Ollama for in-game
decisions. Discovered and fixed a critical parse bug: the Qwen 3.5 Modelfile prefills
with `{"` (two chars), not `{` — causing a ~100% silent fallback rate to HeuristicPlayer.
Added regex fallback for responses truncated by `num_predict` and increased `num_predict`
to 200. Wired AI decision persistence through `batch.py` into the `decisions` Postgres table.

### Key Files Created
- `backend/app/players/ai_player.py` — Full AIPlayer implementation (~240 lines)
- `backend/tests/test_players/test_ai_player.py` — 17 unit tests

### Key Files Modified
- `backend/app/memory/postgres.py` — Added `write_decisions()` method
- `backend/app/engine/batch.py` — AI decision drain + persist wiring
- `backend/scripts/run_hh.py` — Added `--ai` flag

### Test Results
- **71 tests pass** (was 66; +5 net after updating 2 old prefill tests)
- AI/H benchmark (5 games): 80% P1 win rate | 35.4 avg turns | 0 crashes | ~6 min/game
- LLM fallback rate after fix: ~0%

### Bugs Fixed
- `_parse_response`: prepend `{"` not `{` (Qwen 3.5 Modelfile strips two chars, not one)
- `_parse_response`: regex fallback for mid-string truncation when `num_predict` is hit
- `num_predict`: increased 100 → 200 to reduce truncation frequency

---

## Phase 4 — Database Layer & Memory Stack (2026-04-26)

### Summary
Built the full Postgres + pgvector + Neo4j memory pipeline. Ran 500 H/H games end-to-end
through the pipeline and verified all 5 exit criteria. `MatchMemoryWriter` persists match
records, events (chunked insert), card/deck references, and round metadata. `GraphMemoryWriter`
maintains SYNERGIZES_WITH (co-occurrence weighted) and BEATS (win-rate) edges in Neo4j.
`EmbeddingService` stores 768-dim game-state vectors via nomic-embed-text.

### Key Files Created
- `backend/app/db/models.py` — SQLAlchemy ORM (12 tables, `Vector(768)`)
- `backend/app/db/session.py` — Async engine + `AsyncSessionLocal`
- `backend/app/db/graph.py` — Neo4j driver singleton + `ensure_constraints()`
- `backend/app/memory/postgres.py` — `MatchMemoryWriter`
- `backend/app/memory/graph.py` — `GraphMemoryWriter`
- `backend/app/memory/embeddings.py` — `EmbeddingService`
- `backend/alembic/` — Alembic async migration setup + initial migration
- `backend/tests/test_memory/` — 5 integration tests

### Key Files Modified
- `backend/app/engine/batch.py` — `simulation_id`, `persist` params + memory pipeline wiring
- `backend/scripts/run_hh.py` — `--persist` flag
- `backend/app/config.py` — `env_file = [".env", "../.env"]`

### Test Results
- **54 tests pass** (49 engine/player + 5 memory integration)
- 500-game pipeline: 506 matches, ~278 events/match, BEATS edge 0.750, embedding 768 ✓

---

## Phase 3 — Heuristic Player & H/H Simulation Loop (2026-04-26)

### Summary
Built `HeuristicPlayer(BasePlayer)` implementing the 8-step priority chain from Appendix I.
Extracted `BasePlayer` with shared helpers (`_find_action`, `_choose_target`, `_best_energy_target`,
`_discard_priority`, etc.) so all player types share common logic. Added `run_hh_batch()` batch
runner and `run_hh.py` CLI script with `--swap` flag for matchup asymmetry analysis.

### Key Files Created
- `backend/app/players/heuristic.py` — `HeuristicPlayer(BasePlayer)`
- `backend/app/engine/batch.py` — `run_hh_batch()` + `BatchResult`
- `backend/scripts/run_hh.py` — CLI benchmark runner
- `backend/tests/test_players/test_heuristic.py` — 7 HeuristicPlayer tests

### Key Files Modified
- `backend/app/players/base.py` — Extracted `BasePlayer`; GreedyPlayer becomes thin subclass

### Test Results
- **49 tests pass**
- H/H (100 games): 82% P1 win rate | 42.0 avg turns | 4% deck-out
- H/H swapped: TR Mewtwo P1 wins 23% — Dragapult asymmetry confirmed, not first-player advantage

---

## Phase 1 — Game Engine Core (2026-04-26)

### What Was Built
- Pure-Python state machine covering the full Pokémon TCG turn structure:
  DRAW → MAIN (attach, evolve, play trainers, abilities) → ATTACK → KO aftermath
- `GameState` dataclass with `PlayerState`, `CardInstance`, `Phase` enum
- `ActionValidator`: 14 rules enforced, including first-turn attack ban, supporter 
  limit, energy-attachment limit, same-turn evolution ban, ex prize award
- `MatchRunner`: drives games to completion, handles forced bench promotion after KO, 
  deck-out and no-bench detection, prize-taking
- `EffectRegistry`: `_default_damage()` handles fixed-damage attacks; `×`-multiplier 
  attacks correctly yield 0 base damage (Phase 2 effect handlers will supply real values)
- `CardListLoader` + `CardRegistry`: loads 157 cards from live TCGDex fixtures; 
  SET_CODE_MAP with 13 corrected IDs and 6 ME-era sets
- `RandomPlayer` and `GreedyPlayer` as game-simulation baselines
- 157 live TCGDex fixture files captured under `backend/tests/fixtures/cards/`
- 42 unit tests all passing

### Key Files Created
- `backend/app/engine/state.py`
- `backend/app/engine/actions.py`
- `backend/app/engine/transitions.py`
- `backend/app/engine/runner.py`
- `backend/app/engine/rules.py`
- `backend/app/engine/effects/registry.py`
- `backend/app/engine/effects/base.py`
- `backend/app/cards/loader.py`
- `backend/app/cards/models.py`
- `backend/app/cards/registry.py`
- `backend/app/cards/tcgdex.py`
- `backend/app/players/base.py`
- `backend/tests/` (42 tests across 6 test files)
- `backend/tests/fixtures/cards/*.json` (157 live fixtures)

### Phase 1 Baseline Metrics
- **Greedy vs Greedy (100 games):** avg 53.9 turns, prizes=74% / no_bench=14% / 
  deck_out=12%, 26.2 attacks/game, 4.5 KOs/game, 0 crashes
- **Random vs Random (100 games):** avg 94.6 turns, deck_out=100%, 0 crashes

### Bugs Fixed During Verification
- `loader.py`: Prism Energy wrongly classified as "Basic" — fixed subcategory logic
- `players/base.py`: GreedyPlayer RETREAT priority was #7 (before PASS #8), 
  causing energy to be burned on retreat every turn before attacking — fixed to #9
- SET_CODE_MAP: 13 blueprint entries used wrong format/numbering (sv1 vs sv01, 
  wrong numbers for SSP/PRE/JTG/DRI) — all corrected to match actual TCGDex IDs
