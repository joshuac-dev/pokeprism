# PokéPrism Changelog

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
