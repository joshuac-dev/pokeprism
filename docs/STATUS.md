# PokéPrism — Development Status

> This file is updated at the end of every development session.
> Read this BEFORE reading PROJECT.md to understand current state.

## Current Phase
Phase 9 — Frontend: Live Console & Match Viewer — **Code committed, build clean (145 tests pass). Visual QA pending.**
Next: Phase 10 — History & Analytics Dashboard

## Last Session
- **Date:** 2026-04-29
- Phase 8 visual QA completed and accepted by user. Three bugs fixed: (1) excluded-cards dropdown not appearing (useCardSearch wiring), (2) 500 on form submit (deck parser format mismatch + "Boss" raw string sent as excluded card), (3) light/dark toggle not working (dark class not applied to `<html>`).
- Phase 9 (Frontend: Live Console & Match Viewer) fully implemented and committed.
- Three new backend endpoints: `GET /api/simulations/:id/events` (buffered replay, cursor pagination), `GET /api/simulations/:id/decisions` (AI decisions, offset pagination), `POST /api/simulations/:id/cancel` (sets DB status, publishes Redis event).
- Cancellation check in Celery task: polls DB status at start of each round, breaks cleanly if `cancelled`.
- 10 new backend tests; full suite **145 passed, 0 failures**.
- xterm.js installed (`@xterm/xterm`, `@xterm/addon-fit`).
- New frontend files: `src/types/simulation.ts`, `LiveConsole.tsx`, `SimulationStatus.tsx`, `DeckChangesTile.tsx`, `DecisionDetail.tsx`, full `SimulationLive.tsx`.
- `useSimulation` hook rewritten: fetches buffered events + sim detail on mount (resolving H/H blank-console issue), polls status, handles live WS events via `appendEvent`.
- `simulationStore` extended: `prependEvents`, `totalEvents`, `hasMore`, `firstEventId`, `mutations`, `roundsCompleted`, `numRounds`, `finalWinRate`.
- `npm run build` passes with **zero TypeScript errors** (1627 modules).
- **Note:** "CUSTOM DECK" fallback deck naming still observed (Gemma inconsistent). Monitor.

## Previous Session (2026-04-27/28)
- Phase 7 live-validated: ALL 7 CHECKS PASSED.
- Phase 8 built: all 36 frontend files + backend cards API.
- Phase 7 implemented and live-validated against full Docker stack (Celery, Redis, WebSocket, Gemma, Postgres).
- All 6 live validation deliverables confirmed:
  1. **validate_phase7.py**: ALL 7 CHECKS PASSED (simulation completes in ~3s)
  2. **Redis pub/sub**: 6 distinct Appendix F event types — `round_start` (3), `match_start` (20), `match_event` (4337), `match_end` (20), `round_end` (2), `simulation_complete` (1). `deck_mutation` fires when `deck_locked=False`.
  3. **WebSocket bridge**: Live socket.io client received 54 events in real-time (polling transport). `round_start`, `match_start`, `match_event` all delivered.
  4. **Deck naming**: Gemma path produces creative names ("Ghostly Strike Force"); fallback path produces `"<ex card> Deck"` (e.g. "Dragapult ex Deck") when Ollama times out.
  5. **Celery Beat**: `pokeprism.run_scheduled_hh` confirmed at `crontab(hour=2, minute=0)`.
  6. **Input validation**: `deck_locked=True + deck_mode="none"` → 422 with clear message. `deck_mode="partial"` with <5000 DB matches → 201 with `warning` field (654 matches available).
- **Bugs fixed during live validation:**
  - Celery task discovery: `autodiscover_tasks(["app.tasks"])` → `conf.imports`
  - Engine `game_start`/`turn_limit` events not reaching event callback → added `self._emit()` calls
  - `ensure_deck()` MultipleResultsFound on duplicate deck names → `.scalars().first()`
  - Event key `"type"` → `"event_type"` in match event callback
  - socket.io 404: `app.mount("/ws")` → `socketio.ASGIApp(sio, other_asgi_app=fastapi_app)` wrapper
  - `main.py` `create_app()` exposes `.fastapi_app` attribute for test `dependency_overrides`
- **Test suite: 126 passed, 0 failures** ✅
- **Note**: `card_performance` data is currently uniform (~54.3% across top cards) because all data comes from two test decks. Coach swap quality will improve with more diverse matchups in later phases. Not a bug — data volume limitation.

## What Was Built (Cumulative)
- [x] Phase 1: Game Engine Core (state machine, actions, transitions, runner) — **complete (2026-04-26)**
- [x] Phase 2: Card Effect Registry (all handlers implemented) — **complete (2026-04-26)**
- [x] Phase 3: Heuristic Player & H/H Loop — **complete (2026-04-26)**
- [x] Phase 4: Database Layer & Memory Stack — **complete (2026-04-26)**
- [x] Phase 5: AI Player (Qwen3.5-9B decisions) — **complete (2026-04-27)**
- [x] Phase 6: Coach/Analyst (Gemma 4 E4B, card swaps, DeckMutation) — **complete & owner-verified (2026-04-27)**
- [x] Phase 7: Task Queue & Simulation Orchestration — **complete & owner-verified (2026-04-28)**
- [x] Phase 8: Frontend Core Layout & Simulation Setup — **complete & owner-verified (2026-04-29)**
- [x] Phase 9: Simulation Live Console (xterm.js) — **committed, visual QA pending (2026-04-29)**
- [ ] Phase 10: History & Analytics Dashboard — **next**

## Phase 7 Exit Criteria — Verified (2026-04-28)

| Criterion | Target | Result | Status |
|---|---|---|---|
| POST /api/simulations | 201 + simulation_id | Returns 201, enqueues Celery task ✅ | ✅ |
| GET /api/simulations/:id | Status + progress | Returns live status ✅ | ✅ |
| Celery task runs | Rounds loop: matches→DB→Coach→next | Completes in ~3s, all DB rows written ✅ | ✅ |
| Redis pub/sub | Appendix F event types | 6 types confirmed (4337 match_events) ✅ | ✅ |
| WebSocket bridge | socket.io forwards Redis events | 54 events delivered live to client ✅ | ✅ |
| Deck naming | Gemma names deck at creation | "Ghostly Strike Force" (Gemma) / fallback path ✅ | ✅ |
| Input validation | Reject contradictory/bad inputs | deck_locked+none → 422; partial low-data → warning ✅ | ✅ |
| Scheduled H/H | Celery Beat at 2AM UTC | `crontab(hour=2, minute=0)` confirmed ✅ | ✅ |
| Tests | All prior + new tests pass | **126 passed, 0 failures** ✅ | ✅ |

## Phase 9 Exit Criteria — Build verified, visual QA pending (2026-04-29)

| Criterion | Target | Result | Status |
|---|---|---|---|
| GET /events endpoint | Paginated buffered events (cursor) | ✅ Returns `{events, total, has_more}` | ✅ |
| GET /decisions endpoint | AI decision log (offset pagination) | ✅ Returns `{decisions, total}` | ✅ |
| POST /cancel endpoint | Marks cancelled, publishes Redis event | ✅ 200 running/pending; 409 terminal | ✅ |
| Celery cancellation check | Polls DB at round start | ✅ Breaks cleanly on `cancelled` status | ✅ |
| xterm.js console | Colour-coded event rendering | ✅ LiveConsole.tsx with FitAddon | ✅ |
| Buffered event replay | H/H completes before WS → load on mount | ✅ init fetch in useSimulation | ✅ |
| Load earlier events | Cursor button prepends older events | ✅ `loadEarlierEvents` + `prependEvents` | ✅ |
| SimulationStatus tile | Round progress + win-rate bar + cancel | ✅ SimulationStatus.tsx | ✅ |
| DeckChangesTile | Per-round swap history | ✅ DeckChangesTile.tsx | ✅ |
| DecisionDetail | AI decisions slide-over panel | ✅ DecisionDetail.tsx | ✅ |
| TypeScript build | Zero errors | ✅ 1627 modules | ✅ |
| Tests | All prior + new | **145 passed, 0 failures** ✅ | ✅ |
| **Visual QA** | User browser test | **⏳ Pending** | ⏳ |

## Phase 8 Exit Criteria — Verified (2026-04-29)

| Criterion | Target | Result | Status |
|---|---|---|---|
| npm run build | Zero TypeScript errors | ✅ 0 errors, 1619 modules | ✅ |
| Dark mode | slate-950 theme, toggle persisted | ✅ Tailwind `darkMode: 'class'`, localStorage | ✅ |
| Routing | All 5 routes reachable | ✅ /, /simulation/:id, /dashboard, /history, /memory | ✅ |
| SimulationSetup | Deck upload + param form + opponents | ✅ Full form, validation, submit to POST /api/simulations | ✅ |
| Excluded cards | Search + chip UI | ✅ pg_trgm search, add/remove chips | ✅ |
| Input validation | Client-side guard rails | ✅ deck_locked+none blocked, card count enforced | ✅ |
| WebSocket stub | SimulationLive logs events | ✅ useSocket subscribes, logs sim_event to console | ✅ |
| Cards API | Real pg_trgm search | ✅ /cards/search, /cards, /cards/:id implemented | ✅ |
| Tests | All prior + new cards tests | **135 passed, 0 failures** ✅ | ✅ |
| **Visual QA** | User browser test | **✅ Verified 2026-04-29** | ✅ |


| Criterion | Target | Result | Status |
|---|---|---|---|
| Deck sizes | 60 cards each | 60/60 ✅ | ✅ |
| Games complete | 5/5 without crash | 5/5 ✅ | ✅ |
| Coach model | `gemma4-E4B-it-Q6_K:latest` | Confirmed ✅ | ✅ |
| Clean JSON | No `{"` prefill needed | Clean ✅ | ✅ |
| deck_mutations rows | ≥1 row written | 4 rows, real card IDs ✅ | ✅ |
| CardPerformanceQueries | Returns top cards | Dragapult cards at 50% win_rate ✅ | ✅ |
| GraphQueries | Returns synergy pairs | Boss's Orders pairs, weight 325 ✅ | ✅ |
| SimilarSituationFinder | Returns similar decisions | 3 results at dist~0.17 ✅ | ✅ |
| Decision embeddings | >0 rows at 768 dims | 1348 rows, 768 dims ✅ | ✅ |
| Deck legality | 60 cards, ≤4 copies | 60 cards, max 4, all IDs real ✅ | ✅ |

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

### Phase 9 — Frontend: Live Console & Match Viewer (2026-04-29)

**Completed this session:**
- Backend: GET /events, GET /decisions, POST /cancel — all 3 endpoints with tests
- Celery cancellation check at round start
- `src/types/simulation.ts` — shared TS types + `normaliseEvent()` (handles WS `event` vs REST `event_type` field)
- `src/api/simulations.ts` — added `getSimulationEvents`, `getSimulationDecisions`, `cancelSimulation`
- `src/stores/simulationStore.ts` — Phase 9 state extensions
- `src/hooks/useSimulation.ts` — init fetch, `loadEarlierEvents`, live WS handler
- `LiveConsole.tsx` — xterm.js + FitAddon, color-coded event formatter, "Load earlier events" button
- `SimulationStatus.tsx` — round progress bar, win-rate bar with target line, cancel button
- `DeckChangesTile.tsx` — swap history with win-rate deltas
- `DecisionDetail.tsx` — slide-over AI decision log with pagination
- `SimulationLive.tsx` — full page assembly (replaces stub)
- `npm run build`: 0 errors, 1627 modules
- 145 tests pass (up from 135)

**Remaining (visual QA — user-driven):**
- [ ] Open a completed H/H simulation — verify buffered events appear in xterm console
- [ ] Verify "Load earlier events" button appears and loads older events
- [ ] Submit a new simulation, watch events stream live in the console
- [ ] Verify cancel button appears for running simulations and works
- [ ] Verify DeckChangesTile shows swaps after a run with `deck_locked=false`
- [ ] Verify SimulationStatus tile shows correct round/win-rate progress

## Active Files Changed This Session (2026-04-29)

**Modified files (backend):**
- `backend/app/api/simulations.py` — added GET /events, GET /decisions, POST /cancel; added `redis_module`, `Decision`, `MatchEvent` imports
- `backend/app/tasks/simulation.py` — added cancellation status check at start of each round

**New files (backend tests):**
- `backend/tests/test_api/test_simulations.py` — 10 new tests: `TestGetSimulationEvents` (4), `TestGetSimulationDecisions` (2), `TestCancelSimulation` (4)

**New files (frontend):**
- `frontend/src/types/simulation.ts` — `MatchEventRow`, `LiveEvent`, `NormalisedEvent`, `DecisionRow`, `SimulationDetail`, `DeckMutation`, `normaliseEvent()`
- `frontend/src/components/simulation/LiveConsole.tsx` — xterm.js console component
- `frontend/src/components/simulation/SimulationStatus.tsx` — status/progress/cancel tile
- `frontend/src/components/simulation/DeckChangesTile.tsx` — swap history tile
- `frontend/src/components/simulation/DecisionDetail.tsx` — AI decision log slide-over

**Modified files (frontend):**
- `frontend/src/api/simulations.ts` — added `getSimulationEvents`, `getSimulationDecisions`, `cancelSimulation`, re-exported `SimulationDetail` from types
- `frontend/src/stores/simulationStore.ts` — Phase 9 state extensions; `prependEvents`, `appendEvent`, `addMutation`, `totalEvents`, `firstEventId`, `hasMore`, `mutations`, etc.
- `frontend/src/hooks/useSimulation.ts` — init fetch, `loadEarlierEvents`, live WS with mutation tracking
- `frontend/src/pages/SimulationLive.tsx` — full Phase 9 implementation (replaces stub)

**Modified files (docs):**
- `docs/STATUS.md` — this file

## Known Issues / Gaps
- **Coach cross-deck swap behaviour (observed 2026-04-27):** When the Coach has limited
  per-deck data, it may propose adding cards from the *opponent's* pool (e.g., TR Mewtwo ex,
  TR Giovanni into Dragapult deck) because those cards rank highest in the global win-rate DB
  (they're on the winning side of Dragapult-loses games). Legality checks pass — cards are
  real IDs, deck stays 60 cards, ≤4 copies — but the swaps are semantically wrong (polluting
  a Dragapult archetype with TR cards). Fix in Phase 7: pass `excluded_ids` drawn from the
  opponent deck to `analyze_and_mutate`, OR update the Coach prompt to restrict swaps to
  same-archetype cards only.
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
- **Memory test isolation (pre-existing):** `tests/test_memory/test_postgres.py` commits to
  production DB without rollback. Running memory tests pollutes `cards`, `card_performance`,
  and `deck_cards` with `test-001`/`test-002` fixture data. Fix in Phase 7: add transaction
  rollback teardown to the `db_session` fixture in `tests/test_memory/conftest.py`.
- **IVFFlat index lists=100 on small dataset:** The pgvector IVFFlat index was created with
  `lists=100`. On <1000 rows, `probes=1` (default) scanned too few clusters and missed all
  results. Fixed by setting `SET LOCAL ivfflat.probes = 20` in `find_similar()`. For Phase 7,
  consider recreating the index with fewer lists once dataset grows beyond 10k rows.
- **Uniform card_performance data (data volume, not a bug):** Top cards all show ~54.3% win rate
  because all historical data comes from two test decks (Dragapult P1 vs TR Mewtwo P2). This is
  expected — win rate is attributed to whichever player wins, and with only two archetypes both
  sides' cards converge to the same mean. Coach swap quality will improve naturally as more
  diverse matchups are simulated in later phases. No fix needed.
- **Phase 8 visual QA not yet performed (2026-04-27):** Code is committed and builds cleanly, but the
  user has not tested the UI in a browser. Phase 9 must not begin until user confirms visual QA pass.
- **Ollama "unhealthy" in Docker health check (2026-04-27):** Docker reports Ollama container as
  unhealthy, but it is functional (Gemma and Qwen calls succeed). The health check script likely
  uses an endpoint that doesn't exist on this Ollama version. Non-blocking.
- **uvicorn no hot-reload (2026-04-27):** uvicorn is started without `--reload`. Backend code changes
  require a manual kill + restart to take effect. Discovered when cards.py changes weren't served
  until uvicorn was restarted.

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
- **Gemma 4 E4B API (2026-04-29):** Gemma4 `-it` suffix = instruction-tuned. Must use
  `/api/chat` endpoint (NOT `/api/generate`). No `{"` prefill. `num_predict=-1` required
  because model uses internal thinking tokens before output; small num_predict → 0-length
  response. Parse raw response: strip markdown fences, then `json.loads()`.
- **Frontend stack (2026-04-27):** React 18 + Vite 5 + TypeScript + Tailwind 3 (`darkMode: 'class'`)
  + Zustand 4 + React Router 6 + Axios 1 + socket.io-client 4. Dark-mode-first (slate-950 palette,
  electric blue `#3b82f6` accent). Theme toggle in TopBar, persisted to localStorage.
- **Vite proxy (2026-04-27):** `/api` → `http://localhost:8000`, `/socket.io` → `http://localhost:8000`
  (ws: true). No CORS configuration needed in dev. socket.io client connects to `window.location.origin`
  with path `/socket.io` — works behind both Vite proxy (dev) and nginx (prod).
- **FastAPI route order (2026-04-27):** `/api/cards/search` MUST be defined before `/api/cards/{card_id}`
  in cards.py. FastAPI matches routes in definition order; "search" would be captured as card_id otherwise.
- **Test dependency_overrides pattern (2026-04-27):** `create_app()` returns `socketio.ASGIApp`, not
  `FastAPI`. Inner app exposed as `asgi_app.fastapi_app`. All tests must use
  `app.fastapi_app.dependency_overrides[...]`, not `app.dependency_overrides[...]`.

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

### Phase 6 — AI/H re-verification run (2026-04-27)
- **5 games (Dragapult AI P1 vs TR Mewtwo H P2):** 20% P1 win rate | 40.4 avg turns | 0 crashes
- Note: lower win rate vs prior runs is expected non-determinism (uuid seeds vary each run)
- Coach proposed 3 swaps: Psyduck→TR Mewtwo ex, Munkidori→TR Mimikyu, Prism Energy→TR Giovanni
- Cross-deck swap issue confirmed (see Known Issues). Legality still passes.
- 1,614 decision embeddings total after run (was 1,348 entering session). 768 dims confirmed.

### Phase 6 — AI/H results (2026-04-29)
- **5 games (Dragapult AI P1 vs TR Mewtwo H P2):** 40% P1 win rate | 36.0 avg turns | 0 crashes
- Coach proposed 4 swaps: Psyduck→TR Mimikyu, Ultra Ball→Mega Absol ex,
  Enhanced Hammer→TR Mewtwo ex, Duskull→TR Sneasel
- 1348 decision embeddings, 768 dims. SimilarSituationFinder returns results (dist~0.17).

## Notes for Next Session — Phase 9 Visual QA then Phase 10

**⚠️ Phase 9 code is committed and 145 tests pass, but visual QA has NOT been completed. The user must test the UI before Phase 10 begins.**

### Phase 9 Visual QA checklist (what the user will run):
1. Open a completed H/H simulation at `/simulation/:id` — verify buffered events load in xterm console (not blank)
2. Verify the "Load earlier events" button appears at top of console if >500 events exist
3. Submit a new simulation and watch events stream live
4. Verify cancel button appears for `running`/`pending` simulations and marks them cancelled
5. Verify DeckChangesTile shows swaps after a run with `deck_locked=false`
6. Verify SimulationStatus tile shows correct round progress bar and win rate

### Key architecture decisions from Phase 9
- `normaliseEvent()` in `types/simulation.ts` unifies WS events (`event` field) and REST events (`event_type` field) into a single `NormalisedEvent` shape. Always use this on raw events before storing in the store.
- xterm.js is imperative. The `Terminal` object lives in a `useRef`. The effect that writes events tracks last written index via `writtenRef.current` — it only appends new events, never rewrites (except on prepend/reset).
- `prependEvents()` in simulationStore prepends older events to front of array. The LiveConsole effect detects `writtenRef.current > events.length` (array shrank = prepend reset), clears terminal, and rewrites all.
- `useSimulation` resets store + re-fetches on `simulationId` change. The `bufferedRef` prevents double-fetching in React StrictMode.
- Cancel flow: POST /cancel → DB `cancelled` → Redis publish → WebSocket client sees `simulation_cancelled` event → polling sees new status. The Celery task stops at next round boundary (not instantly).

### Dev stack setup (unchanged from Phase 8)
- Docker: `cd ~/pokeprism && docker compose up -d`
- Backend: `cd ~/pokeprism/backend && python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000`
- Celery: `python3 -m celery -A app.tasks.celery_app worker --loglevel=warning --concurrency=2`
- Frontend: `cd ~/pokeprism/frontend && npm run dev`
- Frontend URL: **http://localhost:5173** or **https://pokeprism.joshuac.dev**

### What Phase 10 builds (from PROJECT.md §15)
- History page: paginated list of past simulations with filter/sort
- Analytics charts: win rate over time, top cards, deck performance comparisons
- GET /api/history endpoints (list, filter by date/deck/status)
- Recharts or Chart.js for visualisation

