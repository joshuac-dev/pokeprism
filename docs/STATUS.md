# PokePrism - Current Status

> Read this first for current operational state. This file is the live handoff.
> `docs/PROJECT.md` is historical architecture context, not the active source
> of truth for implementation status.

Last updated: 2026-05-05 (session 7 reverification)

## Current Workstream

PokePrism is post-phase-buildout. The original phase blueprint through Phase 13
and the 2026-05-03 hardening sweep are complete. Active work is ongoing
post-phase development:

- DB-backed card-effect audits and cursor-based handler fixes.
- Card-effect correctness, handler registration, and simulation validation.
- AI/coach hardening and decision-quality follow-up.
- Operational refinement for Docker, Celery, CI, and local workflows.

`docs/AUDIT_RULES.md` and `docs/AUDIT_STATE.md` define the active card audit
workflow. `docs/CARDLIST.md`, `docs/POKEMON_MASTER_LIST.md`, and
`docs/CARD_EXPANSION_RULES.md` are historical or supporting expansion-era docs;
they do not define current audit scope.

## Authoritative Metrics

These values are a dated local snapshot, not a permanent release baseline.
Re-check them before making claims in user-facing docs.

| Metric | Current evidence |
|---|---|
| Local cards table | **2,036** rows from `docker compose exec postgres psql -U pokeprism -d pokeprism -c "SELECT count(*) FROM cards;"` on 2026-05-05 |
| Coverage endpoint snapshot | **2,035 auditable cards, 1,742 implemented, 293 flat-only, 0 missing, 100.0%** from direct `backend` container call to `app.api.coverage.get_coverage()` on 2026-05-05 |
| Local matches table | 12,266 rows from 2026-05-05 DB snapshot |
| Local `card_performance` table | **1,947** rows from 2026-05-05 DB snapshot |
| Running simulations | 0 from 2026-05-05 DB snapshot |
| Backend test baseline | Latest full documented run: **466 passed, 1 skipped** on 2026-05-05. Run with `cd backend && python3 -m pytest tests/ -x -q`. Prior: 463 passed on 2026-05-04. |
| Frontend unit tests | **17 passed (4 files)** on 2026-05-05 with `cd frontend && npm test -- --run --reporter=dot`. Prior report of "4 passed" referred to 4 test *files*, not individual tests. |
| Playwright E2E inventory | 14 tests listed on 2026-05-04 with `cd frontend && npm run test:e2e -- --list` |
| Effect import smoke | Passed on 2026-05-05 with `docker compose exec backend python -c "import app.engine.effects.attacks; import app.engine.effects.trainers; import app.engine.effects.energies; import app.engine.effects.abilities; import app.engine.effects.base"` |

## Session 2 Work (2026-05-04)

Three features completed:

1. **Precious Trolley handler (sv08-185)** — ACE SPEC trainer that benches up to
   all available bench spaces worth of Basic Pokémon from deck. Generator-based
   handler with ChoiceRequest. Registered as `sv08-185` in the Ace Spec block of
   `trainers.py`. 3 tests added.

2. **Neutralization Zone handler (sv06.5-060)** — Stadium registered as `_noop`
   (passive). Passive damage prevention added to `_apply_damage` in `attacks.py`:
   if the attacker has `has_rule_box` and the defender does not, damage is zeroed.
   `IRRECOVERABLE_FROM_DISCARD` frozenset added to `base.py` (contains
   `sv06.5-060`); `is_recoverable_from_discard()` helper applied to Pal Pad and
   Miracle Headset candidate filtering as forward-defense. 7 tests added (3
   damage-prevention, 4 irrecoverable-from-discard).

3. **Simulation queue (one-at-a-time)** — Only one simulation runs at a time.
   New sims check `active_count` (pending + running); if >0 they are created as
   `queued` and not dispatched. `_dispatch_next_queued()` uses `SELECT FOR UPDATE
   SKIP LOCKED` to atomically claim the oldest queued sim on every task
   completion. A Beat safety-net task (`advance_simulation_queue`) runs every
   60 seconds to recover from worker crashes. Celery worker concurrency reduced
   from 2 → 1 in `docker-compose.yml`. `'queued'` added to status unions in
   `frontend/src/types/history.ts` and `frontend/src/types/simulation.ts`.
   `cancel_simulation` also handles queued sims and triggers dispatch.

Files changed (sessions 2–3):
- `backend/app/engine/effects/trainers.py` — Precious Trolley handler + NZ noop registration + sv08.5-097/098/099 alt registrations
- `backend/app/engine/effects/attacks.py` — Neutralization Zone passive damage check + svp-173/200/208 alt registrations
- `backend/app/engine/effects/abilities.py` — svp-173 Boosted Evolution passive registration
- `backend/app/engine/effects/base.py` — IRRECOVERABLE_FROM_DISCARD + is_recoverable_from_discard()
- `backend/app/api/simulations.py` — queue-aware create/cancel
- `backend/app/tasks/simulation.py` — _dispatch_next_queued(), run_simulation modified
- `backend/app/tasks/scheduled.py` — advance_simulation_queue Beat task
- `backend/app/tasks/celery_app.py` — Beat schedule entry
- `backend/tests/test_engine/test_audit_fixes.py` — 10 new tests (411→424 total)
- `docker-compose.yml` — --concurrency=2 → --concurrency=1
- `frontend/src/types/history.ts` — 'queued' added to status union
- `frontend/src/types/simulation.ts` — 'queued' added to status union
- `frontend/src/components/history/StatusBadge.tsx` — 'queued' entry with distinct style/label
- `frontend/src/components/history/FilterBar.tsx` — 'Queued' option added to status filter

## Session 3 Work (2026-05-04)

Six missing handler registrations fixed (all alt prints — no new handler logic):

- **sv08.5-097, sv08.5-098, sv08.5-099** (Black Belt's Training alts) — registered
  to existing `_black_belt_training` in `trainers.py`.
- **svp-173** (Eevee alt) — attack registered to `_reckless_charge_eevee` in
  `attacks.py`; Boosted Evolution passive registered as noop in `abilities.py`.
- **svp-200** (Eevee alt) — attack registered to `_call_for_family` in `attacks.py`.
- **svp-208** (Victini alt) — attack registered to `_v_force` in `attacks.py`.

Frontend: "Queued" StatusBadge entry added with a distinct muted-slate style
(previously fell through to raw string display). "Queued" option added to
History page FilterBar status dropdown.

## Session 4 Work (2026-05-04)

Neo4j graph persistence optimized:

- `GraphMemoryWriter._update_synergies()` now builds deterministic unique-card
  pairs and writes them with chunked `UNWIND $pairs AS pair` Cypher instead of
  one `session.run()` per card pair. Semantics are unchanged: duplicate card
  copies are ignored, win/loss deltas remain +1.0/-0.5, and `weight` /
  `games_observed` updates match the prior behavior.
- `GraphMemoryWriter` now caches Deck/Card/BELONGS_TO setup per writer instance
  using a deck ID/name/card-quantity fingerprint and batches Card and BELONGS_TO
  MERGEs with `UNWIND $cards AS card`. MatchResult and BEATS writes still happen
  per match.

Focused tests added for pair generation, chunking, deltas, exact Neo4j
relationship values, deterministic deck card rows, and once-per-writer deck
setup caching.

Validation after these graph optimizations:

- `python3 -m pytest backend/tests/test_memory/test_graph_synergy_batch.py -q`
  — 12 passed.
- `python3 -m pytest backend/tests/test_memory/test_graph.py -q` — 6 passed.
- `cd backend && python3 -m pytest tests/ -x -q` — 439 passed.

Benchmark handoff: 25 persisted H/H matches, 1 opponent, Iron Crown ex Deck vs
Torterra ex Deck, both decks with 60 unique cards. After synergy batching:
total 13.38s, simulation+Redis 1.40s, Postgres 1.60s, Neo4j 10.21s. After
deck setup caching/batching: total 12.29s, simulation+Redis 1.39s, Postgres
1.53s, Neo4j 9.21s, 10,037 match events, 100 expected synergy chunks, 2 deck
setup cache entries. Absolute times include contention from an older
redelivered Celery simulation that remained active.

Decision: Neo4j graph optimization is paused after the safe batching/caching
improvements in commit `b92f4e1`. H/H slowdown was investigated and confirmed
not to involve Ollama, `nomic-embed-text`, or AI inference. The completed
optimizations batch `SYNERGIZES_WITH` updates with `UNWIND $pairs AS pair` and
cache/batch Deck/Card/BELONGS_TO setup per `GraphMemoryWriter` instance, with
strong backend validation (`439 passed`).

Batch-level or deferred graph persistence remains a possible future
optimization, but it is deferred rather than rejected. Current performance is
acceptable relative to the higher priority of preserving memory fidelity,
immediate graph visibility, and AI/coach data quality. Revisit deeper graph
batching only if runtime becomes unacceptable again, and only with strict
reference-equivalence tests against the current per-match graph writer.

## Session 5 Work (2026-05-04)

Opponent-batch checkpointing implemented for simulation replay safety:

- New `simulation_opponent_results` table and `SimulationOpponentResult` ORM
  model checkpoint each `(simulation_id, round_number, opponent_deck_id)` batch.
- Completed opponent checkpoints are verified against persisted match counts and
  skipped on retry/redelivery, preventing duplicate Match, MatchEvent, Decision,
  card_performance, and Neo4j graph updates for already-persisted batches.
- Stale `running` checkpoints with zero persisted matches are reset and rerun.
  Stale `running` checkpoints with the full target match count are finalized
  from persisted Match/MatchEvent rows and skipped. Partial nonzero batches are
  marked `failed` and fail safely without destructive cleanup.
- Graph failures remain non-fatal, matching existing behavior. Checkpoints track
  `graph_status` as `complete` or `failed`.
- Skipped completed batches reconstruct `MatchResult` objects, including events,
  from persisted Postgres rows so round aggregation and coach evidence do not
  silently drop completed opponent data. If a retry reaches an unlocked round
  whose coach mutations were already persisted, the task fails safely rather
  than duplicating mutation decisions.
- Follow-up live validation found and fixed a deck-identity mismatch: match
  persistence now preserves scheduled `Simulation.user_deck_id` and
  `SimulationOpponent.deck_id` values instead of replacing them with name-based
  deck IDs. Completed-checkpoint replay now verifies against the same deck IDs
  used by persisted `matches.opponent_deck_id` rows.

Validation:

- `python3 -m pytest backend/tests/test_tasks/test_simulation_checkpointing.py -q`
  — 10 passed.
- `python3 -m pytest backend/tests/test_tasks -q` — 63 passed.
- `python3 -m pytest backend/tests/test_memory -q` — 20 passed.
- `python3 -m pytest backend/tests/test_api -q` — 79 passed.
- `cd backend && python3 -m pytest tests/ -x -q` — 460 passed (after energy_provides enum fix).
- `cd backend && alembic heads` — `5b7e9c2d4a11 (head)`.
- Live Docker/Celery replay validation passed after the deck-ID fix: a
  completed disposable H/H simulation was re-enqueued, checkpoint rows skipped,
  match/event/card-performance counts stayed unchanged, and duplicate detection
  returned zero rows.
- Live simulation `2bc45a4e-35af-473c-9e4f-aded9800095d` diagnosed and fixed:
  failed with `EnumType.__call__() got an unexpected keyword argument 'energy_type'`
  in the Cresselia me02-039 Swelling Light handler (`_ET_ATTACH`). Root cause was
  `_ET_ATTACH` calling the `EnergyType` enum instead of `EnergyAttachment`.
  Checkpointing was not the cause. After worker rebuild/deploy, re-enqueueing
  `2bc45a4e` is safe: completed opponent checkpoints will skip, the in-progress
  Mega Heracross ex Deck checkpoint (0 matches persisted) will rerun from scratch.
- Live simulation `005109f8-496f-4193-8df3-faee2cdcc981` diagnosed and fixed:
  failed with `'str' object has no attribute 'current_hp'` in the TR Venture Bomb
  sv10-179 handler (`_tr_venture_bomb_b19`). Both `check_ko` calls had transposed
  `(state, player_id_string, card_instance)` arguments; correct order is
  `(state, card_instance, player_id_string)`. Checkpointing was not the cause.
  7 completed opponent checkpoints are clean; Amoonguss ex Deck checkpoint is
  running/0-persisted. After worker rebuild/deploy, re-enqueueing `005109f8` is
  safe: completed opponents skip, Amoonguss reruns from scratch, N's Zoroark and
  Veluza ex Decks run normally.
- Live simulation `40612eb1-38b4-4e62-b0d9-58b7cf4b031e` diagnosed and fixed:
  failed with `'EnergyType' object has no attribute 'strip'` in `_attach_energy`.
  Root cause: three energy-return attack handlers (`_upthrusting_horns_b4` sv08-039
  Paldean Tauros, `_opposing_winds_b5` sv05-135 Unfezant, `_balloon_return_b5`
  mep-006 Drifblim) reconstructed energy `CardInstance` objects from
  `EnergyAttachment.provides` using `list(att.provides)`, which copies
  `EnergyType` enum values into `energy_provides` (typed `list[str]`). Fixed all
  three to use `[et.value for et in att.provides]`. Regression tests added (#L3).
  After worker rebuild/deploy, re-enqueueing `40612eb1` is safe: Greninja, Iron
  Crown, Torterra checkpoints skip; Lickilicky (running/0-persisted) reruns.

## Session 6 Work (2026-05-04)

Full hardening sweep reverification against all 8 sections of the prior report.
Findings and fixes:

1. **`_sinister_surge` duplicate removed (me02-068 Toxtricity)** — A second
   (incorrect) definition at lines 2313–2368 of `abilities.py` shadowed the
   correct implementation at line 676. The incorrect version attached energy to
   ANY in-play Pokémon and placed no damage counters. Correct behavior: attach
   to a benched Darkness-type Pokémon only, place 2 damage counters on it. The
   duplicate and its module-level `_cond_sinister_surge` were deleted.

2. **`_jasmine_gaze` bench coverage (sv08-178)** — Handler was applying
   `incoming_damage_reduction += 30` only to `player.active`. TCGDex text
   confirmed: "all of your Pokémon take 30 less damage." Fixed to apply to all
   in-play Pokémon (active + bench). The "includes new Pokémon that come into
   play" clause and systemic `incoming_damage_reduction` reset-timing issue are
   documented engine gaps (not fixed).

3. **`_grimsleys_move_b18` max count (me02-090)** — Handler was using
   `max_count=max_choose` allowing multiple Pokémon. Card text says "put a (1)
   Darkness-type Pokémon." Fixed to `max_count=1`.

3 regression tests added (`test_audit_fixes.py`). Backend test baseline: **463 passed**.

Engine gaps documented (not fixed): svp-089 Feraligatr Torrential Heart (noop),
svp-134 Crabominable Food Prep (noop), systemic `incoming_damage_reduction`
reset-before-opponent-attacks timing issue.

Section 2C AI behavioral run was blocked by Qwen3.5-9B cold-start exceeding time
budget. Hard gate (Section 2B) and AI prompt (Section 2A) verified by code review.

**Session 8 (2026-05-05):** Closed remaining hardening sweep gaps. 5 handler mismatches
fixed (Ninjask Cast-Off Shell wrong card ID, Clawitzer Fall Back to Reload wrong source/
count/type, Grumpig Energized Steps 4 deviations, Fighting Gong missing Basic filter,
Risky Ruins missing Basic check). Section 2C AI/AI behavioral run completed: 3 games,
489 decisions, 0 validator violations. Section 7B fault injection ran: Redis 1-hour
recovery window gap documented. Backend test count: **466 passed, 1 skipped**.

Files changed:
- `backend/app/engine/effects/abilities.py` — incorrect `_sinister_surge` duplicate deleted
- `backend/app/engine/effects/trainers.py` — `_jasmine_gaze` bench fix, `_grimsleys_move_b18` max_count=1
- `backend/tests/test_engine/test_audit_fixes.py` — 3 new regression tests
- `docs/HARDENING_SWEEP_REPORT.md` — replaced prior report with full reverification

## Current Known Issues / Gaps

- DeckBuilder Phase 3, simulation-backed preference weighting from historical
  data, remains deferred. The current builder is conservative and deterministic.
- AI/Coach provider abstraction is intentionally not planned. PokePrism remains
  Ollama-only by product decision; see
  `docs/proposals/AI_COACH_HARDENING_ASSESSMENT.md`.
- AI decision quality minor finding: forward-planning bias on PASS decisions (AI
  narrates future action rather than evaluating present-turn play). No hallucinations
  or illegal action acceptance found in 489-decision audit. Not a correctness issue.
- **NOOP stubs (require engine work before they take effect in games):**
  - me01-118 Iron Defender: turn-scoped Metal damage reduction (30 less) — requires
    `fighting_damage_bonus_30`-style flag on `PlayerState` + `_apply_damage` check
  - me01-124 Premium Power Pro: turn-scoped Fighting damage bonus (30 more) — same pattern
  - me01-028 Cinderace Explosiveness: setup-phase placement — requires mulligan/setup hook
- **Resilience gap: Redis 1-hour recovery window** — if Celery worker is killed mid-task,
  the simulation stuck in `running` status blocks `advance_simulation_queue` until the
  Redis visibility timeout expires (default 3600s). Fix: set
  `broker_transport_options={"visibility_timeout": N}` in `celery_app.py`, or add
  stale-running detection in `_dispatch_next_queued()`.
- Team Rocket's Watchtower (sv10-180 / me02.5-210): Colorless Pokémon ability
  suppression is fully implemented in the action validator. Passive ability
  interactions (e.g. Damp) remain a future gap if a Colorless Pokémon with a
  passive ability becomes relevant.
- Mystery Garden (me02.5-194 / me01-122): fully implemented via `USE_STADIUM`
  ActionType; once-per-turn Energy-discard draw effect is live.
- Spiky Energy (sv09-159): damage-retaliation effect fully implemented in
  `_apply_damage`; detection fixed to use `att.card_def_id` directly.
- Boomerang Energy (sv06-166): reattach-after-discard effect fully implemented
  in `transitions.py`.
- Neutralization Zone (sv06.5-060): passive damage prevention is implemented.
  The "cannot be retrieved from discard" restriction is enforced in Pal Pad and
  Miracle Headset. Other future retrieval handlers (if added) must apply
  `is_recoverable_from_discard()` filtering.
- `celery-worker` has no dedicated healthcheck. It restarts via
  `restart: unless-stopped`.
- Simulation queue relies on Beat task as crash-recovery fallback (every 60s).
  There is no push notification to the frontend when a queued sim transitions to
  running; the frontend must poll for status changes.
- Opponent-batch checkpointing prevents future retry/redelivery replay
  duplication, but it does not clean any duplicate historical data that may
  already exist. Partial persisted opponent batches are intentionally not
  deleted automatically; they are marked failed for manual repair.
- Neo4j graph writes remain per-match for MatchResult and BEATS relationships.
  Deck/Card/BELONGS_TO setup and synergy pair updates are batched/cached.
  Match-result aggregation and batch-level/deferred graph persistence are
  deferred future opportunities, not active next work; if revisited, they need
  reference-equivalence tests against current per-match persistence.

## Operational Caveats

- After changes under `backend/app/engine/effects/`, rebuild the worker image:
  `docker compose build celery-worker && docker compose up -d celery-worker`.
  The backend container mounts `./backend/app:/app/app`, but `celery-worker`
  runs baked code from its image.
- `make restart` restarts backend, worker, and beat, but it does not rebuild the
  worker image.
- `make reset-data` truncates simulation data and clears Neo4j relationships.
  Do not run it unless that destructive action is explicitly intended.
- Full-stack E2E is opt-in: run from `frontend/` with
  `POKEPRISM_E2E_FULL_STACK=1 npm run test:e2e` against a running Docker stack.
- AI-backed modes require a working Ollama model and suitable local hardware.
  H/H simulations do not require Ollama inference.
- Running frontend dependency commands can dirty tracked `frontend/node_modules`
  in this repository. Do not commit `frontend/node_modules`.

## Current Commands

```bash
# Services
make up
make down
make build
make restart
make ps
make logs
make logs-all

# Database
make migrate
make seed

# Tests and checks
make test
make test-engine
make test-cards
make lint
cd frontend && npm test
cd frontend && npm run build
cd frontend && npm run test:e2e -- --list
docker compose config --quiet
```

## Immediate Next Steps

1. Monitor opponent-batch checkpointing under real Celery retry/restart
   conditions and add non-destructive duplicate-reporting tooling if historical
   duplicate cleanup becomes necessary.
2. Continue the DB-backed audit from `docs/AUDIT_STATE.md` using the rules in
   `docs/AUDIT_RULES.md`. Do not advance `next_start_cursor` unless an actual
   card audit is performed.
3. Implement the next safe card-handler batch discovered by audit or simulation
   coverage gates, with focused tests and a worker rebuild.
4. Run at least one simulation containing newly implemented cards to verify the
   coverage gate and runtime worker path use the new handlers.
5. Re-run the full backend suite when handler or engine changes are complete and
   update this file with the exact command and result.
6. Keep `docs/CHANGELOG.md` as the historical record for completed work and
   resolved uncertainty.

## Read This First

- Current state and operations: `docs/STATUS.md`
- Historical changes and evidence: `docs/CHANGELOG.md`
- Active card audit workflow: `docs/AUDIT_RULES.md` and `docs/AUDIT_STATE.md`
- Historical architecture blueprint: `docs/PROJECT.md`
- Public setup/onboarding: `README.md`
- Supporting proposals and assessments: `docs/proposals/*.md`

## Archival Note

Older session-by-session notes that previously lived in this file were
compressed into this current-state handoff. Historical facts should be preserved
in `docs/CHANGELOG.md`; if a future detail is missing from the changelog, add it
there rather than expanding this status file back into a session log.
