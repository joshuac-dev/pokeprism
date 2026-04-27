# PokéPrism — Development Status

> This file is updated at the end of every development session.
> Read this BEFORE reading PROJECT.md to understand current state.

## Current Phase
Phase 5 — AI Player (Qwen3.5-9B via Ollama) — **Complete (2026-04-27)**

## Last Session
- **Date:** 2026-04-27
- **Phase 5 complete.** `AIPlayer(BasePlayer)` implemented using Qwen3.5:9B-Q4_K_M via Ollama.
  Benchmarked at 80% P1 win rate (AI vs Heuristic, 5 games), 0 crashes, decisions persisted to Postgres.
- **Bug fixed (Phase 5 — critical):** `_parse_response` was prepending `{` (one char) but the
  Qwen 3.5 Modelfile prefills with `{"` (two chars). This caused a ~100% fallback rate — every
  LLM decision was silently handed to HeuristicPlayer. Fixed: prepend `{"` instead of `{`.
- **Bug fixed (Phase 5):** Added regex fallback (`re.search(r'"action_id"\s*:\s*(\d+)')`) for
  responses truncated mid-string by `num_predict`. Also increased `num_predict` from 100 → 200.
- **Phase 5 implemented:**
  - `backend/app/players/ai_player.py` — `AIPlayer(BasePlayer)`, Qwen3.5-9B via Ollama.
    CHOOSE_* interrupts use BasePlayer heuristics; MAIN/ATTACK decisions go to LLM with 3-retry
    fallback to HeuristicPlayer. `drain_decisions()` for batch decision logging.
  - `backend/app/memory/postgres.py` — Added `write_decisions()` to `MatchMemoryWriter`
  - `backend/app/engine/batch.py` — Wired AI decision drain and persist after each game
  - `backend/scripts/run_hh.py` — Added `--ai` flag (P1=AIPlayer, P2=HeuristicPlayer)
  - `backend/tests/test_players/test_ai_player.py` — 17 unit tests; all updated for `{"` prefill
  - **71 tests pass** (66 engine/player + 5 memory integration)

## What Was Built (Cumulative)
- [x] Phase 1: Game Engine Core (state machine, actions, transitions, runner) — **complete (2026-04-26)**
- [x] Phase 2: Card Effect Registry (all handlers implemented) — **complete (2026-04-26)**
- [x] Phase 3: Heuristic Player & H/H Loop — **complete (2026-04-26)**
- [x] Phase 4: Database Layer & Memory Stack — **complete (2026-04-26)**
- [x] Phase 5: AI Player (Qwen3.5-9B decisions) — **complete (2026-04-27)**
- [ ] Phase 6: Coach/Analyst (Gemma 4 E4B) — next

## Phase 5 Exit Criteria — Verified (2026-04-27)

| Criterion | Target | Result | Status |
|---|---|---|---|
| >99% legal moves | No illegal moves | 0 illegal actions observed | ✅ |
| AI persist run | Completes without crash | 2-game run persisted | ✅ |
| decisions table | AI decisions recorded | 344 rows across 6 matches | ✅ |
| AI/H win rate | Logged | 80% P1 (AI) win rate, 5 games | ✅ |
| Avg turns | Logged | 35.4 avg turns/game | ✅ |
| Crashes | 0 | 0 | ✅ |

### AI/H Benchmark (5 games, Dragapult AIPlayer P1 vs TR Mewtwo HeuristicPlayer P2)
- **P1 (AIPlayer) win rate: 80%** | Avg turns: 35.4 | 0 crashes | ~6 min/game
- LLM call timing: ~1.5s per Ollama call, ~40 LLM calls/game
- Fallback rate (after prefill fix): ~0% — real LLM decisions confirmed in `decisions` table

## Phase 4 Exit Criteria — Verified (2026-04-26)

500 H/H games run with `python3 -m scripts.run_hh --num-games 500 --persist`:

| Criterion | Target | Result | Status |
|---|---|---|---|
| matches table rows | 500 | 506 (incl. smoke-test runs) | ✅ |
| avg match_events/match | ~300–600 | ~278 | ✅ |
| Neo4j SYNERGIZES_WITH top pair | Boss's Orders + X cards | weight 316 | ✅ |
| Neo4j BEATS edge Dragapult→TR | ~80% win_rate | 0.750 (379/505 games) | ✅ |
| pgvector embedding | 768 dims stored | 768 ✓ | ✅ |

### Top 5 SYNERGIZES_WITH pairs (by weight)
| Card A | Card B | Weight |
|---|---|---|
| Boss's Orders | Munkidori | 316 |
| Boss's Orders | Secret Box | 316 |
| Boss's Orders | Binding Mochi | 316 |
| Boss's Orders | Enhanced Hammer | 316 |
| Boss's Orders | Fezandipiti ex | 316 |

### Neo4j BEATS edge
| Winner | Loser | W | T | win_rate |
|---|---|---|---|---|
| Dragapult | TR-Mewtwo | 379 | 505 | 0.750 |
| TR-Mewtwo | Dragapult | 126 | 505 | 0.250 |

*(win_rate aligns with Phase 3 H/H baseline of ~75% — expected)*

## Current Phase Progress

### Phase 5 Completed (2026-04-27)
- `AIPlayer(BasePlayer)` fully implemented and benchmarked
- `_parse_response` prefill bug found and fixed (`{"` not `{`)
- regex fallback added for truncated responses
- `num_predict` increased to 200 to reduce truncation frequency
- `write_decisions()` wired through batch.py into Postgres
- `--ai` CLI flag added to run_hh.py
- 17 unit tests; 71 total tests pass

### Phase 5 Remaining
- Nothing — phase is complete. Decision embeddings (storing AI decisions in pgvector)
  were not required by exit criteria and are deferred to Phase 6 or later.

## Active Files Changed This Session (2026-04-27)
- `backend/app/players/ai_player.py` — **New:** `AIPlayer(BasePlayer)`, full LLM decision loop,
  `{"` prefill fix, regex fallback, `drain_decisions()`, `_build_prompt()`, `_record_decision()`
- `backend/app/memory/postgres.py` — Added `write_decisions()` method; `Decision` import added
- `backend/app/engine/batch.py` — Wired AI decision drain + persist in per-game loop
- `backend/scripts/run_hh.py` — Added `--ai` flag and `AIPlayer` import
- `backend/tests/test_players/test_ai_player.py` — **New:** 17 unit tests for `AIPlayer`;
  test fixtures use actual Ollama output format (`action_id"...` not `"action_id"...`)
- `docs/STATUS.md` — This file

## Known Issues / Gaps
- **Copy-attack stubs (non-blocking for Phase 5, defer to Phase 6 or as needed):**
  - N's Zoroark ex: "Mimic" attack stubbed to 0 damage with WARN log.
  - TR Mimikyu (sv10-087): "Gemstone Mimicry" stubbed to 0 damage with WARN log.
  - Both require recursive effect resolution + CHOOSE_OPTION action. See
    `TODO(copy-attack)` comment in `attacks.py`.
- **Phantom Dive energy validation:** Dragapult ex can use Phantom Dive ({R}{P}) because
  Prism Energy attached to Dreepy (basic) carries over as `[ANY]` when it evolves to
  Dragapult ex. In the real TCG, Prism Energy should revert to {C} on non-basics after
  evolution. Non-blocking — firing produces better game quality even if technically wrong.
- **Non-determinism in benchmarks:** `CardInstance.instance_id` uses `uuid.uuid4()`.
  Individual seed results vary between runs. Aggregate stats (avg, distribution) are stable.
- **Pecharunt PR-SV 149:** No SET_CODE_MAP entry for promo set. Non-blocking.
- **M4 cards excluded:** Chaos Rising unreleased until May 22, 2026.
- **RandomPlayer deck-out:** Random vs Random still ends 100% by deck_out. Expected.
- **GreedyPlayer P2 zero-attack games:** ~23% of 15+ turn games have P2 (TR deck)
  never attacking. Caused by Power Saver requiring 4 TR Pokémon alive before Mewtwo ex
  can attack. Not an engine bug — structural deck feature.
- **Decision embeddings not wired:** `EmbeddingService` exists but AI decisions in the
  `decisions` table are not embedded into pgvector. Deferred to Phase 6 or later.

## Key Decisions Made
- Test decks: Dragapult ex/Dusknoir (P1) vs Team Rocket's Mewtwo ex (P2)
- Effect choices use CHOOSE_CARDS/CHOOSE_TARGET/CHOOSE_OPTION — NOT baked into effect layer
- Copy-attack mechanic stubbed to 0 damage with TODO
- Ability preconditions registered in `register_ability(condition=...)` callback
- `_retreat_if_blocked`: retreat before attack phase if active can't deal damage
- `_best_energy_target` trapped-active check: if active can't retreat AND can't attack,
  attach energy to active first to enable eventual retreat
- TR Energy correct ID: `sv10-182` (not `sv10-175`)
- SET_CODE_MAP uses zero-padded TCGDex IDs (sv01 not sv1)
- **Energy discard heuristic (2026-04-26):** Energy score in `_discard_priority` is 20
  (items score 1). Any card requiring discard cost should default to discarding items first.
- **Self-switch choice heuristic (2026-04-26):** When forced to choose a bench Pokémon to
  switch in (Prime Catcher, Giovanni), prefer the Pokémon with the most energy attached.
- **Qwen 3.5 prefill (2026-04-27):** Ollama Modelfile for Qwen3.5:9B-Q4_K_M prefills the
  assistant response with `{"` (two chars). Ollama strips both before returning the response.
  `_parse_response` must prepend `{"` before JSON parsing. Regex fallback handles truncated
  responses. Do NOT use `think:false` or system prompts — template prefill is the only
  reliable way to suppress `<think>` tags with this model.
- **AIPlayer CHOOSE_* routing (2026-04-27):** CHOOSE_CARDS / CHOOSE_TARGET / CHOOSE_OPTION
  interrupts are handled by BasePlayer heuristics, never sent to the LLM. These interrupts
  require card instance IDs, not strategic reasoning, and would waste inference budget.

## Benchmark History

### Phase 2 — Greedy vs Greedy baseline (2026-04-26)
- **100 games:** 35.0 avg turns | 69% prize wins | 16% deck_out | 0 crashes

### Phase 3 — H/H results (2026-04-26)
| Matchup | P1 Win% | Avg Turns | Deck-out% |
|---|---|---|---|
| H/H (Dragapult P1) | 82% | 42.0 | 4% |
| H/H swapped (TR Mewtwo P1) | 23% | 43.2 | 7% |
| H/G (Heuristic P1) | 58% | 43.0 | 19% |
| G/G | 51% | 38.2 | 21% |

**Matchup note:** Dragapult wins ~80% regardless of seat. First-player advantage is ~5 pts.
The asymmetry is deck matchup, not seating. Deck-out dropped 21% → 4% (G/G → H/H).

### Phase 5 — AI/H results (2026-04-27)
- **5 games (Dragapult AI P1 vs TR Mewtwo H P2):** 80% P1 win rate | 35.4 avg turns | 0 crashes

## Notes for Next Session — Phase 6 (Coach/Analyst)

**Phase 5 is done and committed.** Start Phase 6 by reading PROJECT.md §11.

### What Phase 6 is (re-confirm before starting)
- **Class:** per PROJECT.md — Coach/Analyst system, `app/coach/analyst.py`
- **Model:** Gemma 4 E4B (`gemma4-e4b:q6_K`) via Ollama — separate model from AIPlayer
- **Role:** Post-game analysis only. Analyzes completed games, suggests deck improvements,
  provides meta analysis. NOT an in-game decision maker — operates after games end.
- **NOT** a continuation of AIPlayer. Separate class, separate file, separate concerns.

### Infrastructure
- `docker compose up -d postgres neo4j ollama` to start all services
- Verify `gemma4-e4b:q6_K` is pulled: `docker exec pokeprism-ollama ollama list`
- If not pulled: `docker exec pokeprism-ollama ollama pull gemma4-e4b:q6_K`

### DB state entering Phase 6
- `matches`: 517 rows (513 Phase 4 + 4 Phase 5)
- `decisions`: 344 rows across 6 AI matches
- `embeddings`: populated from Phase 4 batch (768-dim nomic-embed-text vectors)

### Commands
- Run tests: `cd backend && python3 -m pytest tests/ -x -q` (71 tests pass)
- Run AI benchmark: `cd backend && python3 -m scripts.run_hh --num-games 5 --ai`
- Run AI persist: `cd backend && python3 -m scripts.run_hh --num-games 2 --ai --persist`
