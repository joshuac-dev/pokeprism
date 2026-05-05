# PokéPrism Changelog

This changelog reconstructs the repository's development history from project
documentation, Git history, current implementation, tests, workflows, and
available GitHub PR/issue metadata. It is intended to explain what changed, why
it changed, what evidence supports the reconstruction, and where the historical
record remains uncertain.

## Methodology

Repository history has no release tags, so entries are grouped by documented
project phase, date range, and coherent clusters of commits/PRs. Existing
changelog entries were preserved by folding their useful details into the
phase-based history below, then adding missing motivation, evidence, confidence
labels, current-state notes, and uncertainty tracking.

Confidence labels mean:

- High: directly supported by code, tests, migrations, project/status docs, PRs,
  issues, or explicit commit history.
- Medium: supported by implementation and surrounding context, but motivation,
  impact, or exact scope is partly inferred.
- Low: material historical detail exists but evidence is incomplete,
  contradictory, or unavailable. Low-confidence items are generally listed in
  the uncertainty log rather than as completed history.

Plans and roadmaps are treated as evidence of intent only. A planned item is
listed as completed only when current code, tests, migrations, workflows, or
merged PR history support that it actually landed.

## Current / Unreleased

### Summary

As of `docs/STATUS.md` last updated on 2026-05-06, the project is in
**post-phase DB-backed audit and handler refinement**. Phase 13 and the earlier
hardening sweep are documented as complete. Current work continues to close
card-specific implementation gaps found by database-backed audits, coverage
gates, and runtime simulation checks.

### 2026-05-06 — Session 11: E2E CI workflow fix (Alembic DATABASE_URL override)

Fixed the GitHub Actions Playwright E2E workflow failure where `alembic upgrade head`
ran inside the backend container but used the hardcoded `localhost:5433` URL from
`backend/alembic.ini` instead of the container-network `postgres:5432` address.

- **Root cause:** `backend/alembic/env.py` read `sqlalchemy.url` from `alembic.ini`
  without checking `DATABASE_URL`. `docker compose exec backend alembic` inherits the
  container environment (which has `DATABASE_URL=postgresql+asyncpg://...@postgres:5432/...`),
  but `alembic.ini` was read unconditionally, overriding the correct URL.
- **Fix:** `backend/alembic/env.py` now calls
  `config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])` when
  `DATABASE_URL` is set. Falls back to `alembic.ini` for local dev without the var.
- **Workflow improvements (`.github/workflows/e2e.yml`):**
  - Added `DATABASE_URL`, `REDIS_URL`, `NEO4J_URI`, `OLLAMA_BASE_URL` to the CI `.env`
    for explicit intent and belt-and-suspenders.
  - Added env sanity check (asserts `postgres:5432` in URL, `localhost` not present)
    and asyncpg Postgres reachability retry before `alembic upgrade head`.
  - Added "Seed card pool" step (`python /app/scripts/seed_cards.py`) after migrations
    — required for the coverage-page and deck-builder full-stack E2E tests.
  - Added `if: failure()` Docker diagnostics step (compose ps + 200-line log tails)
    before Playwright artifact upload, so pre-Playwright failures are visible.
- **Frontend startup:** Playwright `webServer` in `playwright.config.ts` auto-starts
  the Vite dev server; Docker `frontend` container is not needed in CI. Vite proxies
  to `http://localhost:8000` (mapped Docker backend port).
- Confidence: High.

### 2026-05-06 — Session 10: DB-backed audit, 25 findings (TARGET_REACHED)

**15 handler fixes** (attacks.py / abilities.py):
- **Fix #1** sv05-015 Wafting Heal: `register_passive_ability` → `register_ability` with real `_wafting_heal` handler
- **Fix #2** sv10-023 Oil Salvo: active-Pokémon path now uses `bypass_wr=True` (TCGDex: "not affected by W/R")
- **Fix #3** sv06-087 Floette Minor Errand-Running: `max_count` 1 → 3 (TCGDex: "up to 3 Basic Energy")
- **Fix #4** sv06-089 Swirlix Sneaky Placement: now targets any opp Pokémon via ChoiceRequest (not just active)
- **Fix #5** sv06-021 Poltchageist Tea Server: implemented — put 1 Basic Grass Energy from discard to hand
- **Fix #6** sv06-022 Sinistcha Cursed Drop: implemented — distribute 4 damage counters across opp Pokémon
- **Fix #7** sv06-022 Sinistcha Spill the Tea: implemented — discard up to 3 Grass Energy, 70 damage each
- **Fix #8** sv06-023 Sinistcha ex Re-Brew: implemented — 2 counters per Grass Energy in discard on chosen target; shuffle those energy back
- **Fix #9** sv06-045 Seaking Peck Off: implemented — discard opp Active's Tool, then 50 damage
- **Fix #10** sv06-046 Jynx Inviting Kiss: implemented — bench Basic Pokémon + apply Confused to newly benched Pokémon
- **Fix #11** sv06-056 Froakie Flock: implemented — search deck for up to 2 Froakie, bench them
- **Fix #12** sv06-048 Crawdaunt Snip Snip: implemented — 40 damage + flip 2 coins, 1 mill per heads
- **Fix #13** sv06.5-050 Eevee Colorful Catch: implemented — search deck for up to 3 Basic Energy of different types
- **Fix #14** sv06.5-051 Furfrou Energy Assist: implemented — 30 damage + attach Basic Energy from discard to bench
- **Fix #15** sv07-037 Tirtouga Splashing Turn: implemented — 70 damage + switch self with chosen bench Pokémon

**10 engine gaps documented** (EG4–EG13 in `tests/test_engine/test_audit_fixes.py`):
- EG4 sv06-016 Rillaboom Drum Beating — per-Pokémon attack/retreat cost modifier for next turn
- EG5 sv06-068 Luxray ex Piercing Gaze — discard card from opponent's revealed hand
- EG6 sv06-076 Kilowattrel Wind Power Charge — per-Pokémon next-turn +120 damage bonus
- EG7 sv07-011 Eldegoss Breezy Gift — shuffle self+attached into deck mid-attack + deck search
- EG8 sv05-072 Reuniclus Summoning Gate — peek top 8, bench any Pokémon found
- EG9 sv06-079 Clefable Metronome — copy opponent active's attack at runtime
- EG10 sv07-032 Lapras ex Larimar Rain — peek top 20, attach any Energy found
- EG11 sv07-047 Electivire Unleash Lightning — player-wide attack lock including future Pokémon
- EG12 sv07-049 Lanturn Disorienting Flash — Confused with 8-counter custom penalty (needs engine field)
- EG13 sv06-010 Illumise Slowing Perfume — second-player first-turn conditional bench manipulation

**Tests**: 488 passed, 17 skipped (was 478/1). 16 new test functions added to `test_audit_fixes.py`.

**Audit cursor advanced**: `sv07-031` (Lapras / SCR) is the next start cursor.

The current operational handoff is `docs/STATUS.md`. This changelog remains the
evidence-based history, not the live status file.

### Fixed (2026-05-05 Session 10 — Stale-Running Simulation Recovery)

Fixed the operational reliability gap found during Session 8 fault injection: a worker crash
could leave a simulation in `status='running'` indefinitely, blocking the one-at-a-time queue
for up to 1 hour (Redis/Celery default visibility timeout with `task_acks_late=True`).

- **Root cause:** `task_acks_late=True` means the Celery task message stays unacknowledged in
  Redis until the task returns. A SIGKILL moves the message to Redis's internal `unacked` set,
  where it stays until the visibility timeout (default 3600s) expires. During that window,
  `_dispatch_next_queued()` saw the stuck `running` sim as active and returned immediately.

- **Fix: application-level stale detection** (`backend/app/tasks/simulation.py`):
  - `SIMULATION_STALE_RUNNING_MINUTES = 45` (default), overridable via env var.
  - `_classify_stale_simulation(db, sim, cutoff)` classifies stale sims as `'skip'`/`'requeue'`/`'fail'` based on checkpoint progress. Uses `SimulationOpponentResult.updated_at` as the liveness signal — if any checkpoint was updated after the cutoff, the worker may still be alive (`'skip'`). Partial-nonzero running checkpoints are marked `'fail'` (unsafe to replay); all others are `'requeue'`.
  - `_recover_stale_running_simulations(SessionFactory)` — called in Phase 0 of `_dispatch_next_queued()` before the active-count check. Uses `SELECT FOR UPDATE SKIP LOCKED` for concurrent Beat safety.
  - Concurrent delivery guard: `_run_simulation_async()` now uses `SELECT ... FOR UPDATE` at task start and bails immediately if `sim.status == 'running'` (prevents two workers from executing the same sim if stale recovery re-dispatches at T+45m AND Redis redelivers the original unacked message at T+60m).

- **12 new tests** in `backend/tests/test_tasks/test_scheduled.py` — DB integration + mock-based.

- **Live validation:** Injected fake stale sim (90 min old, no checkpoints). Recovery triggered
  within one Beat cycle (< 60s). Worker log: `Stale-running recovery: requeuing simulation...`.
  Sim completed successfully after requeue. No duplicate rows. Queue unblocked.

- Backend test baseline: **490 passed, 1 skipped** (was 478).
- `docs/HARDENING_SWEEP_REPORT.md` Section 7B updated with implementation and validation evidence.
- Confidence: High.

### Added (2026-05-05 Session 9 — Handler Regression Tests + Bug Fixes)

Added 14 focused regression tests for five handler bugs fixed in Session 8. Fixed 2 additional
latent bugs discovered while authoring the regression tests.

- **2 latent handler bugs fixed** (`backend/app/engine/effects/abilities.py`):
  - `_fall_back_to_reload` / `_cond_fall_back_to_reload`: called `_energy_provides_type` which
    was never imported in `abilities.py` (defined in `trainers.py`). Any game involving Clawitzer
    and Water Energy in hand would fire `NameError` at runtime.
    Fix: inlined as `"Water" in (c.energy_provides or [])`. Confidence: High.
  - `_energized_steps`: `state.emit_event(...)` referenced `action.card_def_id` (does not exist
    on `Action`). Every Grumpig Energized Steps resolution would fire `AttributeError`.
    Fix: replaced with `action.card_instance_id or ""`. Confidence: High.

- **14 regression tests added** (`backend/tests/test_engine/test_audit_fixes.py`):
  - Ninjask Cast-Off Shell (me01-017): 2 tests
  - Clawitzer Fall Back to Reload (me01-038): 3 tests
  - Grumpig Energized Steps (me01-063): 1 test
  - Fighting Gong (me01-116): 1 test
  - Risky Ruins (me01-127): 5 tests (two placement paths × Darkness/non-Darkness)
  - Total regression test count: 88 passed in `test_audit_fixes.py`.

- Backend test baseline: **478 passed, 1 skipped** (was 466).
- Confidence: High.

### Added (2026-05-05 Session 7 — Hardening Sweep Reverification)

Full reverification of all 8 sections of the hardening sweep report. No handler
bugs found in the 50-card TCGDex spot check. The following work was performed:

- **4 new ActionValidator rejection tests** — `TestIllegalActionRejections` class
  added to `backend/tests/test_engine/test_actions.py`:
  - `test_evolve_blocked_when_just_played` — evolution blocked turn it is played
  - `test_retreat_blocked_without_energy` — retreat action absent when no energy
  - `test_attack_blocked_without_energy` — attack action absent when insufficient energy
  - `test_extra_tool_beyond_limit_blocked` — no second Tool action when one is attached
    (skips when deck has no Tool card)
  - All 3 active tests pass; 1 correctly skips. New baseline: **466 passed, 1 skipped**.
  - Confidence: High.

- **`docs/HARDENING_SWEEP_REPORT.md` fully rewritten** — Prior Session 6 report
  replaced with complete Session 7 evidence for all 19 items. Key corrections:
  - Frontend test count: "4 passed" → "17 passed (4 files)" (prior referred to files, not tests)
  - DB card count: 2,027 → 2,036 (STATUS.md was stale)
  - card_performance rows: 270 → 1,947 (STATUS.md was very stale)
  - Neo4j BEATS edge properties: `wins`/`losses` → `win_count`/`total_games`/`win_rate` (prior query used wrong names)
  - Section 2C verdict: BLOCKED_OLLAMA → BLOCKED_NO_AI_DATA (Ollama IS warm; decisions table is empty because no AI/AI game has run)
  - Section 6A: 14-point exhaustive check added (all 0 orphans)
  - Sections 7A/7B/7C: Docker health + resilience code review added (new section 7B)
  - Sections 8A/8B: Docker/env sections replaced with injection+data-quality test inventories

- **`docs/STATUS.md` metrics updated** — Cards 2036, card_performance 1947, backend tests 466, frontend tests 17.

- Confidence: High.

### Fixed (2026-05-05 Session 8 — Hardening Sweep Gap Closeout)

Closed remaining gaps from Session 7 hardening sweep: completed Section 2C (AI/AI
games), Section 5 (full 50-card live TCGDex comparison), and Section 7B (fault injection).

- **5 handler mismatches fixed** found by full 50-card live TCGDex comparison:

  - **`_cast_off_shell` wrong card ID (me01-017 Ninjask, abilities.py)** — Handler
    searched for `card_def_id == "me01-016"` (Nincada) instead of `"me01-061"`
    (Shedinja). In decks containing Shedinja but not Nincada, Cast-Off Shell silently
    failed; in decks with Nincada it would bench Nincada instead.
    Fix: changed target to `"me01-061"`. Confidence: High.

  - **`_fall_back_to_reload` wrong source/count/type (me01-038 Clawitzer, abilities.py)**
    — Handler was attaching from `player.discard` (not hand), limited to 1 energy
    (not 2), and accepted any energy type (not Water-only). Three distinct deviations
    from TCGDex card text.
    Fix: rewritten to use hand, filter `_energy_provides_type(c, "Water")`,
    `max_count=2`. Condition function updated accordingly. Confidence: High.

  - **`_energized_steps` four deviations (me01-063 Grumpig, abilities.py)** —
    Handler searched entire deck (not top 4 cards), restricted to Psychic Energy
    (not any Basic Energy), targeted Bench only (not any Pokémon), and allowed only
    1 attachment (not any number). TCGDex text: "Look at the top 4 cards of your
    deck. Attach any number of Basic Energy cards you find there to any of your
    Pokémon in any way you like."
    Fix: rewritten to peek `player.deck[:4]`, extract any Basic Energy from those 4,
    ChoiceRequest for any number, ChoiceRequest target for each (active+bench). Confidence: High.

  - **`_fighting_gong` missing Basic Pokémon filter (me01-116 Fighting Gong, trainers.py)**
    — Pokémon branch had no evolution stage check, allowing Stage 1 and Stage 2
    Fighting Pokémon to be searched. TCGDex text specifies "Basic {F} Pokémon."
    Fix: added `and c.evolution_stage == 0` to Pokémon branch. Confidence: High.

  - **`_place_bench` / `_play_basic` Risky Ruins missing Basic check (me01-127, transitions.py)**
    — Stadium effect applied 20 damage to any non-Darkness Pokémon placed on bench,
    including evolved Pokémon placed via special effects. TCGDex text specifies "Basic
    Pokémon" only. Fix: added `cdef_rr.is_basic_pokemon` check in both bench placement
    functions. Confidence: High.

- **3 NOOP stubs documented as deferred engine gaps:**
  - me01-118 Iron Defender: turn-scoped Metal damage reduction (requires `PlayerState`
    flag + `_apply_damage` check)
  - me01-124 Premium Power Pro: turn-scoped Fighting damage bonus (same pattern)
  - me01-028 Cinderace Explosiveness: setup-phase placement hook (requires
    mulligan/setup engine changes)

- **Section 7B fault injection completed** — Created and killed a disposable H/H
  simulation mid-run to test recovery. Found: `advance_simulation_queue` beat task
  does not detect stuck-running simulations; Redis visibility timeout default is 3600s
  (1 hour), so re-delivery of the killed task takes up to 1 hour. Queue is blocked by
  the stuck running sim during this window. Two remediation options documented:
  Option A (set `broker_transport_options.visibility_timeout`); Option B (stale-running
  detection in `_dispatch_next_queued()`). Checkpointing idempotency confirmed correct.

- **Section 2C AI/AI behavioral run completed** — 3 games run via
  `backend/scripts/ai_diagnostic_3games.py` (model: Qwen3.5:9B-Q4_K_M). Results:
  - Game 1: p2 wins (TR Mewtwo beats Dragapult), 57 turns, 127 decisions
  - Game 2: p1 wins (Dragapult beats Ogerpon), 125 turns, 264 decisions
  - Game 3: p2 wins (Ogerpon beats TR Mewtwo), 41 turns, 98 decisions
  - 0 validator warnings across 489 decisions — hard gate held
  - No hallucinations, no illegal action acceptance, no state contradictions
  - Minor BAD_STRATEGIC_PLAY finding (forward-planning bias on PASS decisions)

- **`docs/HARDENING_SWEEP_REPORT.md` updated** — Section 2C, Section 5, and Section
  7B replaced/extended with actual evidence. Summary table updated. Session 8 fixes table added.

- **Test count unchanged at 466 passed, 1 skipped** — all 5 handler fixes maintain
  existing passing tests.

- Confidence: High.

### Fixed + Test (2026-05-05 Session 9 — Regression Tests for Session 8 Fixes)

Added 14 focused regression tests for all five Session 8 handler fixes. Two latent
bugs found and corrected during test authoring:

- **`_fall_back_to_reload` / `_cond_fall_back_to_reload` NameError (me01-038 Clawitzer,
  abilities.py)** — Both functions called `_energy_provides_type(c, "Water")` but this
  helper was never imported into `abilities.py` (defined in `trainers.py`). Any player
  with Clawitzer and Water Energy in hand would cause a `NameError` at runtime.
  Fix: inlined the check as `"Water" in (c.energy_provides or [])` in both call sites.
  Confidence: High.

- **`_energized_steps` AttributeError (me01-063 Grumpig, abilities.py)** — Session 8
  emit_event call referenced `action.card_def_id`, a field that does not exist on the
  `Action` dataclass (which has `card_instance_id`). Would fire AttributeError on the
  emit line every time Energized Steps resolved.
  Fix: replaced with `action.card_instance_id or ""`. Confidence: High.

- **14 regression tests added** to `backend/tests/test_engine/test_audit_fixes.py`:
  - Ninjask Cast-Off Shell: 2 tests (Shedinja benched; no-Shedinja no-op)
  - Clawitzer Fall Back to Reload: 3 tests (hand-only, Water-only, max 2; condition true/false)
  - Grumpig Energized Steps: 1 test (top-4, any Basic Energy, active+bench, any number)
  - Fighting Gong: 1 test (Basic included; Stage 1/2 excluded)
  - Risky Ruins: 5 tests (Basic non-Darkness damaged; Darkness no damage; evolved no damage; `_play_basic` both cases; `_place_bench` evolved)

- **New baseline: 478 passed, 1 skipped** (up from 466).

- Confidence: High.

### Added (2026-05-05 Session 7 — Hardening Sweep Reverification)

- **`_sinister_surge` duplicate deleted (me02-068 Toxtricity)** — A second
  definition of `_sinister_surge` existed at lines 2313–2368 of `abilities.py`,
  shadowing the correct implementation at line 676 due to Python module-level
  name resolution. The incorrect duplicate attached energy to any in-play Pokémon
  and placed no damage counters. The correct implementation at line 676 restricts
  to benched Darkness-type Pokémon and places 2 damage counters on the target.
  - Root cause: developer authored the duplicate handler with "attach to any
    Pokémon" semantics and never removed it; correct handler was overwritten at
    registration time.
  - Fix: deleted incorrect duplicate and module-level `_cond_sinister_surge`
    (lines 2311–2368); registration at line 4295 now uses the correct handler.
  - Evidence: TCGDex me02-068 card text; `abilities.py` lines 676–719;
    `test_sinister_surge_targets_darkness_bench_and_places_counters` regression test.
  - Confidence: High.

- **`_jasmine_gaze` bench coverage (sv08-178)** — Handler was applying
  `incoming_damage_reduction += 30` to only `player.active`. TCGDex text (verified
  live): "all of your Pokémon take 30 less damage from attacks ... (This includes
  new Pokémon that come into play.)" Fixed to apply to active + all bench Pokémon.
  - Engine gap documented (not fixed): "includes new Pokémon that come into play"
    requires a player-level flag and bench-entry hook. Additionally,
    `incoming_damage_reduction` is reset unconditionally for all Pokémon in
    `_end_turn()` (runner.py:532,555), meaning protection effects set during the
    current player's turn are cleared before the opponent attacks — a systemic
    timing bug affecting Gaia Wave and similar "opponent's next turn" effects.
  - Evidence: TCGDex sv08-178 card text (fetched live); `trainers.py`; state.py:122;
    runner.py:532,555; `test_jasmine_gaze_applies_to_active_and_bench`.
  - Confidence: High.

- **`_grimsleys_move_b18` max_count (me02-090 Grimsley's Move)** — Handler used
  `max_count=max_choose` allowing multiple Darkness Pokémon to be benched. TCGDex
  text: "You may put a Darkness-type Pokémon you find there onto your Bench" —
  "a" meaning 1. Fixed to `max_count=1`.
  - Evidence: TCGDex me02-090 card text; `trainers.py`; `test_grimsleys_move_max_one_pokemon`.
  - Confidence: High.

- **3 regression tests added** — all in `backend/tests/test_engine/test_audit_fixes.py`.
  Backend test count: **463 passed** (up from 460).

Engine gaps documented (not fixed in this sweep):
- svp-089 Feraligatr Torrential Heart: noop — requires energy-attach trigger callback
- svp-134 Crabominable Food Prep: noop — requires multi-source bench-energy redistribution
- Systemic `incoming_damage_reduction` timing: reset before opponent attacks in `_end_turn()`

### Fixed (2026-05-04 Session 3 — Missing Alt-Print Registrations + StatusBadge)

- **6 missing handler registrations** — all alt prints of already-implemented cards:
  - sv08.5-097, sv08.5-098, sv08.5-099 (Black Belt's Training alts) → `_black_belt_training`
  - svp-173 (Eevee alt) → `_reckless_charge_eevee` attack + Boosted Evolution passive noop
  - svp-200 (Eevee alt) → `_call_for_family`
  - svp-208 (Victini alt) → `_v_force`
  - Root cause: the cards were in the DB and deck builder could select them, but their
    tcgdex IDs had never been registered in the effects registry.
  - Evidence: runtime "missing handler" error on simulation submit; `attacks.py`,
    `trainers.py`, `abilities.py` registration blocks; test run (424 passed).
  - Confidence: High.

- **"Queued" StatusBadge and FilterBar** — `queued` sims previously displayed the raw
  string "queued" because `StatusBadge` had no entry for it. Added distinct muted-slate
  style and "Queued" label. Added "Queued" option to History page FilterBar status
  dropdown. Frontend build clean.
  - Evidence: `frontend/src/components/history/StatusBadge.tsx`;
    `frontend/src/components/history/FilterBar.tsx`; `npm run build` (clean).
  - Confidence: High.

### Changed (2026-05-04 Session 4 — Batched Neo4j Synergy Writes)

- **Neo4j synergy updates batched** — `GraphMemoryWriter._update_synergies()` now
  builds deterministic unique-card pairs and submits them via chunked
  `UNWIND $pairs AS pair` Cypher instead of one Neo4j round trip per card pair.
  Semantics are unchanged: duplicate card copies are ignored, win/loss deltas
  remain +1.0/-0.5, and `weight` / `games_observed` final values match the
  previous per-pair implementation.
  - Why: H/H simulations with singleton-heavy decks can create thousands of
    synergy pair updates per match; batching removes the largest obvious Neo4j
    round-trip multiplier without changing coach data.
  - Evidence: `backend/app/memory/graph.py`;
    `backend/tests/test_memory/test_graph_synergy_batch.py`;
    `backend/tests/test_memory/test_graph.py`; focused test runs.
  - Confidence: High.

- **Neo4j deck setup writes cached and batched** — `GraphMemoryWriter` now ensures
  Deck/Card/BELONGS_TO setup once per writer instance per deck
  ID/name/card-quantity fingerprint, and `_ensure_deck_nodes()` batches Card
  node and BELONGS_TO edge MERGEs with `UNWIND $cards AS card`. MatchResult and
  BEATS relationships still write per match.
  - Why: After synergy batching, persisted H/H benchmarks still spent most
    wall-clock time in Neo4j. Repeated matches against the same decks were
    redundantly re-running idempotent Deck/Card/BELONGS_TO setup for every
    match.
  - Evidence: `backend/app/memory/graph.py`;
    `backend/tests/test_memory/test_graph_synergy_batch.py`;
    `backend/tests/test_memory/test_graph.py`; focused test runs; 25-match
    persisted H/H benchmark improved from 13.38s total / 10.21s Neo4j to
    12.29s total / 9.21s Neo4j under concurrent Neo4j load.
  - Confidence: High.

### Fixed (2026-05-04 Session 5 — Opponent-Batch Checkpointing)

- **Celery retry/redelivery replay safety** — added a
  `simulation_opponent_results` checkpoint table and `SimulationOpponentResult`
  ORM model keyed by `(simulation_id, round_number, opponent_deck_id)`.
  Completed opponent batches are verified and skipped on retry, preventing
  duplicate Match, MatchEvent, Decision, card_performance, and Neo4j updates for
  already-persisted opponent blocks.
  - Stale `running` checkpoints with zero persisted matches are rerun.
  - Stale `running` checkpoints with the full target match count are finalized
    from persisted rows and skipped.
  - Partial nonzero persisted batches are marked failed and require manual
    repair; no destructive cleanup is attempted.
  - Graph failures remain non-fatal and are tracked separately with
    `graph_status`.
  - Skipped batches reconstruct `MatchResult` objects, including events, from
    Postgres so round aggregation and coach evidence do not silently lose
    completed opponent data.
  - Evidence: `backend/app/tasks/simulation.py`; `backend/app/db/models.py`;
    Alembic revision `5b7e9c2d4a11`;
    `backend/tests/test_tasks/test_simulation_checkpointing.py`; full backend
    test suite (449 passed).
  - Follow-up fix: match persistence now preserves scheduled deck IDs for
    `Simulation.user_deck_id` and `SimulationOpponent.deck_id` instead of
    replacing them through name-based deck lookup. Live Docker/Celery replay
    validation passed after the fix; full backend suite: 453 passed.
  - Follow-up fix 2: `_ET_ATTACH` helper (used by Cresselia me02-039 Swelling
    Light) was calling the `EnergyType` enum instead of `EnergyAttachment`,
    causing live simulation `2bc45a4e` to fail with `EnumType.__call__() got an
    unexpected keyword argument 'energy_type'`. Fixed to call
    `EnergyAttachment(...)`. Regression test added to `test_audit_fixes.py`
    (#L1). Full backend suite: 454 passed.
  - Follow-up fix 3: `_tr_venture_bomb_b19` (sv10-179 TR Venture Bomb) called
    `check_ko` with transposed arguments `(state, player_id_string, card_instance)`
    in both coin branches; correct signature is `(state, card_instance,
    player_id_string)`. Caused live simulation `005109f8` to fail with
    `'str' object has no attribute 'current_hp'`. Two regression tests added to
    `test_audit_fixes.py` (#L2, both heads and tails branches). Full backend suite:
    456 passed.
  - Follow-up fix 4: three energy-return attack handlers
    (`_upthrusting_horns_b4` sv08-039 Paldean Tauros, `_opposing_winds_b5`
    sv05-135 Unfezant, `_balloon_return_b5` mep-006 Drifblim) reconstructed energy
    `CardInstance` objects from `EnergyAttachment.provides` (a `list[EnergyType]`)
    using `list(att.provides)`, which stored enum objects in `energy_provides`
    (typed `list[str]`). When the player subsequently attached that energy,
    `_attach_energy` called `EnergyType.from_str(EnergyType.X)` which calls
    `.strip()` on the enum and raised `AttributeError`. Fixed all three to use
    `[et.value for et in att.provides]`. Caused live simulation `40612eb1` to fail.
    Regression tests added to `test_audit_fixes.py` (#L3). Full backend suite:
    460 passed.
  - Confidence: High.

### Added / Fixed (2026-05-04 Session 2 — Card Handlers + Simulation Queue)

- **Precious Trolley (sv08-185)** — ACE SPEC trainer handler implemented.
  Benches any number of Basic Pokémon chosen from deck (capped by available bench
  space); shuffles deck after. Generator-based with `ChoiceRequest`. 3 tests
  added in `test_audit_fixes.py`.
  - Evidence: TCGDex sv08-185 card text; `backend/app/engine/effects/trainers.py`;
    test run (424 passed).
  - Confidence: High.

- **Neutralization Zone (sv06.5-060)** — Stadium registered as `_noop` (passive).
  Damage prevention added to `_apply_damage` in `attacks.py`: if attacker has
  `has_rule_box` and defender does not, the attack deals 0 damage. Forward-defense
  `IRRECOVERABLE_FROM_DISCARD` frozenset + `is_recoverable_from_discard()` helper
  added to `base.py`; Pal Pad and Miracle Headset candidate lists now filter with
  this helper. 7 tests added (3 damage-prevention, 4 irrecoverable-from-discard).
  - Evidence: TCGDex sv06.5-060 card text; `backend/app/engine/effects/attacks.py`;
    `backend/app/engine/effects/base.py`; test run (424 passed).
  - Confidence: High.

- **Simulation queue (one-at-a-time FIFO)** — Only one simulation runs at a time.
  `create_simulation` checks for any active sim; if one exists the new sim is
  created as `queued` and not dispatched to Celery. `_dispatch_next_queued()` in
  `tasks/simulation.py` uses `SELECT FOR UPDATE SKIP LOCKED` to atomically claim
  and dispatch the oldest queued sim on every task completion (success or
  failure). `advance_simulation_queue` Beat task fires every 60 seconds as a
  crash-recovery fallback. Worker concurrency reduced to 1. `cancel_simulation`
  also handles queued sims. `'queued'` added to frontend status type unions.
  - Evidence: `backend/app/tasks/simulation.py`; `backend/app/tasks/scheduled.py`;
    `backend/app/tasks/celery_app.py`; `backend/app/api/simulations.py`;
    `docker-compose.yml`; `frontend/src/types/history.ts`;
    `frontend/src/types/simulation.ts`; docker compose config --quiet (clean);
    frontend build (clean); test run (424 passed).
  - Confidence: High.

### Fixed (2026-05-05 Audit Session — Batch A)

- **DB-backed audit session 2026-05-05** — 9 card-handler bugs fixed (Bugs #A1–#A9):
  - #A1: Removed duplicate `_strong_bash_b2` definition from `attacks.py`.
  - #A2+#A3: `_acerolas_mischief` — removed bogus draw-to-4 clause and added missing
    prize-count gate (opponent must have ≤2 prizes remaining per TCGDex text).
  - #A4: `_lucian_b5` completely rewritten — each player shuffles hand to deck, flips
    coin; heads=draw 6, tails=draw 3 (previous implementation drew 3 + attached energy).
  - #A5: `sv06-159` (Ogre's Mask) re-registered to `_ogres_mask` (was incorrectly `_noop`
    with a wrong "Penny" comment).
  - #A6: `_unfair_stamp` player draw count corrected from 3 to 5 (TCGDex: you draw 5,
    opponent draws 2).
  - #A7: `_dangle_tail_flag` replaced with `_dangle_tail` — puts 1 Pokémon from discard
    to hand (was a no-op flag).
  - #A8: `_recovery_net_flag` replaced with `_recovery_net` — puts up to 2 Pokémon from
    discard to hand (was a no-op flag).
  - #A9: `_avenging_edge_flag` replaced with `_avenging_edge` — deals 100 + 60 bonus if
    `ko_taken_last_turn` is set (was a no-op flag with partial default damage).
  - 12 new regression tests added to `backend/tests/test_engine/test_audit_fixes.py`.
  - Full backend test suite: **411 passed / 3 skipped**.
  - Evidence: TCGDex card text for sv06-159, sv06-165, sv06-019, sv06-157, sv07-057,
    me01-113; `backend/app/engine/effects/attacks.py`;
    `backend/app/engine/effects/trainers.py`; test run output.
  - Confidence: High.

### Added, including Neo
  Upper Energy and the documented Batch 1/Batch 2 handlers such as Arven,
  Bravery Charm, Earthen Vessel, Iron Hands ex, Mew ex, Miraidon ex, Nest Ball,
  Super Rod, Armarouge, Chi-Yu, Defiance Band, Electric Generator, Iono, Iron
  Bundle, Jet Energy, Pal Pad, Professor's Research, and Squawkabilly ex.
  - Why: The current audit phase is closing DB-populated cards whose live
    TCGDex text requires explicit handlers before reliable simulation and
    deckbuilding workflows can depend on them.
  - Evidence: `docs/STATUS.md`; commit `6ba3bba`; current files under
    `backend/app/engine/effects/`; TCGDex fixtures under
    `backend/app/data/tcgdex_cache/cards/`.
  - Confidence: High.

- Added runtime notes for card implementation deployment, especially the need
  to rebuild the `celery-worker` image after effect handler changes.
  - Why: During the 2026-05-04 session, runtime testing showed the worker did
    not mount source code live, so simulations could keep using stale handlers
    unless the image was rebuilt.
  - Evidence: `docs/STATUS.md`; Docker service structure in
    `docker-compose.yml`.
  - Confidence: High.

- Established the current documentation hierarchy:
  `docs/STATUS.md` for current-state handoff, `docs/CHANGELOG.md` for evidence
  history, `docs/AUDIT_RULES.md` and `docs/AUDIT_STATE.md` for active DB-backed
  audit workflow, `docs/PROJECT.md` for historical architecture context, and
  `README.md` for public onboarding.
  - Why: The original phase blueprint and expansion-era card lists were still
    phrased as active authority after the phase buildout and hardening sweep
    had completed.
  - Evidence: Documentation cleanup on 2026-05-04; `docs/STATUS.md`;
    `docs/PROJECT.md`; `README.md`.
  - Confidence: High.

### Fixed

- Fixed the Neo Upper Energy runtime field mismatch by using
  `EnergyAttachment.source_card_id` rather than a nonexistent `card_id` field.
  - Why: The handler crashed during live validation before the field mismatch
    was corrected.
  - Evidence: `docs/STATUS.md`; `backend/app/engine/state.py`; current effect
    handler code.
  - Confidence: High.

### Known Issues

- DeckBuilder Phase 3 simulation-backed preference weighting remains deferred.
  Current deck construction is deterministic and conservative rather than
  memory-optimized.
  - Evidence: `docs/STATUS.md`; `backend/app/coach/deck_builder.py`.
  - Confidence: High.

- The AI stack remains intentionally Ollama-only after the hardening proposal's
  provider abstraction stage was rejected by product decision.
  - Evidence: `docs/STATUS.md`;
    `docs/proposals/AI_COACH_HARDENING_ASSESSMENT.md`.
  - Confidence: High.

- Celery workers still have no dedicated healthcheck, and handler edits require
  rebuild/restart discipline.
  - Evidence: `docs/STATUS.md`; `docker-compose.yml`.
  - Confidence: High.

- Mystery Garden and Watchtower are documented as `_noop` pending specific
  bench/stadium support; AI decision quality gaps remain for reasoning-to-action
  mismatch, Fairy Zone misunderstanding, and greedy KO override behavior.
  - Evidence: `docs/STATUS.md`.
  - Confidence: High.

### Current Metrics Snapshot

- Local database on 2026-05-04: 2,027 cards, 6,900 matches, 270
  `card_performance` rows, and 0 running simulations. Coverage reported 2,026
  auditable cards, 1,734 implemented, 292 flat-only, 0 missing, and 100.0%
  coverage.
  - Evidence: `docker compose exec postgres psql -U pokeprism -d pokeprism -c
    "SELECT (SELECT count(*) FROM cards) AS cards, (SELECT count(*) FROM
    matches) AS matches, (SELECT count(*) FROM card_performance) AS
    card_performance, (SELECT count(*) FROM simulations WHERE status='running')
    AS running_simulations;"`; direct `backend` container call to
    `app.api.coverage.get_coverage()`.
  - Confidence: High for the local environment snapshot; not a release
    baseline.

- Latest documented full backend suite baseline remains 374 passed / 4 skipped
  from the 2026-05-03 hardening report. Current backend count should be checked
  with `cd backend && python3 -m pytest tests/ -x -q` before updating public
  claims.
  - Evidence: `docs/HARDENING_SWEEP_REPORT.md`; `docs/STATUS.md`.
  - Confidence: High for the documented baseline; current count must be
    re-verified before reuse.

## Historical Changelog

## DB-Backed Audit and Hardening Sweep - 2026-05-01 to 2026-05-03

### Summary

This period shifted card validation from expansion-list tracking to a
database-backed audit loop, completed the AI/deckbuilder hardening sweep, and
fixed many card implementation defects discovered by comparing DB cards against
live TCGDex text.

### Added

- Added the DB-backed card audit process, replacing the earlier expansion-list
  audit scope with a rotating cursor over cards already present in the
  database.
  - Why: `docs/AUDIT_RULES.md` explicitly says the DB is the audit scope and
    TCGDex is the source of truth for card text; older project lists are not
    authoritative for this audit.
  - Evidence: `docs/AUDIT_RULES.md`; `docs/AUDIT_STATE.md`;
    `.github/workflows/nightly-card-effect-audit.yml`; issues #18, #29, #31,
    #33; PRs #19, #30, #32, #34; commits `c798f18`, `6f4ab0e`.
  - Confidence: High.

- Added GitHub/Copilot setup support for DB-backed audit runs, including service
  setup, migrations, card seeding, and database count verification.
  - Why: Scheduled audit issues needed a reproducible environment with
    PostgreSQL, Redis, and seeded card data before an agent could compare DB
    entries to TCGDex and code handlers.
  - Evidence: `.github/workflows/copilot-setup-steps.yml`;
    `.github/workflows/nightly-card-effect-audit.yml`; issues #29, #31, #33.
  - Confidence: High.

- Added hardening around AI prompts, coach evidence, mutation validation, and
  forced action handling.
  - Why: The AI coach hardening proposal identified prompt injection,
    ungrounded output, mutation legality, and structured-output fragility as
    production-readiness risks.
  - Evidence: `docs/HARDENING_SWEEP_REPORT.md`;
    `docs/proposals/AI_COACH_HARDENING_PROPOSAL.md`;
    `docs/proposals/AI_COACH_HARDENING_ASSESSMENT.md`; PR #28; commit
    `5921ac0`; tests under `backend/tests/test_coach/` and
    `backend/tests/test_players/`.
  - Confidence: High.

- Added deck mutation evidence persistence.
  - Why: Coach recommendations needed provenance so added/removed card
    suggestions could be tied to match evidence instead of unsupported model
    assertions.
  - Evidence: migration
    `backend/alembic/versions/d6b7f3c91a2e_add_deck_mutation_evidence.py`;
    `docs/proposals/AI_COACH_HARDENING_ASSESSMENT.md`.
  - Confidence: High.

### Changed

- Changed AI provider scope to remain Ollama-only instead of adding a generic
  provider abstraction.
  - Why: The hardening assessment records Stage 2 as intentionally rejected by
    product decision because the project is self-hosted and local-model first.
  - Evidence: `docs/proposals/AI_COACH_HARDENING_ASSESSMENT.md`;
    `docs/STATUS.md`.
  - Confidence: High.

- Reframed audit documentation around TCGDex preflight, cursor discipline,
  handler requirements, atomic per-card fixes, and engine-gap documentation.
  - Why: Earlier card-expansion rules were too broad for ongoing DB-backed
    correctness audits; the new audit loop needed to prevent stale-list drift
    and unverified handler claims.
  - Evidence: `docs/AUDIT_RULES.md`; `docs/AUDIT_STATE.md`;
    `docs/CARD_EXPANSION_RULES.md`.
  - Confidence: High.

### Fixed

- Fixed broad card implementation bugs found by DB-backed audits, including
  duplicate function shadowing, wrong effect targets, optional effects treated
  as mandatory, top-of-deck ordering bugs, stale active Pokemon references,
  malformed selected-option access, and missing special handlers.
  - Why: Audit PRs compared live TCGDex card text against registered handlers
    and current code behavior, surfacing defects that could silently corrupt
    simulation outcomes.
  - Evidence: PRs #5, #7, #9, #11, #13, #15, #19, #30, #32;
    `backend/tests/test_engine/test_audit_fixes.py`; current effect handlers
    under `backend/app/engine/effects/`.
  - Confidence: High.

- Fixed or implemented specific audited effects such as Abra Teleporter,
  Cinnabar Lure, Crimson Blaster, Cursed Edge, Guarded Rolling, Mischievous
  Painting, Surf Back, Time Manipulation, Upthrusting Horns, Auto Heal, Mammoth
  Hauler, Hop's Choice Band, Postwick, Snack Seek, and Wide Wall.
  - Why: These cards were called out in DB-backed audit PRs as missing,
    partially implemented, or behaviorally incorrect relative to TCGDex text.
  - Evidence: PRs #19, #30, #32; current effect handlers and regression tests.
  - Confidence: High.

### Testing

- Added hardening coverage for damage calculation, status conditions, special
  mechanics, effect spot checks, API endpoints, coach mutation legality, and
  prompt-injection fixtures.
  - Why: The hardening sweep targeted defect classes that could make simulation
    results, coach advice, or exposed API behavior unreliable before production
    testing.
  - Evidence: `docs/HARDENING_SWEEP_REPORT.md`;
    `backend/tests/test_engine/test_damage_calc.py`;
    `backend/tests/test_engine/test_status_conditions.py`;
    `backend/tests/test_engine/test_special_mechanics.py`;
    `backend/tests/test_engine/test_effect_coverage_spot_check.py`;
    `backend/tests/test_api/test_simulations.py`;
    `backend/tests/test_coach/`.
  - Confidence: High.

- Raised the documented backend test baseline to 374 passed / 4 skipped at the
  end of the hardening sweep.
  - Why: The project needed a regression baseline after prompt, coach, engine,
    and API hardening.
  - Evidence: `docs/HARDENING_SWEEP_REPORT.md`; `docs/STATUS.md`.
  - Confidence: High.

### Documentation

- Rewrote the README to describe the full-stack architecture, setup path,
  runtime services, known limitations, and current project status.
  - Why: The repository had grown from an engine prototype into a full-stack
    simulator/deck-evolution system and needed maintainable onboarding docs.
  - Evidence: PR #16; `README.md`.
  - Confidence: High.

## Complex Card Mechanics and Final Expansion Closure - 2026-04-30

### Summary

After broad card ingestion, the project implemented many previously flagged
complex mechanics and closed the documented Phase 12 expansion push.

### Added

- Added explicit handlers for the final documented flagged-card set from the
  expansion work, including Abomasnow, Barbaracle, Cook, Crabominable, and
  Clefairy.
  - Why: The card pool expansion rules prohibited leaving non-flat effect cards
    as unsupported stubs, so remaining flagged cards needed explicit handling
    before Phase 12 could be marked complete.
  - Evidence: Existing changelog history; `docs/STATUS.md`;
    `docs/CARD_EXPANSION_RULES.md`; commits `e97b4ae`, `c246f2b`;
    `backend/app/engine/effects/`.
  - Confidence: Medium; the completion claim is documented, but exact counts
    differ across later docs.

- Added broad engine support for complex mechanics required by expanded card
  coverage, including dynamic HP, conditional attack costs, first-turn attack
  exceptions, attack copying, deck attack selection, devolve behavior, temporary
  attack attachment, draw triggers, knockout/self-damage triggers, energy-move
  prompts, and special-energy behavior.
  - Why: Expansion batches increasingly exposed cards that could not be modeled
    as flat damage or simple attach/draw effects.
  - Evidence: commits `83ada8d`, `61c2b60`, `2b80dfc`, `9570ca7`, `519efd7`,
    `d4ddf92`, `4aad18e`, `5b49e01`, `0fc9095`; `docs/STATUS.md`;
    `backend/app/engine/`; `backend/app/engine/effects/`;
    `backend/tests/test_engine/`.
  - Confidence: High for the landed mechanics; Medium for exact per-card
    behavioral completeness.

- Added a TM attack subsystem and supporting code for cards that grant attacks
  from attached Trainer cards.
  - Why: Technical Machine effects required attacks to be exposed dynamically
    rather than only through the printed attacks on a Pokemon card definition.
  - Evidence: `docs/STATUS.md`; commits `83ada8d`, `61c2b60`;
    engine/effect files under `backend/app/engine/`.
  - Confidence: High.

### Changed

- Changed expansion closure criteria from "card exists in fixtures" toward
  "card has an appropriate handler, intentional noop, or documented engine gap."
  - Why: Expanded card data alone was insufficient for simulation correctness;
    active card text needed to map to executable behavior or a documented
    limitation.
  - Evidence: `docs/CARD_EXPANSION_RULES.md`; `docs/STATUS.md`;
    `backend/app/engine/effects/registry.py`.
  - Confidence: High.

### Testing

- Expanded engine regression coverage around complex effect behavior.
  - Why: New engine primitives such as copy attacks, dynamic HP, and
    trigger-based effects are high-risk rules areas.
  - Evidence: `backend/tests/test_engine/test_copy_attacks.py`;
    `backend/tests/test_engine/test_special_mechanics.py`;
    `backend/tests/test_engine/test_audit_fixes.py`; commits listed above.
  - Confidence: Medium; test files confirm coverage exists, but exact original
    introduction per assertion was reconstructed from commit clusters.

## Full Card Pool Expansion - 2026-04-29 to 2026-04-30

### Summary

Phase 12 expanded the simulator's card data from a small curated set to a broad
Standard-format pool driven by live TCGDex data and the project master card
list.

### Added

- Expanded populated card coverage through a series of documented batches from
  the original small pool toward the full Standard-format scope.
  - Why: The project needed enough real cards to support meaningful deck
    simulation, deck evolution, benchmark matchups, and AI coach evaluation.
  - Evidence: `docs/CARD_EXPANSION_RULES.md`;
    `docs/POKEMON_MASTER_LIST.md`; `docs/CARDLIST.md`; commits `201a498`,
    `d2d7b71`, `da42c26`, `b1f81a5`, `7601961`, `768da74`, `61748c6`,
    `a0d4085`, `d1c39f0`, `7517c1f`, `26c4647`, `b80499f`, `660110e`,
    `cb12521`, `f767cb1`, `5fd2250`, `cc9a996`, `d70bb78`, `df59240`,
    `d9a74f5`; TCGDex cache under `backend/app/data/tcgdex_cache/cards/`.
  - Confidence: High for the expansion work; Medium for exact historical
    totals because later documents disagree on whether the relevant count is
    1,927, 2,001, or 2,005.

- Added support for new set code conventions such as `MEP`, `PR-SV`, and `SVE`
  while ingesting expansion cards.
  - Why: The master list included special/promo/energy products outside the
    earliest set-code assumptions.
  - Evidence: `docs/CARD_EXPANSION_RULES.md`;
    `docs/POKEMON_MASTER_LIST.md`; fixtures under
    `backend/app/data/tcgdex_cache/cards/`.
  - Confidence: High.

- Added multiple batches of Trainer, Stadium, Tool, Special Energy, Pokemon ex,
  Baby Pokemon, and archetype-support handlers.
  - Why: The expansion process identified many non-flat cards whose text affects
    game state, deck search, energy movement, switching, damage modification,
    or evolution.
  - Evidence: `docs/STATUS.md`; commits from `201a498` through `c246f2b`;
    `backend/app/engine/effects/`.
  - Confidence: Medium; handler presence is clear, but later audits found bugs
    in some earlier implementations.

### Changed

- Retired `docs/CARDLIST.md` as the active card-population source in favor of
  `docs/POKEMON_MASTER_LIST.md`.
  - Why: The expansion scope moved beyond a short current/deferred list into a
    full master list.
  - Evidence: `docs/CARDLIST.md`; `docs/POKEMON_MASTER_LIST.md`;
    `docs/CARD_EXPANSION_RULES.md`.
  - Confidence: High.

### Removed

- Removed ten nonexistent Mega Evolution Promo (`MEP`) entries during the final
  expansion audit.
  - Why: Live TCGDex verification showed those master-list entries did not map
    to real cards, so retaining them would create false coverage gaps.
  - Evidence: Existing changelog history; `docs/STATUS.md`;
    `docs/CARD_EXPANSION_RULES.md`; expansion commits around `e97b4ae` and
    `c246f2b`.
  - Confidence: Medium; the removal is documented, but exact deleted entries
    were not independently reconstructed from a release boundary.

### Testing

- Preserved the existing expansion-era documented backend baseline of 215
  passing tests after Phase 12 closure.
  - Why: Expansion completion needed a regression check after adding many card
    definitions and handlers.
  - Evidence: Existing changelog history; `docs/STATUS.md`; backend tests under
    `backend/tests/`.
  - Confidence: Medium; later hardening raised the baseline to 374 passed / 4
    skipped.

## Production Hardening, Coach Intelligence, and Phase 13 - 2026-04-28 to 2026-04-29

### Summary

Phase 13 focused on production readiness: orchestration reliability, API and
console polish, Docker/Makefile workflow, card coverage enforcement, coach
quality, and frontend usability.

### Added

- Added API health checks, Celery Beat scheduling, simulation retry behavior,
  and orchestration hardening.
  - Why: Long-running simulation jobs needed observable service health,
    recoverability, and scheduled execution.
  - Evidence: Existing changelog history; commits `b0462df`, `0931ea5`,
    `933e77f`; `backend/app/tasks/`; `backend/app/api/`; `docker-compose.yml`.
  - Confidence: High.

- Added card coverage gating and on-demand TCGDex fetching before simulations.
  - Why: Simulations should fail early or populate missing card definitions
    instead of running with incomplete or unsupported card data.
  - Evidence: `backend/app/api/simulations.py`; existing changelog history;
    commits `933e77f`, `ab0a258`, `b74610d`; `backend/tests/test_api/`.
  - Confidence: High.

- Added a copy-attack engine and related tests.
  - Why: Expanded card coverage required attacks that can copy or reuse attacks
    from other cards instead of only executing a card's own printed attacks.
  - Evidence: Existing changelog history; commit `1cfc1c2`;
    `backend/tests/test_engine/test_copy_attacks.py`.
  - Confidence: High.

- Added Decision Map support, best deck snapshots, and richer coach history
  tracking.
  - Why: Maintainers needed to understand how decks changed over generations
    and why coach decisions were accepted or rolled back.
  - Evidence: Existing changelog history; migration
    `backend/alembic/versions/c3e91f7a5b22_add_best_deck_snapshot.py`;
    frontend history/dashboard components; commits `196dab3`, `3b57787`,
    `ecdc34b`.
  - Confidence: High.

- Added coach intelligence guards for evolution-line protection, regression
  detection, rollback behavior, and performance-history-aware recommendations.
  - Why: The coach was capable of making legal but strategically harmful deck
    mutations, including breaking evolution lines or repeatedly accepting
    performance regressions.
  - Evidence: Existing changelog history; `docs/STATUS.md`;
    `backend/app/coach/`; `backend/tests/test_coach/`; commits `ce796b3`,
    `22921ad`.
  - Confidence: High.

- Added Docker/Makefile workflow improvements, including compose-based commands,
  log helpers, rebuild/restart helpers, and reset paths.
  - Why: The stack had grown into multiple services and needed repeatable local
    operations for simulation, worker, database, and frontend workflows.
  - Evidence: Existing changelog history; `Makefile`; `docker-compose.yml`;
    commits `3ef7a26`, `ecdc34b`.
  - Confidence: High.

### Changed

- Changed the frontend visual system toward a light-mode dashboard and improved
  console readability.
  - Why: Phase 13 included usability polish for the live console, history, and
    dashboard surfaces.
  - Evidence: Existing changelog history; frontend files under `frontend/src/`;
    commits `3ef7a26`, `ecdc34b`.
  - Confidence: Medium; current frontend confirms implementation, but exact
    theme-history details are partly reconstructed from commits and docs.

- Changed PTCGL deck parsing and SimulationSetup integration to support pasted
  decklists, validation errors, and legal-submit handling.
  - Why: Users needed a practical path from decklist text to simulation without
    manually constructing card IDs.
  - Evidence: Existing changelog history; `frontend/src/utils/deckParser.ts`;
    `frontend/src/components/setup/DeckUploader.tsx`;
    `frontend/src/pages/SimulationSetup.tsx`; frontend tests.
  - Confidence: High.

### Fixed

- Fixed live console event detail rendering, empty event output, KO/winner prize
  handling, and history payload gaps.
  - Why: The frontend console and history views needed coherent event streams
    and correct match-end state for live monitoring.
  - Evidence: Existing changelog history; commits `22921ad`, `3b57787`,
    `ecdc34b`; files under `frontend/src/components/simulation/`,
    `frontend/src/pages/SimulationLive.tsx`, and backend simulation APIs.
  - Confidence: High.

- Fixed timeout behavior around Gemma-based deck naming.
  - Why: Slow local model calls could block or degrade deck naming workflows.
  - Evidence: Existing changelog history; `backend/app/coach/`;
    `docs/STATUS.md`.
  - Confidence: Medium.

### Testing

- Added or extended backend, frontend, and Playwright-style validation around
  deck parsing, simulation setup, dashboard flows, copy attacks, and production
  hardening.
  - Why: Phase 13 changes touched cross-service workflows that needed regression
    coverage beyond isolated engine tests.
  - Evidence: Existing changelog history; `frontend/src/**/*.test.*`;
    `backend/tests/`; `.github/workflows/e2e.yml`.
  - Confidence: Medium; exact test introduction dates are reconstructed from
    current files and commit clusters.

## Phase 12 Initial Card Pool Expansion - 2026-04-28

### Added

- Expanded the initial populated card pool from the early 55-card set to roughly
  160 implemented cards.
  - Why: The first engine and AI phases had enough cards for smoke tests but not
    enough variety for broader deck simulation and evolution.
  - Evidence: Existing changelog history; commit `31ca990`;
    `docs/STATUS.md`; `backend/app/data/tcgdex_cache/cards/`.
  - Confidence: High.

## Phase 10 Dashboard and Analytics - 2026-04-27 to 2026-04-28

### Added

- Added the dashboard analytics surface with metrics tiles, charts, history
  summaries, prize-race visualization, deck drift, mutation timeline, type
  balance, synergy graph, and AI decision summary components.
  - Why: Simulation and coach runs needed an inspectable UI for long-running
    deck evolution rather than only CLI/log output.
  - Evidence: Existing changelog history; commits `f447d08`, `507449c`,
    `4251866`, `9ee661c`; frontend files under
    `frontend/src/components/dashboard/`; backend APIs under
    `backend/app/api/history.py`.
  - Confidence: High.

- Added backend aggregation endpoints for matches, prize race, deck composition,
  timeline, and decision graph data.
  - Why: Dashboard charts needed structured API data instead of ad hoc frontend
    derivation.
  - Evidence: Existing changelog history; `backend/app/api/history.py`;
    `backend/app/services/`; tests under `backend/tests/test_api/`.
  - Confidence: High.

### Fixed

- Fixed dashboard QA issues such as incorrect API base URL usage, chart
  overflow, deck-drift normalization, AI-decision axis rendering, loading/error
  states, and TypeScript build errors.
  - Why: Initial dashboard implementation needed to be usable across screens and
    pass production frontend builds.
  - Evidence: Existing changelog history; commits `507449c`, `4251866`,
    `9ee661c`; frontend components and tests.
  - Confidence: High.

### Testing

- Added or updated frontend tests for dashboard and history rendering.
  - Why: The dashboard had multiple data states and visual components where
    regression risk was high.
  - Evidence: Existing changelog history; frontend tests under
    `frontend/src/`.
  - Confidence: Medium.

## Phase 9 Live Console and Simulation Monitoring - 2026-04-27

### Added

- Added the live simulation console with xterm rendering, Socket.IO streaming,
  event history, simulation controls, cancel support, and detail panels.
  - Why: Long-running simulation jobs needed interactive observation and
    control from the frontend.
  - Evidence: Existing changelog history; commits `6092766`, `185b173`,
    `3811803`; `frontend/src/pages/SimulationLive.tsx`;
    `frontend/src/components/simulation/`; `backend/app/api/ws.py`.
  - Confidence: High.

- Added normalized event models and replay/history support for simulation
  streams.
  - Why: Live and historical views needed the same event semantics, including
    deck changes and decision detail.
  - Evidence: Existing changelog history; backend API and frontend simulation
    state files; commits `6092766`, `185b173`.
  - Confidence: High.

### Fixed

- Fixed QA issues in live-console state handling, including store field
  mismatches and missing deck-change display behavior.
  - Why: The first console iteration exposed frontend/backend contract drift.
  - Evidence: Existing changelog history; commit `185b173`; frontend simulation
    store and component files.
  - Confidence: High.

## Phase 9 Engine Gap Resolution - 2026-05-04

### Fixed

- Fixed Spiky Energy (sv09-159) retaliation detection. The `_apply_damage`
  pipeline was searching for the energy card by instance ID in discard/hand/deck,
  but attached energy cards are consumed from zones on attachment. The check now
  reads `att.card_def_id == "sv09-159"` directly from the `EnergyAttachment`
  list on the defender, consistent with how Boomerang Energy and all other
  special energies are identified.
  - Evidence: `backend/app/engine/effects/attacks.py` (Spiky Energy block);
    test `test_spiky_energy_triggers_on_direct_card_def_id`.
  - Confidence: High.

- Fixed Team Rocket's Watchtower alt-print (me02.5-210) missing from ability
  suppression check. The action validator was checking only `sv10-180`; the
  alt-print `me02.5-210` is now included in the same set so Colorless Pokémon
  abilities are suppressed under either print.
  - Evidence: `backend/app/engine/actions.py` (Watchtower block);
    test `test_watchtower_alt_print_suppresses_colorless_ability`.
  - Confidence: High.

- Implemented Mystery Garden (me02.5-194 / me01-122) as a live USE_STADIUM
  engine action. A new `ActionType.USE_STADIUM` was added; the action validator
  offers it during MAIN phase whenever Mystery Garden is the active stadium, the
  player has at least one Energy card in hand, and the once-per-turn
  `mystery_garden_used_this_turn` flag is clear. The transition layer drives the
  handler via `EffectRegistry.resolve_trainer`. The handler prompts the player to
  choose an Energy to discard, then draws until hand size equals the number of
  Psychic Pokémon in play. The per-turn flag is reset in `runner._end_turn`.
  - Evidence: `backend/app/engine/actions.py` (`USE_STADIUM`, `_get_stadium_actions`);
    `backend/app/engine/state.py` (`mystery_garden_used_this_turn`);
    `backend/app/engine/transitions.py` (`_use_stadium`);
    `backend/app/engine/effects/trainers.py` (`_mystery_garden`);
    `backend/app/engine/runner.py` (flag reset);
    tests `test_mystery_garden_*`.
  - Confidence: High.

## Phase 8 Frontend Core - 2026-04-27

### Added

- Added the React/Vite frontend application with routing, shared layout,
  navigation, API client, cards view, simulation setup flow, and deck upload
  utilities.
  - Why: Earlier phases were backend/CLI-first; the project blueprint required
    a frontend for simulation setup, live monitoring, history, memory, and
    analytics.
  - Evidence: Existing changelog history; commits `470ab5c`, `eafdcbb`;
    `frontend/package.json`; `frontend/src/App.tsx`;
    `frontend/src/pages/`; `frontend/src/services/api.ts`.
  - Confidence: High.

- Added frontend testing with Vitest and React Testing Library.
  - Why: Deck parsing and UI flows needed regression coverage as the frontend
    became a first-class surface.
  - Evidence: `frontend/package.json`; frontend tests under `frontend/src/`;
    existing changelog history.
  - Confidence: High.

### Fixed

- Fixed visual QA issues in the initial frontend, including overflow, sizing,
  missing active navigation state, invalid card-image placeholders, progress
  rendering, mobile layout, and empty/error states.
  - Why: The initial frontend needed to be usable on desktop/mobile and robust
    against empty API responses.
  - Evidence: Existing changelog history; commit `eafdcbb`; frontend source.
  - Confidence: High.

## Phase 7 Task Orchestration and Live Simulation Infrastructure - 2026-04-27

### Added

- Added Celery/Redis-backed simulation orchestration, WebSocket/pubsub event
  delivery, simulation lifecycle tracking, and round validation.
  - Why: The project needed asynchronous, observable, repeatable simulation
    runs rather than one-off CLI execution.
  - Evidence: commits `ddd25bc`, `f7b8478`, `d9ac8af`, `361e4f6`;
    `backend/app/tasks/`; `backend/app/api/simulations.py`;
    `backend/app/api/ws.py`; `backend/tests/test_tasks/`.
  - Confidence: High.

- Added validation and isolation around coach/memory writes in task execution.
  - Why: Multi-run orchestration risked leaking state or persisting malformed
    coach outputs without stronger boundaries.
  - Evidence: commits `d9ac8af`, `361e4f6`; `backend/app/tasks/`;
    `backend/tests/test_tasks/test_simulation_task.py`.
  - Confidence: Medium.

## Phase 6 Coach, Analyst, and Deck Mutation Loop - 2026-04-27

### Added

- Added Coach and Analyst agents for report-card style analysis, deck mutation
  recommendations, memory queries, and end-to-end loop execution.
  - Why: The project blueprint calls for a self-improving deck loop where match
    results feed analysis and legal deck changes.
  - Evidence: commits `65a58c2`, `992a0ed`; `backend/app/coach/`;
    `backend/tests/test_coach/`; `docs/PROJECT.md`.
  - Confidence: High.

### Fixed

- Fixed early coach/deck mutation issues including legality enforcement and
  cross-deck swap behavior.
  - Why: The coach needed to produce valid 60-card decks and avoid illegal or
    incoherent mutations.
  - Evidence: Existing changelog history; commits `65a58c2`, `992a0ed`;
    `backend/tests/test_coach/test_deck_builder.py`.
  - Confidence: Medium.

## Phase 5 AI Player Integration - 2026-04-27

### Added

- Added `AIPlayer` support backed by local Ollama/Qwen model calls, including
  prompt construction, legal-action presentation, response parsing, regex
  fallback, and heuristic fallback behavior.
  - Why: The project needed to compare heuristic play against local LLM-driven
    decisions while preserving legal action execution.
  - Evidence: Existing changelog history; commits `b4fe6fe`, `d1cfb0d`;
    `backend/app/players/ai.py`; `backend/tests/test_players/test_ai_player.py`;
    `docs/PROJECT.md`.
  - Confidence: High.

- Added decision persistence linking simulated actions to card context.
  - Why: Later coach and dashboard features needed to inspect model decisions
    and associate decisions with card definitions.
  - Evidence: migration
    `backend/alembic/versions/8ac02d648b4f_add_card_def_id_to_decisions.py`;
    backend models and tests.
  - Confidence: High.

### Fixed

- Fixed malformed model output handling and prefill-related JSON parsing issues.
  - Why: Local model outputs were not always strict JSON, so the engine needed
    robust parsing and fallback to keep simulations legal.
  - Evidence: Existing changelog history; `backend/app/players/ai.py`;
    `backend/tests/test_players/test_ai_player.py`.
  - Confidence: High.

## Phase 4 Persistence and Memory Layer - 2026-04-26

### Added

- Added PostgreSQL persistence, pgvector embeddings, Neo4j relationship storage,
  SQLAlchemy models, Alembic migrations, and memory writers for match and
  decision data.
  - Why: Simulation, AI analysis, and deck evolution required persistent match
    history and queryable memory rather than transient in-process state.
  - Evidence: commit `898871f`; migrations under
    `backend/alembic/versions/`; `backend/app/models/`;
    `backend/app/memory/`; `backend/tests/test_memory.py`.
  - Confidence: High.

- Added a 500-game persistence benchmark path.
  - Why: The memory layer needed to prove it could handle multi-match simulation
    volume.
  - Evidence: Existing changelog history; commit `898871f`;
    `backend/app/cli.py`; `docs/STATUS.md`.
  - Confidence: Medium.

## Phase 3 Heuristic Player and Batch Simulation - 2026-04-26

### Added

- Added `BasePlayer` and `HeuristicPlayer` abstractions, legal-action scoring,
  batch simulation CLI support, and heuristic-vs-heuristic benchmarks.
  - Why: The project needed a deterministic non-LLM baseline before comparing
    AI-player decisions or coach-driven deck evolution.
  - Evidence: commits `ae25341`, `9f78ee8`; `backend/app/players/`;
    `backend/app/cli.py`; `backend/tests/test_players/test_heuristic.py`;
    `docs/STATUS.md`.
  - Confidence: High.

### Fixed

- Fixed early batch simulation issues involving deck-out behavior, deck
  isolation, RNG reuse, role assignment, and attack-choice logging.
  - Why: Heuristic benchmarks are meaningful only if each simulated game starts
    cleanly and ends according to engine rules.
  - Evidence: Existing changelog history; commits `b3b671f`, `f1fe237`,
    `9f78ee8`; engine/player tests.
  - Confidence: High.

## Phase 2 Trainer, Ability, and Effect Handler Expansion - 2026-04-26

### Added

- Added early Trainer/Ability effect handlers and effect-engine support beyond
  flat damage attacks.
  - Why: The first card set included search, draw, attach, heal, switch,
    discard, and passive effects that required explicit game-state mutation.
  - Evidence: commits `9cd88e9`, `f1fe237`, `b3b671f`;
    `backend/app/engine/effects/`; `backend/tests/test_engine/`;
    `docs/PROJECT.md`.
  - Confidence: High.

### Fixed

- Fixed early effect-resolution bugs involving support for more complex trainer
  effects and heuristic interactions.
  - Why: Phase 2 exposed that hard-coded attack handling was insufficient for
    realistic Pokemon TCG card behavior.
  - Evidence: commits `9cd88e9`, `f1fe237`, `b3b671f`; backend tests.
  - Confidence: Medium.

## Phase 1 Engine Core and Initial Project Setup - 2026-04-25 to 2026-04-26

### Added

- Added the initial FastAPI/Python backend project, Docker service definitions,
  engine modules, TCGDex card cache, starter deck files, tests, and project
  documentation.
  - Why: This established the self-hosted simulator foundation described in the
    project blueprint.
  - Evidence: commit `bf6caee`; `README.md`; `docs/PROJECT.md`;
    `docker-compose.yml`; `backend/pyproject.toml`; `backend/app/`.
  - Confidence: High.

- Added the initial core rules engine for setup, mulligans, actions, attacks,
  prizes, knockouts, win/loss detection, random simulation, and deterministic
  smoke tests.
  - Why: All later AI, coach, dashboard, and card-expansion work depended on a
    working game-state model and legal-action runner.
  - Evidence: Existing changelog history; commit `90ebdae`;
    `backend/app/engine/`; `backend/tests/test_engine/`; `docs/STATUS.md`.
  - Confidence: High.

### Fixed

- Fixed Phase 1 setup and runner bugs, including bench capacity, mulligan
  reshuffle behavior, forced active replacement, prize winner assignment, and
  structured event emission.
  - Why: The first engine implementation needed to obey basic game-flow
    invariants before higher-level simulations could be trusted.
  - Evidence: Existing changelog history; commit `90ebdae`;
    `backend/tests/test_engine/test_runner.py`;
    `backend/tests/test_engine/test_state.py`.
  - Confidence: High.

## Historical Uncertainty Log

- Uncertainty: There are no Git tags or release boundaries.
  - Evidence found: `git tag --sort=creatordate` returned no tags; GitHub
    repository metadata did not expose releases through the inspected sources.
  - Missing evidence: Formal release notes or deployment records.
  - Suggested follow-up: Add tags or release notes for future milestones.

- Uncertainty: Exact card-count milestones differ across documents.
  - Evidence found: `docs/STATUS.md` currently says 2,005 cards in DB
    including two test fixtures; `README.md` says 2,001 cards as of 2026-05-01;
    expansion-era changelog/status notes mention 1,927 and 2,001 totals.
  - Missing evidence: A single timestamped database export or release snapshot
    tying each count to an exact commit.
  - Suggested follow-up: Record card-count snapshots with commit SHA, DB query,
    and fixture count whenever audit state changes.

- Uncertainty: Historical `docs/STATUS.md` sections contain retained notes with
  dates and counts that conflict with the current top section.
  - Evidence found: The current top of `docs/STATUS.md` is dated 2026-05-04 and
    is treated as authoritative; older retained notes include different metrics
    and future-looking headings.
  - Missing evidence: A normalized status archive or dated session log per
    entry.
  - Suggested follow-up: Split live status from archived session notes.

- Uncertainty: Card handler entries in this changelog mean "implemented or
  registered according to available evidence," not guaranteed official-perfect
  behavior.
  - Evidence found: DB-backed audit PRs after the expansion found many bugs in
    already-implemented handlers.
  - Missing evidence: Exhaustive per-card conformance tests against official
    rulings.
  - Suggested follow-up: Continue DB-backed audits and add regression tests for
    every fixed card behavior.

- Uncertainty: Some proposal docs were created or restored after the original
  changelog reconstruction, so early reconstruction notes about unavailable
  proposal files are superseded.
  - Evidence found: `docs/proposals/DECKBUILDER_ROADMAP.md`,
    `docs/proposals/PLAYWRIGHT_E2E_PLAN.md`, and
    `docs/proposals/VITE_UPGRADE_PLAN.md` are present as of 2026-05-04.
  - Remaining uncertainty: Exact approval/implementation boundaries still come
    from current code, tests, workflows, and git history, not from proposal text
    alone.
  - Suggested follow-up: Keep proposal headers marked as proposal, accepted,
    implemented, rejected, or superseded when decisions change.

- Uncertainty: Deployment history was not reconstructed.
  - Evidence found: Docker Compose and CI workflow configuration exist.
  - Missing evidence: Vercel/Netlify/Render/Railway deployment records, GitHub
    Environment history, image tags, or production release logs.
  - Suggested follow-up: Add deployment metadata or release records if the stack
    is deployed outside local compose.

## Evidence Sources Reviewed

- [x] Existing `docs/CHANGELOG.md`
- [x] `docs/PROJECT.md`
- [x] `docs/STATUS.md`
- [x] `docs/HARDENING_SWEEP_REPORT.md`
- [x] `docs/CARD_EXPANSION_RULES.md`
- [x] `docs/AUDIT_RULES.md`
- [x] `docs/AUDIT_STATE.md`
- [x] `docs/CARDLIST.md`
- [x] `docs/POKEMON_MASTER_LIST.md`
- [x] `docs/proposals/AI_COACH_HARDENING_ASSESSMENT.md`
- [x] `docs/proposals/AI_COACH_HARDENING_PROPOSAL.md`
- [x] `docs/proposals/DECKBUILDER_ROADMAP.md`
- [x] `docs/proposals/PLAYWRIGHT_E2E_PLAN.md`
- [x] `docs/proposals/VITE_UPGRADE_PLAN.md`
- [x] `README.md`
- [x] Git commit history across `main` and `origin/main`
- [x] Git branches and remotes
- [x] Git tags checked; no tags found
- [x] Current file inventory
- [x] File rename/delete-oriented history inspected through commit history
- [x] Tests and fixtures
- [x] Database migrations
- [x] Dependency manifests and lockfiles (`backend/pyproject.toml`,
  `frontend/package.json`, lockfiles present in repo)
- [x] Build and CI configuration (`.github/workflows/`, `docker-compose.yml`,
  `Makefile`)
- [x] GitHub PR metadata available through connector, including PRs #1, #3, #5,
  #7, #9, #11, #13, #15, #19, #24, #26, #28, #30, #32, #34
- [x] GitHub issue metadata available through connector, including scheduled
  audit issues #2, #4, #6, #8, #14, #18, #29, #31, #33
- [ ] GitHub release metadata unavailable / no releases or tags found in
  inspected evidence
- [ ] Deployment metadata unavailable / not found
